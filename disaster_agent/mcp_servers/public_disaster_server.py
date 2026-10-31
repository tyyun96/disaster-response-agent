import os
import requests
import urllib3
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from _utils import mask_secrets

# 저장소 루트 (disaster_agent/mcp_servers/ 기준 두 단계 위)
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

dotenv_path = os.path.join(project_root, '.env')
load_dotenv(dotenv_path=dotenv_path)

mcp = FastMCP("disaster_mcp_server")
KMA_WARNING_API_PATH = os.getenv("KMA_WARNING_API_PATH", "DSSP-IF-00045")


def fetch_safety_data(url: str, service_key: str, params: dict) -> dict:
    """재난안전데이터공유플랫폼 API 공통 호출 함수"""
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    if not service_key:
        return {'resultCode': '99', 'resultMsg': 'API 서비스 키가 설정되지 않았습니다.'}

    payloads = {
        "serviceKey": service_key,
        "returnType": "json",
        "pageNo": "1",
        "numOfRows": "50",
        **params,
    }

    try:
        response = requests.get(url, params=payloads, verify=False, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {'resultCode': '99', 'resultMsg': f'API 요청 실패: {mask_secrets(e)}'}
    except ValueError:
        return {'resultCode': '99', 'resultMsg': 'JSON 응답 파싱 실패'}


@mcp.tool()
def getDisasterMessage(search_date: str) -> dict:
    """
    특정 날짜(YYYYMMDD)의 긴급 재난 문자 정보를 수집합니다.
    :param search_date: 조회할 날짜 (YYYYMMDD 형식)
    """
    url = "https://www.safetydata.go.kr/V2/api/DSSP-IF-00247"
    return fetch_safety_data(url, os.getenv("DISASTER_MESSAGE_API_KEY"), {"crtDt": search_date})

@mcp.tool()
def getForestFires(search_date: str) -> dict:
    """
    특정 날짜(YYYYMMDD)의 산불 정보를 수집합니다.
    :param search_date: 조회할 날짜 (YYYYMMDD 형식)
    """
    url = "https://www.safetydata.go.kr/V2/api/DSSP-IF-10346"
    return fetch_safety_data(url, os.getenv("FOREST_FIRES_API_KEY"), {"startDt": search_date})


@mcp.tool()
def getKMAWeatherWarning(search_date: str) -> dict:
    """
    특정 날짜(YYYYMMDD)의 기상청 기상 재난 특보 정보를 수집합니다.
    :param search_date: 조회할 날짜 (YYYYMMDD 형식)
    """
    url = f"https://www.safetydata.go.kr/V2/api/{KMA_WARNING_API_PATH}"
    return fetch_safety_data(url, os.getenv("KMA_WEATHER_API_KEY"), {"inqDt": search_date})


if __name__ == "__main__":
    mcp.run(transport="stdio")
