from functools import lru_cache

from langchain_openai import ChatOpenAI

from disaster_agent.config import MODEL_NAME, OPENAI_API_KEY


@lru_cache(maxsize=1)
def get_llm() -> ChatOpenAI:
    """
    ChatOpenAI 모델을 초기 설정과 함께 반환합니다. (최초 호출 시 1회 생성)
    자동 재시도 기능이 활성화되어 있습니다.
    """
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY 환경변수가 설정되지 않았습니다. .env 파일을 확인해주세요.")

    return ChatOpenAI(
        model=MODEL_NAME,
        temperature=0,
        max_retries=6,  # 오류 발생 시 6번까지 자동 재시도
        request_timeout=50,
        api_key=OPENAI_API_KEY,
    )
