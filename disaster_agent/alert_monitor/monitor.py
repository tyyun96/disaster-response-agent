"""
주기 재난 모니터링 + 구독자 위치 기반 알림 서비스

KPAS 그래프로 전국 재난 상황을 분석 → 사건 추출 → 좌표 변환 → 반경 내 구독자에게
RAG 기반 맞춤형 대응 요령을 포함한 알림 전송 → 날짜별 로그 및 RAG 팀 전달용 JSON 저장

    python -m disaster_agent.alert_monitor --once
    python -m disaster_agent.alert_monitor --interval-seconds 600 --cooldown-minutes 60
"""
import argparse
import asyncio
import hashlib
import json
import re
import time
import uuid
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from disaster_agent.alert_monitor.subscribers import SUBSCRIBERS_FILE, Subscriber, load_subscribers
from disaster_agent.config import ALERT_MONITOR_DIR
from disaster_agent.geo import geocode_location, haversine_km, now_str
from disaster_agent.kpas.workflow import run_kpas_graph
from disaster_agent.llm import get_llm
from disaster_agent.rag.vector_store import get_retriever

HISTORY_FILE = ALERT_MONITOR_DIR / "alert_history.json"
DISASTER_LOGS_DIR = ALERT_MONITOR_DIR / "disaster_logs"
RAG_OUTPUT_DIR = ALERT_MONITOR_DIR / "rag_export"  # RAG 팀 전달용 디렉토리

DEFAULT_MONITOR_QUESTION = (
    "현재 시점 기준으로 대한민국 화재/재난 상황을 탐지하고 "
    "발생 위치와 위험도를 포함해 분석해줘"
)
DEFAULT_SCOPE = "대한민국"
DEFAULT_INTERVAL_SECONDS = 600
DEFAULT_COOLDOWN_MINUTES = 60
DEFAULT_EVIDENCE_LIMIT = 3
DEFAULT_RESPONSE_GUIDE_LIMIT = 3
MAX_LOG_ENTRIES_PER_FILE = 500

RISK_KEYWORDS = {
    "화재",
    "산불",
    "재난",
    "대피",
    "긴급",
    "확산",
    "통제",
    "인명피해",
    "연기",
    "폭발",
    "주의보",
    "경보",
}
SAFE_HINTS = {
    "수집된 정보 없음",
    "관련 게시물을 찾을 수 없습니다",
    "특이사항 없음",
    "발견되지 않았습니다",
    "오류 발생",
    "시스템 오류",
}


@dataclass
class Incident:
    incident_type: str
    location_text: str
    summary: str
    confidence: float
    evidence: List[str] = field(default_factory=list)
    response_guide: List[str] = field(default_factory=list)
    latitude: Optional[float] = None
    longitude: Optional[float] = None


@dataclass
class DisasterLogEntry:
    """날짜별 JSON 로그에 저장될 재난 정보"""
    timestamp: str
    incident_type: str
    location_text: str
    latitude: Optional[float]
    longitude: Optional[float]
    summary: str
    confidence: float
    evidence: List[str]
    sources: Dict[str, str]
    fingerprint: str
    notified_users: int = 0


@dataclass
class RAGDocument:
    """RAG 팀에 전달할 경량화된 포맷 (필요한 소스 원본만 포함)"""
    document_id: str
    timestamp: str  # 수집 시각
    incident_type: str  # 화재/산불/재난
    location_text: str  # 위치명
    latitude: float
    longitude: float
    summary: str  # 사건 요약
    confidence: float  # 신뢰도
    keywords: List[str]  # 추출된 키워드
    source_snippets: Dict[str, str]  # 사건 관련 원본 발췌 (NEWS/SNS/DISASTER/FINAL)


class IncidentCandidate(BaseModel):
    incident_type: str = Field(default="화재")
    location_text: str = Field(default="")
    summary: str = Field(default="")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: List[str] = Field(default_factory=list)


class IncidentExtraction(BaseModel):
    incidents: List[IncidentCandidate] = Field(default_factory=list)


class EvidenceExtraction(BaseModel):
    """근거 추출을 위한 Pydantic 모델"""
    evidence: List[str] = Field(default_factory=list, description="구체적인 증거 문장 리스트")


