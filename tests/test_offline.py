"""API 키 / 네트워크 없이 실행되는 단위 테스트:  python -m pytest"""
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from disaster_agent.alert_monitor import monitor
from disaster_agent.alert_monitor.subscribers import (
    Subscriber,
    generate_mock_subscribers,
    load_subscribers,
    save_subscribers,
)
from disaster_agent.collector import incidents as collector_incidents
from disaster_agent.collector.service import build_collection_text
from disaster_agent.geo import guess_city_seed, haversine_km

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "disaster_agent" / "mcp_servers"))
from _utils import mask_secrets  # noqa: E402


def test_haversine_seoul_busan():
    assert 320 < haversine_km(37.5665, 126.9780, 35.1796, 129.0756) < 330


def test_guess_city_seed():
    assert guess_city_seed("부산광역시 해운대구") == (35.1796, 129.0756)
    assert guess_city_seed("어딘가") is None


def test_collector_regex_extraction():
    reports = {
        "news": "경기도 가평군 가평읍 개곡리에서 산불이 발생해 주민 대피 중",
        "sns": "오늘 날씨 맑음",
        "disaster": "",
    }
    result = collector_incidents.extract_incidents_by_regex(reports)
    assert result
    assert result[0]["source"] == "NEWS"
    assert result[0]["incident_type"] == "산불"
    assert "가평군" in result[0]["location_text"]


def test_scope_filter(monkeypatch):
    monkeypatch.setattr(collector_incidents, "geocode_location", lambda _: (37.5665, 126.9780))
    items = [
        {"location_text": "서울 마포구", "summary": "", "latitude": 37.56, "longitude": 126.90},
        {"location_text": "부산 해운대구", "summary": "", "latitude": 35.16, "longitude": 129.16},
    ]
    assert len(collector_incidents.filter_incidents_by_scope(items, "대한민국")) == 2
    filtered = collector_incidents.filter_incidents_by_scope(items, "서울특별시")
    assert [i["location_text"] for i in filtered] == ["서울 마포구"]


def test_build_collection_text():
    text = build_collection_text(
        {"metadata": {"location": "신촌"}, "reports": {"news": "뉴스 보고서"}, "errors": ["sns agent 실패"]}
    )
    assert "- 위치: 신촌" in text
    assert "뉴스 보고서" in text
    assert "sns agent 실패" in text
    assert "[DISASTER]\n수집 결과 없음" in text


def test_monitor_alert_rules():
    assert monitor.should_alert("서울 화재 발생, 주민 대피")
    assert not monitor.should_alert("화재 대피 관련 특이사항 없음")

    incident = monitor.Incident("화재", "서울 마포구", "마포구 화재", 0.9, evidence=["[NEWS] 마포구 화재 발생"])
    assert monitor.build_alert_fingerprint(incident) == monitor.build_alert_fingerprint(incident)

    message = monitor.build_notification_message(incident)
    assert "발생 판단 출처: NEWS" in message

    near = Subscriber("u1", 37.5663, 126.9019, radius_km=3.0)
    far = Subscriber("u2", 35.1796, 129.0756, radius_km=3.0)
    selected = monitor.select_nearby_subscribers([near, far], 37.5663, 126.9019)
    assert [s.user_id for s, _ in selected] == ["u1"]


def test_subscribers_roundtrip(tmp_path):
    generated = generate_mock_subscribers(5, seed=42)
    assert generated == generate_mock_subscribers(5, seed=42)

    path = tmp_path / "subscribers.json"
    save_subscribers(generated, path=path)
    assert load_subscribers(path=path) == generated


def test_mask_secrets():
    error = "403 Client Error for url: https://x.go.kr/api?serviceKey=ABC123&returnType=json"
    masked = mask_secrets(error)
    assert "ABC123" not in masked
    assert "serviceKey=***" in masked
    assert "access_token=***" in mask_secrets("https://graph.threads.net/v1.0/x?access_token=TOKEN")


def test_streamlit_app_renders():
    from streamlit.testing.v1 import AppTest

    app_path = Path(__file__).resolve().parents[1] / "disaster_agent" / "apps" / "streamlit_app.py"
    at = AppTest.from_file(str(app_path)).run()
    assert not at.exception
    assert at.title[0].value == "🚨 재난 대응 AI 에이전트"


def test_api_and_kakao_health():
    from disaster_agent.apps.api import app as api_app
    from disaster_agent.apps.kakao import app as kakao_app

    assert TestClient(api_app).get("/health").json() == {"status": "OK"}

    kakao_client = TestClient(kakao_app)
    assert kakao_client.get("/health").json() == {"status": "OK"}

    payload = {
        "intent": {"id": "i", "name": "n"},
        "userRequest": {
            "timezone": "Asia/Seoul",
            "params": {},
            "block": {"id": "b", "name": "n"},
            "utterance": "신촌 화재 상황 알려줘",
            "user": {"id": "user-1", "type": "botUserKey", "properties": {}},
        },
        "bot": {"id": "bot", "name": "bot"},
        "action": {"name": "a", "params": {}, "id": "a", "detailParams": {}},
    }
    response = kakao_client.post("/skill/chat", json=payload).json()
    assert "콜백 URL 누락" in response["template"]["outputs"][0]["simpleText"]["text"]
