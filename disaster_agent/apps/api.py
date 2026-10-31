"""
외부 시스템 연동용 REST API

    uvicorn disaster_agent.apps.api:app --port 8000
"""
import uuid
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from disaster_agent.collector import scheduler
from disaster_agent.collector.incidents import run_collection_flow
from disaster_agent.collector.service import DEFAULT_COLLECTION_QUESTION, save_snapshot
from disaster_agent.config import COLLECTOR_SNAPSHOT_DIR, EXTERNAL_API_KEY
from disaster_agent.kpas.workflow import DEFAULT_KPAS_QUESTION, run_kpas_workflow

app = FastAPI(title="Disaster Response Agent API", version="1.0.0")


def verify_api_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    """
    EXTERNAL_API_KEY가 설정되어 있으면 x-api-key 헤더 검증을 강제합니다.
    """
    if not EXTERNAL_API_KEY:
        return
    if x_api_key != EXTERNAL_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


class CollectRequest(BaseModel):
    location: str = Field(..., description="수집 대상 위치 (예: 신촌, 서울 서대문구)")
    scenario_time: Optional[str] = Field(
        default=None,
        description="기준 시점 (예: 2026년 03월 06일 10시 00분). 미입력 시 현재 시점",
    )
    question: str = Field(default=DEFAULT_COLLECTION_QUESTION)
    save_json: bool = Field(default=True, description="수집 결과 JSON 저장 여부")


class MonitorOnceRequest(BaseModel):
    scope: str = Field(default="대한민국", description="수집 범위")
    scenario_time: Optional[str] = Field(default=None)
    question: str = Field(default=DEFAULT_COLLECTION_QUESTION)
    output_dir: Optional[str] = Field(
        default=str(COLLECTOR_SNAPSHOT_DIR),
        description="저장 디렉토리 절대경로",
    )


class KpasDraftRequest(BaseModel):
    location: str = Field(..., description="분석 대상 위치 (예: 강남역, 서대문구 홍제동)")
    scenario_time: Optional[str] = Field(default=None, description="기준 시점. 미입력 시 현재 시점")
    question: str = Field(default=DEFAULT_KPAS_QUESTION)


@app.get("/health")
async def health() -> dict:
    return {"status": "OK"}


@app.post("/collect/run")
async def collect_run(
    payload: CollectRequest,
    _: None = Depends(verify_api_key),
) -> dict:
    """지정 위치의 재난 정보를 수집하고 사건 목록(incidents)까지 포함한 JSON을 반환합니다."""
    thread_id = f"api-session-{uuid.uuid4()}"
    snapshot = await run_collection_flow(
        location=payload.location,
        scenario_time=payload.scenario_time,
        question=payload.question,
        thread_id=thread_id,
    )

    saved_path = str(save_snapshot(snapshot)) if payload.save_json else None
    return {
        "ok": True,
        "thread_id": thread_id,
        "saved_path": saved_path,
        "data": snapshot,
    }


@app.post("/monitor/run-once")
async def monitor_run_once(
    payload: MonitorOnceRequest,
    _: None = Depends(verify_api_key),
) -> dict:
    """주기 수집기(collector.scheduler)의 1회 실행과 동일합니다."""
    output_dir = Path(payload.output_dir) if payload.output_dir else COLLECTOR_SNAPSHOT_DIR
    output_path = await scheduler.run_once(
        scope=payload.scope,
        scenario_time=payload.scenario_time,
        question=payload.question,
        output_dir=output_dir,
    )
    return {
        "ok": True,
        "saved_path": str(output_path),
    }


@app.post("/kpas/draft")
async def kpas_draft(
    payload: KpasDraftRequest,
    _: None = Depends(verify_api_key),
) -> dict:
    """KPAS 재난문자 초안과 작성 근거를 생성합니다."""
    draft = await run_kpas_workflow(
        question=payload.question,
        gps=payload.location,
        scenario_time=payload.scenario_time,
    )
    return {"ok": True, "draft": draft}