class ActionGuideExtraction(BaseModel):
    """대응 요령 추출을 위한 Pydantic 모델"""
    guides: List[str] = Field(default_factory=list, description="맞춤형 행동 지침 리스트")


# --- 날짜별 재난 로그 ---

def today_date_str() -> str:
    """오늘 날짜 문자열 (YYYY-MM-DD)"""
    return datetime.now().strftime("%Y-%m-%d")


def get_disaster_log_file(date_str: Optional[str] = None) -> Path:
    """날짜별 재난 로그 파일 경로 반환"""
    if date_str is None:
        date_str = today_date_str()
    return DISASTER_LOGS_DIR / f"disaster_log_{date_str}.json"


def get_rag_output_file() -> Path:
    """RAG 팀 전달용 JSON 파일 경로 (타임스탬프 포함)"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return RAG_OUTPUT_DIR / f"rag_incidents_{timestamp}.json"


def _empty_log(date_str: Optional[str]) -> Dict[str, Any]:
    return {
        "date": date_str or today_date_str(),
        "created_at": now_str(),
        "last_updated": now_str(),
        "incidents": [],
    }


def load_disaster_log(date_str: Optional[str] = None) -> Dict[str, Any]:
    """날짜별 재난 로그 로드"""
    log_file = get_disaster_log_file(date_str)
    if not log_file.exists():
        return _empty_log(date_str)

    try:
        return json.loads(log_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return _empty_log(date_str)


def save_disaster_log(log_data: Dict[str, Any], date_str: Optional[str] = None) -> None:
    """날짜별 재난 로그 저장"""
    log_file = get_disaster_log_file(date_str)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_data["last_updated"] = now_str()

    incidents = log_data.get("incidents", [])
    if len(incidents) > MAX_LOG_ENTRIES_PER_FILE:
        print(f"[{now_str()}] 로그 파일이 {MAX_LOG_ENTRIES_PER_FILE}개 초과, 최신 항목만 유지")
        log_data["incidents"] = incidents[-MAX_LOG_ENTRIES_PER_FILE:]

    log_file.write_text(
        json.dumps(log_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def is_duplicate_in_log(
        log_data: Dict[str, Any],
        fingerprint: str,
        cooldown_sec: int,
) -> bool:
    """로그 파일 내 중복 체크"""
    now_ts = int(time.time())

    for entry in log_data.get("incidents", []):
        if entry.get("fingerprint") != fingerprint:
            continue

        timestamp_str = entry.get("timestamp", "")
        try:
            entry_dt = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
            entry_ts = int(entry_dt.timestamp())

            if now_ts - entry_ts < cooldown_sec:
                return True
        except ValueError:
            continue

    return False


def add_incident_to_log(
        incident: Incident,
        reports: Dict[str, str],
        fingerprint: str,
        notified_count: int,
        date_str: Optional[str] = None,
) -> None:
    """재난 정보를 로그에 추가"""
    log_data = load_disaster_log(date_str)

    log_entry = DisasterLogEntry(
        timestamp=now_str(),
        incident_type=incident.incident_type,
        location_text=incident.location_text,
        latitude=incident.latitude,
        longitude=incident.longitude,
        summary=incident.summary,
        confidence=incident.confidence,
        evidence=incident.evidence,
        sources={
            "news": reports.get("news", "")[:1000],
            "sns": reports.get("sns", "")[:1000],
            "disaster": reports.get("disaster", "")[:1000],
        },
        fingerprint=fingerprint,
        notified_users=notified_count,
    )

    log_data["incidents"].append(asdict(log_entry))
    save_disaster_log(log_data, date_str)

    print(f"[{now_str()}] 재난 로그 저장 완료: {incident.location_text} (파일: {get_disaster_log_file(date_str).name})")


# --- RAG 팀 전달용 ---

def extract_keywords_from_text(text: str) -> List[str]:
    """텍스트에서 키워드 추출"""
    return sorted({keyword for keyword in RISK_KEYWORDS if keyword in text})


def build_source_snippets(incident: Incident, reports: Dict[str, str]) -> Dict[str, str]:
    """Agent가 본 원문 그대로 저장 (소스별 최대 2000자)"""
    snippets = {}
    for source_name in ("news", "sns", "disaster", "final"):
        text = reports.get(source_name, "").strip()
        if text:
            snippets[source_name] = text[:2000]

    # 모든 소스가 비었으면 summary라도 넣기
    if not snippets:
        snippets["summary_based"] = f"소스 정보 없음. 사건 요약: {incident.summary}"

    return snippets


def generate_document_id(incident: Incident) -> str:
    """문서 ID 생성"""
    date_str = datetime.now().strftime("%Y%m%d")
    location_slug = incident.location_text.replace(" ", "-")
    type_slug = incident.incident_type.replace("/", "-")

    return f"{date_str}-{type_slug}-{location_slug}-{uuid.uuid4().hex[:8]}"


def convert_incident_to_rag_document(
        incident: Incident,
        reports: Dict[str, str],
) -> RAGDocument:
    """Incident를 RAG 팀 경량 포맷으로 변환 (필요한 소스 원본만)"""
    return RAGDocument(
        document_id=generate_document_id(incident),
        timestamp=now_str(),
        incident_type=incident.incident_type,
        location_text=incident.location_text,
        latitude=incident.latitude,
        longitude=incident.longitude,
        summary=incident.summary,
        confidence=incident.confidence,
        keywords=extract_keywords_from_text(incident.summary),
        source_snippets=build_source_snippets(incident, reports),
    )


def save_rag_documents(documents: List[RAGDocument]) -> Optional[Path]:
    """RAG 팀 전달용 JSON 파일 저장"""
    if not documents:
        print(f"[{now_str()}] RAG 저장할 문서 없음")
        return None

    output_file = get_rag_output_file()
    output_file.parent.mkdir(parents=True, exist_ok=True)

    output_data = {
        "schema_version": "v2.0",  # 경량화 버전
        "export_timestamp": now_str(),
        "total_documents": len(documents),
        "documents": [asdict(doc) for doc in documents],
    }

    output_file.write_text(
        json.dumps(output_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"[{now_str()}] ✅ RAG 출력 저장: {output_file.name} ({len(documents)}건)")
    return output_file


# --- 구독자 / 중복 알림 관리 ---

def get_subscribers_or_log(default_radius_km: float) -> List[Subscriber]:
    subscribers = load_subscribers(default_radius_km=default_radius_km)
    if subscribers:
        return subscribers

    print(
        f"[{now_str()}] '{SUBSCRIBERS_FILE.name}'에 구독자 정보가 없습니다. 알림 전송을 건너뜁니다. "
        "(python -m disaster_agent.alert_monitor.subscribers 로 mock 구독자를 생성할 수 있습니다)"
    )
    return []


def select_nearby_subscribers(
        subscribers: List[Subscriber], center_lat: float, center_lon: float
) -> List[Tuple[Subscriber, float]]:
    selected: List[Tuple[Subscriber, float]] = []
    for sub in subscribers:
        dist = haversine_km(center_lat, center_lon, sub.latitude, sub.longitude)
        if dist <= sub.radius_km:
            selected.append((sub, dist))
    return selected


def should_alert(result_text: str) -> bool:
    compact = result_text.replace(" ", "")
    if any(hint.replace(" ", "") in compact for hint in SAFE_HINTS):
        return False
    hit_count = sum(1 for keyword in RISK_KEYWORDS if keyword in result_text)
    return hit_count >= 2


def load_history() -> Dict[str, Any]:
    if not HISTORY_FILE.exists():
        return {"alerts": []}
    try:
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"alerts": []}


def save_history(history: Dict[str, Any]) -> None:
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(
        json.dumps(history, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def build_alert_fingerprint(incident: Incident) -> str:
    raw = f"{incident.incident_type}|{incident.location_text}|{' '.join(incident.summary.split())[:500]}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def is_duplicate_alert(history: Dict[str, Any], fingerprint: str, cooldown_sec: int) -> bool:
    now_ts = int(time.time())
    for item in history.get("alerts", []):
        if item.get("fingerprint") != fingerprint:
            continue
        sent_at = int(item.get("sent_at", 0))
        if now_ts - sent_at < cooldown_sec:
            return True
    return False


def remember_alert(history: Dict[str, Any], fingerprint: str) -> None:
    alerts = history.setdefault("alerts", [])
    alerts.append({"fingerprint": fingerprint, "sent_at": int(time.time())})
    history["alerts"] = alerts[-500:]


# --- 분석 실행 ---

async def run_monitor_workflow(question: str, scope: str) -> Dict[str, str]:
    result = await run_kpas_graph(
        question=question,
        gps=scope,
        thread_id=f"monitor-session-{uuid.uuid4()}",
    )
    return {
        "final": result.get("messages", [])[-1].content if result.get("messages") else "",
        "news": result.get("news", ""),
        "sns": result.get("SNS", ""),
        "disaster": result.get("disaster", ""),
    }


def build_combined_report_text(reports: Dict[str, str]) -> str:
    return "\n\n".join(
        [
            f"[NEWS]\n{reports.get('news', '')}",
            f"[SNS]\n{reports.get('sns', '')}",
            f"[DISASTER]\n{reports.get('disaster', '')}",
            f"[FINAL]\n{reports.get('final', '')}",
        ]
    )


# --- 근거 추출 ---

def _candidate_evidence_lines(text: str, keyword: Optional[str] = None) -> List[str]:
    lines: List[str] = []
    for raw_line in text.splitlines():
        line = " ".join(raw_line.split()).strip()
        if len(line) < 12:
            continue
        if keyword and keyword not in line:
            continue
        if any(k in line for k in RISK_KEYWORDS):
            lines.append(line)
    return lines


def build_incident_evidence(incident: Incident, reports: Dict[str, str]) -> List[str]:
    """폴백용 키워드 기반 근거 추출 함수"""
    evidence_pool: List[str] = []
    source_map = {
        "NEWS": reports.get("news", ""),
        "SNS": reports.get("sns", ""),
        "DISASTER": reports.get("disaster", ""),
        "FINAL": reports.get("final", ""),
    }

    for source, text in source_map.items():
        for line in _candidate_evidence_lines(text, keyword=incident.location_text):
            evidence_pool.append(f"[{source}] {line[:180]}")

    if not evidence_pool:
        for source, text in source_map.items():
            for line in _candidate_evidence_lines(text):
                evidence_pool.append(f"[{source}] {line[:180]}")

    deduped: List[str] = []
    seen: set[str] = set()
    for item in evidence_pool:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
        if len(deduped) >= DEFAULT_EVIDENCE_LIMIT:
            break

    return deduped


async def build_incident_evidence_with_llm(
        incident: Incident,
        reports: Dict[str, str],
) -> List[str]:
    """LLM을 활용해 요약과 관련된 구체적 근거만 추출"""
    source_texts = []
    for source_name in ["news", "sns", "disaster", "final"]:
        text = reports.get(source_name, "").strip()
        if text:
            source_texts.append(f"[{source_name.upper()}]\n{text}")

    if not source_texts:
        return [incident.summary[:180]]

    combined_text = "\n\n".join(source_texts)[:8000]

    prompt = f"""
