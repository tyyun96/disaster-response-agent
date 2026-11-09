"""
웹 데모 (KPAS 재난문자 초안 / 재난 정보 수집)

    python -m streamlit run disaster_agent/apps/streamlit_app.py
"""
import asyncio
import datetime
import json
import uuid

import streamlit as st

from disaster_agent.collector.incidents import run_collection_flow
from disaster_agent.collector.service import summarize_report
from disaster_agent.kpas.workflow import DEFAULT_KPAS_QUESTION, run_kpas_workflow

KPAS_MODE = "KPAS 재난문자 초안"
COLLECT_MODE = "재난 정보 수집 (JSON)"
REPORT_LABELS = (("news", "📰 NEWS"), ("sns", "💬 SNS"), ("disaster", "🏛️ DISASTER"))


def collection_markdown(result: dict) -> str:
    """수집 결과를 출처별 문단으로 요약합니다."""
    metadata = result.get("metadata", {})
    reports = result.get("reports", {})
    parts = [
        f"**[수집 완료]** {metadata.get('location', '미지정')} · 기준 시점: {metadata.get('scenario_time') or '현재'}"
        f" · 탐지된 사건 {metadata.get('incident_count', 0)}건"
    ]
    parts += [f"⚠️ {error}" for error in result.get("errors", [])]
    for key, label in REPORT_LABELS:
        parts.append(f"**{label}** · {summarize_report(reports.get(key) or '수집 결과 없음', 350)}")
    # Streamlit 마크다운에서 $는 수식으로 해석되므로 이스케이프
    return "\n\n".join(parts).replace("$", "\\$")


def render_collection_details(result: dict) -> None:
    """탐지된 사건 표와 전체 JSON을 보여줍니다."""
    incidents = result.get("incidents", [])
    if incidents:
        st.dataframe(
            [
                {
                    "유형": incident.get("incident_type"),
                    "위치": incident.get("location_text"),
                    "출처": incident.get("source"),
                    "신뢰도": incident.get("confidence"),
                    "위도": incident.get("latitude"),
                    "경도": incident.get("longitude"),
                    "요약": incident.get("summary"),
                }
                for incident in incidents
            ],
            hide_index=True,
        )
    with st.expander("전체 수집 결과 JSON"):
        st.code(json.dumps(result, ensure_ascii=False, indent=2), language="json")


st.set_page_config(
    page_title="재난 대응 AI 에이전트",
    page_icon="🚨",
    layout="centered",
)

st.title("🚨 재난 대응 AI 에이전트")
st.markdown(
    "**실시간 이종 데이터(뉴스, SNS, 공공데이터)를 융합**하여 "
    "KPAS 재난문자 초안을 작성하거나, 지역별 재난 정보를 수집합니다."
)

if "messages" not in st.session_state:
    st.session_state.messages = []
if "thread_id" not in st.session_state:
    st.session_state.thread_id = f"web-session-{uuid.uuid4()}"

with st.sidebar:
    st.header("⚙️ 설정")
    feature = st.radio("기능", [KPAS_MODE, COLLECT_MODE])
    st.info(f"Session ID:\n{st.session_state.thread_id}")

    mode = st.radio("분석 모드", ["실시간 (Live)", "과거 시점 (Simulation)"])
    scenario_time_str = None
    if mode == "과거 시점 (Simulation)":
        date = st.date_input("날짜", datetime.date.today())
        time = st.time_input("시간", datetime.datetime.now().time())
        scenario_time_str = f"{date.year}년 {date.month}월 {date.day}일 {time.hour}시 {time.minute}분"
        st.caption(f"설정된 시점: {scenario_time_str}")
    else:
        st.caption("현재 시간을 기준으로 최신 데이터를 수집합니다.")

    if st.button("대화 기록 초기화"):
        st.session_state.messages = []
        st.session_state.thread_id = f"web-session-{uuid.uuid4()}"
        st.rerun()


for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message.get("json"):
            render_collection_details(message["json"])

if prompt := st.chat_input("분석할 지역을 입력하세요 (예: 강남역, 부산 해운대구)"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    result = None
    with st.chat_message("assistant"):
        with st.spinner(f"🕵️ '{prompt}' 지역의 뉴스, SNS, 공공데이터를 수집 및 분석 중입니다..."):
            try:
                if feature == KPAS_MODE:
                    response_text = asyncio.run(
                        run_kpas_workflow(
                            DEFAULT_KPAS_QUESTION,
                            prompt,
                            scenario_time_str,
                            st.session_state.thread_id,
                        )
                    )
                else:
                    result = asyncio.run(
                        run_collection_flow(
                            location=prompt,
                            scenario_time=scenario_time_str,
                            thread_id=st.session_state.thread_id,
                        )
                    )
                    response_text = collection_markdown(result)
            except Exception as exc:
                response_text = f"❌ 처리 중 오류가 발생했습니다: {exc}"

        st.markdown(response_text)
        if result is not None:
            render_collection_details(result)

    st.session_state.messages.append({"role": "assistant", "content": response_text, "json": result})
