import uuid
from typing import Any, Dict, Optional

from langchain_core.messages import HumanMessage

from disaster_agent.config import RECURSION_LIMIT
from disaster_agent.kpas.graph import app
from disaster_agent.state import GraphState

DEFAULT_KPAS_QUESTION = "KPAS 실시간 재난 문자를 작성해"


async def run_kpas_graph(
    question: str,
    gps: str,
    scenario_time: Optional[str] = None,
    thread_id: Optional[str] = None,
) -> Dict[str, Any]:
    """KPAS 그래프를 실행하고 최종 상태(뉴스/SNS/공공데이터 보고서 + 메시지)를 그대로 반환합니다."""
    thread_id = thread_id or f"kpas-analysis-session-{uuid.uuid4()}"
    config = {
        "recursion_limit": RECURSION_LIMIT,
        "configurable": {"thread_id": thread_id},
    }
    input_data: GraphState = {
        "messages": [HumanMessage(content=question)],
        "question": question,
        "scenario_time": scenario_time,
        "GPS": gps,
    }

    mode_msg = f"시점: {scenario_time}" if scenario_time else "시점: 현재 (라이브 모드)"
    print(f"\n🚀 [Thread ID: {thread_id}] 요청: '{question}' (위치: {gps}) 분석 시작 ({mode_msg})")
    return await app.ainvoke(input_data, config=config)


async def run_kpas_workflow(
    question: str,
    gps: str,
    scenario_time: Optional[str] = None,
    thread_id: Optional[str] = None,
) -> str:
    """워크플로우를 실행하고 최종 답변(KPAS 문자 초안 + 작성 근거) 텍스트를 반환합니다."""
    try:
        result = await run_kpas_graph(question, gps, scenario_time, thread_id)
    except Exception as e:
        print(f"❌ 워크플로우 실행 중 오류 발생: {e}")
        return f"오류 발생: {e}"

    if result.get("messages"):
        return result["messages"][-1].content
    return "응답을 생성할 수 없습니다."
