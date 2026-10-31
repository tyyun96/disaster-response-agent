from datetime import datetime, timedelta, timezone

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.prebuilt import create_react_agent

from disaster_agent.config import VERBOSE
from disaster_agent.llm import get_llm
from disaster_agent.state import GraphState


async def sns_agent_node(state: GraphState, tools) -> GraphState:
    print("======= [Sub-agent] SNS Agent 실행 =======")

    kst = timezone(timedelta(hours=9))
    try:
        scenario_time_str = state.get("scenario_time")
        if not scenario_time_str:
            scenario_dt_utc = datetime.now(timezone.utc)
            scenario_time_str = scenario_dt_utc.astimezone(kst).strftime("%Y년 %m월 %d일 %H시 %M분 (KST)")
        else:
            scenario_dt_local = datetime.strptime(scenario_time_str, "%Y년 %m월 %d일 %H시 %M분").replace(tzinfo=kst)
            scenario_dt_utc = scenario_dt_local.astimezone(timezone.utc)
    except (ValueError, TypeError):
        scenario_dt_utc = datetime.now(timezone.utc)
        scenario_time_str = scenario_dt_utc.astimezone(kst).strftime("%Y년 %m월 %d일 %H시 %M분 (KST)")

    published_before_dt_utc = scenario_dt_utc
    published_after_dt_utc = published_before_dt_utc - timedelta(days=1)

    # YouTube API용 (RFC 3339 / ISO 8601)
    published_after_iso = published_after_dt_utc.isoformat()
    published_before_iso = published_before_dt_utc.isoformat()

    # Threads API용 (YYYY-MM-DD)
    start_date_str = published_after_dt_utc.strftime("%Y-%m-%d")
    end_date_str = published_before_dt_utc.strftime("%Y-%m-%d")

    prompt = f"""
        당신은 SNS 데이터 분석가입니다.
        여러 소셜 미디어 플랫폼(YouTube, Threads)에서 수집된 정보를 교차 검증하여, 화재 상황을 분석해주세요.

        ## 현재 분석 기준
        - 분석 기준 시점: {scenario_time_str}
        - 관리자 관심 위치: {state["GPS"]}

        ## 최종 목표 (Goal)
        제공되는 MCP Tools들을 활용하여 소셜미디어를 통해 화재 상황을 분석하고, 종합적인 "SNS 화재 분석 보고서"를 생성합니다.

        ## 수행 절차 (Step-by-Step Procedure)
        **1단계: YouTube 검색**
        - `searchVideos` 도구를 사용하여 화재 영상 10건을 검색하세요.
            - 호출 시 `publishedAfter`='{published_after_iso}', `publishedBefore`='{published_before_iso}' 사용.
        - 검색한 영상에 대한 세부 정보들을 검색하세요
            - `getVideoDetails`, `getVideoComments` 도구 사용

        **2단계: Threads 검색**
        - `get_fire_related_threads_with_replies` 도구를 사용하여 실시간 반응을 확인하세요.
            - `start_date`='{start_date_str}', `end_date`='{end_date_str}' 사용.

        **3단계: 최종 보고서 생성**
        수집된 모든 정보를 종합하여 "SNS 화재 분석 보고서"를 작성하여 최종 응답으로 반환하세요.
    """

    sns_agent = create_react_agent(
        get_llm(),
        tools=tools,
        prompt=prompt,
        state_schema=GraphState,
    )

    trigger_message = HumanMessage(
        content=f"지금 바로 주어진 도구들을 사용하여 {state['GPS']} 지역의 SNS 데이터를 수집하고 분석하세요."
    )

    agent_response = await sns_agent.ainvoke({"messages": [trigger_message]})
    sns_content = agent_response["messages"][-1].content
    sns_message = AIMessage(content=sns_content, name="SNSAgent")

    if VERBOSE:
        print("--- SNS Agent 세부 분석 과정 ---")
        print(agent_response)

    print("--- SNS Agent 분석 완료 ---")
    return {"messages": [sns_message], "SNS": sns_content}
