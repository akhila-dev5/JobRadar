"""Settings: companies, keywords, preferences, resume profile."""

from __future__ import annotations

import streamlit as st

from frontend.views.common import client, fmt_dt, guard

PLATFORMS = ["greenhouse", "lever", "ashby"]


def _lines(text: str) -> list[str]:
    return [p.strip() for chunk in text.splitlines() for p in chunk.split(",") if p.strip()]


def tab_companies() -> None:
    api = client()
    st.caption(
        "Companies must use a supported public job-board platform. The board token is the part of the careers URL "
        "after the platform host, e.g. boards.greenhouse.io/**acme**, jobs.lever.co/**acme**, jobs.ashbyhq.com/**acme**."
    )
    with st.form("add-company", clear_on_submit=True):
        c = st.columns([2, 1, 2, 1])
        name = c[0].text_input("Company name")
        platform = c[1].selectbox("Platform", PLATFORMS)
        token = c[2].text_input("Board token")
        region = c[3].selectbox("Lever region", ["us", "eu"])
        if st.form_submit_button("Add company", type="primary"):
            if guard(
                api.post,
                "/companies",
                json={"name": name, "platform": platform, "board_token": token, "api_region": region},
            ):
                st.rerun()

    companies = guard(api.get, "/companies") or []
    for co in companies:
        with st.container(border=True):
            c = st.columns([3, 1, 1, 1, 1])
            c[0].markdown(f"**{co['name']}**  \n`{co['platform']}` / `{co['board_token']}`")
            c[1].caption(f"{co['jobs_collected']} jobs")
            c[1].caption(f"ok: {fmt_dt(co['last_success_at'])}")
            enabled = c[2].toggle("Enabled", value=co["enabled"], key=f"en-{co['id']}")
            if enabled != co["enabled"]:
                guard(api.patch, f"/companies/{co['id']}", json={"enabled": enabled})
                st.rerun()
            if c[3].button("Test", key=f"te-{co['id']}"):
                res = guard(api.post, f"/companies/{co['id']}/test")
                if res:
                    (st.success if res["ok"] else st.error)(res["message"])
            if c[4].button("Delete", key=f"de-{co['id']}"):
                guard(api.delete, f"/companies/{co['id']}")
                st.rerun()
            if co["last_error"]:
                st.caption(f"⚠️ {co['last_error']}")
            with st.expander("Edit"):
                with st.form(f"edit-{co['id']}"):
                    e = st.columns(3)
                    n = e[0].text_input("Name", co["name"])
                    p = e[1].selectbox("Platform", PLATFORMS, index=PLATFORMS.index(co["platform"]))
                    t = e[2].text_input("Board token", co["board_token"])
                    if st.form_submit_button("Save"):
                        if guard(
                            api.patch,
                            f"/companies/{co['id']}",
                            json={"name": n, "platform": p, "board_token": t},
                        ):
                            st.rerun()

    st.subheader("Import / export")
    c = st.columns(3)
    fmt = c[0].radio("Format", ["json", "csv"], horizontal=True)
    exported = guard(api.get_text, "/companies/export", format=fmt)
    if exported is not None:
        c[1].download_button(f"Export .{fmt}", exported, file_name=f"companies.{fmt}")
    upload = c[2].file_uploader("Import file", type=["json", "csv"], key="co-import")
    if upload and st.button("Import"):
        res = guard(
            api.post,
            "/companies/import",
            params={"format": upload.name.rsplit(".", 1)[-1]},
            files={"file": (upload.name, upload.getvalue())},
        )
        if res:
            st.success(f"Created {res['created']}, updated {res['updated']}.")
            for err in res["errors"]:
                st.warning(err)


def tab_keywords() -> None:
    api = client()
    st.info("A job qualifies when **any one** enabled keyword (or alias) matches its title or description.")
    with st.form("add-kw", clear_on_submit=True):
        c = st.columns([2, 3])
        kw = c[0].text_input("Keyword or phrase")
        aliases = c[1].text_input("Aliases (comma separated, optional)")
        if st.form_submit_button("Add keyword", type="primary"):
            if guard(api.post, "/keywords", json={"keyword": kw, "aliases": _lines(aliases)}):
                st.rerun()
    for k in guard(api.get, "/keywords") or []:
        c = st.columns([3, 3, 1, 1])
        c[0].markdown(f"**{k['keyword']}**")
        c[1].caption(", ".join(k["aliases"]) or "no aliases")
        enabled = c[2].toggle("On", value=k["enabled"], key=f"kon-{k['id']}")
        if enabled != k["enabled"]:
            guard(api.patch, f"/keywords/{k['id']}", json={"enabled": enabled})
            st.rerun()
        if c[3].button("Delete", key=f"kde-{k['id']}"):
            guard(api.delete, f"/keywords/{k['id']}")
            st.rerun()

    st.subheader("Try it")
    t = st.text_input("Job title", "Software Engineer")
    d = st.text_area("Description", "We build services in Python and React.")
    if st.button("Test match"):
        res = guard(api.post, "/keywords/test", json={"title": t, "description": d})
        if res:
            if res["qualified"]:
                st.success("Qualifies via: " + ", ".join(res["matched_keywords"]))
            else:
                st.warning("No enabled keyword matches.")
            st.markdown(res["highlighted_description"], unsafe_allow_html=True)


