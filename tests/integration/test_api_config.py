import json

from tests.helpers import RESUME_TEXT, make_blank_pdf, make_docx, make_pdf

CO = {"name": "Acme", "platform": "greenhouse", "board_token": "acme"}


# ------------------------------------------------------------- companies
def test_company_crud_and_toggle(client):
    r = client.post("/companies", json=CO)
    assert r.status_code == 201
    cid = r.json()["id"]
    assert r.json()["enabled"] is True and r.json()["jobs_collected"] == 0

    r = client.patch(f"/companies/{cid}", json={"enabled": False, "name": "Acme Inc"})
    assert r.json()["enabled"] is False and r.json()["name"] == "Acme Inc"
    assert [c["name"] for c in client.get("/companies").json()] == ["Acme Inc"]

    assert client.delete(f"/companies/{cid}").status_code == 204
    assert client.get("/companies").json() == []
    assert client.patch(f"/companies/{cid}", json={"enabled": True}).status_code == 404


def test_company_validation_and_duplicates(client):
    assert client.post("/companies", json={**CO, "platform": "workday"}).status_code == 422
    assert client.post("/companies", json={**CO, "board_token": "bad token!"}).status_code == 422
    assert client.post("/companies", json={**CO, "name": "  "}).status_code == 422
    assert client.post("/companies", json=CO).status_code == 201
    assert client.post("/companies", json=CO).status_code == 409
    other = {"name": "acme", "platform": "lever", "board_token": "x"}  # same name, case-insensitive
    assert client.post("/companies", json=other).status_code == 409


def test_company_export_import_roundtrip_json_and_csv(client):
    client.post("/companies", json=CO)
    client.post(
        "/companies",
        json={
            "name": "Globex",
            "platform": "lever",
            "board_token": "globex",
            "api_region": "eu",
            "enabled": False,
        },
    )
    exported_json = client.get("/companies/export?format=json").text
    exported_csv = client.get("/companies/export?format=csv").text
    assert json.loads(exported_json)[1]["api_region"] == "eu"
    assert exported_csv.splitlines()[0] == "name,platform,board_token,api_region,enabled"

    for c in client.get("/companies").json():
        client.delete(f"/companies/{c['id']}")

    r = client.post("/companies/import?format=json", files={"file": ("c.json", exported_json)})
    assert r.json() == {"created": 2, "updated": 0, "errors": []}
    r = client.post("/companies/import?format=csv", files={"file": ("c.csv", exported_csv)})
    assert r.json() == {"created": 0, "updated": 2, "errors": []}
    globex = next(c for c in client.get("/companies").json() if c["name"] == "Globex")
    assert globex["enabled"] is False and globex["api_region"] == "eu"


def test_company_import_reports_bad_rows_and_bad_files(client):
    bad = json.dumps(
        [
            {"name": "Ok", "platform": "ashby", "board_token": "ok"},
            {"name": "Bad", "platform": "nope", "board_token": "x"},
            "junk",
        ]
    )
    r = client.post("/companies/import?format=json", files={"file": ("c.json", bad)}).json()
    assert r["created"] == 1 and len(r["errors"]) == 2
    r = client.post("/companies/import?format=json", files={"file": ("c.json", "{not json")}).json()
    assert r["created"] == 0 and "Could not read" in r["errors"][0]


def test_company_test_endpoint(client, boards):
    boards.greenhouse["acme"] = [{"id": 1, "title": "T", "absolute_url": "https://x", "content": "c"}]
    cid = client.post("/companies", json=CO).json()["id"]
    r = client.post(f"/companies/{cid}/test").json()
    assert r["ok"] and r["job_count"] == 1
    cid2 = client.post("/companies", json={**CO, "name": "Ghost", "board_token": "ghost"}).json()["id"]
    r = client.post(f"/companies/{cid2}/test").json()
    assert not r["ok"] and "404" in r["message"]


# ------------------------------------------------------------- keywords
def test_keyword_crud_aliases_and_duplicates(client):
    r = client.post(
        "/keywords", json={"keyword": "PostgreSQL", "aliases": ["postgres", "Postgres", " psql "]}
    )
    assert r.status_code == 201 and r.json()["aliases"] == ["postgres", "psql"]
    kid = r.json()["id"]
    assert client.post("/keywords", json={"keyword": "postgresql"}).status_code == 409
    r = client.patch(f"/keywords/{kid}", json={"enabled": False})
    assert r.json()["enabled"] is False
    assert client.delete(f"/keywords/{kid}").status_code == 204
    assert client.get("/keywords").json() == []


def test_keyword_test_endpoint_or_logic_and_highlight(client):
    client.post("/keywords", json={"keyword": "Python"})
    client.post("/keywords", json={"keyword": "React"})
    client.post("/keywords", json={"keyword": "Azure", "enabled": False})
    r = client.post(
        "/keywords/test", json={"title": "Dev", "description": "Only Python here, Azure too"}
    ).json()
    assert r["qualified"] and r["matched_keywords"] == ["Python"]  # disabled keyword ignored
    assert "<mark>Python</mark>" in r["highlighted_description"]
    r = client.post("/keywords/test", json={"title": "Chef", "description": "Bake bread"}).json()
    assert not r["qualified"]


