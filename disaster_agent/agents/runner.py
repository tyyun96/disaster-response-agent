import asyncio
from typing import Any, Dict, List, Tuple

from disaster_agent.agents.disaster_agent import disaster_agent_node
from disaster_agent.agents.news_agent import news_agent_node
from disaster_agent.agents.sns_agent import sns_agent_node
from disaster_agent.mcp_client import MCPClientManager
from disaster_agent.state import GraphState

# 각 하위 에이전트가 사용할 MCP 도구 이름
NEWS_TOOLS = {"get_naver_news", "get_yonhap_news", "scrape"}
SNS_TOOLS = {"getVideoDetails", "searchVideos", "getVideoComments", "get_fire_related_threads_with_replies"}
DISASTER_TOOLS = {"getForestFires", "getKMAWeatherWarning"}


async def run_sub_agents(state: GraphState) -> Tuple[Dict[str, Any], List[str]]:
    """
    뉴스 / SNS / 공공데이터 하위 에이전트를 병렬 실행합니다.
    KPAS 그래프의 Supervisor와 수집기(collector)가 공통으로 사용합니다.

    Returns:
        (reports, errors)
        reports: {"news": ..., "SNS": ..., "disaster": ...} 중 성공한 에이전트의 보고서
        errors: 실패한 에이전트의 오류 메시지 목록
    """
    mcp_client = await MCPClientManager.get_client()
    all_tools = await mcp_client.get_tools()

    news_tools = [t for t in all_tools if t.name in NEWS_TOOLS]
    sns_tools = [t for t in all_tools if t.name in SNS_TOOLS]
    disaster_tools = [t for t in all_tools if t.name in DISASTER_TOOLS]

    parallel_results = await asyncio.gather(
        news_agent_node(state, news_tools),
        sns_agent_node(state, sns_tools),
        disaster_agent_node(state, disaster_tools),
        return_exceptions=True,
    )

    reports: Dict[str, Any] = {}
    errors: List[str] = []
    for agent_name, agent_result in zip(("news", "sns", "disaster"), parallel_results):
        if isinstance(agent_result, Exception):
            print(f"🚨 하위 에이전트({agent_name}) 실행 중 오류 발생: {agent_result}")
            errors.append(f"{agent_name} agent 실패: {agent_result}")
            continue
        agent_result.pop("messages", None)
        reports.update(agent_result)

    return reports, errors
