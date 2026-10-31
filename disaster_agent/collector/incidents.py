"""수집 보고서에서 사건(위치 + 요약)을 추출하고, 좌표를 붙이고, 요청 지역 기준으로 필터링합니다."""
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from disaster_agent.collector.service import collect_disaster_data
from disaster_agent.geo import geocode_location, haversine_km, now_str
from disaster_agent.llm import get_llm

RISK_KEYWORDS = {
    "화재",
    "산불",
    "재난",
    "대피",
    "연기",
    "폭발",
    "경보",
    "주의보",
}

LOCATION_PATTERN = re.compile(
    r"([가-힣]{2,}(?:특별시|광역시|자치시|도|시|군|구|읍|면|동)(?:\s+[가-힣0-9-]{1,}(?:시|군|구|읍|면|동|리))?)"
)

NATIONWIDE_SCOPES = {"대한민국", "전국", "한국", "국내"}


class IncidentCandidate(BaseModel):
    incident_type: str = Field(default="재난")
    location_text: str = Field(default="")
    source: str = Field(default="UNKNOWN")
    summary: str = Field(default="")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class IncidentExtraction(BaseModel):
    incidents: List[IncidentCandidate] = Field(default_factory=list)


def build_combined_report_text(reports: Dict[str, str]) -> str:
    return "\n\n".join(
        [
            f"[NEWS]\n{reports.get('news', '')}",
            f"[SNS]\n{reports.get('sns', '')}",
            f"[DISASTER]\n{reports.get('disaster', '')}",
        ]
    )


def infer_incident_type(text: str) -> str:
    if "산불" in text:
        return "산불"
    if "화재" in text:
        return "화재"
    return "재난"


async def extract_incidents_with_llm(reports: Dict[str, str]) -> List[Dict[str, Any]]:
    combined_text = build_combined_report_text(reports)
    if not any(reports.get(key, "").strip() for key in ("news", "sns", "disaster")):
        return []

    prompt = f"""
당신은 재난 사건 추출기입니다.
아래 수집 데이터에서 '실제 발생했거나 매우 임박한 화재/산불/재난 사건'만 추출하세요.
예방 수칙이나 일반 설명은 제외하세요.

출력 규칙:
1) location_text는 한국어 지명으로 작성
2) source는 반드시 NEWS, SNS, DISASTER 중 하나
3) confidence는 0.0~1.0
4) 최대 20건

수집 데이터:
{combined_text[:12000]}
"""

    try:
        structured_llm = get_llm().with_structured_output(IncidentExtraction)
        parsed = await structured_llm.ainvoke(prompt)
    except Exception:
        return []

    incidents: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in parsed.incidents:
        location = item.location_text.strip()
        if not location:
            continue
        source = (item.source or "UNKNOWN").upper().strip()
        if source not in {"NEWS", "SNS", "DISASTER"}:
            source = "UNKNOWN"
        summary = item.summary.strip() or "수집 데이터에서 위험 신호 감지"
        key = (source, location, summary[:120])
        if key in seen:
            continue
        seen.add(key)
        incidents.append(
            {
                "incident_type": infer_incident_type(item.incident_type + " " + summary),
                "location_text": location,
                "source": source,
                "summary": summary,
                "confidence": float(item.confidence),
            }
        )
    return incidents


def extract_incidents_by_regex(reports: Dict[str, str]) -> List[Dict[str, Any]]:
    """LLM 추출이 실패했을 때 사용하는 키워드 + 지명 정규식 기반 폴백"""
    incidents: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for source_key in ("news", "sns", "disaster"):
        text = reports.get(source_key, "")
        source = source_key.upper()
        for raw_line in text.splitlines():
            line = " ".join(raw_line.split()).strip()
            if len(line) < 10:
                continue
            if not any(keyword in line for keyword in RISK_KEYWORDS):
                continue
            for location in LOCATION_PATTERN.findall(line):
                location = location.strip()
                if not location:
                    continue
                key = (source, location, line[:120])
                if key in seen:
                    continue
                seen.add(key)
                incidents.append(
                    {
                        "incident_type": infer_incident_type(line),
                        "location_text": location,
                        "source": source,
                        "summary": line[:300],
                        "confidence": 0.35,
                    }
                )
    return incidents


