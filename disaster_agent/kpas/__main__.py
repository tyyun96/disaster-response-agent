"""
KPAS 재난문자 초안 생성 CLI

    python -m disaster_agent.kpas
"""
import asyncio

from disaster_agent.kpas.workflow import DEFAULT_KPAS_QUESTION, run_kpas_workflow


def main():
    """메인 대화 루프"""
    print("=" * 50)
    print("🚨 KPAS 관리자 지원 AI 에이전트 🚨")
    print("=" * 50)
    print("종료하려면 'exit' 또는 'quit'를 입력하세요.\n")

    while True:
        try:
            user_location = input("\n📍 분석할 지역 (종료: exit): ").strip()

            if user_location.lower() in ["exit", "quit", "종료"]:
                print("\n👋 시스템을 종료합니다.")
                break

            if not user_location:
                print("⚠️  분석할 지역을 입력해주세요.")
                continue

            user_scenario_time = input("🕒 분석 기준 시점 (YYYY년 MM월 DD일 HH시 MM분) [Enter: 현재 시간]: ").strip()
            scenario_time_to_pass = user_scenario_time or None

            response = asyncio.run(
                run_kpas_workflow(DEFAULT_KPAS_QUESTION, user_location, scenario_time_to_pass)
            )
            print(f"\n🤖 AI: {response}")

        except KeyboardInterrupt:
            print("\n\n👋 프로그램을 종료합니다...")
            break
        except Exception as e:
            print(f"\n❌ 오류: {e}")
            print("다시 시도해주세요.")


if __name__ == "__main__":
    main()
