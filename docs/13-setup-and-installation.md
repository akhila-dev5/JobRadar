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

Two terminals. **Each new terminal starts without the virtual environment, so run `source .venv/bin/activate` in both** (your prompt should start with `(.venv)`; otherwise you get `uvicorn: command not found`):

```bash
# terminal 1: backend  (API docs at http://127.0.0.1:8000/docs)
cd ~/projects/JobRadar && source .venv/bin/activate
uvicorn backend.app.main:app --host 127.0.0.1 --port 8000

# terminal 2: dashboard  (http://localhost:8501)
cd ~/projects/JobRadar && source .venv/bin/activate
streamlit run frontend/dashboard.py
```

WSL2 forwards localhost, so open `http://localhost:8501` in your Windows browser.

## 7. First-time configuration

1. **Settings > Resume**: upload your PDF or DOCX; fix skills.
2. **Settings > Keywords**: add keywords, or run `python scripts/seed_keywords.py` to load
   `examples/keywords.example.json`.
3. **Settings > Companies**: type company **names only**, one per line, and press
   **Add and find job boards**. The app looks for each company's job board on Greenhouse, Lever and
   Ashby (doc 06). Within a few seconds each company shows:
   - ✅ **Job board found** (verified as the right company)
   - 🟡 **Job board found: please confirm it is the right company**: open the careers link; if it is the wrong company, delete it
   - ❌ **No public job board found**: the company probably runs its own careers site; if you have its
     Greenhouse/Lever/Ashby link, paste it under *Edit / paste a careers link*
   - 📡 **Could not reach the job-board servers**: check your internet; it retries at the next search
4. **Dashboard > Search all enabled companies** (or pick specific ones). Job Results shows the matching
   postings with a direct link to each original posting.

## How to check that a search has started

- **Dashboard > Search activity** (top of the page): a green line "Search #N is running ... X of Y companies
  done. Now: <company>" with a progress bar that updates every 2 seconds. When it finishes it turns into a
  summary (✅ success, ⚠️ partial, ❌ failed) with expandable notes.
- **Dashboard > Search history**: the last 10 runs, including scheduled and command-line ones.
- **Backend terminal**: lines such as `Search 3 started: 12 companies`, `Search 3: fetching Stripe (greenhouse/stripe)`,
  `Search 3 finished: success (...)`.
- **API**: `http://127.0.0.1:8000/search/history?limit=1` (or `/docs`).

A search only runs when you press the button, or on a schedule if you enabled it (`SCHEDULER_ENABLED=true`
in `.env` while the backend runs), or when you run `python scripts/run_search.py`. Adding companies on its own
only looks up their job boards; it does not search for jobs.

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
