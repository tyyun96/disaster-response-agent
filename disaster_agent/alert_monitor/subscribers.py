"""
알림 구독자(위치 + 반경) 관리 및 mock 구독자 생성

    python -m disaster_agent.alert_monitor.subscribers --seed-users 250 --seed 42
    python -m disaster_agent.alert_monitor.subscribers --show
"""
import argparse
import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from disaster_agent.config import ALERT_MONITOR_DIR
from disaster_agent.geo import now_str

SUBSCRIBERS_FILE = ALERT_MONITOR_DIR / "subscribers.json"

# 대한민국 전국 주요 시/군/구 좌표
NATIONWIDE_LOCATIONS: List[Tuple[str, float, float]] = [
    # 서울특별시 (25개 구)
    ("서울 종로구", 37.5735, 126.9788),
    ("서울 중구", 37.5641, 126.9979),
    ("서울 용산구", 37.5326, 126.9905),
    ("서울 성동구", 37.5632, 127.0369),
    ("서울 광진구", 37.5384, 127.0822),
    ("서울 동대문구", 37.5744, 127.0395),
    ("서울 중랑구", 37.6066, 127.0927),
    ("서울 성북구", 37.5894, 127.0167),
    ("서울 강북구", 37.6396, 127.0257),
    ("서울 도봉구", 37.6686, 127.0471),
    ("서울 노원구", 37.6542, 127.0568),
    ("서울 은평구", 37.6027, 126.9291),
    ("서울 서대문구", 37.5791, 126.9368),
    ("서울 마포구", 37.5663, 126.9019),
    ("서울 양천구", 37.5170, 126.8664),
    ("서울 강서구", 37.5509, 126.8495),
    ("서울 구로구", 37.4954, 126.8874),
    ("서울 금천구", 37.4519, 126.8955),
    ("서울 영등포구", 37.5264, 126.8963),
    ("서울 동작구", 37.5124, 126.9393),
    ("서울 관악구", 37.4784, 126.9516),
    ("서울 서초구", 37.4837, 127.0324),
    ("서울 강남구", 37.5172, 127.0473),
    ("서울 송파구", 37.5145, 127.1059),
    ("서울 강동구", 37.5301, 127.1238),

    # 부산광역시 (16개 구/군)
    ("부산 중구", 35.1063, 129.0326),
    ("부산 서구", 35.0972, 129.0244),
    ("부산 동구", 35.1296, 129.0454),
    ("부산 영도구", 35.0913, 129.0679),
    ("부산 부산진구", 35.1626, 129.0533),
    ("부산 동래구", 35.2048, 129.0837),
    ("부산 남구", 35.1365, 129.0846),
    ("부산 북구", 35.1975, 128.9895),
    ("부산 해운대구", 35.1631, 129.1635),
    ("부산 사하구", 35.1045, 128.9748),
    ("부산 금정구", 35.2428, 129.0918),
    ("부산 강서구", 35.2119, 128.9806),
    ("부산 연제구", 35.1764, 129.0798),
    ("부산 수영구", 35.1454, 129.1134),
    ("부산 사상구", 35.1523, 128.9910),
    ("부산 기장군", 35.2446, 129.2219),

    # 대구광역시 (8개 구/군)
    ("대구 중구", 35.8694, 128.6060),
    ("대구 동구", 35.8868, 128.6350),
    ("대구 서구", 35.8718, 128.5593),
    ("대구 남구", 35.8463, 128.5974),
    ("대구 북구", 35.8858, 128.5829),
    ("대구 수성구", 35.8581, 128.6311),
    ("대구 달서구", 35.8299, 128.5326),
    ("대구 달성군", 35.7749, 128.4312),

    # 인천광역시 (10개 구/군)
    ("인천 중구", 37.4738, 126.6216),
    ("인천 동구", 37.4738, 126.6433),
    ("인천 미추홀구", 37.4634, 126.6505),
    ("인천 연수구", 37.4106, 126.6782),
    ("인천 남동구", 37.4474, 126.7314),
    ("인천 부평구", 37.5068, 126.7219),
    ("인천 계양구", 37.5375, 126.7378),
    ("인천 서구", 37.5452, 126.6762),
    ("인천 강화군", 37.7467, 126.4881),
    ("인천 옹진군", 37.4461, 126.6369),

    # 광주광역시 (5개 구)
    ("광주 동구", 35.1465, 126.9223),
    ("광주 서구", 35.1522, 126.8894),
    ("광주 남구", 35.1328, 126.9025),
    ("광주 북구", 35.1740, 126.9118),
    ("광주 광산구", 35.1396, 126.7934),

    # 대전광역시 (5개 구)
    ("대전 동구", 36.3504, 127.4549),
    ("대전 중구", 36.3255, 127.4211),
    ("대전 서구", 36.3556, 127.3835),
    ("대전 유성구", 36.3622, 127.3567),
    ("대전 대덕구", 36.3466, 127.4166),

    # 울산광역시 (5개 구/군)
    ("울산 중구", 35.5692, 129.3326),
    ("울산 남구", 35.5454, 129.3300),
    ("울산 동구", 35.5049, 129.4163),
    ("울산 북구", 35.5827, 129.3611),
    ("울산 울주군", 35.5226, 129.1419),

    # 세종특별자치시
    ("세종시", 36.4875, 127.2817),

    # 경기도 (주요 시/군)
    ("수원", 37.2636, 127.0286),
    ("성남", 37.4200, 127.1267),
    ("고양", 37.6584, 126.8320),
    ("용인", 37.2411, 127.1775),
    ("부천", 37.5034, 126.7660),
    ("안산", 37.3219, 126.8309),
    ("안양", 37.3943, 126.9568),
    ("남양주", 37.6361, 127.2168),
    ("화성", 37.1991, 126.8310),
    ("평택", 36.9922, 127.1129),
    ("의정부", 37.7381, 127.0336),
    ("시흥", 37.3799, 126.8028),
    ("파주", 37.7599, 126.7800),
    ("김포", 37.6152, 126.7158),
    ("광명", 37.4786, 126.8644),
    ("광주", 37.4292, 127.2550),
    ("군포", 37.3617, 126.9352),
    ("이천", 37.2720, 127.4350),
    ("양주", 37.7854, 127.0458),
    ("오산", 37.1497, 127.0773),
    ("구리", 37.5943, 127.1295),
    ("안성", 37.0079, 127.2797),
    ("포천", 37.8948, 127.2006),
    ("의왕", 37.3448, 126.9684),
    ("하남", 37.5391, 127.2148),
    ("여주", 37.2982, 127.6377),
    ("양평", 37.4910, 127.4876),
    ("동두천", 37.9034, 127.0606),
    ("과천", 37.4292, 126.9877),
    ("가평", 37.8314, 127.5095),
    ("연천", 38.0965, 127.0748),

    # 강원특별자치도
    ("춘천", 37.8813, 127.7299),
    ("원주", 37.3422, 127.9202),
    ("강릉", 37.7519, 128.8761),
    ("동해", 37.5247, 129.1144),
    ("태백", 37.1640, 128.9856),
    ("속초", 38.2070, 128.5918),
    ("삼척", 37.4500, 129.1656),
    ("홍천", 37.6975, 127.8889),
    ("횡성", 37.4828, 127.9846),
    ("영월", 37.1836, 128.4615),
    ("평창", 37.3708, 128.3901),
    ("정선", 37.3807, 128.6608),
    ("철원", 38.1467, 127.3136),
    ("화천", 38.1063, 127.7084),
    ("양구", 38.1097, 127.9896),
    ("인제", 38.0695, 128.1706),
    ("고성", 38.3807, 128.4679),
    ("양양", 38.0754, 128.6190),

    # 충청북도
    ("청주", 36.6424, 127.4890),
    ("충주", 36.9910, 127.9259),
    ("제천", 37.1326, 128.1911),
    ("보은", 36.4894, 127.7294),
    ("옥천", 36.3006, 127.5721),
    ("영동", 36.1750, 127.7834),
    ("증평", 36.7848, 127.5817),
    ("진천", 36.8551, 127.4327),
    ("괴산", 36.8154, 127.7869),
    ("음성", 36.9401, 127.6922),
    ("단양", 36.9845, 128.3661),

    # 충청남도
    ("천안", 36.8151, 127.1139),
    ("공주", 36.4465, 127.1189),
    ("보령", 36.3334, 126.6129),
    ("아산", 36.7898, 127.0018),
    ("서산", 36.7848, 126.4503),
    ("논산", 36.1872, 127.0989),
    ("계룡", 36.2744, 127.2488),
    ("당진", 36.8925, 126.6476),
    ("금산", 36.1088, 127.4879),
    ("부여", 36.2756, 126.9100),
    ("서천", 36.0806, 126.6919),
    ("청양", 36.4592, 126.8024),
    ("홍성", 36.6012, 126.6650),
    ("예산", 36.6829, 126.8509),
    ("태안", 36.7456, 126.2980),

    # 전북특별자치도
    ("전주", 35.8242, 127.1480),
    ("군산", 35.9676, 126.7369),
    ("익산", 35.9483, 126.9575),
    ("정읍", 35.5699, 126.8559),
    ("남원", 35.4163, 127.3903),
    ("김제", 35.8031, 126.8809),
    ("완주", 35.9045, 127.1630),
    ("진안", 35.7917, 127.4249),
    ("무주", 36.0071, 127.6608),
    ("장수", 35.6477, 127.5211),
    ("임실", 35.6177, 127.2879),
    ("순창", 35.3742, 127.1376),
    ("고창", 35.4355, 126.7019),
    ("부안", 35.7318, 126.7330),

    # 전라남도
    ("목포", 34.8118, 126.3922),
    ("여수", 34.7604, 127.6622),
    ("순천", 34.9507, 127.4872),
    ("나주", 35.0160, 126.7107),
    ("광양", 34.9406, 127.6956),
    ("담양", 35.3208, 126.9882),
    ("곡성", 35.2819, 127.2918),
    ("구례", 35.2022, 127.4632),
    ("고흥", 34.6117, 127.2754),
    ("보성", 34.7714, 127.0799),
    ("화순", 35.0641, 126.9866),
    ("장흥", 34.6814, 126.9069),
    ("강진", 34.6423, 126.7672),
    ("해남", 34.5733, 126.5989),
    ("영암", 34.8003, 126.6967),
    ("무안", 34.9904, 126.4819),
    ("함평", 35.0665, 126.5158),
    ("영광", 35.2773, 126.5121),
    ("장성", 35.3018, 126.7841),
    ("완도", 34.3110, 126.7552),
    ("진도", 34.4867, 126.2632),
    ("신안", 34.8271, 126.1085),

    # 경상북도
    ("포항", 36.0190, 129.3435),
    ("경주", 35.8562, 129.2247),
    ("김천", 36.1399, 128.1137),
    ("안동", 36.5684, 128.7294),
    ("구미", 36.1195, 128.3445),
    ("영주", 36.8056, 128.6239),
    ("영천", 35.9733, 128.9386),
    ("상주", 36.4109, 128.1590),
    ("문경", 36.5866, 128.1867),
    ("경산", 35.8250, 128.7414),
    ("군위", 36.2428, 128.5729),
    ("의성", 36.3525, 128.6969),
    ("청송", 36.4364, 129.0570),
    ("영양", 36.6665, 129.1123),
    ("영덕", 36.4151, 129.3655),
    ("청도", 35.6473, 128.7364),
    ("고령", 35.7273, 128.2625),
    ("성주", 35.9190, 128.2828),
    ("칠곡", 35.9950, 128.4017),
    ("예천", 36.6557, 128.4516),
    ("봉화", 36.8931, 128.7325),
    ("울진", 36.9930, 129.4006),
    ("울릉", 37.4844, 130.9058),

    # 경상남도
    ("창원", 35.2281, 128.6811),
    ("진주", 35.1800, 128.1076),
    ("통영", 34.8544, 128.4331),
    ("사천", 34.9570, 128.0642),
    ("김해", 35.2285, 128.8894),
    ("밀양", 35.5034, 128.7465),
    ("거제", 34.8806, 128.6211),
    ("양산", 35.3350, 129.0373),
    ("의령", 35.3222, 128.2619),
    ("함안", 35.2724, 128.4064),
    ("창녕", 35.5445, 128.4923),
    ("고성", 34.9732, 128.3232),
    ("남해", 34.8375, 127.8924),
    ("하동", 35.0673, 127.7514),
    ("산청", 35.4150, 127.8736),
    ("함양", 35.5204, 127.7252),
    ("거창", 35.6869, 127.9094),
    ("합천", 35.5664, 128.1656),

    # 제주특별자치도
    ("제주시", 33.4996, 126.5312),
    ("서귀포시", 33.2541, 126.5601),
]


