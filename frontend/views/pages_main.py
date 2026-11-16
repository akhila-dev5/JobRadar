"""Dashboard, Job Results, Saved Jobs, Application Tracker, Search runner."""

from __future__ import annotations

import time
from datetime import date, timedelta

import streamlit as st

from frontend.views.common import STATUS_LABELS, client, fmt_dt, guard, render_job_card

SOURCES = ["", "greenhouse", "lever", "ashby"]


def _run_search_panel(company_ids: list[int] | None = None) -> None:
    api = client()
    started = guard(api.post, "/search", json={"company_ids": company_ids})
    if not started:
        return
    box = st.empty()
    for _ in range(600):  # up to ~10 minutes
        status = guard(api.get, f"/search/{started['id']}")
        if status is None:
            return
        if status["finished_at"]:
            break
        box.info(f"Searching… {status['companies_searched']} companies, {status['jobs_fetched']} jobs so far")
        time.sleep(1)
    box.empty()
    # Keep the outcome across the rerun below, which refreshes the metrics and tables.
    st.session_state["last_search"] = {
        "status": status["status"],
        "text": f"{status['jobs_fetched']} jobs fetched, {status['qualified_jobs']} matched your keywords, "
        f"{status['new_jobs']} new.",
        "errors": status["errors"],
    }
    st.rerun()


def _show_last_search() -> None:
    result = st.session_state.pop("last_search", None)
    if not result:
        return
    show = {"success": st.success, "partial": st.warning}.get(result["status"], st.error)
    show(("Search finished: " if result["status"] != "failed" else "Search failed. ") + result["text"])
    for err in result["errors"]:
        st.caption(f"⚠️ {err}")


def page_dashboard() -> None:
    api = client()
    st.title("📡 JobRadar AI")
    _show_last_search()
    stats = guard(api.get, "/jobs/stats")
    if stats is None:
        return
    c = st.columns(3)
    c[0].metric("Qualified jobs", stats["qualified_jobs"], help="Jobs matching at least one keyword")
    c[1].metric("New (last 7 days)", stats["new_jobs"])
    thr = f"≥ {stats['ai_threshold']:.0f}%" if stats["ai_threshold_enabled"] else "threshold off"
    c[2].metric(f"Above AI threshold ({thr})", stats["above_threshold"])
    c = st.columns(3)
    c[0].metric("Jobs stored", stats["stored_jobs"])
    c[1].metric("Companies monitored", stats["companies_monitored"])
    c[2].metric("Last successful search", fmt_dt(stats["last_success_at"]))

    st.divider()
    companies = guard(api.get, "/companies") or []
    enabled = [co for co in companies if co["enabled"]]
    if not enabled:
        st.info(
            "Add target companies under **Settings → Companies**, and keywords under **Settings → Keywords**."
        )
    left, right = st.columns([1, 2])
    if left.button("🔍 Search all enabled companies", type="primary", disabled=not enabled):
        _run_search_panel(None)
    names = {co["name"]: co["id"] for co in enabled}
    picked = right.multiselect("…or search selected companies only", list(names))
    if picked and right.button("Search selected"):
        _run_search_panel([names[n] for n in picked])

    if companies:
        st.subheader("Target companies")
        st.dataframe(
            [
                {
                    "Company": co["name"],
                    "Platform": co["platform"],
                    "Enabled": co["enabled"],
                    "Jobs collected": co["jobs_collected"],
                    "Last success": fmt_dt(co["last_success_at"]),
                    "Last error": co["last_error"] or "",
                }
                for co in companies
            ],
            hide_index=True,
            use_container_width=True,
        )
    history = guard(api.get, "/search/history", limit=5) or []
    if history:
        with st.expander("Recent searches"):
            st.dataframe(
                [
                    {
                        "Started": fmt_dt(h["started_at"]),
                        "Trigger": h["trigger"],
                        "Status": h["status"],
                        "Fetched": h["jobs_fetched"],
                        "Qualified": h["qualified_jobs"],
                        "New": h["new_jobs"],
                        "Issues": len(h["errors"]),
                    }
                    for h in history
                ],
                hide_index=True,
                use_container_width=True,
            )


