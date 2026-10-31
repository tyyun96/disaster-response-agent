import os
import sys
import json
import requests
import urllib3
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from trafilatura import extract, extract_metadata

from _utils import mask_secrets

# --- 경로 설정 및 .env 로드 ---
# 저장소 루트 (disaster_agent/mcp_servers/ 기준 두 단계 위)
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
dotenv_path = os.path.join(project_root, '.env')
load_dotenv(dotenv_path=dotenv_path)

mcp = FastMCP("news_mcp_server")

SERPAPI_API_KEY = os.getenv("SERP_API_KEY")
YONHAP_API_PATH = os.getenv("YONHAP_API_PATH", "DSSP-IF-10747")

@mcp.tool()
def get_naver_news(query: str, display: int = 5, start: int = 1, sort: str = "sim") -> dict:
    """네이버 검색 API를 사용하여 뉴스를 검색합니다."""
    url = "https://openapi.naver.com/v1/search/news.json"
    params = {'query': query, 'display': display, 'start': start, 'sort': sort}
    headers = {
        'X-Naver-Client-Id': os.getenv("NAVER_CLIENT_ID"),
        'X-Naver-Client-Secret': os.getenv("NAVER_CLIENT_SECRET")
    }
    
    if not headers['X-Naver-Client-Id'] or not headers['X-Naver-Client-Secret']:
        return {'status': 'error', 'message': '네이버 API 키가 .env 파일에 설정되지 않았습니다.'}

    try:
        response = requests.get(url, params=params, headers=headers, timeout=5)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {'status': 'error', 'message': mask_secrets(e)}

@mcp.tool()
def get_yonhap_news(date: str) -> dict:
    """
    연합 뉴스를 검색하고 입력된 날짜(date)에 해당하는 뉴스만 필터링하여 반환합니다.
    param date: 'YYYYMMDD' 형식의 문자열 (예: '20240130')
    """
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    url = f"https://www.safetydata.go.kr/V2/api/{YONHAP_API_PATH}"
    serviceKey = os.getenv("YONHAP_NEWS_API_KEY")
    if not serviceKey:
        return {'status': 'error', 'message': '연합뉴스 API 키가 .env 파일에 설정되지 않았습니다.'}
    
    payloads = {
        "serviceKey": serviceKey,
        "returnType": "json",
        "pageNo": "1",
        "numOfRows": "100",
        "inqDt": date 
    }

    try:
        response = requests.get(url, params=payloads, verify=False, timeout=10)
        response.raise_for_status()
        
        try:
            data = response.json()
            
            # 결과값이 정상적으로 body를 포함하는지 확인
            if 'body' in data and isinstance(data['body'], list):
                original_count = len(data['body'])
                
                # 날짜 포맷 변환 (YYYYMMDD -> YYYY-MM-DD)
                target_date_prefix = f"{date[:4]}-{date[4:6]}-{date[6:]}"
                
                # 리스트 컴프리헨션을 사용하여 날짜 필터링
                # YNA_YMD 필드가 해당 날짜 문자열로 시작하는지 확인
                filtered_body = [
                    item for item in data['body'] 
                    if item.get('YNA_YMD', '').startswith(target_date_prefix)
                ]
                
                # 필터링된 데이터로 body 교체 및 메타데이터 업데이트
                data['body'] = filtered_body
                data['filtered_count'] = len(filtered_body)
                data['original_fetch_count'] = original_count
                
                print(f"✅ 데이터 필터링 완료: {original_count}개 중 {len(filtered_body)}개 추출됨 ({target_date_prefix})", file=sys.stderr)
                
            return data

        except json.JSONDecodeError:
            return {'status': 'error', 'message': 'JSON 디코딩 실패', 'raw_text': response.text}
            
    except requests.exceptions.RequestException as e:
        return {'status': 'error', 'message': mask_secrets(e)}

@mcp.tool()
def scrape(url: str) -> str:
    """
    무료 로컬 추출기(trafilatura) 기반으로 뉴스 기사 본문을 JSON 문자열로 반환합니다.
    - 외부 유료 크롤링 API를 사용하지 않습니다.
    - MCP 호환을 위해 항상 문자열(JSON)로 반환합니다.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    try:
        response = requests.get(
            url,
            headers=headers,
            timeout=10,
            allow_redirects=True,
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        return json.dumps(
            {"status": "error", "message": f"기사 요청 실패: {mask_secrets(e)}"},
            ensure_ascii=False,
            indent=2,
        )

    if not response.encoding or response.encoding.lower() == "iso-8859-1":
        response.encoding = response.apparent_encoding

    html = response.text

    try:
        body = extract(
            html,
            url=response.url,
            favor_precision=True,
            include_comments=False,
            include_tables=False,
            include_images=False,
            include_links=False,
            deduplicate=True,
            no_fallback=False,
            output_format="txt",
        )
        metadata = extract_metadata(html, default_url=response.url)
    except Exception as e:
        return json.dumps(
            {"status": "error", "message": f"Trafilatura 추출 중 예외 발생: {e}"},
            ensure_ascii=False,
            indent=2,
        )

    body = (body or "").strip()
    paragraphs = [line.strip() for line in body.splitlines() if line.strip()]

    if not body:
        return json.dumps(
            {
                "status": "error",
                "message": "Trafilatura가 기사 본문을 추출하지 못했습니다.",
                "url": response.url,
            },
            ensure_ascii=False,
            indent=2,
        )

    title = None
    published_at = None
    if metadata is not None:
        title = getattr(metadata, "title", None) or None
        published_at = getattr(metadata, "date", None) or None

    result = {
        "status": "ok",
        "url": response.url,
        "extracted": {
            "title": title,
            "published_at": published_at,
            "body": body,
            "paragraphs": paragraphs,
        },
    }
    return json.dumps(result, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
