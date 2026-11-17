"""Dashboard, Job Results, Saved Jobs, Application Tracker, Search runner."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import streamlit as st

from frontend.views.common import STATUS_LABELS, client, fmt_dt, guard, render_job_card

SOURCES = ["", "greenhouse", "lever", "ashby"]


STALE_AFTER_MINUTES = 30


def _start_search(company_ids: list[int] | None = None) -> None:
    """Start a search in the background. The activity panel then shows live progress."""
    if guard(client().post, "/search", json={"company_ids": company_ids}):
        st.rerun()


def _elapsed(started_at: str) -> str:
    try:
        started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        seconds = int((datetime.now(UTC) - started).total_seconds())
    except ValueError:
        return ""
    return f"{seconds // 60} min {seconds % 60} s" if seconds >= 60 else f"{max(seconds, 0)} s"


def _is_stale(run: dict) -> bool:
    try:
        started = datetime.fromisoformat(run["started_at"].replace("Z", "+00:00"))
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
    except ValueError:
        return False
    return datetime.now(UTC) - started > timedelta(minutes=STALE_AFTER_MINUTES)


def _render_run(run: dict | None) -> bool:
    """Draw the latest search. Returns True while it is still running."""
    if run is None:
        st.info("No search has been run yet. Press **Search all enabled companies** below.")
        return False
    if run["finished_at"] is None:
        if _is_stale(run):
            st.warning(
                f"Search #{run['id']} has shown no result for over {STALE_AFTER_MINUTES} minutes; the backend "
                "was probably restarted while it ran. You can start a new search."
            )
            return False
        total, done = max(run["companies_searched"], 0), run["companies_done"]
        st.progress(done / total if total else 0.0)
        where = f" Now: **{run['current_company']}**." if run["current_company"] else ""
        st.markdown(
            f"🟢 **Search #{run['id']} is running** ({run['trigger']}, {_elapsed(run['started_at'])}). "
            f"{done} of {total or '…'} companies done.{where} "
            f"{run['jobs_fetched']} jobs fetched, {run['qualified_jobs']} matched your keywords so far."
        )
        return True
    icon = {"success": "✅", "partial": "⚠️"}.get(run["status"], "❌")
    st.markdown(
        f"{icon} **Last search #{run['id']}: {run['status']}** ({run['trigger']}, finished {fmt_dt(run['finished_at'])}). "
        f"{run['companies_done']} of {run['companies_searched']} companies, {run['jobs_fetched']} jobs fetched, "
        f"**{run['qualified_jobs']} matched your keywords**, {run['new_jobs']} new."
    )
    if run["errors"]:
        with st.expander(
            f"{len(run['errors'])} note(s) from this search", expanded=run["status"] == "failed"
        ):
            for err in run["errors"]:
                st.caption(f"⚠️ {err}")
    return False


def _activity_panel() -> None:
    """Shows whether a search is running. Refreshes itself every 2 s while one is."""
    api = client()
    latest = (guard(api.get, "/search/history", limit=1) or [None])[0]
    if latest is not None and latest["finished_at"] is None and not _is_stale(latest):

        @st.fragment(run_every=2)
        def live() -> None:
            run = (guard(api.get, "/search/history", limit=1) or [None])[0]
            if not _render_run(run):
                st.rerun()  # finished: redraw the whole page so the numbers below update

        live()
    else:
        _render_run(latest)


def page_dashboard() -> None:
    api = client()
    st.title("📡 JobRadar AI")
    st.subheader("Search activity")
    _activity_panel()
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
            "Add company names under **Settings → Companies**, and keywords under **Settings → Keywords**."
        )
    left, right = st.columns([1, 2])
    if left.button("🔍 Search all enabled companies", type="primary", disabled=not enabled):
        _start_search(None)
    names = {co["name"]: co["id"] for co in enabled}
    picked = right.multiselect("…or search selected companies only", list(names))
    if picked and right.button("Search selected"):
        _start_search([names[n] for n in picked])

    if companies:
        st.subheader("Target companies")
        st.dataframe(
            [
                {
                    "Company": co["name"],
                    "Job board": (
                        f"{co['platform']} ({co['discovery_status']})"
                        if co["platform"]
                        else co["discovery_status"]
                    ),
                    "Careers page": co["careers_url"],
                    "Enabled": co["enabled"],
                    "Jobs collected": co["jobs_collected"],
                    "Last success": fmt_dt(co["last_success_at"]),
                    "Last error": co["last_error"] or "",
                }
                for co in companies
            ],
            column_config={"Careers page": st.column_config.LinkColumn("Careers page", display_text="open")},
            hide_index=True,
            width="stretch",
        )
    history = guard(api.get, "/search/history", limit=10) or []
    if history:
        with st.expander("Search history"):
            st.dataframe(
                [
                    {
                        "#": h["id"],
                        "Started": fmt_dt(h["started_at"]),
                        "Trigger": h["trigger"],
                        "Status": h["status"] if h["finished_at"] else "running",
                        "Companies": f"{h['companies_done']}/{h['companies_searched']}",
                        "Fetched": h["jobs_fetched"],
                        "Qualified": h["qualified_jobs"],
                        "New": h["new_jobs"],
                        "Notes": len(h["errors"]),
                    }
                    for h in history
                ],
                hide_index=True,
                width="stretch",
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