당신은 재난 분석가입니다. 아래 소스 데이터에서 다음 사건을 뒷받침하는 **구체적인 증거 문장**만 추출하세요.

**사건 정보:**
- 유형: {incident.incident_type}
- 위치: {incident.location_text}
- 요약: {incident.summary}

**요구사항:**
1. 위 사건 요약을 **직접 뒷받침하는** 문장만 선택
2. 각 증거는 30-100자 정도로 핵심만 요약
3. 반드시 출처 태그([NEWS], [SNS], [DISASTER], [FINAL]) 포함
4. 최대 {DEFAULT_EVIDENCE_LIMIT}개까지만 선택
5. 무관한 내용(예: 예방 수칙, 다른 지역 사건)은 절대 포함하지 마세요
6. 사건의 **발생 사실**을 입증하는 문장만 추출

**소스 데이터:**
{combined_text}

구체적이고 관련성 높은 증거만 추출하세요.
"""

    try:
        structured_llm = get_llm().with_structured_output(EvidenceExtraction)
        parsed = await structured_llm.ainvoke(prompt)
        evidence = [e.strip() for e in parsed.evidence if e.strip()][:DEFAULT_EVIDENCE_LIMIT]

        if evidence:
            print(f"[{now_str()}] LLM 근거 추출 성공: {len(evidence)}건")
            return evidence
        print(f"[{now_str()}] LLM 근거 추출 결과 없음 -> 폴백 사용")
        return build_incident_evidence(incident, reports)

    except Exception as e:
        print(f"[{now_str()}] LLM 근거 추출 오류: {e} -> 폴백 사용")
        return build_incident_evidence(incident, reports)


# --- 대응 요령 (RAG) ---

ACTION_KEYWORDS = {
    "대피",
    "신고",
    "통제",
    "접근 금지",
    "주의",
    "우회",
    "문자 확인",
    "마스크",
    "젖은 수건",
    "실내",
    "창문",
    "환기",
    "전원 차단",
    "가스 차단",
    "119",
}


def split_sentences(text: str) -> List[str]:
    raw_sentences = re.split(r"(?<=[.!?])\s+|[\n\r]+", text)
    sentences: List[str] = []
    for raw in raw_sentences:
        sentence = " ".join(raw.replace("*", " ").replace("-", " ").split()).strip()
        if sentence:
            sentences.append(sentence)
    return sentences


def normalize_rag_source(source_path: str) -> str:
    if not source_path:
        return "재난안전 매뉴얼"
    return Path(source_path).stem


def extract_action_lines_from_doc(doc_text: str) -> List[str]:
    candidates: List[str] = []
    for sentence in split_sentences(doc_text):
        if len(sentence) < 12 or len(sentence) > 180:
            continue
        if any(k in sentence for k in ACTION_KEYWORDS):
            candidates.append(sentence)
    return candidates


async def extract_action_guide_from_rag(incident: Incident) -> List[str]:
    """폴백용 RAG 문장 추출 함수"""
    retriever = get_retriever()
    if retriever is None:
        return []

    query = (
        f"{incident.incident_type} {incident.location_text} {incident.summary} "
        "발생 시 대응 요령 대피 행동요령"
    )

    try:
        docs = await retriever.ainvoke(query)
    except Exception:
        return []

    guide_pool: List[str] = []
    for doc in docs[:8]:
        source = normalize_rag_source(doc.metadata.get("source", ""))
        for line in extract_action_lines_from_doc(doc.page_content):
            guide_pool.append(f"{line} (출처: {source})")

    deduped: List[str] = []
    seen: set[str] = set()
    for item in guide_pool:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
        if len(deduped) >= DEFAULT_RESPONSE_GUIDE_LIMIT:
            break
    return deduped


def build_default_action_guide() -> List[str]:
    return [
        "연기나 화염이 보이면 즉시 119에 신고하고 건물 밖 안전지대로 이동하세요.",
        "재난문자 및 지자체 통제 안내를 확인하고 통제 구역에는 접근하지 마세요.",
        "노약자와 어린이를 우선 대피시키고, 연기 흡입을 줄이기 위해 마스크나 젖은 수건을 사용하세요.",
    ]


async def extract_personalized_action_guide(
        incident: Incident,
        subscriber: Subscriber,
        distance_km: float,
) -> List[str]:
    """RAG + LLM으로 사용자 맞춤형 대응 요령 생성"""
    rag_context = ""
    retriever = get_retriever()
    if retriever is not None:
        query = (
            f"{incident.incident_type} {incident.location_text} "
            f"대응 요령 행동요령 대피 안전"
        )

        try:
            rag_docs = await retriever.ainvoke(query)
            context_parts = []
            for doc in rag_docs[:5]:
                source = normalize_rag_source(doc.metadata.get("source", ""))
                content = doc.page_content[:500].strip()
                if content:
                    context_parts.append(f"[출처: {source}]\n{content}")

            rag_context = "\n\n".join(context_parts)
        except Exception as e:
            print(f"[{now_str()}] RAG 검색 오류: {e}")
            rag_context = ""

    if distance_km <= 1.0:
        urgency_level = "매우 위급 (1km 이내)"
        action_priority = "즉시 대피 및 안전 확보가 최우선"
    elif distance_km <= 3.0:
        urgency_level = "주의 필요 (3km 이내)"
        action_priority = "상황 주시 및 예방 조치 필요"
    else:
        urgency_level = "정보 확인 필요 (3km 이상)"
        action_priority = "정보 모니터링 및 사전 준비"

    prompt = f"""
