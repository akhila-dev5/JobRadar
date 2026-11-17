# 10 - FastAPI and REST APIs

Code: `backend/app/main.py`, `api/routes_config.py`, `api/routes_jobs.py`, `schemas/api.py`.
Interactive docs while the server runs: http://127.0.0.1:8000/docs

## REST in short

Resources are nouns in URLs; HTTP methods are the verbs; status codes report the outcome.

| Method | Meaning | Example |
|---|---|---|
| GET | read | `GET /companies` |
| POST | create / start | `POST /keywords` |
| PUT | replace | `PUT /preferences` |
| PATCH | partial update | `PATCH /companies/3` |
| DELETE | remove | `DELETE /keywords/5` |

## Endpoints

| Area | Endpoints |
|---|---|
| Companies | `GET/POST /companies` (a name alone is enough), `POST /companies/bulk` (list of names), `PATCH/DELETE /companies/{id}`, `POST /companies/{id}/discover` (look for the job board again), `POST /companies/{id}/test`, `GET /companies/export?format=json\|csv`, `POST /companies/import?format=` |
| Keywords | `GET/POST /keywords`, `PATCH/DELETE /keywords/{id}`, `POST /keywords/test` |
| Preferences | `GET/PUT /preferences` |
| Resume | `POST /resume` (multipart), `GET /resume`, `GET /resume/active`, `POST /resume/{id}/activate`, `PATCH /resume/{id}`, `POST /resume/{id}/skills`, `DELETE /resume/{id}/skills/{name}`, `DELETE /resume/{id}` |
| Jobs | `GET /jobs` (filters), `GET /jobs/stats`, `GET /jobs/{id}`, `POST/DELETE /jobs/{id}/save` |
| Tracker | `GET /tracker`, `PUT/DELETE /tracker/{job_id}` |
| Search | `POST /search` (202), `GET /search/{id}`, `GET /search/history` |
| System | `GET /health` |

`GET /jobs` filters: `company, title, keyword, location, min_score, source, published_after,
saved_only, sort (score|date), limit, offset, include_below_threshold, include_expired`.

## Example exchange

```http
POST /keywords
Content-Type: application/json

{"keyword": "PostgreSQL", "aliases": ["postgres"], "enabled": true}
```
```http
201 Created
{"id": 4, "keyword": "PostgreSQL", "aliases": ["postgres"], "enabled": true}
```
Errors share one shape: `{"detail": "..."}`. A duplicate gives `409`, a missing id `404`,
bad input `422` (Pydantic validation), a bad resume file `400`, a missing `DATABASE_URL` `503`.

## How a request is processed

1. **Routing** picks the function from the method and path.
2. **Pydantic** validates the body into a typed object (`CompanyIn`). Invalid data never reaches your code.
3. **Dependencies** run: `get_db` opens a session; `require_api_key` checks `X-API-Key` if `API_KEY` is set.
4. The function calls a repository/service and returns an ORM object.
5. `response_model` filters it into the output schema (so internals never leak).
6. `get_db` commits, or rolls back if anything raised.

## Concepts demonstrated

- **Dependency injection**: `db: Session = DbSession` and `Depends(get_deps_factory)`. Tests
  replace the factory to inject a fake network and fake SMTP.
- **Background tasks**: `POST /search` returns `202` immediately; `BackgroundTasks` runs
  `execute_search`. The client polls `GET /search/{id}`. For a single-user local tool this is
  simpler than Celery; the trade-off is that a server restart loses an in-flight search
  (it is then marked stale after 30 minutes and a new one may start).
- **Exception handlers** translate domain errors (`NotFound`, `Conflict`, `ResumeError`) into
  HTTP responses in one place.
- **Lifespan**: starts the optional APScheduler on startup and stops it on shutdown.

## Security notes

Bind to `127.0.0.1` (the default) so only your machine can reach the API. If you ever expose
it, set `API_KEY` and put TLS in front. There is no user login because the app is single-user.

## Common errors

| Symptom | Cause |
|---|---|
| `422 Unprocessable Entity` | body does not match the schema; read `detail[].loc` |
| `409 A search is already running` | wait, or it is stale for under 30 minutes |
| `503 DATABASE_URL is not set` | `.env` missing |
| `401` | `API_KEY` is set in `.env` but the client does not send it |

## Interview questions

- PUT vs PATCH? Idempotency of each HTTP method?
- What does `response_model` do and why is it a security feature?
- Explain dependency injection in FastAPI.
- Why return 202 instead of 200 for a long task? What are the alternatives (polling, webhooks, websockets)?