def tab_preferences() -> None:
    api = client()
    p = guard(api.get, "/preferences")
    if p is None:
        return
    with st.form("prefs"):
        titles = st.text_area("Preferred job titles (one per line)", "\n".join(p["preferred_titles"]))
        locs = st.text_area("Preferred locations (one per line)", "\n".join(p["preferred_locations"]))
        modes = st.multiselect("Work mode", ["remote", "hybrid", "onsite"], default=p["work_modes"])
        c = st.columns(2)
        min_exp = c[0].number_input(
            "Min experience (years)", 0.0, 60.0, float(p["min_experience"] or 0.0), 0.5
        )
        max_exp = c[1].number_input(
            "Max experience (years, 0 = no limit)", 0.0, 60.0, float(p["max_experience"] or 0.0), 0.5
        )
        types = st.text_input("Employment types (comma separated)", ", ".join(p["employment_types"]))
        c = st.columns(3)
        smin = c[0].number_input("Salary min (optional)", 0, value=int(p["salary_min"] or 0), step=1000)
        smax = c[1].number_input("Salary max (optional)", 0, value=int(p["salary_max"] or 0), step=1000)
        cur = c[2].text_input("Currency", p["salary_currency"] or "")
        st.markdown("**AI relevance**")
        c = st.columns(2)
        thr_on = c[0].toggle("Use AI score threshold to filter results", value=p["ai_threshold_enabled"])
        thr = c[1].slider("Minimum AI relevance score", 0, 100, int(p["ai_threshold"]))
        st.caption(
            "Jobs matching a keyword are always kept. The threshold only decides what is shown by default and emailed."
        )
        w = p["scoring_weights"] or {}
        with st.expander("Scoring weights (advanced; normalised automatically)"):
            wc = st.columns(5)
            weights = {
                name: wc[i].number_input(name.title(), 0.0, 1.0, float(w.get(name, default)), 0.05)
                for i, (name, default) in enumerate(
                    [
                        ("skills", 0.30),
                        ("semantic", 0.30),
                        ("title", 0.15),
                        ("experience", 0.10),
                        ("keywords", 0.15),
                    ]
                )
            }
        st.markdown("**Email notifications (optional)**")
        email_on = st.toggle("Email me about new qualifying jobs", value=p["email_enabled"])
        email_to = st.text_input("Send to", p["email_to"] or "")
        st.caption("SMTP credentials live in your local .env file, never here.")
        if st.form_submit_button("Save preferences", type="primary"):
            body = {
                "preferred_titles": _lines(titles),
                "preferred_locations": _lines(locs),
                "work_modes": modes,
                "min_experience": min_exp or None,
                "max_experience": max_exp or None,
                "employment_types": _lines(types),
                "salary_min": smin or None,
                "salary_max": smax or None,
                "salary_currency": cur or None,
                "ai_threshold_enabled": thr_on,
                "ai_threshold": thr,
                "scoring_weights": weights if sum(weights.values()) > 0 else None,
                "email_enabled": email_on,
                "email_to": email_to or None,
            }
            if guard(api.put, "/preferences", json=body) is not None:
                st.success("Saved.")


def tab_resume() -> None:
    api = client()
    st.caption(
        "Your original file stays in the local data/resumes folder. Only the extracted profile is stored in Supabase."
    )
    up = st.file_uploader("Upload resume (PDF or DOCX, max 5 MB)", type=["pdf", "docx"])
    label = st.text_input("Label (optional)")
    if up and st.button("Upload and parse", type="primary"):
        res = guard(api.post, "/resume", files={"file": (up.name, up.getvalue())}, data={"label": label})
        if res:
            st.success(f"Parsed {len(res['skills'])} skills.")
            st.rerun()
    resumes = guard(api.get, "/resume") or []
    if not resumes:
        st.info("No resume yet. Without one, scores use keywords and titles only.")
    for r in resumes:
        with st.container(border=True):
            c = st.columns([4, 1, 1])
            c[0].markdown(
                f"**{r['label']}** {'· ✅ active' if r['is_active'] else ''}  \n{r['original_filename']}"
            )
            if not r["is_active"] and c[1].button("Activate", key=f"ra-{r['id']}"):
                guard(api.post, f"/resume/{r['id']}/activate")
                st.rerun()
            if c[2].button("Delete", key=f"rd-{r['id']}"):
                guard(api.delete, f"/resume/{r['id']}", delete_local_file="true")
                st.rerun()
            if not r["is_active"]:
                continue
            st.markdown(f"**Experience:** {r['experience_years'] or 'unknown'} years")
            st.markdown("**Titles:** " + (", ".join(r["job_titles"]) or "–"))
            st.markdown("**Education:** " + (" | ".join(r["education"]) or "–"))
            st.markdown("**Certifications:** " + (" | ".join(r["certifications"]) or "–"))
            by_cat: dict[str, list[str]] = {}
            for s in r["skills"]:
                by_cat.setdefault(s["category"], []).append(s["name"])
            for cat, names in sorted(by_cat.items()):
                st.markdown(f"**{cat.title()}:** " + ", ".join(sorted(names)))
            st.markdown("**Correct extracted skills**")
            c = st.columns([3, 1])
            new_skill = c[0].text_input("Add a skill", key=f"ns-{r['id']}")
            if c[1].button("Add", key=f"na-{r['id']}") and new_skill:
                guard(api.post, f"/resume/{r['id']}/skills", json={"name": new_skill})
                st.rerun()
            drop = st.multiselect(
                "Remove skills", sorted(s["name"] for s in r["skills"]), key=f"rs-{r['id']}"
            )
            if drop and st.button("Remove selected", key=f"rr-{r['id']}"):
                for name in drop:
                    guard(api.delete, f"/resume/{r['id']}/skills/{name}")
                st.rerun()
    st.caption("Deleting a resume removes its extracted data from the database and its local copy.")


def page_settings() -> None:
    st.title("Settings")
    t1, t2, t3, t4 = st.tabs(["🏢 Companies", "🔑 Keywords", "🎯 Preferences", "📄 Resume"])
    with t1:
        tab_companies()
    with t2:
        tab_keywords()
    with t3:
        tab_preferences()
    with t4:
        tab_resume()
