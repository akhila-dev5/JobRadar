# 14 - Configuration and Security

## Configuration

`backend/app/core/config.py` defines one `Settings` class (pydantic-settings). Values come
from environment variables, then `.env`, then defaults. `get_settings()` is cached.
`.env.example` lists every option with comments; `.env` itself is gitignored.

| Group | Variables |
|---|---|
| Mode | `APP_ENV` (development / test / production) |
| Database | `DATABASE_URL`, `TEST_DATABASE_URL` |
| API | `API_HOST`, `API_PORT`, `API_KEY`, `API_BASE_URL` (frontend) |
| Resume | `RESUME_DIR`, `MAX_UPLOAD_MB` |
| AI | `EMBEDDING_BACKEND`, `EMBEDDING_MODEL`, `WEIGHT_*` |
| Collectors | `HTTP_TIMEOUT_SECONDS`, `HTTP_MAX_RETRIES`, `HTTP_MIN_INTERVAL_SECONDS` |
| Scheduler | `SCHEDULER_ENABLED`, `SCHEDULER_INTERVAL_HOURS` |
| Email | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_USE_TLS` |

Preferences you edit in the dashboard (threshold, weights, titles, locations...) live in the
database, not in `.env`. Nothing personal is hard-coded in source: company names, keywords and
preferences are all data.

## Security checklist and where it is implemented

| Requirement | Implementation |
|---|---|
| Secrets in environment variables | `Settings`; `.env` in `.gitignore`; only `.env.example` is committed |
| No credentials to the frontend | the Streamlit app only knows `API_BASE_URL`; only the backend has `DATABASE_URL` |
| Validate uploads | extension, size limit, magic bytes, password/scan checks (`resume_parser.validate_upload`) |
| Limit upload size | `MAX_UPLOAD_MB`; the endpoint never reads more than limit + 1 bytes; company import capped at 1 MB |
| Sanitise extracted input | `sanitize_text`: NFKC, strip control characters, length cap |
| Parameterised queries | SQLAlchemy binds all values; no string-built SQL |
| XSS from job text | descriptions are HTML-escaped before highlighting |
| Supabase public API closed | RLS enabled on every table with no policies (migration 0001) |
| Backend-mediated DB access | single-user design: no Supabase client in any user-facing component |
| Optional API key | `API_KEY` -> `X-API-Key` header, constant-time comparison |
| Test isolation | test mode refuses the real database URL |
| Personal data | resume files in `data/resumes/` (gitignored, along with `*.pdf`, `*.docx`) |
| Email credentials | env vars only; use an app password or provider SMTP credential, never your normal password |
| Minimal data | only extracted skills/titles/education and a short profile text go to the database |

## Things to do yourself

- Keep `.env` out of screenshots, chats and commits. If a password leaks, rotate it in Supabase
  (Project Settings > Database).
- Leave the API on `127.0.0.1`. If you expose it on a network, set `API_KEY` and add HTTPS.
- Before pushing, run `git status` and confirm no `.env`, resume or export file is staged.
- The Supabase dashboard may flag "RLS enabled, no policies" as an info notice. That is intentional here.

## Logging

`core/logging.py` writes timestamped lines to stderr. Collector retries, skipped postings,
embedding cache activity and scheduler events are logged; resume contents and credentials are not.

## Interview questions

- Why environment variables for secrets instead of config files in the repo?
- What is SQL injection and how do ORMs/parameterised queries stop it?
- What is Row Level Security and why enable it even if the app bypasses it?
- Why validate file content, not just the file name?
- What is constant-time comparison and when does it matter?