당신은 재난 안전 전문가입니다. 아래 상황에 맞는 **구체적이고 실행 가능한** 대응 요령을 작성하세요.

**현재 상황:**
- 사건 유형: {incident.incident_type}
- 발생 위치: {incident.location_text}
- 사건 요약: {incident.summary}
- 사용자와의 거리: 사건 현장으로부터 약 {distance_km:.1f}km
- 긴급도: {urgency_level}
- 대응 우선순위: {action_priority}

**참고 자료 (재난 안전 매뉴얼):**
{rag_context if rag_context else "관련 매뉴얼 없음 - 일반 안전 수칙 적용"}

**작성 요구사항:**
1. 사용자 거리({distance_km:.1f}km)와 긴급도를 반드시 고려
2. "귀하는", "~하세요", "~바랍니다" 같은 직접적 표현 사용
3. 각 요령은 50-120자의 **즉시 실행 가능한 구체적 행동 지침**
4. 정확히 {DEFAULT_RESPONSE_GUIDE_LIMIT}개만 작성
5. RAG 매뉴얼의 내용을 참고하되, 현 상황에 맞게 **완전히 새로 작성**
6. 법령 원문이나 추상적 표현은 절대 사용 금지
7. 순서: 1) 즉각 행동, 2) 안전 확보, 3) 추가 대비

