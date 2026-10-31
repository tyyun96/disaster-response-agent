import re

# 요청 URL 쿼리스트링에 포함된 인증 값 (requests 예외 메시지에 URL이 그대로 들어감)
_SECRET_PARAM_PATTERN = re.compile(r"(?i)\b(servicekey|access_token|api_key|apikey|key)=[^&\s'\"]+")


def mask_secrets(error) -> str:
    """오류 메시지에서 API 키/토큰 값을 가립니다. (LLM 보고서와 저장 로그로 키가 새는 것을 방지)"""
    return _SECRET_PARAM_PATTERN.sub(r"\1=***", str(error))
