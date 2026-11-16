"""Verify the database connection and that migrations have been applied.

python scripts/check_db.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import inspect, text  # noqa: E402

from backend.app.database.session import DatabaseConfigError, get_engine  # noqa: E402

EXPECTED = {
    "companies",
    "search_keywords",
    "job_preferences",
    "resumes",
    "resume_skills",
    "jobs",
    "job_matches",
    "saved_jobs",
    "application_tracking",
    "search_history",
    "notification_history",
    "embedding_cache",
    "alembic_version",
}


def main() -> int:
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            dialect = engine.dialect.name
            version = conn.execute(text("SELECT version()")).scalar() if dialect == "postgresql" else dialect
        print(f"Connected OK ({str(version)[:60]})")
    except DatabaseConfigError as exc:
        print(f"Configuration problem: {exc}")
        return 2
    except Exception as exc:  # network, auth, paused project...
        print(f"Could not connect: {exc}")
        print(
            "Hints: use the Supabase *Session pooler* string, check the password, and make sure the "
            "project is not paused (free projects pause after ~7 days of inactivity)."
        )
        return 1

    missing = EXPECTED - set(inspect(engine).get_table_names())
    if missing:
        print(f"Missing tables: {', '.join(sorted(missing))}\nRun: alembic upgrade head")
        return 3
    print("All tables present. Database is ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