def enrich_incidents_with_coordinates(incidents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    for incident in incidents:
        coords = geocode_location(incident.get("location_text", ""))
        incident["latitude"] = coords[0] if coords else None
        incident["longitude"] = coords[1] if coords else None
    return incidents


# --- 요청 지역(scope) 기준 필터링 ---

def _normalize_text(value: str) -> str:
    return "".join(value.split()).lower()


def is_nationwide_scope(scope: str) -> bool:
    return _normalize_text(scope) in NATIONWIDE_SCOPES


def scope_radius_km(scope: str) -> float:
    if any(token in scope for token in ("특별시", "광역시", "자치시", "도")):
        return 80.0
    if any(token in scope for token in ("시", "군", "구")):
        return 25.0
    if any(token in scope for token in ("읍", "면", "동", "리", "역")):
        return 8.0
    return 10.0


def is_incident_related_to_scope(
    incident: Dict[str, Any],
    scope: str,
    scope_coords: Optional[Tuple[float, float]],
) -> bool:
    scope_normalized = _normalize_text(scope)
    incident_text = _normalize_text(f"{incident.get('location_text', '')} {incident.get('summary', '')}")

    if scope_normalized and scope_normalized in incident_text:
        return True

    if scope_coords:
        latitude = incident.get("latitude")
        longitude = incident.get("longitude")
        if latitude is not None and longitude is not None:
            distance = haversine_km(scope_coords[0], scope_coords[1], latitude, longitude)
            if distance <= scope_radius_km(scope):
                return True

    return False


def filter_incidents_by_scope(incidents: List[Dict[str, Any]], scope: str) -> List[Dict[str, Any]]:
    if is_nationwide_scope(scope):
        return incidents

    scope_coords = geocode_location(scope)
    return [
        incident
        for incident in incidents
        if is_incident_related_to_scope(incident, scope, scope_coords)
    ]


async def enrich_snapshot_with_incidents(snapshot: Dict[str, Any], scope: str) -> Dict[str, Any]:
    """수집 결과(snapshot)에 incidents 목록과 관련 메타데이터를 추가합니다."""
    reports = snapshot.get("reports", {})
    incidents = await extract_incidents_with_llm(reports)
    if not incidents:
        incidents = extract_incidents_by_regex(reports)
    incidents = enrich_incidents_with_coordinates(incidents)
    incidents_before_filter = len(incidents)
    incidents = filter_incidents_by_scope(incidents, scope)

    metadata = snapshot.setdefault("metadata", {})
    metadata["incident_extracted_at"] = now_str()
    metadata["incident_count_before_scope_filter"] = incidents_before_filter
    metadata["incident_count"] = len(incidents)
    metadata["geocoded_count"] = sum(
        1
        for incident in incidents
        if incident.get("latitude") is not None and incident.get("longitude") is not None
    )
    snapshot["incidents"] = incidents
    return snapshot


async def run_collection_flow(
    location: str,
    scenario_time: Optional[str] = None,
    question: Optional[str] = None,
    thread_id: Optional[str] = None,
) -> Dict[str, Any]:
    """수집 → 사건 추출 → 좌표 변환 → 지역 필터링까지 한 번에 실행합니다."""
    kwargs = {"question": question} if question else {}
    snapshot = await collect_disaster_data(
        location=location,
        scenario_time=scenario_time,
        thread_id=thread_id or f"kpas-collection-session-{uuid.uuid4()}",
        **kwargs,
    )
    return await enrich_snapshot_with_incidents(snapshot, location)
