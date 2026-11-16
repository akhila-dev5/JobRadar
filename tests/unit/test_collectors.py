import httpx
import pytest

from backend.app.collectors import CollectorError, CompanyTarget, HttpFetcher, get_collector
from backend.app.collectors.base import html_to_text, parse_datetime
from tests.helpers import FakeBoards, ashby_job, gh_job, lever_job


def fetcher(boards: FakeBoards, retries=2, sleeps=None):
    return HttpFetcher(
        transport=boards.transport(),
        min_interval=0,
        max_retries=retries,
        sleep=(sleeps.append if sleeps is not None else (lambda s: None)),
    )


def test_html_to_text_handles_double_encoding_and_blocks():
    assert (
        html_to_text(
            "&lt;p&gt;Hello&lt;/p&gt;&lt;ul&gt;&lt;li&gt;A&lt;/li&gt;&lt;li&gt;B&lt;/li&gt;&lt;/ul&gt;"
        )
        == "Hello\nA\nB"
    )
    assert html_to_text("<script>x()</script><p>Hi &amp; bye</p>") == "Hi & bye"
    assert html_to_text(None) == ""


def test_parse_datetime_variants():
    assert parse_datetime("2026-11-01T10:00:00Z").year == 2026
    assert parse_datetime(1761990000000).tzinfo is not None
    assert parse_datetime("garbage") is None and parse_datetime(None) is None


def test_greenhouse_normalisation():
    b = FakeBoards()
    b.greenhouse["acme"] = [gh_job(1, "Python Dev", "Build <b>APIs</b>")]
    (job,) = get_collector("greenhouse", fetcher(b)).fetch_jobs(CompanyTarget("Acme", "acme"))
    assert (job.source, job.external_id, job.company_name) == ("greenhouse", "1", "Acme")
    assert job.title == "Python Dev" and "APIs" in job.description and "<" not in job.description
    assert job.location == "Remote" and job.published_at is not None
    assert job.application_url.endswith("/jobs/1")
    assert "content=true" in b.calls[0]


def test_lever_paginates_and_normalises():
    b = FakeBoards()
    b.lever["globex"] = [lever_job(f"id{i}", f"Role {i}", "desc here") for i in range(205)]
    jobs = get_collector("lever", fetcher(b)).fetch_jobs(CompanyTarget("Globex", "globex"))
    assert len(jobs) == 205 and len(b.calls) == 3  # 100 + 100 + 5
    j = jobs[0]
    assert j.employment_type == "Full-time" and j.workplace_type == "hybrid"
    assert "3+ years" in j.description and j.application_url.endswith("/apply")


def test_lever_eu_region_uses_eu_host():
    b = FakeBoards()
    b.lever["globex"] = []
    get_collector("lever", fetcher(b)).fetch_jobs(CompanyTarget("Globex", "globex", "eu"))
    assert "api.eu.lever.co" in b.calls[0]


def test_ashby_skips_unlisted_and_uses_fields():
    b = FakeBoards()
    b.ashby["initech"] = [
        ashby_job("a1", "React Dev", "Build UI"),
        ashby_job("a2", "Hidden", "x", listed=False),
    ]
    jobs = get_collector("ashby", fetcher(b)).fetch_jobs(CompanyTarget("Initech", "initech"))
    assert [j.external_id for j in jobs] == ["a1"]
    assert jobs[0].employment_type == "FullTime" and jobs[0].workplace_type == "Hybrid"


def test_ashby_id_falls_back_to_url_segment():
    b = FakeBoards()
    item = ashby_job("zzz", "Dev", "d")
    del item["id"]
    b.ashby["initech"] = [item]
    (j,) = get_collector("ashby", fetcher(b)).fetch_jobs(CompanyTarget("Initech", "initech"))
    assert j.external_id == "zzz"


