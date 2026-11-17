"""Add companies by NAME ONLY: the app finds the job board and shows direct posting links."""

import io

from backend.app.models import Company
from tests.helpers import ashby_job, gh_job, lever_job


def companies(client):
    return {c["name"]: c for c in client.get("/companies").json()}


def add(client, name, **extra):
    r = client.post("/companies", json={"name": name, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def search(client, ids=None):
    r = client.post("/search", json={"company_ids": ids})
    assert r.status_code == 202, r.text
    return client.get(f"/search/{r.json()['id']}").json()


# ------------------------------------------------------------------ adding by name
def test_name_only_company_is_accepted_and_its_board_found_automatically(client, boards):
    boards.greenhouse_names["acme"] = "Acme, Inc."
    boards.greenhouse["acme"] = [gh_job(1, "Python Engineer", "We use Python.")]
    created = add(client, "Acme")
    assert (
        created["discovery_status"] == "pending" and created["platform"] is None
    )  # response before discovery

    acme = companies(client)["Acme"]  # background task has run
    assert (acme["platform"], acme["board_token"], acme["discovery_status"]) == (
        "greenhouse",
        "acme",
        "verified",
    )
    assert acme["careers_url"] == "https://boards.greenhouse.io/acme"


def test_unverified_match_is_used_but_flagged_with_a_link_to_confirm(client, boards):
    boards.lever["globex"] = [lever_job("L1", "Backend Developer", "Python")]
    add(client, "Globex")
    globex = companies(client)["Globex"]
    assert (globex["platform"], globex["discovery_status"]) == ("lever", "unverified")
    assert globex["careers_url"] == "https://jobs.lever.co/globex"


def test_company_without_a_public_board_says_so(client):
    add(client, "Mystery Corp")
    mystery = companies(client)["Mystery Corp"]
    assert mystery["discovery_status"] == "not_found" and mystery["platform"] is None
    assert mystery["careers_url"] is None and "own careers site" in mystery["last_error"]


def test_board_of_a_differently_named_company_is_not_adopted(client, boards):
    boards.greenhouse_names["acme"] = "Acme Rocket Skates"
    boards.greenhouse["acme"] = [gh_job(1, "Engineer", "x")]
    add(client, "Acme Labs")
    assert companies(client)["Acme Labs"]["discovery_status"] == "not_found"


def test_pasting_a_careers_link_skips_discovery(client, boards):
    created = add(client, "Initech", careers_url="https://jobs.ashbyhq.com/initech/abc")
    assert (created["platform"], created["board_token"], created["discovery_status"]) == (
        "ashby",
        "initech",
        "manual",
    )
    assert not any("ashbyhq" in c for c in boards.calls)  # nothing probed: the user chose the board


def test_unrecognised_careers_link_is_rejected_with_help(client):
    r = client.post("/companies", json={"name": "X", "careers_url": "https://www.example.com/careers"})
    assert r.status_code == 422 and "Greenhouse, Lever or Ashby" in r.text


def test_platform_and_token_must_come_together(client):
    assert client.post("/companies", json={"name": "X", "platform": "lever"}).status_code == 422
    assert client.post("/companies", json={"name": "X", "board_token": "x"}).status_code == 422


def test_explicit_platform_and_token_still_work(client):
    created = add(client, "Acme", platform="greenhouse", board_token="acme")
    assert created["discovery_status"] == "manual"


def test_bulk_add_from_a_list_of_names(client, boards):
    boards.greenhouse_names["acme"] = "Acme"
    boards.greenhouse["acme"] = [gh_job(1, "Engineer", "x")]
    boards.ashby["initech"] = [ashby_job("A1", "Dev", "x")]
    add(client, "Globex Existing")
    r = client.post(
        "/companies/bulk", json={"names": ["Acme", "Initech", "Nobody Ltd", "globex existing", "acme"]}
    )
    assert r.status_code == 201
    body = r.json()
    assert [c["name"] for c in body["created"]] == ["Acme", "Initech", "Nobody Ltd"]
    assert body["skipped"] == [
        "globex existing"
    ]  # already exists (case-insensitive); duplicate "acme" collapsed

    status = {n: c["discovery_status"] for n, c in companies(client).items()}
    assert (
        status["Acme"] == "verified"
        and status["Initech"] == "unverified"
        and status["Nobody Ltd"] == "not_found"
    )


def test_same_company_spelled_differently_is_rejected_as_a_duplicate(client, boards):
    boards.greenhouse_names["acme"] = "Acme"
    boards.greenhouse["acme"] = [gh_job(1, "Engineer", "x")]
    add(client, "Acme")
    for variant in ("Acme Inc", "ACME, Inc.", "acme"):
        r = client.post("/companies", json={"name": variant})
        assert r.status_code == 409 and "already exists (Acme)" in r.json()["detail"]
    assert list(companies(client)) == ["Acme"]


def test_bulk_add_skips_spelling_variants_of_the_same_company(client, boards):
    r = client.post("/companies/bulk", json={"names": ["Stripe", "Stripe, Inc.", "stripe"]})
    assert r.status_code == 201
    assert [c["name"] for c in r.json()["created"]] == ["Stripe"]
    assert r.json()["skipped"] == ["Stripe, Inc."]  # exact repeats ("stripe") are collapsed earlier


def test_a_board_already_tracked_under_another_entry_is_not_adopted_twice(client, boards, db):
    from backend.app.services.board_discovery import BoardCandidate, DiscoveryResult
    from backend.app.services.discovery_runner import discover_company

    boards.greenhouse_names["acme"] = "Acme"
    boards.greenhouse["acme"] = [gh_job(1, "Engineer", "x")]
    add(client, "Acme")  # discovered: greenhouse/acme
    other = Company(name="Totally Different Name", discovery_status="pending")
    db.add(other)
    db.commit()

    class StubDiscovery:  # pretends discovery resolved the other entry to the same board
        def discover(self, name):
            best = BoardCandidate("greenhouse", "acme", "us", 1, verified=True)
            return DiscoveryResult("verified", [best], best, "found", ["acme"])

    result = discover_company(db, db.get(Company, other.id), StubDiscovery())
    assert result.status == "not_found" and "already tracked as 'Acme'" in result.message
    assert db.get(Company, other.id).platform is None


def test_rediscover_looks_again(client, boards):
    add(client, "Acme")
    assert companies(client)["Acme"]["discovery_status"] == "not_found"
    boards.greenhouse_names["acme"] = "Acme"  # the company has since published a board
    boards.greenhouse["acme"] = [gh_job(1, "Engineer", "x")]
    r = client.post(f"/companies/{companies(client)['Acme']['id']}/discover")
    assert r.status_code == 200
    assert companies(client)["Acme"]["discovery_status"] == "verified"


def test_editing_the_board_by_hand_marks_it_manual(client, boards):
    boards.lever["globex"] = [lever_job("L1", "Dev", "x")]
    add(client, "Globex")
    cid = companies(client)["Globex"]["id"]
    r = client.patch(f"/companies/{cid}", json={"careers_url": "https://jobs.lever.co/globex-eu"})
    assert r.status_code == 200 and r.json()["discovery_status"] == "manual"
    assert r.json()["board_token"] == "globex-eu"


def test_test_button_on_a_company_without_a_board(client):
    add(client, "Mystery Corp")
    cid = companies(client)["Mystery Corp"]["id"]
    res = client.post(f"/companies/{cid}/test").json()
    assert res["ok"] is False and "No job board known" in res["message"]


def test_import_of_names_only_csv_discovers_boards(client, boards):
    boards.greenhouse_names["acme"] = "Acme"
    boards.greenhouse["acme"] = [gh_job(1, "Engineer", "x")]
    csv = "name,platform,board_token\nAcme,,\nNobody Ltd,,\n"
    r = client.post("/companies/import?format=csv", files={"file": ("c.csv", io.BytesIO(csv.encode()))})
    assert r.json()["created"] == 2 and r.json()["errors"] == []
    status = {n: c["discovery_status"] for n, c in companies(client).items()}
    assert status == {"Acme": "verified", "Nobody Ltd": "not_found"}


def test_reimport_of_a_name_does_not_wipe_a_known_board(client, boards):
    add(client, "Acme", platform="greenhouse", board_token="acme")
    csv = "name,platform,board_token\nAcme,,\n"
    client.post("/companies/import?format=csv", files={"file": ("c.csv", io.BytesIO(csv.encode()))})
    acme = companies(client)["Acme"]
    assert (acme["platform"], acme["board_token"]) == ("greenhouse", "acme")


# ------------------------------------------------------------------ search integration
def test_search_discovers_pending_companies_and_returns_direct_posting_links(client, boards, db):
    boards.greenhouse_names["acme"] = "Acme"
    boards.greenhouse["acme"] = [gh_job(7, "Python Engineer", "We use Python."), gh_job(8, "Chef", "Bake.")]
    db.add(Company(name="Acme", discovery_status="pending"))  # e.g. added while discovery was down
    db.commit()
    client.post("/keywords", json={"keyword": "Python"})

    s = search(client)
    assert s["status"] == "success" and s["qualified_jobs"] == 1
    job = client.get("/jobs", params={"include_below_threshold": "true"}).json()["items"][0]
    assert job["application_url"] == "https://boards.greenhouse.io/acme/jobs/7"  # the real posting link
    assert companies(client)["Acme"]["discovery_status"] == "verified"


def test_search_continues_past_companies_without_a_board_and_reports_them(client, boards):
    boards.greenhouse_names["acme"] = "Acme"
    boards.greenhouse["acme"] = [gh_job(1, "Python Engineer", "Python")]
    add(client, "Acme")
    add(client, "Mystery Corp")
    client.post("/keywords", json={"keyword": "Python"})
    s = search(client)
    assert s["status"] == "partial" and s["qualified_jobs"] == 1
    assert any("Mystery Corp" in e and "own careers site" in e for e in s["errors"])


def test_search_progress_fields_are_filled_in(client, boards):
    boards.greenhouse_names["acme"] = "Acme"
    boards.greenhouse["acme"] = [gh_job(1, "Python Engineer", "Python")]
    boards.lever["globex"] = [lever_job("L1", "Python Dev", "Python")]
    add(client, "Acme")
    add(client, "Globex")
    client.post("/keywords", json={"keyword": "Python"})
    s = search(client)
    assert s["companies_searched"] == 2 and s["companies_done"] == 2
    assert s["current_company"] is None and s["finished_at"] is not None
    assert s["jobs_fetched"] == 2 and s["qualified_jobs"] == 2
    history = client.get("/search/history").json()
    assert history[0]["id"] == s["id"] and history[0]["companies_done"] == 2


def test_offline_discovery_is_marked_unreachable_and_recovers_at_the_next_search(client, boards):
    boards.offline = True
    add(client, "Acme")
    acme = companies(client)["Acme"]
    assert acme["discovery_status"] == "unreachable" and acme["platform"] is None
    assert "internet" in acme["last_error"]

    boards.offline = False  # connection is back
    boards.greenhouse_names["acme"] = "Acme"
    boards.greenhouse["acme"] = [gh_job(1, "Python Engineer", "Python")]
    client.post("/keywords", json={"keyword": "Python"})
    s = search(client)
    assert s["status"] == "success" and s["qualified_jobs"] == 1
    assert companies(client)["Acme"]["discovery_status"] == "verified"
