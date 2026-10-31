import os
import sys
import json
import requests
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from typing import Dict, List, Any, Optional
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from _utils import mask_secrets

# --- 경로 설정 및 .env 로드 ---
# 저장소 루트 (disaster_agent/mcp_servers/ 기준 두 단계 위)
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
dotenv_path = os.path.join(project_root, '.env')
load_dotenv(dotenv_path=dotenv_path)

mcp = FastMCP("SNS_mcp_server")

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
YOUTUBE_API_SERVICE_NAME = "youtube"
YOUTUBE_API_VERSION = "v3"

def get_youtube_service():
    """Google API 클라이언트 서비스 객체를 생성하여 반환합니다."""
    if not YOUTUBE_API_KEY:
        return None
    try:
        service = build(YOUTUBE_API_SERVICE_NAME, YOUTUBE_API_VERSION, developerKey=YOUTUBE_API_KEY)
        return service
    except Exception as e:
        print(f"❌ YouTube 서비스 빌드 중 오류 발생: {e}", file=sys.stderr)
        return None

THREADS_BASE_URL = "https://graph.threads.net/v1.0"

def _get_replies_for_thread(media_id: str, access_token: str) -> List[Dict[str, Any]]:
    """주어진 게시물 ID에 대한 댓글(답글) 목록을 가져오는 헬퍼 함수입니다."""
    url = f"{THREADS_BASE_URL}/{media_id}/replies"
    params = {'access_token': access_token, 'fields': 'id,text,timestamp,author_id,permalink'}
    try:
        response = requests.get(url, params=params, timeout=5)
        if response.status_code == 200:
            return response.json().get('data', [])
    except requests.exceptions.RequestException:
        pass
    return []

@mcp.tool()
def get_fire_related_threads_with_replies(start_date: str, end_date: str, max_results: int = 20) -> str:
    """
    '화재' TAG가 포함된 최신 Threads 게시물을 검색합니다.
    API에서 받아온 데이터를 'start_date'와 'end_date' 사이의 기간으로 필터링합니다.
    :param start_date: 검색 시작일 (YYYY-MM-DD 형식의 문자열)
    :param end_date: 검색 종료일 (YYYY-MM-DD 형식의 문자열)
    :param max_results: 반환할 최대 결과 수 (기본 20)
    """
    ACCESS_TOKEN = os.getenv("THREADS_ACCESS_TOKEN")
    if not ACCESS_TOKEN:
        error_message = {"error": "THREADS_ACCESS_TOKEN이 .env 파일에 설정되지 않았습니다."}
        return json.dumps(error_message, indent=2, ensure_ascii=False)

    try:
        since_time_utc = datetime.strptime(start_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)
        until_time_utc = (datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)) - timedelta(seconds=1)
        until_time_utc = until_time_utc.replace(tzinfo=timezone.utc)
    except ValueError:
        return json.dumps({"error": "날짜 형식이 잘못되었습니다. 'YYYY-MM-DD' 형식을 사용하세요."}, indent=2, ensure_ascii=False)

    search_url = f"{THREADS_BASE_URL}/keyword_search"
    search_params = {
        'q': '화재',
        'search_mode': 'TAG',
        'search_type': 'RECENT',
        'access_token': ACCESS_TOKEN,
        'fields': 'id,text,timestamp,author_id,permalink,media_type',
        'limit': 5
    }
    
    final_result = []
    try:
        response = requests.get(search_url, params=search_params, timeout=10)
        response.raise_for_status()
        
        threads = response.json().get('data', [])
        if not threads:
            return json.dumps({"message": "'화재' 관련 게시물을 찾을 수 없습니다."}, indent=2, ensure_ascii=False)

        for thread in threads:
            if len(final_result) >= max_results:
                break
            
            try:
                post_time_utc = datetime.fromisoformat(thread['timestamp'])
                
                if since_time_utc <= post_time_utc <= until_time_utc:
                    thread_id = thread.get('id')
                    if thread_id:
                        replies = _get_replies_for_thread(thread_id, ACCESS_TOKEN)
                        thread['replies'] = replies
                    final_result.append(thread)
                        
            except (KeyError, ValueError, TypeError):
                continue 

        if not final_result:
            return json.dumps({"message": f"'{start_date}'부터 '{end_date}' 사이의 '화재' 관련 게시물을 찾을 수 없습니다."}, indent=2, ensure_ascii=False)

    except requests.exceptions.RequestException as e:
        details = "N/A"
        if e.response:
            try:
                details = e.response.json()
            except json.JSONDecodeError:
                details = e.response.text
        error_message = {"error": f"Threads API 요청 실패: {mask_secrets(e)}", "details": details}
        return json.dumps(error_message, indent=2, ensure_ascii=False)
    
    return json.dumps(final_result, indent=2, ensure_ascii=False)