def test_malformed_items_are_skipped_not_fatal():
    b = FakeBoards()
    b.greenhouse["acme"] = [gh_job(1, "Good", "ok"), {"id": 2}, {"title": "no id"}, "string"]
    c = get_collector("greenhouse", fetcher(b))
    jobs = c.fetch_jobs(CompanyTarget("Acme", "acme"))
    assert len(jobs) == 1 and c.skipped == 3


def test_unknown_board_404_is_clear_error_without_retry():
    b = FakeBoards()
    with pytest.raises(CollectorError, match="404"):
        get_collector("greenhouse", fetcher(b)).fetch_jobs(CompanyTarget("X", "nope"))
    assert len(b.calls) == 1


def test_invalid_json_and_wrong_shapes():
    b = FakeBoards()
    b.greenhouse["acme"] = "bad-json"
    with pytest.raises(CollectorError, match="Invalid JSON"):
        get_collector("greenhouse", fetcher(b)).fetch_jobs(CompanyTarget("A", "acme"))

    def handler(request):
        return httpx.Response(200, json={"unexpected": True})

    http = HttpFetcher(transport=httpx.MockTransport(handler), min_interval=0, sleep=lambda s: None)
    for platform in ("greenhouse", "ashby"):
        with pytest.raises(CollectorError, match="no 'jobs' list"):
            get_collector(platform, http).fetch_jobs(CompanyTarget("A", "t"))
    with pytest.raises(CollectorError, match="not a list"):
        get_collector("lever", http).fetch_jobs(CompanyTarget("A", "t"))


def test_retries_on_server_error_then_succeeds():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"jobs": []})

    sleeps: list[float] = []
    http = HttpFetcher(
        transport=httpx.MockTransport(handler), min_interval=0, max_retries=3, sleep=sleeps.append
    )
    assert get_collector("greenhouse", http).fetch_jobs(CompanyTarget("A", "t")) == []
    assert calls["n"] == 3 and sleeps  # backed off between attempts


def test_gives_up_after_max_retries_and_on_network_errors():
    def always_500(request):
        return httpx.Response(500)

    http = HttpFetcher(
        transport=httpx.MockTransport(always_500), min_interval=0, max_retries=2, sleep=lambda s: None
    )
    with pytest.raises(CollectorError, match="Giving up"):
        get_collector("greenhouse", http).fetch_jobs(CompanyTarget("A", "t"))

    def boom(request):
        raise httpx.ConnectTimeout("timeout")

    http = HttpFetcher(
        transport=httpx.MockTransport(boom), min_interval=0, max_retries=1, sleep=lambda s: None
    )
    with pytest.raises(CollectorError, match="Giving up"):
        get_collector("ashby", http).fetch_jobs(CompanyTarget("A", "t"))


def test_rate_limit_waits_between_calls_to_same_host():
    sleeps: list[float] = []

    def ok(request):
        return httpx.Response(200, json={"jobs": []})

    http = HttpFetcher(transport=httpx.MockTransport(ok), min_interval=5.0, sleep=sleeps.append)
    http.get_json("https://boards-api.greenhouse.io/v1/boards/a/jobs")
    http.get_json("https://boards-api.greenhouse.io/v1/boards/b/jobs")
    assert sleeps and 0 < sleeps[0] <= 5.0


def test_unknown_platform_rejected():
    with pytest.raises(CollectorError, match="No collector"):
        get_collector("workday", HttpFetcher())


def test_content_hash_changes_with_content():
    b = FakeBoards()
    b.greenhouse["acme"] = [gh_job(1, "A", "one")]
    (j1,) = get_collector("greenhouse", fetcher(b)).fetch_jobs(CompanyTarget("A", "acme"))
    b.greenhouse["acme"] = [gh_job(1, "A", "two")]
    (j2,) = get_collector("greenhouse", fetcher(b)).fetch_jobs(CompanyTarget("A", "acme"))
    assert j1.content_hash() != j2.content_hash()
