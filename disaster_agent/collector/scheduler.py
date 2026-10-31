"""
주기적 재난 정보 수집 + JSON 저장 서비스

    python -m disaster_agent.collector.scheduler --once
    python -m disaster_agent.collector.scheduler --interval-seconds 600 --scope 대한민국
"""
import argparse
import asyncio
import time
from pathlib import Path
from typing import Optional

from disaster_agent.collector.incidents import run_collection_flow
from disaster_agent.collector.service import DEFAULT_COLLECTION_QUESTION, save_snapshot
from disaster_agent.config import COLLECTOR_SNAPSHOT_DIR
from disaster_agent.geo import now_str

DEFAULT_SCOPE = "대한민국"
DEFAULT_INTERVAL_SECONDS = 600


async def run_once(
    scope: str,
    scenario_time: Optional[str],
    question: str,
    output_dir: Path,
) -> Path:
    print(f"[{now_str()}] 수집 시작 (scope={scope}, scenario_time={scenario_time or '현재'})")
    snapshot = await run_collection_flow(
        location=scope,
        scenario_time=scenario_time,
        question=question,
    )

    output_path = save_snapshot(snapshot, output_dir=output_dir)
    metadata = snapshot["metadata"]
    print(
        f"[{now_str()}] 수집 결과 저장 완료: {output_path} "
        f"(incidents={metadata['incident_count']}, geocoded={metadata['geocoded_count']})"
    )
    return output_path


async def run_forever(
    interval_seconds: int,
    scope: str,
    scenario_time: Optional[str],
    question: str,
    output_dir: Path,
) -> None:
    print(
        f"주기 수집 시작: interval={interval_seconds}s, scope={scope}, "
        f"scenario_time={scenario_time or '현재'}, output_dir={output_dir}"
    )

    while True:
        started = time.monotonic()
        try:
            await run_once(
                scope=scope,
                scenario_time=scenario_time,
                question=question,
                output_dir=output_dir,
            )
        except Exception as exc:
            print(f"[{now_str()}] 수집 사이클 오류: {exc}")

        elapsed = time.monotonic() - started
        sleep_sec = max(0, interval_seconds - int(elapsed))
        print(f"[{now_str()}] 다음 수집까지 {sleep_sec}s 대기")
        await asyncio.sleep(sleep_sec)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="주기적 재난 정보 수집 + JSON 저장 서비스")
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=DEFAULT_INTERVAL_SECONDS,
        help=f"수집 주기(초). 기본값: {DEFAULT_INTERVAL_SECONDS}",
    )
    parser.add_argument(
        "--scope",
        type=str,
        default=DEFAULT_SCOPE,
        help=f"수집 범위(GPS 텍스트). 기본값: {DEFAULT_SCOPE}",
    )
    parser.add_argument(
        "--scenario-time",
        type=str,
        default=None,
        help="기준 시점 (예: '2026년 03월 03일 09시 00분'). 미입력 시 현재 시점",
    )
    parser.add_argument(
        "--question",
        type=str,
        default=DEFAULT_COLLECTION_QUESTION,
        help="수집 에이전트에 전달할 질문",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(COLLECTOR_SNAPSHOT_DIR),
        help=f"JSON 저장 디렉토리. 기본값: {COLLECTOR_SNAPSHOT_DIR}",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="1회만 수집 후 종료",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    if args.once:
        asyncio.run(
            run_once(
                scope=args.scope,
                scenario_time=args.scenario_time,
                question=args.question,
                output_dir=output_dir,
            )
        )
        return

    asyncio.run(
        run_forever(
            interval_seconds=args.interval_seconds,
            scope=args.scope,
            scenario_time=args.scenario_time,
            question=args.question,
            output_dir=output_dir,
        )
    )


if __name__ == "__main__":
    main()