# ------------------------------------------------------------- preferences
def test_preferences_defaults_and_update(client):
    d = client.get("/preferences").json()
    assert d["ai_threshold"] == 40.0 and d["ai_threshold_enabled"] is True
    body = {
        "preferred_titles": ["Backend Engineer", "backend engineer"],
        "preferred_locations": ["Hyderabad"],
        "work_modes": ["remote", "hybrid"],
        "min_experience": 2,
        "max_experience": 5,
        "ai_threshold": 55,
        "ai_threshold_enabled": False,
        "scoring_weights": {"skills": 2, "semantic": 1},
    }
    r = client.put("/preferences", json=body)
    assert r.status_code == 200
    out = client.get("/preferences").json()
    assert out["preferred_titles"] == ["Backend Engineer"] and out["ai_threshold"] == 55
    assert out["ai_threshold_enabled"] is False and out["scoring_weights"] == {"skills": 2, "semantic": 1}


def test_preferences_validation(client):
    bad_bodies = [
        {"min_experience": 6, "max_experience": 2},
        {"ai_threshold": 150},
        {"work_modes": ["moon"]},
        {"salary_min": 10, "salary_max": 5},
        {"email_enabled": True},
        {"email_enabled": True, "email_to": "not-an-email"},
        {"scoring_weights": {"skills": 0}},
        {"scoring_weights": {"magic": 1}},
    ]
    for body in bad_bodies:
        assert client.put("/preferences", json=body).status_code == 422, body


# ------------------------------------------------------------- resume
def test_resume_upload_pdf_and_docx_parse_and_active(client, settings):
    pdf_bytes = make_pdf()  # PyMuPDF adds a random ID, so reuse one byte string
    r = client.post("/resume", files={"file": ("jane.pdf", pdf_bytes, "application/pdf")})
    assert r.status_code == 201
    body = r.json()
    names = {s["name"] for s in body["skills"]}
    assert {"Python", "FastAPI", "PostgreSQL"} <= names and body["is_active"]
    assert body["experience_years"] >= 6

    r2 = client.post(
        "/resume",
        files={
            "file": ("jane2.docx", make_docx(RESUME_TEXT + "\nKubernetes")),
        },
        data={"label": "v2"},
    )
    assert r2.status_code == 201 and r2.json()["label"] == "v2" and r2.json()["is_active"]
    assert client.get("/resume/active").json()["id"] == r2.json()["id"]
    assert [x["is_active"] for x in client.get("/resume").json()].count(True) == 1

    again = client.post("/resume", files={"file": ("copy.pdf", pdf_bytes)})  # same bytes -> same resume
    assert again.json()["id"] == body["id"] and len(client.get("/resume").json()) == 2
    assert any(p.suffix == ".pdf" for p in settings.resume_dir.iterdir())  # original stays local


def test_resume_upload_rejections(client):
    assert client.post("/resume", files={"file": ("a.txt", b"hello")}).status_code == 400
    assert client.post("/resume", files={"file": ("a.pdf", b"not a pdf")}).status_code == 400
    assert client.post("/resume", files={"file": ("a.pdf", make_blank_pdf())}).status_code == 400
    big = b"%PDF-" + b"0" * (2 * 1024 * 1024)  # test settings cap uploads at 1 MB
    r = client.post("/resume", files={"file": ("big.pdf", big)})
    assert r.status_code == 400 and "limit" in r.json()["detail"]


def test_resume_manual_skill_correction_and_delete(client, settings):
    rid = client.post("/resume", files={"file": ("jane.pdf", make_pdf())}).json()["id"]
    r = client.post(f"/resume/{rid}/skills", json={"name": "kubernetes"})
    added = next(s for s in r.json()["skills"] if s["name"] == "Kubernetes")
    assert added["source"] == "manual" and added["category"] == "cloud"
    r = client.delete(f"/resume/{rid}/skills/Docker")
    assert "Docker" not in {s["name"] for s in r.json()["skills"]}
    assert client.delete(f"/resume/{rid}/skills/Nope").status_code == 404
    r = client.patch(f"/resume/{rid}", json={"experience_years": 9.5, "job_titles": ["Staff Engineer"]})
    assert r.json()["experience_years"] == 9.5 and r.json()["job_titles"] == ["Staff Engineer"]

    assert client.delete(f"/resume/{rid}?delete_local_file=true").status_code == 204
    assert client.get("/resume").json() == [] and client.get("/resume/active").json() is None
    assert not any(settings.resume_dir.iterdir())


def test_health_and_api_key(client, monkeypatch):
    assert client.get("/health").json()["status"] == "ok"
    from backend.app.core.config import get_settings

    monkeypatch.setenv("API_KEY", "s3cret")
    get_settings.cache_clear()
    assert client.get("/companies").status_code == 401
    assert client.get("/companies", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/companies", headers={"X-API-Key": "s3cret"}).status_code == 200
