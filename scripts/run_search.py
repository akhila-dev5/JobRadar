"""Run one job search from the command line (handy for cron / Windows Task Scheduler).

python scripts/run_search.py                 # all enabled companies
python scripts/run_search.py --company 1 3   # only companies with these ids
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.core.logging import configure_logging  # noqa: E402
from backend.app.database.session import session_scope  # noqa: E402
from backend.app.repositories.job_repos import HistoryRepository  # noqa: E402
from backend.app.services.search_runner import execute_search, start_search  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--company", type=int, nargs="*", help="company ids (default: all enabled)")
    args = parser.parse_args()
    configure_logging()

    history_id = start_search("cli")
    if history_id is None:
        print("Another search is already running.")
        return 1
    execute_search(history_id, args.company or None)
    with session_scope() as db:
        h = HistoryRepository(db).get(history_id)
        print(
            f"Status: {h.status} | fetched {h.jobs_fetched} | matched {h.qualified_jobs} | new {h.new_jobs}"
        )
        for err in h.errors:
            print(f"  ! {err}")
        return 0 if h.status in ("success", "partial") else 1


if __name__ == "__main__":
    raise SystemExit(main())
