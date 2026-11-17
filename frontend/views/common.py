from __future__ import annotations

from datetime import datetime

import streamlit as st

from frontend.api_client import ApiClient, ApiError

STATUS_LABELS = {
    "discovered": "Discovered",
    "interested": "Interested",
    "applied": "Applied",
    "interviewing": "Interviewing",
    "rejected": "Rejected",
    "offer_received": "Offer received",
}


def client() -> ApiClient:
    if "api" not in st.session_state:
        st.session_state["api"] = ApiClient()
    return st.session_state["api"]


def guard(fn, *args, **kwargs):
    """Run an API call; show a readable error instead of a traceback. Returns None on failure."""
    try:
        return fn(*args, **kwargs)
    except ApiError as exc:
        st.error(str(exc))
        return None


def fmt_dt(value: str | None) -> str:
    if not value:
        return "never"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%d %b %Y %H:%M UTC")
    except ValueError:
        return value


def fmt_date(value: str | None) -> str:
    if not value:
        return "n/a"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%d %b %Y")
    except ValueError:
        return value


def score_badge(score: float, above: bool) -> str:
    icon = "🟢" if score >= 60 else ("🟡" if score >= 40 else "⚪")
    return f"{icon} {score:.0f}%" + ("" if above else " (below threshold)")


def render_job_card(job: dict, key_prefix: str, show_actions: bool = True) -> None:
    api = client()
    with st.container(border=True):
        left, right = st.columns([5, 1])
        with left:
            st.markdown(
                f"**[{job['title']}]({job['application_url']})**  \n"
                f"{job['company_name']} · {job.get('location') or 'Location n/a'}"
            )
            st.caption(
                f"{job['source'].title()} · published {fmt_date(job.get('published_at') or job['first_seen_at'])}"
                + ("" if job["is_active"] else " · ⚠️ no longer listed")
            )
        with right:
            st.markdown(f"### {score_badge(job['score'], job['above_threshold'])}")
        if job["matched_keywords"]:
            st.markdown("**Keywords:** " + " ".join(f"`{k}`" for k in job["matched_keywords"]))
        cols = st.columns(2)
        cols[0].markdown("**Matched skills:** " + (", ".join(job["matched_skills"]) or "–"))
        cols[1].markdown("**Missing skills:** " + (", ".join(job["missing_skills"][:10]) or "–"))

        a, b, c = st.columns([1, 1, 2])
        a.link_button("Apply ↗", job["application_url"])
        if show_actions:
            if job["saved"]:
                if b.button("★ Unsave", key=f"{key_prefix}-unsave-{job['id']}"):
                    guard(api.delete, f"/jobs/{job['id']}/save")
                    st.rerun()
            elif b.button("☆ Save", key=f"{key_prefix}-save-{job['id']}"):
                guard(api.post, f"/jobs/{job['id']}/save")
                st.rerun()
        if job.get("tracking_status"):
            c.caption(f"Tracker: {STATUS_LABELS.get(job['tracking_status'], job['tracking_status'])}")

        with st.expander("Why this job? (details, excerpts, score breakdown)"):
            detail = guard(api.get, f"/jobs/{job['id']}")
            if detail:
                st.write(detail["explanation"])
                if detail["excerpts"]:
                    st.markdown("**Relevant excerpts**")
                    for ex in detail["excerpts"]:
                        st.markdown(f"> {ex}")
                comp = detail["score_breakdown"].get("components", {})
                weights = detail["score_breakdown"].get("weights", {})
                if comp:
                    st.markdown("**Score components** (0–100%, weight used)")
                    for name, val in comp.items():
                        w = weights.get(name)
                        label = f"{name.title()}: " + ("n/a" if val is None else f"{val * 100:.0f}%")
                        label += f" · weight {w * 100:.0f}%" if w else ""
                        st.progress(0.0 if val is None else float(val), text=label)
                st.markdown("**Description** (matched keywords highlighted)")
                st.markdown(detail["highlighted_description"].replace("\n", "  \n"), unsafe_allow_html=True)
