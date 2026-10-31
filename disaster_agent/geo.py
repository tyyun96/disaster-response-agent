"""위치 관련 공통 유틸: 카카오 지오코딩, 거리 계산"""
import math
from datetime import datetime
from typing import List, Optional, Tuple

import requests

from disaster_agent.config import KAKAO_REST_API_KEY

# 카카오 API 키가 없거나 검색 실패 시 사용하는 주요 도시 좌표
CITY_SEEDS: List[Tuple[str, float, float]] = [
    ("서울", 37.5665, 126.9780),
    ("부산", 35.1796, 129.0756),
    ("대구", 35.8714, 128.6014),
    ("인천", 37.4563, 126.7052),
    ("광주", 35.1595, 126.8526),
    ("대전", 36.3504, 127.3845),
    ("울산", 35.5384, 129.3114),
    ("세종", 36.4875, 127.2817),
    ("수원", 37.2636, 127.0286),
    ("창원", 35.2281, 128.6811),
    ("제주", 33.4996, 126.5312),
]


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return radius * c


def guess_city_seed(location_text: str) -> Optional[Tuple[float, float]]:
    for city_name, lat, lon in CITY_SEEDS:
        if city_name in location_text:
            return lat, lon
    return None


def geocode_location(location_text: str) -> Optional[Tuple[float, float]]:
    """지명을 (위도, 경도)로 변환합니다. 카카오 주소 검색 → 키워드 검색 → 도시 좌표 순으로 시도"""
    if not KAKAO_REST_API_KEY:
        return guess_city_seed(location_text)

    headers = {"Authorization": f"KakaoAK {KAKAO_REST_API_KEY}"}
    candidates = [
        ("https://dapi.kakao.com/v2/local/search/address.json", {"query": location_text}),
        ("https://dapi.kakao.com/v2/local/search/keyword.json", {"query": location_text}),
    ]

    for url, params in candidates:
        try:
            response = requests.get(url, headers=headers, params=params, timeout=6)
            response.raise_for_status()
            docs = response.json().get("documents", [])
            if docs:
                y = docs[0].get("y")
                x = docs[0].get("x")
                if y and x:
                    return float(y), float(x)
        except requests.RequestException:
            continue

    return guess_city_seed(location_text)
