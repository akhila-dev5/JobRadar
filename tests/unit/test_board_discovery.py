"""Finding a company's career board from its name (services/board_discovery.py)."""

import pytest

from backend.app.collectors import HttpFetcher
from backend.app.services.board_discovery import (
    BoardDiscovery,
    careers_url,
    name_key,
    parse_careers_url,
    same_company,
    slug_candidates,
)
from tests.helpers import ashby_job, gh_job, lever_job


@pytest.fixture
def discovery(boards):
    http = HttpFetcher(transport=boards.transport(), min_interval=0, max_retries=0, sleep=lambda _s: None)
    return BoardDiscovery(http)


# ------------------------------------------------------------------ names
def test_slug_candidates_best_guess_first_and_capped():
    slugs = slug_candidates("Acme Technologies, Inc.")
    assert slugs[0] == "acme"  # legal suffix and generic words dropped
    assert "acmetechnologies" in slugs and "acme-technologies" in slugs
    assert len(slugs) <= 6 and len(set(slugs)) == len(slugs)


@pytest.mark.parametrize("name", ["", "   ", "***", "!"])
def test_slug_candidates_of_unusable_names_are_empty(name):
    assert slug_candidates(name) == []


def test_slug_candidates_handle_accents_and_ampersands():
    assert "ericsson" in slug_candidates("Éricsson")
    assert "johnsonandjohnson" in slug_candidates("Johnson & Johnson")


def test_same_company_ignores_case_punctuation_and_legal_suffixes():
    assert same_company("Stripe, Inc.", "stripe")
    assert same_company("Acme Labs", "ACME")
    assert not same_company("Acme Foods", "Acme Motors")
    assert name_key("The Acme Company Ltd") == "acme"


# ------------------------------------------------------------------ links
@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://boards.greenhouse.io/acme", ("greenhouse", "acme", "us")),
        ("https://job-boards.greenhouse.io/acme/jobs/123", ("greenhouse", "acme", "us")),
        ("boards.greenhouse.io/embed/job_board?for=acme", ("greenhouse", "acme", "us")),
        ("https://boards-api.greenhouse.io/v1/boards/acme/jobs", ("greenhouse", "acme", "us")),
        ("https://jobs.lever.co/globex/abc-123", ("lever", "globex", "us")),
        ("https://jobs.eu.lever.co/globex", ("lever", "globex", "eu")),
        ("https://api.lever.co/v0/postings/globex?mode=json", ("lever", "globex", "us")),
        ("https://jobs.ashbyhq.com/initech/1234", ("ashby", "initech", "us")),
    ],
)
def test_parse_careers_url_recognises_the_three_platforms(url, expected):
    ref = parse_careers_url(url)
    assert ref is not None and (ref.platform, ref.board_token, ref.api_region) == expected


@pytest.mark.parametrize(
    "url",
    [
        "",
        "https://www.acme.com/careers",
        "https://jobs.lever.co/",
        "https://evil.example/boards.greenhouse.io/x",
    ],
)
def test_parse_careers_url_rejects_unknown_links(url):
    assert parse_careers_url(url) is None


def test_careers_url_roundtrip():
    assert careers_url("greenhouse", "acme") == "https://boards.greenhouse.io/acme"
    assert careers_url("lever", "globex", "eu") == "https://jobs.eu.lever.co/globex"
    assert careers_url("ashby", "initech") == "https://jobs.ashbyhq.com/initech"
    assert careers_url(None, None) is None


# ------------------------------------------------------------------ discovery
def test_greenhouse_board_with_matching_name_is_verified(discovery, boards):
    boards.greenhouse_names["acme"] = "Acme, Inc."
    boards.greenhouse["acme"] = [gh_job(1, "Engineer", "x"), gh_job(2, "Designer", "y")]
    result = discovery.discover("Acme")
    assert result.status == "verified"
    assert (result.best.platform, result.best.board_token, result.best.job_count) == ("greenhouse", "acme", 2)


