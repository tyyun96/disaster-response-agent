"""
카카오 i 오픈빌더 스킬 서버 (콜백 방식)

    uvicorn disaster_agent.apps.kakao:app --port 8000

환경변수 KAKAO_MODE 로 응답 방식을 고릅니다.
    collect (기본값) : 재난 정보 수집 결과 요약
    kpas            : KPAS 재난문자 초안 + 작성 근거
"""
import asyncio
import os
from typing import Any, Dict, Optional

import httpx
from fastapi import BackgroundTasks, FastAPI
from pydantic import BaseModel, Field

from disaster_agent.collector.service import build_collection_text, collect_disaster_data
from disaster_agent.kpas.workflow import run_kpas_workflow
from disaster_agent.llm import get_llm

app = FastAPI()

CALLBACK_TIMEOUT_SEC = 55
KAKAO_MODE = os.getenv("KAKAO_MODE", "collect")


# --- Pydantic 모델 ---

class Intent(BaseModel):
    id: str
    name: str


class Block(BaseModel):
    id: str
    name: str


class User(BaseModel):
    id: str
    type: str
    properties: Dict[str, Any]


class UserRequest(BaseModel):
    # 카카오가 1회용 콜백 URL을 여기에 담아 보냄
    callbackUrl: Optional[str] = None
    timezone: str
    params: Dict[str, Any]
    block: Block
    utterance: str
    lang: Optional[str] = None
    user: User


class Bot(BaseModel):
    id: str
    name: str


class Action(BaseModel):
    name: str
    clientExtra: Optional[Dict[str, Any]] = None
    params: Dict[str, Any]
    id: str
    detailParams: Dict[str, Any]


class KakaoRequest(BaseModel):
    intent: Intent
    userRequest: UserRequest
    bot: Bot
    action: Action


class KakaoParsedRequest(BaseModel):
    location: str = Field(
        default="대한민국",
        description="수집 대상 지역명. 없으면 '대한민국'을 사용",
    )
    scenario_time: Optional[str] = Field(
        default=None,
        description="사용자가 과거 시점을 명시한 경우 'YYYY년 MM월 DD일 HH시 MM분' 형식으로 작성",
    )


# --- 내부 유틸 ---

async def parse_utterance(utterance: str) -> KakaoParsedRequest:
    """사용자 발화에서 지역과 기준 시점을 추출합니다."""
    prompt = f"""
사용자 요청 문장에서 재난 정보 수집에 필요한 입력을 추출하세요.

규칙:
1) location은 구체 지명이 있으면 그대로, 없으면 '대한민국'
2) 과거 시점이 명시되면 scenario_time에 'YYYY년 MM월 DD일 HH시 MM분' 형식으로 변환
3) 시점 언급이 없으면 scenario_time은 null

사용자 문장:
{utterance}
"""
    try:
        parsed = await get_llm().with_structured_output(KakaoParsedRequest).ainvoke(prompt)
    except Exception:
        return KakaoParsedRequest()
    if not parsed.location.strip():
        parsed.location = "대한민국"
    return parsed


async def run_kakao_agent(utterance: str, user_id: str) -> str:
    request = await parse_utterance(utterance)

    if KAKAO_MODE == "kpas":
        return await run_kpas_workflow(
            question=utterance,
            gps=request.location,
            scenario_time=request.scenario_time,
            thread_id=f"kakao-{user_id}",
        )

    result = await collect_disaster_data(
        location=request.location,
        scenario_time=request.scenario_time,
        thread_id=f"kakao-{user_id}",
    )
    return build_collection_text(result, max_section_chars=180)


async def _post_callback(callback_url: str, payload: Dict[str, Any]) -> None:
    """
    카카오가 제공한 1회용 callbackUrl로 최종 응답을 POST로 전송합니다.
    """
    print("✅ 작업 완료. Callback URL로 최종 답변 전송 시작...")
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            r = await client.post(callback_url, json=payload)
            r.raise_for_status()
            print(f"✅ Callback 전송 성공. 응답: {r.text}")
        except httpx.HTTPStatusError as e:
            print(f"❌ Callback 전송 실패: {e.response.status_code} {e.response.text}")
        except Exception as e:
            print(f"❌ Callback 전송 중 알 수 없는 오류: {e}")


async def _do_heavy_and_callback(callback_url: str, user_message: str, user_id: str):
    """
    (백그라운드 실행) 무거운 AI 작업을 실행한 뒤, _post_callback을 호출합니다.
    """
    try:
        response_text = await asyncio.wait_for(
            run_kakao_agent(user_message, user_id=user_id),
            timeout=CALLBACK_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError:
        print(f"❌ 백그라운드 오류: 작업 시간 초과 ({CALLBACK_TIMEOUT_SEC}초)")
        response_text = f"죄송합니다. AI 에이전트가 {CALLBACK_TIMEOUT_SEC}초 내에 응답하지 못했습니다."
    except Exception as e:
        print(f"❌ 백그라운드 오류: {e}")
        response_text = "죄송합니다. 요청 처리 중 오류가 발생했습니다."

    payload = {
        "version": "2.0",
        "template": {
            "outputs": [
                {"simpleText": {"text": response_text}}
            ]
        },
    }
    await _post_callback(callback_url, payload)


# --- FastAPI 엔드포인트 ---

@app.post("/skill/chat")
async def chat(request: KakaoRequest, background_tasks: BackgroundTasks):
    """
    (카카오 i 오픈빌더 스킬 URL에 등록될 단일 엔드포인트)
    1. 5초 내 즉시 응답 (useCallback=true, 대기 문구)
    2. 백그라운드에서 전달받은 callbackUrl로 최종 답변을 POST
    """
    user_message = request.userRequest.utterance
    user_id = request.userRequest.user.id
    callback_url = request.userRequest.callbackUrl

    print(f"🚀 요청 접수: '{user_message}' (user_id={user_id}, mode={KAKAO_MODE})")

    if not callback_url:
        print("❌ 'callbackUrl'이 없습니다. 카카오 i 오픈빌더에서 콜백이 활성화되었는지 확인하세요.")
        return {
            "version": "2.0",
            "template": {"outputs": [{"simpleText": {"text": "챗봇 설정에 오류가 발생했습니다. (콜백 URL 누락)"}}]},
        }

    background_tasks.add_task(_do_heavy_and_callback, callback_url, user_message, user_id)

    waiting_text = (
        "AI 에이전트가 재난 문자 초안을 작성 중입니다. 잠시만 기다려주세요."
        if KAKAO_MODE == "kpas"
        else "연결된 에이전트로 재난 정보를 수집 중입니다. 잠시만 기다려주세요."
    )
    return {
        "version": "2.0",
        "useCallback": True,
        "data": {"text": waiting_text},
    }


@app.get("/health")
async def health():
    return {"status": "OK"}
