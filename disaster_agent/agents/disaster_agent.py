from datetime import datetime, timedelta

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.prebuilt import create_react_agent

from disaster_agent.config import VERBOSE
from disaster_agent.llm import get_llm
from disaster_agent.state import GraphState


async def disaster_agent_node(state: GraphState, tools) -> GraphState:
    print("======= [Sub-agent] Disaster Agent 실행 =======")

    try:
        scenario_time_str = state.get("scenario_time")
        if not scenario_time_str:
            # 라이브 모드 (scenario_time이 없는 경우) -> 어제 날짜 사용
            scenario_dt = datetime.now() - timedelta(days=1)
            scenario_time_str = "현재(라이브 모드)"
        else:
            # 평가 모드 (scenario_time이 있는 경우) -> 해당 날짜 파싱
            scenario_dt = datetime.strptime(scenario_time_str, "%Y년 %m월 %d일 %H시 %M분")
    except (ValueError, TypeError):
        # 파싱 실패 시 어제 날짜로 대체
        scenario_dt = datetime.now() - timedelta(days=1)
        scenario_time_str = "현재(파싱 실패)"

    # 도구가 요구하는 YYYYMMDD 형식으로 변환
    search_date_yyyymmdd = scenario_dt.strftime("%Y%m%d")

    prompt = f"""
    당신은 공공 화재 재난 데이터 분석가 입니다.
    '분석 기준 시점'({scenario_time_str})에 발생한 화재 재난 관련 공공 데이터를 분석하여 보고서를 작성해주세요.

    ## 분석 기준
    - 분석 기준 시점: {scenario_time_str}
    - 데이터 조회 날짜: {search_date_yyyymmdd} (YYYYMMDD 형식)

    ## 수집 및 분석할 데이터의 종류
    1. 기상청 기상특보 (getKMAWeatherWarning tool 사용, search_date='{search_date_yyyymmdd}' 파라미터 사용)
    2. 산불 정보 (getForestFires tool 사용, search_date='{search_date_yyyymmdd}' 파라미터 사용)

    ## 지시사항
    위에 명시된 '데이터 조회 날짜'({search_date_yyyymmdd})를 각 도구의 'search_date' 파라미터에 정확히 입력하여 2가지 종류의 데이터를 모두 수집하세요.
    수집된 모든 데이터를 바탕으로 '공공 화재 재난 데이터 분석 보고서'를 작성하세요.
    """

    disaster_agent = create_react_agent(
        get_llm(),
        tools=tools,
        prompt=prompt,
        state_schema=GraphState,
    )

    trigger_message = HumanMessage(
        content=f"지금 바로 주어진 도구들을 사용하여 {state['GPS']} 지역의 재난 공공 데이터를 수집하고 분석하세요."
    )

    agent_response = await disaster_agent.ainvoke({"messages": [trigger_message]})
    disaster_content = agent_response["messages"][-1].content
    disaster_message = AIMessage(content=disaster_content, name="DisasterAgent")

    if VERBOSE:
        print("--- Disaster Agent 세부 분석 과정 ---")
        print(agent_response)

    print("--- Disaster Agent 분석 완료 ---")
    return {"messages": [disaster_message], "disaster": disaster_content}
