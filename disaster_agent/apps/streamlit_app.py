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
from disaster_agent.collector.service import build_collection_text
from disaster_agent.kpas.workflow import DEFAULT_KPAS_QUESTION, run_kpas_workflow

KPAS_MODE = "KPAS 재난문자 초안"
COLLECT_MODE = "재난 정보 수집 (JSON)"

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
            st.code(json.dumps(message["json"], ensure_ascii=False, indent=2), language="json")

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
                    response_text = build_collection_text(result, max_section_chars=350)
            except Exception as exc:
                response_text = f"❌ 처리 중 오류가 발생했습니다: {exc}"

        st.markdown(response_text)
        if result is not None:
            st.code(json.dumps(result, ensure_ascii=False, indent=2), language="json")

    st.session_state.messages.append({"role": "assistant", "content": response_text, "json": result})