def page_jobs() -> None:
    api = client()
    st.title("Job Results")
    companies = [co["name"] for co in (guard(api.get, "/companies") or [])]
    with st.expander("Filters", expanded=True):
        r1 = st.columns(4)
        company = r1[0].selectbox("Company", [""] + companies, format_func=lambda x: x or "All")
        title = r1[1].text_input("Job title contains")
        keyword = r1[2].text_input("Matched keyword")
        location = r1[3].text_input("Location contains")
        r2 = st.columns(4)
        min_score = r2[0].slider("Min match score", 0, 100, 0)
        source = r2[1].selectbox("Source", SOURCES, format_func=lambda x: x or "All")
        since = r2[2].selectbox("Published", ["Any time", "Last 24 hours", "Last 7 days", "Last 30 days"])
        sort = r2[3].selectbox("Sort by", ["Match score", "Newest"])
        show_all = st.checkbox("Include jobs below my AI threshold", value=False)
    days = {"Last 24 hours": 1, "Last 7 days": 7, "Last 30 days": 30}.get(since)
    page_size = 25
    page = st.session_state.get("jobs_page", 0)
    data = guard(
        api.get,
        "/jobs",
        company=company,
        title=title,
        keyword=keyword,
        location=location,
        min_score=min_score or None,
        source=source,
        published_after=(date.today() - timedelta(days=days)).isoformat() if days else None,
        include_below_threshold=str(show_all).lower(),
        sort="score" if sort == "Match score" else "date",
        limit=page_size,
        offset=page * page_size,
    )
    if data is None:
        return
    st.caption(f"{data['total']} matching jobs. Scores rank relevance; they are not a hiring probability.")
    if not data["items"] and data["total"] == 0:
        st.info("No jobs yet. Run a search from the Dashboard, or relax the filters.")
    for job in data["items"]:
        render_job_card(job, "res")
    pages = max(1, -(-data["total"] // page_size))
    if pages > 1:
        a, b, c = st.columns([1, 2, 1])
        if a.button("← Previous", disabled=page == 0):
            st.session_state["jobs_page"] = page - 1
            st.rerun()
        b.caption(f"Page {page + 1} of {pages}")
        if c.button("Next →", disabled=page + 1 >= pages):
            st.session_state["jobs_page"] = page + 1
            st.rerun()


def page_saved() -> None:
    st.title("Saved Jobs")
    data = guard(client().get, "/jobs", saved_only="true", limit=200)
    if data is None:
        return
    if not data["items"]:
        st.info("Nothing saved yet. Use ☆ Save on a job in Job Results.")
    for job in data["items"]:
        render_job_card(job, "saved")


def page_tracker() -> None:
    api = client()
    st.title("Application Tracker")
    jobs = guard(api.get, "/jobs", include_below_threshold="true", limit=200)
    if jobs is None:
        return
    with st.expander("➕ Track a job"):
        options = {
            f"{j['title']} — {j['company_name']}": j["id"] for j in jobs["items"] if not j["tracking_status"]
        }
        if not options:
            st.caption("All listed jobs are already tracked.")
        else:
            label = st.selectbox("Job", list(options))
            status = st.selectbox("Status", list(STATUS_LABELS), index=1, format_func=STATUS_LABELS.get)
            if st.button("Start tracking"):
                guard(api.put, f"/tracker/{options[label]}", json={"status": status})
                st.rerun()

    filt = st.selectbox(
        "Show status", [""] + list(STATUS_LABELS), format_func=lambda x: STATUS_LABELS.get(x, "All")
    )
    rows = guard(api.get, "/tracker", status=filt) or []
    if not rows:
        st.info("No tracked applications.")
    for row in rows:
        job, tr = row["job"], row["tracking"]
        with st.container(border=True):
            st.markdown(f"**{job['title']}** · {job['company_name']}")
            c = st.columns([2, 2, 3])
            keys = list(STATUS_LABELS)
            new_status = c[0].selectbox(
                "Status",
                keys,
                index=keys.index(tr["status"]),
                format_func=STATUS_LABELS.get,
                key=f"st-{job['id']}",
            )
            applied = c[1].date_input(
                "Applied on",
                value=date.fromisoformat(tr["applied_date"]) if tr["applied_date"] else None,
                key=f"ap-{job['id']}",
            )
            notes = c[2].text_area("Notes", value=tr["notes"] or "", key=f"nt-{job['id']}", height=80)
            b = st.columns([1, 1, 4])
            if b[0].button("Save changes", key=f"sv-{job['id']}"):
                guard(
                    api.put,
                    f"/tracker/{job['id']}",
                    json={
                        "status": new_status,
                        "notes": notes or None,
                        "applied_date": applied.isoformat() if applied else None,
                    },
                )
                st.rerun()
            if b[1].button("Remove", key=f"rm-{job['id']}"):
                guard(api.delete, f"/tracker/{job['id']}")
                st.rerun()
            b[2].link_button("Open posting ↗", job["application_url"])
