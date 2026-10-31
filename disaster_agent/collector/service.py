import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from disaster_agent.agents.runner import run_sub_agents
from disaster_agent.config import COLLECTOR_SNAPSHOT_DIR
from disaster_agent.geo import now_str
from disaster_agent.state import GraphState

DEFAULT_COLLECTION_QUESTION = "지정된 위치의 화재/재난 정보를 수집하고 보고서를 작성해줘"


def _trim_text(value: str, max_chars: int) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 3] + "..."


async def collect_disaster_data(
    location: str,
    scenario_time: Optional[str] = None,
    question: str = DEFAULT_COLLECTION_QUESTION,
    thread_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    연결된 MCP 도구 기반 서브 에이전트(뉴스/SNS/공공데이터)를 병렬 실행해
    수집 결과를 JSON 형태로 반환합니다.
    """
    if not location or not location.strip():
        raise ValueError("location은 비어 있을 수 없습니다.")

    result: Dict[str, Any] = {
        "metadata": {
            "thread_id": thread_id or f"collection-session-{uuid.uuid4()}",
            "started_at": now_str(),
            "location": location.strip(),
            "scenario_time": scenario_time,
            "question": question,
        },
        "reports": {
            "news": "",
            "sns": "",
            "disaster": "",
        },
        "errors": [],
    }

    base_state: GraphState = {
        "messages": [],
        "question": question,
        "scenario_time": scenario_time,
        "GPS": location.strip(),
    }

    try:
        reports, errors = await run_sub_agents(base_state)
    except Exception as exc:
        result["errors"].append(f"MCP 초기화 실패: {exc}")
        result["metadata"]["finished_at"] = now_str()
        return result

    result["reports"]["news"] = reports.get("news", "")
    result["reports"]["sns"] = reports.get("SNS", "")
    result["reports"]["disaster"] = reports.get("disaster", "")
    result["errors"].extend(errors)
    result["metadata"]["finished_at"] = now_str()
    return result


def build_collection_text(result: Dict[str, Any], max_section_chars: int = 280) -> str:
    """
    Kakao/CLI처럼 텍스트 출력이 필요한 채널에서 보기 좋은 요약 문자열을 생성합니다.
    """
    metadata = result.get("metadata", {})
    reports = result.get("reports", {})
    errors = result.get("errors", [])

    lines = [
        "[수집 완료]",
        f"- 위치: {metadata.get('location', '미지정')}",
        f"- 기준 시점: {metadata.get('scenario_time') or '현재'}",
        f"- 시작: {metadata.get('started_at', '-')}",
        f"- 종료: {metadata.get('finished_at', '-')}",
    ]
    if "incident_count" in metadata:
        lines.append(f"- 탐지된 사건: {metadata['incident_count']}건")

    if errors:
        lines.append("- 수집 오류:")
        for error in errors:
            lines.append(f"  - {error}")

    lines.append("[NEWS]")
    lines.append(_trim_text(reports.get("news") or "수집 결과 없음", max_section_chars))
    lines.append("[SNS]")
    lines.append(_trim_text(reports.get("sns") or "수집 결과 없음", max_section_chars))
    lines.append("[DISASTER]")
    lines.append(_trim_text(reports.get("disaster") or "수집 결과 없음", max_section_chars))

    return "\n".join(lines)


def save_snapshot(snapshot: Dict[str, Any], output_dir: Path = COLLECTOR_SNAPSHOT_DIR) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    location = snapshot.get("metadata", {}).get("location", "unknown")
    safe_location = location.replace(" ", "_").replace("/", "_")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"collection_{safe_location}_{timestamp}.json"
    output_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path
