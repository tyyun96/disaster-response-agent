from datetime import datetime

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.prebuilt import create_react_agent

from disaster_agent.config import VERBOSE
from disaster_agent.llm import get_llm
from disaster_agent.state import GraphState


async def news_agent_node(state: GraphState, tools) -> GraphState:
    print("======= [Sub-agent] News Agent 실행 =======")

    scenario_time_str = state.get("scenario_time")

    if not scenario_time_str:
        scenario_dt = datetime.now()
        scenario_time_str = scenario_dt.strftime("%Y년 %m월 %d일 %H시 %M분")
    else:
        try:
            scenario_dt = datetime.strptime(scenario_time_str, "%Y년 %m월 %d일 %H시 %M분")
        except ValueError:
            print(f"⚠️ 경고: scenario_time '{scenario_time_str}' 파싱 실패. 현재 시간으로 대체합니다.")
            scenario_dt = datetime.now()

    search_date_yyyymmdd = scenario_dt.strftime("%Y%m%d")

    prompt = f"""
    당신은 화재 뉴스 데이터 분석가입니다.
    당신의 임무는 '특정 재난 시점'을 기준으로 국내 주요 언론사의 화재 재난 관련 뉴스를 수집하고 분석하는 것입니다.

    ## 현재 분석 기준
    - 분석 기준 시점: {scenario_time_str}
    - 관리자 관심 위치: {state["GPS"]}
    - 데이터 조회 날짜: {search_date_yyyymmdd} (YYYYMMDD 형식)

    ## 뉴스데이터 수집 및 분석 지시사항
    1. 'get_naver_news' tool을 사용하여 '{state["GPS"]} 화재' 키워드로 네이버 뉴스를 5건 검색하세요.
    2. 검색 결과에서 나온 네이버 뉴스 5건의 URL(link)들을 'scrape' tool을 사용하여 전체 기사 내용을 추출하세요.
    3. 'get_yonhap_news' tool을 사용하여 한국의 화재 관련 연합 뉴스를 검색하세요. (**tool의 'date' 파라미터에 {search_date_yyyymmdd}를 사용하세요.**)
    4. 수집한 모든 기사 내용을 바탕으로, '분석 기준 시점'({scenario_time_str})의 화재 상황을 정리하여 '화재 뉴스 분석 보고서'를 작성하세요.
    """

    news_agent = create_react_agent(
        get_llm(),
        tools=tools,
        prompt=prompt,
        state_schema=GraphState,
    )

    trigger_message = HumanMessage(
        content=f"지금 바로 주어진 도구들을 사용하여 {state['GPS']} 지역의 뉴스 데이터를 수집하고 분석하세요."
    )

    agent_response = await news_agent.ainvoke({"messages": [trigger_message]})
    news_content = agent_response["messages"][-1].content
    news_message = AIMessage(content=news_content, name="NewsAgent")

    if VERBOSE:
        print("--- News Agent 세부 분석 과정 ---")
        print(agent_response)

    print("--- News Agent 분석 완료 ---")
    return {"messages": [news_message], "news": news_content}
