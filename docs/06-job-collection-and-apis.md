# 06 - Job Collection and APIs

Code: `backend/app/collectors/`. Tests: `tests/unit/test_collectors.py`,
`tests/integration/test_search_pipeline.py`.

## HTTP in 60 seconds

A client sends a **request** (method + URL + headers); the server returns a **response**
(status code + headers + body). `GET` reads data. `200` OK, `404` not found, `429` too many
requests, `5xx` server problem. JSON is the usual body format. Collectors only use `GET`.

## Supported platforms

| Platform | Endpoint (from the vendor docs) | Notes |
|---|---|---|
| Greenhouse | `GET boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true` | description is entity-encoded HTML; no documented pagination |
| Lever | `GET api.lever.co/v0/postings/{token}?mode=json&skip=&limit=` (EU: `api.eu.lever.co`) | paginated with `skip`/`limit` |
| Ashby | `GET api.ashbyhq.com/posting-api/job-board/{token}` | docs list no job `id`, so the job URL's last segment is the fallback id |

None needs an API key for reading public boards. No rate limits are documented, so the
client is polite by default.

## Not supported: LinkedIn, Naukri, Foundit, Indeed

They have no public job-search API for individuals, and automated scraping violates their
terms and risks account bans. The project deliberately avoids them. If you want them in
future, look for official partner programmes or feeds, or add other public ATS platforms
(for example Workable, SmartRecruiters or Recruitee) as new collectors.

## Automatic board discovery (add a company by name only)

You type "Stripe"; the app has to find where Stripe's jobs live. Code:
`services/board_discovery.py`, `services/discovery_runner.py`, `core/names.py`.

1. **Guess board names.** From the company name it builds up to 6 likely slugs, best first:
   "Acme Technologies, Inc." gives `acme`, `acmetechnologies`, `acme-technologies`, ...
   (legal suffixes such as Inc/Ltd/Pvt and generic words such as Technologies are dropped for the first guesses).
2. **Probe the three platforms** for each slug using their public endpoints, one polite request each,
   no retries: Greenhouse `/boards/{slug}`, Lever `/postings/{slug}` (US and EU), Ashby `/job-board/{slug}`.
3. **Check it is the right company.**

| Result | Meaning | What the app does |
|---|---|---|
| verified | Greenhouse reports the board's company name and it matches yours | uses it |
| unverified | board exists on Lever/Ashby (they do not expose a company name) | uses it, but shows ⚠️ and the careers link so you can confirm |
| not_found | nothing public under any guessed name, or Greenhouse boards belong to other companies | marked ❌ and skipped; paste a careers link if the company has one |
| unreachable | no clear answer from any job-board server (offline, blocked, rate limited) | says nothing about the company; retried at the next search |

Discovery runs in the background right after you add names, and again at the start of every search
for any company still `pending` or `unreachable`. A wrong guess therefore costs a few cheap requests,
not a crash. "Stripe", "stripe" and "Stripe, Inc." are treated as the same company.

If you already have the link, paste it (Settings > Companies > Edit): `parse_careers_url` reads
Greenhouse, Lever (US/EU) and Ashby links and skips guessing entirely.

**Direct links.** Every job stores `application_url` exactly as the job board returns it, so the dashboard
opens the original posting. Each company also stores a `careers_url` (the board's public page).

**What cannot be found automatically:** companies whose careers site is not on Greenhouse, Lever or Ashby
(Workday, SAP SuccessFactors, iCIMS, Taleo, custom pages; common for large enterprises). They need a
dedicated collector or an official feed; see doc 15. Search engines are not scraped to find them.

## The common shape

Every collector returns `NormalizedJob` (`collectors/base.py`): source, external_id,
company_name, title, description (plain text), application_url, location, employment_type,
workplace_type, published_at. The rest of the app never sees vendor-specific JSON.

## Adding a new platform (Open/Closed)

1. Subclass `JobCollector`, set `platform = "workable"`, implement `fetch_jobs()`.
2. Decorate with `@register_collector`.
3. Add `"workable"` to the `Platform` literal in `schemas/api.py`.
4. Write a test with a fake payload in `tests/helpers.py`.

Nothing in the search service, repositories or dashboard changes.

## Reliability features (`HttpFetcher`)

| Feature | How |
|---|---|
| Timeout | `HTTP_TIMEOUT_SECONDS` on every request |
| Retries | 429/5xx and network errors retry with exponential backoff (1, 2, 4 s, max 10); honours `Retry-After` |
| Rate limiting | minimum `HTTP_MIN_INTERVAL_SECONDS` between calls to the same host |
| Fail fast | 404 and other 4xx are not retried; they raise `CollectorError` |
| Bad data | invalid JSON or wrong shape raises `CollectorError`; one malformed job is skipped and counted, not fatal |
| Safety stop | Lever pagination stops at 50 pages |

## Duplicates and expiry

- **Unique key**: `(source, external_id)` in `jobs`. Searching twice never inserts twice.
- **Changed jobs**: a content hash (title, description, location, URL) detects edits; edited
  jobs are updated, not duplicated.
- **New vs seen**: `first_seen_at` is set once. Only first-time jobs trigger email.
- **Expiry**: after a *successful* fetch of a company, jobs that vanished from the board are
  marked `is_active = false`. A failed fetch never expires anything.
- **Cross-posting**: the same role on two platforms is two rows; merging them is listed as a
  future improvement.

## Honest testing note

All collector tests use `httpx.MockTransport` with payloads shaped like the vendors'
documented responses. The build environment had no outbound access to the job-board hosts,
so **real endpoints were not called**. First thing to do on your machine: add one company
and press **Test**. If a vendor changed a field, the failure is a clear `CollectorError`
or a "skipped N malformed postings" note rather than a crash.

## Common errors

| Symptom | Cause |
|---|---|
| `Not found (404)` | wrong board token or platform, or a Lever EU board with region US |
| `Giving up on ...` | repeated 5xx/timeouts; try again later |
| 0 jobs, no error | board genuinely empty, or all postings malformed (check the skipped count) |

## Interview questions

- Which HTTP status codes should a client retry, and why not 404?
- What is exponential backoff? Why add jitter in larger systems?
- How do you make data ingestion idempotent?
- What is the difference between polling a public API and scraping HTML?
