# 13 - Setup and Installation (Ubuntu 24.04 on WSL2)

Run everything inside the Ubuntu terminal (VS Code with the WSL extension is fine).

## 1. Prerequisites

```bash
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3-pip git
python3.12 --version
```

Ubuntu 24.04 ships Python 3.12, so no extra repository is needed.

## 2. Get the code

```bash
git clone https://github.com/akhila-dev5/JobRadar.git
cd JobRadar
```

## 3. Virtual environment and dependencies

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip

# CPU-only PyTorch first. Without this, pip may download a multi-GB CUDA build.
pip install torch --index-url https://download.pytorch.org/whl/cpu

pip install -r requirements-dev.txt     # runtime + pytest + ruff
```

The first real search downloads the embedding model (~90 MB) into `~/.cache/huggingface`
(outside the repo). If the download fails, the app falls back to a lightweight hashing
embedder and logs a warning; it keeps working with coarser semantic scores.

## 4. Supabase

1. Open your **jobradar** project in the Supabase dashboard.
2. Click **Connect** and copy the **Session pooler** connection string. Use the pooler:
   it works over IPv4, which WSL2 usually needs; the "direct" string is often IPv6-only.
3. Change the prefix from `postgresql://` to `postgresql+psycopg://`.
4. Create your `.env`:

```bash
cp .env.example .env
nano .env        # paste the string into DATABASE_URL=
```

If your password has special characters (`@ : / ? # %`), URL-encode them
(`@` becomes `%40`), or reset the password to letters and digits.

`.env` is gitignored. Never commit it, and never paste the connection string in chat or an issue.

## 5. Create the tables

```bash
alembic upgrade head
python scripts/check_db.py
```

`check_db.py` should list all tables as present. The migration also turns on Row Level
Security with no policies, so Supabase's public REST API cannot read your data; the app
connects directly as the table owner.

## 6. Run

Two terminals, both with the venv active:

```bash
# terminal 1: backend  (API docs at http://127.0.0.1:8000/docs)
uvicorn backend.app.main:app --host 127.0.0.1 --port 8000

# terminal 2: dashboard  (http://localhost:8501)
streamlit run frontend/dashboard.py
```

WSL2 forwards localhost, so open `http://localhost:8501` in your Windows browser.

## 7. First-time configuration

1. **Settings > Resume**: upload your PDF or DOCX; fix skills.
2. **Settings > Keywords**: add keywords, or run `python scripts/seed_keywords.py` to load
   `examples/keywords.example.json`.
3. **Settings > Companies**: add companies. The board token is the last part of the careers URL:

   | Platform | Careers URL looks like | Token |
   |---|---|---|
   | Greenhouse | `boards.greenhouse.io/<token>` or `job-boards.greenhouse.io/<token>` | `<token>` |
   | Lever | `jobs.lever.co/<token>` (EU: `jobs.eu.lever.co/<token>`, set region to EU) | `<token>` |
   | Ashby | `jobs.ashbyhq.com/<token>` | `<token>` |

   Press **Test** to confirm the token works before searching.
4. **Dashboard > Search all enabled companies** (or pick specific ones).

## 8. Optional

- **Command-line search / cron**: `python scripts/run_search.py`
- **Built-in scheduler**: set `SCHEDULER_ENABLED=true` in `.env` (runs while the API is running)
- **Email**: set `SMTP_*` in `.env` using an app password; enable it in Settings > Preferences

## 9. Run the tests

```bash
pytest
ruff check .
```

Tests use in-memory SQLite and fake network/SMTP. They never touch Supabase.

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| `DATABASE_URL is not set` | `.env` missing or empty; run from the project root |
| `could not translate host name` / network unreachable | used the direct connection string; switch to the Session pooler |
| `password authentication failed` | wrong or un-encoded password; reset it in Supabase |
| First request after days is slow or fails | free project was paused; resume it in the dashboard |
| `ModuleNotFoundError: backend` | run commands from the repository root |
| Company test says "Not found (404)" | wrong token or platform; check the careers URL |
| Dashboard shows "cannot reach API" | backend not running or `API_BASE_URL` wrong |
| Model download blocked | set `EMBEDDING_BACKEND=hashing` to run without it |