def test_lever_and_ashby_boards_are_found_but_unverified(discovery, boards):
    boards.lever["globex"] = [lever_job("L1", "Dev", "x")]
    boards.ashby["initech"] = [ashby_job("A1", "Dev", "x")]
    lever = discovery.discover("Globex")
    ashby = discovery.discover("Initech")
    assert (lever.status, lever.best.platform) == ("unverified", "lever")
    assert (ashby.status, ashby.best.platform) == ("unverified", "ashby")
    assert "confirm" in lever.message


def test_lever_eu_region_is_detected(discovery, boards):
    boards.lever["globex"] = [lever_job("L1", "Dev", "x")]
    # the fake serves both hosts from one store, so remove the US answer to prove EU is probed
    original = boards._handle

    def only_eu(request):
        if request.url.host == "api.lever.co":
            import httpx

            return httpx.Response(404)
        return original(request)

    boards._handle = only_eu
    http = HttpFetcher(transport=boards.transport(), min_interval=0, max_retries=0, sleep=lambda _s: None)
    result = BoardDiscovery(http).discover("Globex")
    assert (result.best.platform, result.best.api_region) == ("lever", "eu")


def test_greenhouse_board_of_a_different_company_is_never_picked(discovery, boards):
    boards.greenhouse_names["acme"] = "Acme Rocket Skates"
    boards.greenhouse["acme"] = [gh_job(1, "Engineer", "x")]
    result = discovery.discover("Acme Labs")  # "labs" is a generic word, so the guessed slug is "acme"
    assert result.status == "not_found" and result.best is None
    assert "Acme Rocket Skates" in result.message  # mentioned so the user can decide


def test_nothing_found_explains_what_to_do(discovery):
    result = discovery.discover("Totally Unknown Company")
    assert result.status == "not_found" and result.best is None and result.candidates == []
    assert "own careers site" in result.message and "paste" in result.message


def test_empty_lever_and_ashby_boards_are_ignored(discovery, boards):
    boards.lever["ghost"] = []
    boards.ashby["ghost"] = [ashby_job("A1", "Hidden", "x", listed=False)]
    assert discovery.discover("Ghost").status == "not_found"


def test_falls_back_to_a_longer_slug_and_stops_guessing_once_found(discovery, boards):
    boards.greenhouse_names["acmetechnologies"] = "Acme Technologies"
    boards.greenhouse["acmetechnologies"] = [gh_job(1, "Engineer", "x")]
    result = discovery.discover("Acme Technologies")
    assert result.best.board_token == "acmetechnologies"
    tried = {url.split("/boards/")[1].split("/")[0] for url in boards.calls if "/boards/" in url}
    assert "acme-technologies" not in tried  # a weaker guess after the hit would be wasted traffic


def test_discovery_survives_server_errors(boards):
    boards.greenhouse_names["acme"] = "Acme"
    boards.greenhouse["acme"] = 500  # jobs endpoint broken, board info fine
    http = HttpFetcher(transport=boards.transport(), min_interval=0, max_retries=0, sleep=lambda _s: None)
    result = BoardDiscovery(http).discover("Acme")
    assert result.status == "verified" and result.best.job_count == 0


# ------------------------------------------------------------------ unreachable vs not found
def test_offline_is_reported_as_unreachable_not_as_missing_board(discovery, boards):
    boards.offline = True
    result = discovery.discover("Acme")
    assert result.status == "unreachable" and result.best is None
    assert "internet" in result.message


@pytest.mark.parametrize("status", [403, 429, 500, 503])
def test_blocked_or_rate_limited_is_unreachable(discovery, boards, status):
    boards.force_status = status
    assert discovery.discover("Acme").status == "unreachable"


def test_clean_404s_mean_the_board_really_does_not_exist(discovery):
    assert discovery.discover("Acme").status == "not_found"  # nothing registered: every probe is a 404