참고 매뉴얼이 있으면 이를 바탕으로, 없으면 일반적 재난 대응 원칙에 따라 작성하세요.
"""

    try:
        structured_llm = get_llm().with_structured_output(ActionGuideExtraction)
        parsed = await structured_llm.ainvoke(prompt)
        guides = [g.strip() for g in parsed.guides if g.strip()][:DEFAULT_RESPONSE_GUIDE_LIMIT]

        if guides:
            if rag_context:
                guides = [f"{guide} (참고: 재난안전 매뉴얼)" for guide in guides]

            print(f"[{now_str()}] 맞춤형 가이드 생성 성공: {len(guides)}건 (거리: {distance_km:.1f}km)")
            return guides
        print(f"[{now_str()}] 맞춤형 가이드 생성 실패 -> 폴백 사용")
        return await extract_action_guide_from_rag(incident) or build_default_action_guide()

    except Exception as e:
        print(f"[{now_str()}] 맞춤형 가이드 생성 오류: {e} -> 폴백 사용")
        return await extract_action_guide_from_rag(incident) or build_default_action_guide()


# --- 사건 추출 ---

async def extract_incidents_with_llm(combined_text: str) -> List[Incident]:
    prompt = f"""
당신은 재난 이벤트 추출기입니다.
아래 텍스트에서 "현재 시점에 실제로 발생했거나 매우 임박한 화재/재난"만 추출하세요.
막연한 예방 수칙/일반 설명은 제외하세요.
위치가 특정 가능한 사건만 남기고, 위치는 한국어 지명으로 작성하세요.
각 사건마다 분석 근거를 evidence 배열에 1~3개로 넣으세요.
evidence는 입력 텍스트 문장을 짧게 요약하거나 인용한 문장으로 작성하세요.

