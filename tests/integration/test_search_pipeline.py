import pytest

from tests.helpers import ashby_job, gh_job, lever_job, make_pdf


def add_company(client, name, platform, token, **kw):
    r = client.post("/companies", json={"name": name, "platform": platform, "board_token": token, **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def run_search(client, company_ids=None):
    r = client.post("/search", json={"company_ids": company_ids})
    assert r.status_code == 202, r.text
    # TestClient runs background tasks before returning, so the run is already finished.
    out = client.get(f"/search/{r.json()['id']}").json()
    assert out["finished_at"] is not None
    return out


@pytest.fixture
def world(client, boards):
    boards.greenhouse["acme"] = [
        gh_job(1, "Senior Python Engineer", "Build APIs with Python and FastAPI. 5+ years of experience."),
        gh_job(2, "Pastry Chef", "Bake bread every morning."),
        gh_job(3, "Frontend Developer", "Work with React and TypeScript."),
    ]
    boards.lever["globex"] = [lever_job("L1", "Backend Developer", "We use Python and PostgreSQL.")]
    boards.ashby["initech"] = [ashby_job("A1", "Cloud Engineer", "AWS and Kubernetes work")]
    ids = {
        "acme": add_company(client, "Acme", "greenhouse", "acme"),
        "globex": add_company(client, "Globex", "lever", "globex"),
        "initech": add_company(client, "Initech", "ashby", "initech"),
    }
    for kw in ("Python", "React"):
        client.post("/keywords", json={"keyword": kw})
    return ids


def titles(client, **params):
    return sorted(j["title"] for j in client.get("/jobs", params=params).json()["items"])


def test_full_pipeline_or_qualification_across_three_platforms(client, world):
    s = run_search(client)
    assert s["status"] == "success" and s["companies_searched"] == 3
    assert s["jobs_fetched"] == 5 and s["qualified_jobs"] == 3 and s["new_jobs"] == 3
    found = titles(client, include_below_threshold="true")
    assert found == ["Backend Developer", "Frontend Developer", "Senior Python Engineer"]
    assert "Pastry Chef" not in found and "Cloud Engineer" not in found  # no keyword -> no qualify

    job = next(j for j in client.get("/jobs").json()["items"] if j["title"].startswith("Senior"))
    assert job["matched_keywords"] == ["Python"] and job["source"] == "greenhouse"
    detail = client.get(f"/jobs/{job['id']}").json()
    assert "<mark>Python</mark>" in detail["highlighted_description"]
    assert detail["excerpts"] and "not a hiring probability" in detail["explanation"]


def test_duplicates_not_created_on_rerun_and_updates_detected(client, world, boards):
    run_search(client)
    s2 = run_search(client)
    assert s2["new_jobs"] == 0 and s2["qualified_jobs"] == 3
    assert client.get("/jobs/stats").json()["stored_jobs"] == 3

    boards.greenhouse["acme"][0] = gh_job(1, "Senior Python Engineer", "Updated text about Python.")
    run_search(client)
    assert client.get("/jobs/stats").json()["stored_jobs"] == 3
    job = next(j for j in client.get("/jobs").json()["items"] if j["title"].startswith("Senior"))
    assert "Updated text" in client.get(f"/jobs/{job['id']}").json()["description"]


def test_selected_companies_and_disabled_company(client, world):
    s = run_search(client, [world["globex"]])
    assert s["companies_searched"] == 1
    assert titles(client, include_below_threshold="true") == ["Backend Developer"]

    client.patch(f"/companies/{world['globex']}", json={"enabled": False})
    s = run_search(client)
    assert s["companies_searched"] == 2  # acme + initech only
    comp = {c["name"]: c for c in client.get("/companies").json()}
    assert comp["Acme"]["jobs_collected"] == 3 and comp["Acme"]["last_success_at"]


def test_ai_threshold_never_discards_keyword_qualified_jobs(client, world):
    client.put("/preferences", json={"ai_threshold": 100, "ai_threshold_enabled": True})
    run_search(client)
    # Everything is stored and qualified even though no job can reach 100%...
    stats = client.get("/jobs/stats").json()
    assert stats["qualified_jobs"] == 3 and stats["above_threshold"] == 0
    # ...the threshold only filters what is *displayed* by default
    assert titles(client) == []
    assert len(titles(client, include_below_threshold="true")) == 3
    # and can be switched off entirely
    client.put("/preferences", json={"ai_threshold": 100, "ai_threshold_enabled": False})
    assert len(titles(client)) == 3
    # above_threshold is recomputed on the next search once the setting changed
    run_search(client)
    assert all(j["above_threshold"] for j in client.get("/jobs").json()["items"])


def test_scores_use_resume_and_report_matched_missing_skills(client, world):
    client.post("/resume", files={"file": ("jane.pdf", make_pdf())})
    run_search(client)
    items = client.get("/jobs", params={"include_below_threshold": "true"}).json()["items"]
    py = next(j for j in items if j["title"].startswith("Senior"))
    assert "Python" in py["matched_skills"] and "FastAPI" in py["matched_skills"]
    detail = client.get(f"/jobs/{py['id']}").json()
    assert detail["score_breakdown"]["components"]["semantic"] is not None
    assert 0 < py["score"] <= 100
    fe = next(j for j in items if j["title"] == "Frontend Developer")
    assert "React" in fe["missing_skills"]
    assert items[0]["score"] >= items[-1]["score"]  # ranked by score


def test_filters_sorting_pagination(client, world):
    run_search(client)
    base = {"include_below_threshold": "true"}
    assert titles(client, company="acme", **base) == ["Frontend Developer", "Senior Python Engineer"]
    assert titles(client, title="backend", **base) == ["Backend Developer"]
    assert titles(client, keyword="react", **base) == ["Frontend Developer"]
    assert titles(client, location="hyderabad", **base) == ["Backend Developer"]
    assert titles(client, source="lever", **base) == ["Backend Developer"]
    assert len(titles(client, min_score=0, **base)) == 3
    assert titles(client, min_score=100, **base) == []
    page = client.get("/jobs", params={"limit": 2, "offset": 0, **base}).json()
    assert page["total"] == 3 and len(page["items"]) == 2
    assert client.get("/jobs", params={"sort": "date", **base}).status_code == 200
    assert client.get("/jobs", params={"limit": 0}).status_code == 422
    assert titles(client, published_after="2027-01-01", **base) == []


def test_expired_jobs_are_detected_and_hidden(client, world, boards):
    run_search(client)
    boards.greenhouse["acme"] = [boards.greenhouse["acme"][0]]  # React job disappears
    run_search(client)
    assert "Frontend Developer" not in titles(client, include_below_threshold="true")
    expired = titles(client, include_below_threshold="true", include_expired="true")
    assert "Frontend Developer" in expired


def test_failed_company_does_not_stop_others_and_is_reported(client, world, boards):
    boards.greenhouse["acme"] = 500
    s = run_search(client)
    assert s["status"] == "partial" and any("Acme" in e for e in s["errors"])
    assert titles(client, include_below_threshold="true") == ["Backend Developer"]
    acme = next(c for c in client.get("/companies").json() if c["name"] == "Acme")
    assert acme["last_error"] and acme["last_success_at"] is None

    boards.greenhouse["acme"] = [gh_job(1, "Python Dev", "Python")]
    assert run_search(client)["status"] == "success"
    acme = next(c for c in client.get("/companies").json() if c["name"] == "Acme")
    assert acme["last_error"] is None


def test_all_companies_failing_and_empty_setup_messages(client, boards):
    assert "No enabled search keywords" in run_search(client)["errors"][0]
    client.post("/keywords", json={"keyword": "Python"})
    assert "No enabled target companies" in run_search(client)["errors"][0]
    add_company(client, "Ghost", "greenhouse", "ghost")
    s = run_search(client)
    assert s["status"] == "failed" and "404" in s["errors"][0]


def test_malformed_postings_are_skipped_and_reported(client, boards):
    boards.greenhouse["acme"] = [gh_job(1, "Python Dev", "Python"), {"id": 99}]
    add_company(client, "Acme", "greenhouse", "acme")
    client.post("/keywords", json={"keyword": "Python"})
    s = run_search(client)
    assert s["qualified_jobs"] == 1 and any("malformed" in e for e in s["errors"])


def test_keyword_removed_makes_stored_job_not_qualified(client, world):
    run_search(client)
    kid = next(k["id"] for k in client.get("/keywords").json() if k["keyword"] == "React")
    client.patch(f"/keywords/{kid}", json={"enabled": False})
    run_search(client)
    assert "Frontend Developer" not in titles(client, include_below_threshold="true")


def test_concurrent_search_is_refused(client, world):
    from backend.app.database.session import session_scope
    from backend.app.repositories.job_repos import HistoryRepository

    with session_scope() as db:
        HistoryRepository(db).start("manual")  # simulates a search still running
    assert client.post("/search", json={}).status_code == 409


# ------------------------------------------------------------- save + tracker
def test_save_and_application_tracker(client, world):
    run_search(client)
    jid = client.get("/jobs", params={"include_below_threshold": "true"}).json()["items"][0]["id"]
    assert client.post(f"/jobs/{jid}/save").status_code == 204
    assert client.post(f"/jobs/{jid}/save").status_code == 204  # idempotent
    saved = client.get("/jobs", params={"saved_only": "true"}).json()
    assert saved["total"] == 1 and saved["items"][0]["saved"] is True

    r = client.put(f"/tracker/{jid}", json={"status": "applied", "notes": "Referred by X"})
    assert r.json()["status"] == "applied" and r.json()["applied_date"]  # defaulted to today
    r = client.put(
        f"/tracker/{jid}", json={"status": "interviewing", "notes": "Round 1", "applied_date": "2026-11-01"}
    )
    assert r.json()["applied_date"] == "2026-11-01"
    tracked = client.get("/tracker").json()
    assert len(tracked) == 1 and tracked[0]["job"]["tracking_status"] == "interviewing"
    assert client.get("/tracker", params={"status": "rejected"}).json() == []
    assert client.put(f"/tracker/{jid}", json={"status": "bogus"}).status_code == 422
    assert client.put("/tracker/99999", json={"status": "applied"}).status_code == 404

    assert client.delete(f"/jobs/{jid}/save").status_code == 204
    assert client.get("/jobs", params={"saved_only": "true"}).json()["total"] == 0
    assert client.delete(f"/tracker/{jid}").status_code == 204 and client.get("/tracker").json() == []


def test_dashboard_stats(client, world):
    s0 = client.get("/jobs/stats").json()
    assert s0["last_success_at"] is None and s0["companies_monitored"] == 3
    run_search(client)
    s = client.get("/jobs/stats").json()
    assert s["qualified_jobs"] == 3 and s["new_jobs"] == 3 and s["last_success_at"]
    assert s["last_search_status"] == "success" and s["stored_jobs"] == 3


# ------------------------------------------------------------- notifications
def enable_email(client):
    r = client.put(
        "/preferences",
        json={"email_enabled": True, "email_to": "me@example.com", "ai_threshold_enabled": False},
    )
    assert r.status_code == 200


def test_email_sent_once_for_new_qualifying_jobs_only(client, world, smtp, boards):
    enable_email(client)
    run_search(client)
    assert len(smtp.sent) == 1
    msg = smtp.sent[0]
    body = msg.get_content()
    assert msg["To"] == "me@example.com" and "3 new matching jobs" in msg["Subject"]
    assert "Senior Python Engineer at Acme" in body and "Match score:" in body and "https://" in body
    assert "Pastry Chef" not in body

    run_search(client)  # nothing new
    assert len(smtp.sent) == 1

    boards.lever["globex"].append(lever_job("L2", "Python Platform Dev", "Python everywhere"))
    run_search(client)
    assert len(smtp.sent) == 2 and "Python Platform Dev" in smtp.sent[1].get_content()
    assert "Backend Developer" not in smtp.sent[1].get_content()  # no duplicate notifications


def test_email_respects_preferences_and_threshold(client, world, smtp):
    run_search(client)  # email disabled (default)
    assert smtp.sent == []
    client.put(
        "/preferences",
        json={
            "email_enabled": True,
            "email_to": "me@example.com",
            "ai_threshold_enabled": True,
            "ai_threshold": 100,
        },
    )
    # first sighting of jobs that score below the threshold: stored, but not emailed
    run_search(client)
    assert client.get("/jobs/stats").json()["qualified_jobs"] == 3
    assert smtp.sent == []


def test_email_failure_is_reported_and_retried_next_time(client, world, smtp):
    enable_email(client)
    smtp.fail = True
    s = run_search(client)
    assert smtp.sent == [] and any("could not be sent" in e for e in s["errors"])
    assert s["status"] == "partial"
    smtp.fail = False
    from backend.app.database.session import session_scope
    from backend.app.models import Job

    with session_scope() as db:
        for j in db.query(Job).all():
            db.delete(j)  # forget jobs so they count as new again
    run_search(client)
    assert len(smtp.sent) == 1


def test_email_not_configured_gives_clear_error(client, world, monkeypatch):
    from backend.app.core.config import get_settings

    enable_email(client)
    monkeypatch.setenv("SMTP_HOST", "")
    get_settings.cache_clear()
    s = run_search(client)
    assert any("SMTP is not configured" in e for e in s["errors"])
    assert client.get("/jobs/stats").status_code == 200  # searching itself still works
