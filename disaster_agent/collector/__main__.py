"""
재난 정보 수집 CLI (호출 시 1회 수집 → JSON 저장)

    python -m disaster_agent.collector
"""
import asyncio
import json

from disaster_agent.collector.incidents import run_collection_flow
from disaster_agent.collector.service import save_snapshot


def main():
    print("=" * 56)
    print("KPAS 재난 정보 수집기 (호출 시 수집 전용)")
    print("=" * 56)
    print("종료하려면 'exit' 또는 'quit'를 입력하세요.\n")

    while True:
        try:
            user_location = input("분석할 지역 (종료: exit): ").strip()
            if user_location.lower() in {"exit", "quit", "종료"}:
                print("시스템을 종료합니다.")
                break
            if not user_location:
                print("분석할 지역을 입력해주세요.")
                continue

            user_scenario_time = input(
                "분석 기준 시점 (YYYY년 MM월 DD일 HH시 MM분) [Enter: 현재 시간]: "
            ).strip()

            result = asyncio.run(
                run_collection_flow(
                    location=user_location,
                    scenario_time=user_scenario_time or None,
                )
            )

            print("\n[수집 결과 JSON]")
            print(json.dumps(result, ensure_ascii=False, indent=2))
            saved_path = save_snapshot(result)
            print(f"\n[저장 완료] {saved_path}")

        except KeyboardInterrupt:
            print("\n프로그램을 종료합니다...")
            break
        except Exception as exc:
            print(f"\n오류: {exc}")
            print("다시 시도해주세요.")


if __name__ == "__main__":
    main()
