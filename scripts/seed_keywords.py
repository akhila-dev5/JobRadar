"""Optionally load keywords from a JSON file (default: examples/keywords.example.json).

    python scripts/seed_keywords.py [path/to/keywords.json]

Existing keywords are skipped. You can always edit them later in the dashboard.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.database.session import session_scope  # noqa: E402
from backend.app.repositories.config_repos import Conflict, KeywordRepository  # noqa: E402


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "examples" / "keywords.example.json"
    items = json.loads(path.read_text(encoding="utf-8"))
    added = skipped = 0
    with session_scope() as db:
        repo = KeywordRepository(db)
        for item in items:
            entry = {"keyword": item} if isinstance(item, str) else item
            try:
                repo.create(entry["keyword"], entry.get("aliases", []), entry.get("enabled", True))
                added += 1
            except Conflict:
                skipped += 1
    print(f"Added {added} keywords, skipped {skipped} existing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
