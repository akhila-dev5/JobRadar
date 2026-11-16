"""Streamlit entry point.  Run:  streamlit run frontend/dashboard.py"""

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from frontend.views.common import client, guard  # noqa: E402
from frontend.views.pages_main import page_dashboard, page_jobs, page_saved, page_tracker  # noqa: E402
from frontend.views.pages_settings import page_settings  # noqa: E402

st.set_page_config(page_title="JobRadar AI", page_icon="📡", layout="wide")

PAGES = {
    "📊 Dashboard": page_dashboard,
    "💼 Job Results": page_jobs,
    "★ Saved Jobs": page_saved,
    "📋 Application Tracker": page_tracker,
    "⚙️ Settings": page_settings,
}

with st.sidebar:
    st.header("JobRadar AI")
    choice = st.radio("Navigate", list(PAGES), label_visibility="collapsed")
    health = guard(client().get, "/health")
    st.caption("Backend: ✅ connected" if health else "Backend: ❌ unreachable")
    if health and not health.get("smtp_configured"):
        st.caption("Email: not configured (optional)")

PAGES[choice]()