텍스트:
{combined_text[:12000]}
"""

    try:
        structured_llm = get_llm().with_structured_output(IncidentExtraction)
        parsed = await structured_llm.ainvoke(prompt)
        incidents: List[Incident] = []
        for item in parsed.incidents:
            if not item.location_text.strip():
                continue
            if item.confidence < 0.30:
                continue
            incidents.append(
                Incident(
                    incident_type=item.incident_type.strip() or "재난",
                    location_text=item.location_text.strip(),
                    summary=item.summary.strip() or "재난 징후 감지",
                    confidence=float(item.confidence),
                    evidence=[e.strip() for e in item.evidence if e.strip()][:DEFAULT_EVIDENCE_LIMIT],
                )
            )
        return incidents
    except Exception:
        return []


def extract_incidents_by_regex(combined_text: str) -> List[Incident]:
    incidents: List[Incident] = []
    location_pattern = re.compile(
        r"([가-힣]{2,}(?:특별시|광역시|자치시|도|시|군|구|읍|면|동)(?:\s+[가-힣0-9-]{1,}(?:시|군|구|읍|면|동|리))?)"
    )

    seen: set[str] = set()
    for line in combined_text.splitlines():
        if not any(keyword in line for keyword in RISK_KEYWORDS):
            continue
        for loc in location_pattern.findall(line):
            loc_norm = loc.strip()
            if not loc_norm or loc_norm in seen:
                continue
            seen.add(loc_norm)
            incidents.append(
                Incident(
                    incident_type="화재/재난",
                    location_text=loc_norm,
                    summary=line.strip()[:300],
                    confidence=0.35,
                    evidence=[line.strip()[:180]],
                )
            )
    return incidents


# --- 알림 ---

def build_notification_message(incident: Incident) -> str:
    preview = " ".join(incident.summary.split())
    if len(preview) > 300:
        preview = preview[:300] + "..."
    evidence_lines = incident.evidence[:DEFAULT_EVIDENCE_LIMIT]
    if not evidence_lines:
        evidence_block = "- 분석 근거: (근거 문장 추출 실패)"
    else:
        evidence_block = "\n".join([f"- 분석 근거 {idx + 1}: {line}" for idx, line in enumerate(evidence_lines)])
    evidence_sources = sorted(
        {
            match.group(1)
            for line in evidence_lines
            for match in [re.match(r"^\[([A-Z]+)\]", line.strip())]
            if match
        }
    )
    evidence_source_text = ", ".join(evidence_sources) if evidence_sources else "출처 식별 실패"

    guide_lines = incident.response_guide[:DEFAULT_RESPONSE_GUIDE_LIMIT]
    if not guide_lines:
        guide_block = "- 대응 요령: (적합한 대응 요령 추출 실패)"
    else:
        guide_block = "\n".join([f"- 대응 요령 {idx + 1}: {line}" for idx, line in enumerate(guide_lines)])

    return (
        f"[재난 탐지 알림]\n"
        f"- 시각: {now_str()}\n"
        f"- 유형: {incident.incident_type}\n"
        f"- 추정 위치: {incident.location_text}\n"
        f"- 신뢰도: {incident.confidence:.2f}\n"
        f"- 요약: {preview}\n"
        f"- 발생 판단 출처: {evidence_source_text}\n"
        f"{evidence_block}\n"
        f"{guide_block}"
    )


def notify(subscriber: Subscriber, message: str, distance_km: float) -> None:
    # TODO: channel 값(kakao, sms 등)에 따라 실제 발송 채널 연동
    print(
        f"[ALERT:{subscriber.channel}] user_id={subscriber.user_id} "
        f"(distance={distance_km:.2f}km)\n{message}\n"
    )


async def run_once(
        question: str,
        scope: str,
        default_radius_km: float,
        cooldown_minutes: int,
) -> None:
    print(f"\n[{now_str()}] 모니터링 시작 (scope={scope})")
    subscribers = get_subscribers_or_log(default_radius_km=default_radius_km)

    reports = await run_monitor_workflow(question=question, scope=scope)
    print(f"[{now_str()}] 분석 완료")

    combined_text = build_combined_report_text(reports)
    if not should_alert(combined_text):
        print(f"[{now_str()}] 경보 조건 미충족 -> 알림 전송 없음")
        return

    incidents = await extract_incidents_with_llm(combined_text)
    if not incidents:
        incidents = extract_incidents_by_regex(combined_text)

    if not incidents:
        print(f"[{now_str()}] 사건 위치를 특정하지 못해 알림 전송을 생략합니다.")
        return

    history = load_history()
    cooldown_sec = cooldown_minutes * 60
    sent_count = 0
    today_log = load_disaster_log()

    # RAG 전달용 문서 리스트 (중복 제거된 신규 사건만)
    rag_documents: List[RAGDocument] = []

    for incident in incidents:
        # LLM 기반 근거 추출
        derived_evidence = await build_incident_evidence_with_llm(incident, reports)
        if derived_evidence:
            incident.evidence = derived_evidence
        elif not incident.evidence:
            incident.evidence = [incident.summary[:180]]

        # 좌표 변환
        coords = geocode_location(incident.location_text)
        if not coords:
            print(f"[{now_str()}] 위치 좌표 변환 실패: {incident.location_text}")
            continue
        incident.latitude, incident.longitude = coords

        # 중복 확인 (히스토리 + 오늘 로그)
        fingerprint = build_alert_fingerprint(incident)
        if is_duplicate_alert(history, fingerprint, cooldown_sec) or is_duplicate_in_log(today_log, fingerprint, cooldown_sec):
            print(f"[{now_str()}] 🚫 중복 사건 제외: {incident.location_text}")
            continue

        # 신규 사건만 RAG 문서 변환
        rag_documents.append(convert_incident_to_rag_document(incident, reports))

        # 근처 구독자 선별
        nearby = select_nearby_subscribers(
            subscribers=subscribers,
            center_lat=incident.latitude,
            center_lon=incident.longitude,
        )

        if not nearby:
            print(f"[{now_str()}] 인근 사용자 없음: {incident.location_text}")
            add_incident_to_log(incident, reports, fingerprint, 0)
            remember_alert(history, fingerprint)
            continue

        # 각 구독자별 맞춤형 대응 요령 생성 및 전송
        for sub, distance in nearby:
            personalized_incident = deepcopy(incident)
            personalized_incident.response_guide = await extract_personalized_action_guide(
                incident, sub, distance
            )

            notify(sub, build_notification_message(personalized_incident), distance)
            sent_count += 1

        add_incident_to_log(incident, reports, fingerprint, len(nearby))
        remember_alert(history, fingerprint)
        print(
            f"[{now_str()}] 사건 '{incident.location_text}' 기준 "
            f"{len(nearby)}명에게 알림 전송"
        )

    save_history(history)

    if rag_documents:
        save_rag_documents(rag_documents)
        print(f"[{now_str()}] 📊 사이클 종료 - 알림 {sent_count}건, RAG 신규 {len(rag_documents)}건")
    else:
        print(f"[{now_str()}] 📊 사이클 종료 - 알림 {sent_count}건, RAG 신규 0건 (모두 중복)")


async def run_forever(
        interval_seconds: int,
        question: str,
        scope: str,
        default_radius_km: float,
        cooldown_minutes: int,
) -> None:
    print(
        f"모니터링 서비스 시작: interval={interval_seconds}s, "
        f"cooldown={cooldown_minutes}m, scope={scope}, users_json={SUBSCRIBERS_FILE}"
    )
    print(f"재난 로그 디렉토리: {DISASTER_LOGS_DIR}")
    print(f"RAG 출력 디렉토리: {RAG_OUTPUT_DIR}")

    while True:
        started = time.monotonic()
        try:
            await run_once(
                question=question,
                scope=scope,
                default_radius_km=default_radius_km,
                cooldown_minutes=cooldown_minutes,
            )
        except Exception as exc:
            print(f"[{now_str()}] 모니터링 사이클 오류: {exc}")

        elapsed = time.monotonic() - started
        sleep_sec = max(0, interval_seconds - int(elapsed))
        print(f"[{now_str()}] 다음 사이클까지 {sleep_sec}s 대기")
        await asyncio.sleep(sleep_sec)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="주기 재난 모니터링 + 위치 기반 알림 서비스")
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=DEFAULT_INTERVAL_SECONDS,
        help=f"모니터링 주기(초). 기본값: {DEFAULT_INTERVAL_SECONDS}",
    )
    parser.add_argument(
        "--cooldown-minutes",
        type=int,
        default=DEFAULT_COOLDOWN_MINUTES,
        help=f"중복 알림 쿨다운(분). 기본값: {DEFAULT_COOLDOWN_MINUTES}",
    )
    parser.add_argument(
        "--default-radius-km",
        type=float,
        default=3.0,
        help="구독자 radius_km 미설정 시 기본 반경(km)",
    )
    parser.add_argument(
        "--scope",
        type=str,
        default=DEFAULT_SCOPE,
        help=f"에이전트 수집 범위(GPS 텍스트). 기본값: {DEFAULT_SCOPE}",
    )
    parser.add_argument(
        "--question",
        type=str,
        default=DEFAULT_MONITOR_QUESTION,
        help="워크플로우에 전달할 질문",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="1회만 실행하고 종료",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.once:
        asyncio.run(
            run_once(
                question=args.question,
                scope=args.scope,
                default_radius_km=args.default_radius_km,
                cooldown_minutes=args.cooldown_minutes,
            )
        )
        return

    asyncio.run(
        run_forever(
            interval_seconds=args.interval_seconds,
            question=args.question,
            scope=args.scope,
            default_radius_km=args.default_radius_km,
            cooldown_minutes=args.cooldown_minutes,
        )
    )


if __name__ == "__main__":
    main()
