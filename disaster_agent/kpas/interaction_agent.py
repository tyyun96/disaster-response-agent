from datetime import datetime

from langchain_core.messages import AIMessage
from langgraph.prebuilt import create_react_agent
from pydantic import BaseModel, Field

from disaster_agent.llm import get_llm
from disaster_agent.rag.vector_store import get_retriever
from disaster_agent.state import GraphState


class UserInteractionResponse(BaseModel):
    use_agent: bool = Field(..., description="관리자의 요청을 수행하기 위해 멀티 에이전트 시스템 사용이 필요한지 여부를 판단")


async def user_interaction_node(state: GraphState) -> GraphState:
    """
    관리자의 초기 요청을 분석하거나, 모든 정보가 수집된 후 최종 KPAS 초안을 생성합니다.
    agent_visited 상태에 따라 두 가지 다른 작업을 수행합니다.
    """
    if state.get("agent_visited", False):
        # 모든 에이전트 작업 완료, 최종 KPAS 초안 생성
        return await _generate_final_kpas_draft(state)
    # 관리자의 초기 요청 분석
    return await _initial_analysis(state)


async def _initial_analysis(state: GraphState) -> GraphState:
    """초기 관리자 요청을 분석하여 멀티 에이전트 시스템 사용 여부를 결정합니다."""
    print("\n======= [Node] User Interaction Agent (초기 분석) 실행 =======")

    prompt = f"""
    당신은 KPAS(재난문자방송시스템) 발송 관리자를 보조하는 '전문 AI 어시스턴트'입니다.
    당신의 임무는 관리자의 요청을 분석하여, '실시간 재난 상황 분석 및 KPAS 문자 초안 작성' 작업이 필요한지 판단하는 것입니다.

    1. 만약 관리자의 요청이 특정 지역의 재난(화재, 홍수, 지진 등)에 대한 '상황 분석', '정보 요약', '문자 초안 작성' 등 구체적인 작업을 지시하는 경우, 내부 재난 분석 멀티 에이전트 시스템을 사용해야 한다고 판단해야 합니다.
    2. 만약 관리자의 요청이 단순 인사, 시스템 점검, 또는 재난과 무관한 일반 질의라면, 시스템을 사용할 필요가 없다고 판단하고, 관리자에게 전문 보조 AI로서 정중하게 응답하세요.

    현재 관리자 요청: "{state.get('question', '')}"
    """

    user_interaction_agent = create_react_agent(
        get_llm(),
        tools=[],
        prompt=prompt,
        state_schema=GraphState,
        response_format=UserInteractionResponse,
    )

    agent_response = await user_interaction_agent.ainvoke(state)
    structured_response = agent_response["structured_response"]

    final_message = AIMessage(
        content=agent_response["messages"][-1].content,
        name="UserInterfaceAgent",
    )

    return {
        "messages": [final_message],
        "use_agent": structured_response.use_agent,
    }


async def _generate_final_kpas_draft(state: GraphState) -> GraphState:
    """모든 에이전트의 분석 결과를 종합하고 RAG 검색을 통해 최종 답변을 생성합니다."""
    print("\n======= [Node] User Interaction Agent (최종 답변 생성) 실행 =======")
    print("재난 분석 완료. RAG 시스템을 조회하여 최종 답변을 생성합니다...")

    refined_query = f"""
    관리자의 질문 : {state.get('question', 'KPAS 실시간 화재 재난 문자를 작성해')}
    관리자의 질문에 답변하기 위해 숙지해야 할 관련 법령 및 규정을 검색해줘.
    """

    rag_context = ""
    retriever = get_retriever()
    if retriever is not None:
        retrieved_docs = await retriever.ainvoke(refined_query)
        rag_context = "\n\n---\n\n".join([doc.page_content for doc in retrieved_docs])

    scenario_time = state.get("scenario_time") or datetime.now().strftime("%Y년 %m월 %d일 %H시 %M분")

    evaluate_prompt = f"""
    당신은 대한민국 재난 대응 AI 에이전트입니다.
    당신의 임무는 국민의 생명과 안전 확보를 위해 현재 상황에 가장 효과적인 재난 문자를 생성하고, 그 논리적 근거를 관리자에게 설명하는 것입니다.

    ## 최종 임무 (Step-by-Step)
    1.  모든 '실시간 분석 데이터'를 종합하여 현재 재난 상황을 판단합니다.
    2.  **[가장 중요]** '실시간 분석 데이터'에서 파악된 **가장 시급하고 구체적인 위험**과 **실행 가능한 행동**을 1순위로 조합하여, **가장 효과적이고 상세한** 재난 문자 초안을 '창작(Generate)'합니다.
    3. 작성된 문안이 왜 최적인지, 어떤 데이터를 근거로 했는지 설명하는 '작성 근거'를 기술합니다.

    ## 실시간 분석 데이터
    - 기준 시점 (재난 상황 시점): {scenario_time}
    - 관리자 관심 위치(GPS): {state.get('GPS', '위치 정보 없음')}
    - 뉴스 데이터 분석 보고서: {state.get('news', '수집된 정보 없음')}
    - 재난 공공 데이터 분석 보고서: {state.get('disaster', '수집된 정보 없음')}
    - SNS 데이터 분석 보고서: {state.get('SNS', '수집된 정보 없음')}

    ## RAG 검색 결과
    {rag_context or '검색 결과 없음'}

    ## 출력 형식
    반드시 아래 두 가지 섹션으로만 구분하여 출력하세요. 불필요한 서론이나 인사는 제외합니다.

    ### 1. KPAS 재난 문자 초안
    [기관명]으로 시작하는 최종 재난 문자 텍스트

    ### 2. 작성 근거
    KPAS 재난 문자 발송 관리자가 납득할 수 있도록 실시간 분석 데이터의 각 데이터 분석 보고서에서 핵심 팩트를 인용하여, KPAS 재난 문자 작성의 이유를 최대한 구체적으로 설명하세요

    Let's think step by step.
    """

    final_agent = create_react_agent(
        get_llm(),
        tools=[],
        prompt=evaluate_prompt,
        state_schema=GraphState,
    )

    final_response = await final_agent.ainvoke(state)
    final_content = final_response["messages"][-1].content
    final_message = AIMessage(content=final_content, name="FinalResponseAgent")

    return {
        "messages": [final_message],
        "rag_context": rag_context,
    }