# 기존 10개 주요 도시 (--legacy-mode)
LEGACY_LOCATIONS: List[Tuple[str, float, float]] = [
    ("서울", 37.5665, 126.9780),
    ("부산", 35.1796, 129.0756),
    ("대구", 35.8714, 128.6014),
    ("인천", 37.4563, 126.7052),
    ("광주", 35.1595, 126.8526),
    ("대전", 36.3504, 127.3845),
    ("울산", 35.5384, 129.3114),
    ("수원", 37.2636, 127.0286),
    ("창원", 35.2281, 128.6811),
    ("제주", 33.4996, 126.5312),
]


@dataclass
class Subscriber:
    user_id: str
    latitude: float
    longitude: float
    radius_km: float = 3.0
    channel: str = "console"


def load_subscribers(path: Path = SUBSCRIBERS_FILE, default_radius_km: float = 3.0) -> List[Subscriber]:
    if not path.exists():
        return []

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []

    items = raw["subscribers"] if isinstance(raw, dict) else raw
    subscribers: List[Subscriber] = []
    for item in items:
        try:
            subscribers.append(
                Subscriber(
                    user_id=str(item["user_id"]),
                    latitude=float(item["latitude"]),
                    longitude=float(item["longitude"]),
                    radius_km=float(item.get("radius_km", default_radius_km)),
                    channel=str(item.get("channel", "console")),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return subscribers


def save_subscribers(subscribers: List[Subscriber], path: Path = SUBSCRIBERS_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": now_str(),
        "subscribers": [asdict(s) for s in subscribers],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def generate_mock_subscribers(
        count: int,
        default_radius_km: float = 3.0,
        seed: Optional[int] = None,
        use_nationwide: bool = True,
) -> List[Subscriber]:
    """
    Mock 구독자 생성

    Args:
        count: 생성할 사용자 수
        default_radius_km: 기본 반경
        seed: 난수 시드
        use_nationwide: True면 전국 시/군/구, False면 기존 10개 도시
    """
    rng = random.Random(seed)
    subscribers: List[Subscriber] = []
    location_pool = NATIONWIDE_LOCATIONS if use_nationwide else LEGACY_LOCATIONS

    for idx in range(count):
        location_name, base_lat, base_lon = rng.choice(location_pool)

        # 오프셋 범위 (±0.05도 = 약 ±5.5km)
        lat_offset = rng.uniform(-0.05, 0.05)
        lon_offset = rng.uniform(-0.05, 0.05)

        # 반경은 2.0 ~ 5.0km 사이 랜덤
        radius = round(rng.uniform(2.0, max(2.5, default_radius_km + 2.0)), 1)

        subscribers.append(
            Subscriber(
                user_id=f"mock-user-{idx + 1:03d}-{location_name}",
                latitude=base_lat + lat_offset,
                longitude=base_lon + lon_offset,
                radius_km=radius,
                channel="console",
            )
        )
    return subscribers


def seed_mock_subscribers(
        count: int,
        default_radius_km: float = 3.0,
        overwrite: bool = False,
        seed: Optional[int] = None,
        path: Path = SUBSCRIBERS_FILE,
        use_nationwide: bool = True,
) -> int:
    existing = load_subscribers(path=path)
    if existing and not overwrite:
        return 0

    generated = generate_mock_subscribers(
        count=count,
        default_radius_km=default_radius_km,
        seed=seed,
        use_nationwide=use_nationwide,
    )
    save_subscribers(generated, path=path)
    return len(generated)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=f"mock 사용자 GPS 생성 및 {SUBSCRIBERS_FILE.name} 저장"
    )
    parser.add_argument(
        "--seed-users",
        type=int,
        default=50,
        help="생성할 mock 사용자 수 (기본 50)",
    )
    parser.add_argument(
        "--default-radius-km",
        type=float,
        default=3.0,
        help="구독 반경 기본값(km)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="난수 시드 (재현 가능한 샘플 필요 시 사용)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="기존 JSON을 덮어쓰고 다시 생성",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="저장된 사용자 샘플 5건 출력",
    )
    parser.add_argument(
        "--legacy-mode",
        action="store_true",
        help="기존 10개 주요 도시만 사용 (전국 모드 비활성화)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    use_nationwide = not args.legacy_mode

    inserted = seed_mock_subscribers(
        count=args.seed_users,
        default_radius_km=args.default_radius_km,
        overwrite=args.overwrite,
        seed=args.seed,
        path=SUBSCRIBERS_FILE,
        use_nationwide=use_nationwide,
    )
    total = len(load_subscribers(path=SUBSCRIBERS_FILE))

    mode_msg = f"전국 {len(NATIONWIDE_LOCATIONS)}개 지역" if use_nationwide else "주요 10개 도시"
    print(f"JSON: {SUBSCRIBERS_FILE}")
    print(f"생성 모드: {mode_msg}")

    if inserted == 0 and not args.overwrite:
        print(f"기존 데이터 유지 (총 {total}명). --overwrite 사용 시 재생성합니다.")
    else:
        print(f"저장 완료: 이번 실행 {inserted}명, 총 {total}명")

    if args.show:
        sample = load_subscribers(path=SUBSCRIBERS_FILE)[:5]
        print("\n[샘플 5건]")
        for row in sample:
            print(
                f"- {row.user_id}: ({row.latitude:.6f}, {row.longitude:.6f}), "
                f"radius={row.radius_km}km, channel={row.channel}"
            )


if __name__ == "__main__":
    main()