@mcp.tool()
def searchVideos(query: str, max_results: int = 10, order: str = "date", 
                 publishedAfter: Optional[str] = None, 
                 publishedBefore: Optional[str] = None) -> dict:
    """
    쿼리 문자열을 기반으로 YouTube 동영상을 검색합니다. (search.list)
    'publishedAfter'와 'publishedBefore' (ISO 8601 형식)를 사용하여 특정 시간대 검색이 가능합니다.
    :param query: 검색할 키워드 (예: "서울역 화재")
    :param max_results: 반환할 최대 결과 수 (기본 10)
    :param order: 정렬 순서 (기본 'date', 'relevance', 'viewCount' 등)
    :param publishedAfter: 검색 시작 시점 (ISO 8601 형식, 예: "2023-04-10T14:00:00Z")
    :param publishedBefore: 검색 종료 시점 (ISO 8601 형식, 예: "2023-04-11T14:00:00Z")
    """
    youtube = get_youtube_service()
    if not youtube:
        return {"error": "YOUTUBE_API_KEY가 설정되지 않았거나 서비스 초기화에 실패했습니다."}
    
    try:
        search_params = {
            'q': query,
            'part': "snippet",
            'maxResults': max_results,
            'order': order,
            'type': "video"
        }
        
        if publishedAfter:
            search_params['publishedAfter'] = publishedAfter
        if publishedBefore:
            search_params['publishedBefore'] = publishedBefore
        
        search_response = youtube.search().list(**search_params).execute()
        return search_response
    
    except HttpError as e:
        return {"error": f"YouTube API 오류: {e.resp.status} {e.content.decode()}"}
    except Exception as e:
        return {"error": f"searchVideos 실행 중 알 수 없는 오류: {mask_secrets(e)}"}

@mcp.tool()
def getVideoDetails(video_ids: List[str]) -> dict:
    """
    하나 이상의 video ID 목록을 받아, 해당 동영상들의 세부 정보(통계, 콘텐츠 세부정보 포함)를 수집합니다. (videos.list)
    :param video_ids: YouTube 비디오 ID의 리스트 (예: ["videoId1", "videoId2"])
    """
    youtube = get_youtube_service()
    if not youtube:
        return {"error": "YOUTUBE_API_KEY가 설정되지 않았거나 서비스 초기화에 실패했습니다."}
        
    try:
        video_response = youtube.videos().list(
            part="snippet,contentDetails,statistics",
            id=",".join(video_ids)
        ).execute()
        return video_response
    except HttpError as e:
        return {"error": f"YouTube API 오류: {e.resp.status} {e.content.decode()}"}
    except Exception as e:
        return {"error": f"getVideoDetails 실행 중 알 수 없는 오류: {mask_secrets(e)}"}

@mcp.tool()
def getVideoComments(video_id: str, max_results: int = 30) -> dict:
    """
    특정 YouTube 동영상의 댓글을 검색합니다. (commentThreads.list)
    :param video_id: 댓글을 수집할 비디오의 ID
    :param max_results: 반환할 최대 댓글 수 (기본 30)
    """
    youtube = get_youtube_service()
    if not youtube:
        return {"error": "YOUTUBE_API_KEY가 설정되지 않았거나 서비스 초기화에 실패했습니다."}
        
    try:
        comment_response = youtube.commentThreads().list(
            part="snippet",
            videoId=video_id,
            maxResults=max_results,
            textFormat="plainText",
            order="relevance" 
        ).execute()
        return comment_response
    except HttpError as e:
        if e.resp.status == 403:
            return {"error": "이 동영상은 댓글이 비활성화되어 있습니다.", "items": []}
        return {"error": f"YouTube API 오류: {e.resp.status} {e.content.decode()}"}
    except Exception as e:
        return {"error": f"getVideoComments 실행 중 알 수 없는 오류: {mask_secrets(e)}"}

if __name__ == "__main__":
    mcp.run(transport="stdio")