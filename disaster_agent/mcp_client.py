import os

from langchain_mcp_adapters.client import MultiServerMCPClient

from disaster_agent.config import (
    DISASTER_MCP_SERVER_PATH,
    NEWS_MCP_SERVER_PATH,
    PYTHON_EXECUTABLE_PATH,
    SNS_MCP_SERVER_PATH,
)


def _stdio_server(script_path) -> dict:
    return {
        "command": PYTHON_EXECUTABLE_PATH,
        "args": [str(script_path)],
        "transport": "stdio",
        # MCP stdio 클라이언트는 기본적으로 일부 환경변수만 넘기므로 API 키를 명시적으로 전달
        "env": dict(os.environ),
    }


class MCPClientManager:
    """
    MultiServerMCPClient 인스턴스를 싱글톤으로 관리하는 클래스입니다.
    애플리케이션 전체에서 단 하나의 클라이언트 연결을 유지합니다.
    """
    client = None

    @classmethod
    async def get_client(cls) -> MultiServerMCPClient:
        """
        MCP 클라이언트 인스턴스를 생성하고 반환합니다.
        이미 인스턴스가 존재하면 기존 인스턴스를 반환합니다.
        """
        if cls.client is None:
            for path in (NEWS_MCP_SERVER_PATH, DISASTER_MCP_SERVER_PATH, SNS_MCP_SERVER_PATH):
                if not path.exists():
                    raise FileNotFoundError(f"MCP 서버 스크립트를 찾을 수 없습니다: {path}")

            cls.client = MultiServerMCPClient({
                "news_mcp_server": _stdio_server(NEWS_MCP_SERVER_PATH),
                "disaster_mcp_server": _stdio_server(DISASTER_MCP_SERVER_PATH),
                "SNS_mcp_server": _stdio_server(SNS_MCP_SERVER_PATH),
                # GPS 서버(gps_server.py)는 apps/location_collector.py와 함께 쓸 때만 활성화하세요.
            })
        return cls.client

    @classmethod
    async def close(cls) -> None:
        """MCP 클라이언트 연결을 종료합니다."""
        cls.client = None
