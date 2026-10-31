from typing import Annotated, Any, List, Optional, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class GraphState(TypedDict, total=False):
    """
    LangGraph의 각 노드 간에 전달되는 상태를 정의합니다.
    """
    messages: Annotated[List[BaseMessage], add_messages]
    question: str

    # 분석 기준 시점 ("2023년 4월 11일 14시 00분" 형식, None이면 현재 시점)
    scenario_time: Optional[str]

    # 에이전트 분석 정보
    news: str
    GPS: str
    SNS: str
    disaster: str

    # 그래프 제어 플래그
    use_agent: bool
    agent_visited: bool
    remaining_steps: int

    # 최종 결과물
    rag_context: str
    structured_response: Any
