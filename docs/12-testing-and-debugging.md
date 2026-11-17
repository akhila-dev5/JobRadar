# 12 - Testing and Debugging

Run: `pytest` (146 tests, a few seconds) and `ruff check .`

## Why tests exist here

The rules that matter most (single keyword qualifies, duplicates never inserted, a low AI
score never discards a qualified job, a failing company never stops the others) are
exactly the kind that silently break during refactoring. Each has a test.

## Test safety

`tests/conftest.py` sets `APP_ENV=test`, clears `DATABASE_URL`, and gives every test a fresh
in-memory SQLite database. `resolve_database_url()` refuses test mode when
`TEST_DATABASE_URL` is missing or equal to `DATABASE_URL`
(`test_test_mode_refuses_real_database_url`). Network access is replaced by
`httpx.MockTransport` (`FakeBoards`) and SMTP by `FakeSMTP`, so a test cannot reach
Supabase, a job board or your mailbox.

## The test pyramid here

| Layer | Files | What they check |
|---|---|---|
| Unit (pure logic) | `test_keyword_matcher` (16), `test_scoring` (13), `test_resume_parser` (10), `test_collectors` (15), `test_safety_and_cache` (5), `test_board_discovery` (34: name normalising, slug guesses, careers-link parsing, verified / unverified / mismatch / unreachable) | one function or class at a time, no database |
| Integration | `test_api_config` (13), `test_search_pipeline` (18), `test_commit_before_response` (1), `test_company_discovery` (21: add by name, bulk add, duplicates, re-discovery, search with discovery, progress fields) | real FastAPI app + real SQLAlchemy on SQLite + fake network |

## Requirement-to-test map

| Requirement | Test |
|---|---|
| One keyword is enough (jobs A-D from the spec) | `test_job_a_only_python_qualifies` ... `test_job_d_no_keyword_does_not_qualify`, `test_single_match_is_sufficient_even_if_other_keywords_missing` |
| Exact word and phrase matching, no partial words | `test_no_partial_word_matches`, `test_c_does_not_match_c_sharp_or_cpp`, `test_phrase_matching_allows_hyphen_and_extra_spaces` |
| Matching independent of AI | `test_keyword_matcher_module_does_not_depend_on_scoring_or_embeddings`, `test_ai_threshold_never_discards_keyword_qualified_jobs` |
| Duplicates | `test_duplicates_not_created_on_rerun_and_updates_detected` |
| Invalid board data / API failures | `test_collectors.py` (404, 5xx retry, bad JSON, wrong shape), `test_malformed_postings_are_skipped_and_reported`, `test_failed_company_does_not_stop_others_and_is_reported` |
| Resume parsing (PDF and DOCX, bad files) | `test_resume_parser.py` |
| Weighted scoring, semantic similarity, caching | `test_scoring.py`, `test_embeddings_are_cached_and_not_recomputed` |
| Company config and CSV/JSON import | `test_api_config.py` |
| Email only for new jobs, once | `test_email_sent_once_for_new_qualifying_jobs_only` |

## What the tests do not prove

- They run on SQLite, not PostgreSQL. SQL is written to be portable, but real Supabase runs
  are your check (`alembic upgrade head`, `scripts/check_db.py`).
- Collector tests use payloads modelled on vendor docs; real endpoints were not reachable
  from the build environment.
- The real MiniLM model was not downloaded in the build environment; the hashing embedder
  is what the tests exercise (see doc 07 for a 5-line verification).
- The Streamlit pages were rendered with Streamlit's `AppTest` against a running API and
  produced no exceptions, but they have not been looked at in a real browser.

## Writing a good test (pattern used here)

```python
def test_single_match_is_sufficient_even_if_other_keywords_missing():
    matcher = KeywordMatcher([KeywordRule("Python"), KeywordRule("React"), KeywordRule("Go")])
    result = matcher.match("Backend dev", "We use Python daily.")
    assert result.qualified
    assert result.matched_keywords == ["Python"]
```
Arrange the inputs, act once, assert on behaviour (not on implementation details), and
name the test after the rule it protects.

## Debugging playbook

1. **Read the error bottom-up**: last line = what, lines above = where.
2. **Reproduce small**: `pytest tests/unit/test_keyword_matcher.py -k phrase -x`.
3. **Print or breakpoint**: `pytest --pdb` drops into the debugger on failure.
4. **API issues**: open `/docs`, send the request by hand, read the `detail` field.
5. **Backend logs**: uvicorn prints tracebacks and collector warnings (`GET ... failed`).
6. **Search problems**: check `search_history.errors` (Settings, or `GET /search/history`).
7. **Data questions**: query Supabase's SQL editor (`SELECT * FROM jobs ORDER BY id DESC LIMIT 5`).

## A subtle regression test worth reading

`tests/integration/test_commit_before_response.py` starts a real uvicorn server and makes
COMMIT slow on purpose. In recent FastAPI versions, the exit code of a `yield` dependency
can run *after* the response is sent, so the API could answer "201 Created" before the
database commit finished (and a failed commit would go unnoticed). `DbSession` is therefore
declared with `scope="function"` in `api/deps.py`, and this test fails if that is removed.
The in-process `TestClient` cannot show this problem, which is why the test needs a real server.

## Interview questions

- Unit vs integration vs end-to-end tests: which did you write and why?
- What is a mock vs a fake? Which do `FakeBoards` and `FakeSMTP` represent?
- How do you stop tests from damaging production data?
- What makes a test flaky? How did you avoid network and time dependence?
