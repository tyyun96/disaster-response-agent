import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# --- 경로 ---
PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent

# 프로젝트 루트의 .env 파일에서 환경 변수를 로드 (실행 위치와 무관)
load_dotenv(PROJECT_ROOT / ".env")

# --- API Keys ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")
KAKAO_REST_API_KEY = os.getenv("KAKAO_REST_API_KEY")
THREADS_ACCESS_TOKEN = os.getenv("THREADS_ACCESS_TOKEN")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")

# --- Public Data API Keys (재난안전데이터공유플랫폼) ---
YONHAP_NEWS_API_KEY = os.getenv("YONHAP_NEWS_API_KEY")
DISASTER_MESSAGE_API_KEY = os.getenv("DISASTER_MESSAGE_API_KEY")
FOREST_FIRES_API_KEY = os.getenv("FOREST_FIRES_API_KEY")
KMA_WEATHER_API_KEY = os.getenv("KMA_WEATHER_API_KEY")

# --- 외부 REST API 보호용 키 (apps/api.py) ---
EXTERNAL_API_KEY = os.getenv("EXTERNAL_API_KEY")

# --- Model & LangGraph Settings ---
MODEL_NAME = os.getenv("OPENAI_MODEL", "gpt-4o")
RECURSION_LIMIT = 50
# 1이면 하위 에이전트의 전체 실행 로그(메시지 목록)를 출력합니다.
VERBOSE = os.getenv("AGENT_VERBOSE", "0") == "1"

# --- MCP 서버 실행 설정 ---
# 기본값: 현재 실행 중인 Python + 패키지 내부 mcp_servers 디렉토리
PYTHON_EXECUTABLE_PATH = os.getenv("PYTHON_EXECUTABLE_PATH") or sys.executable
MCP_SERVER_SCRIPT_DIR = Path(os.getenv("MCP_SERVER_SCRIPT_DIR") or PACKAGE_DIR / "mcp_servers")
NEWS_MCP_SERVER_PATH = MCP_SERVER_SCRIPT_DIR / "news_server.py"
SNS_MCP_SERVER_PATH = MCP_SERVER_SCRIPT_DIR / "sns_server.py"
DISASTER_MCP_SERVER_PATH = MCP_SERVER_SCRIPT_DIR / "public_disaster_server.py"
GPS_MCP_SERVER_PATH = MCP_SERVER_SCRIPT_DIR / "gps_server.py"
GPS_LOCATION_FILE = PROJECT_ROOT / "outputs" / "location.json"

# --- RAG ---
DATA_DIR = PROJECT_ROOT / "data"
RAG_DOCUMENTS_PATH = DATA_DIR / "rag_documents"
CHROMA_DB_PATH = DATA_DIR / "chroma_db"

# --- 실행 결과 저장 위치 (git에 올라가지 않음) ---
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
COLLECTOR_SNAPSHOT_DIR = OUTPUTS_DIR / "collector" / "snapshots"
ALERT_MONITOR_DIR = OUTPUTS_DIR / "alert_monitor"
