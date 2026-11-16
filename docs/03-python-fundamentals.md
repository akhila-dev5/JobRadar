# 03 - Python Fundamentals (as used in JobRadar AI)

Every example below is from this repository, so you can open the file and read it in context.

## Type hints

```python
def title_similarity(job_title: str, candidates: list[str]) -> float | None:
```
Hints do not change runtime behaviour; they document intent and let tools (Ruff, your editor,
Pydantic, FastAPI) catch mistakes. `float | None` means "a float or None". FastAPI and
Pydantic go further and *use* hints to validate data at runtime.

## Dataclasses

```python
@dataclass
class NormalizedJob:
    source: str
    external_id: str
    title: str
    location: str | None = None
```
A dataclass generates `__init__`, `__repr__` and `__eq__` for plain data holders. Use it for
"a bag of fields" (`collectors/base.py`). Use Pydantic models (`schemas/api.py`) when data
crosses a trust boundary (HTTP input) and needs validation.

## Mutable default arguments (a classic trap)

```python
skills: list[str] = field(default_factory=list)   # correct
# skills: list[str] = []                           # wrong: shared by every instance
```

## Comprehensions, sets, and `any`/`all`

```python
matched = [s for s in job_skills if s.lower() in resume_skill_set]
```
Looking up in a `set` is O(1); in a list it is O(n). That is why `resume_skill_set` is a set.
`any(p.search(text) for p in patterns)` stops at the first hit.

## Context managers (`with`)

```python
@contextmanager
def session_scope():
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
```
`with session_scope() as db:` guarantees commit-or-rollback and cleanup, even on errors.
Same idea as `with open(...)`.

## Generators and `yield`

`get_db` in `database/session.py` is a generator FastAPI uses as a dependency: code before
`yield` is setup, the yielded value is injected, code after is teardown.

## Exceptions

Define specific exceptions (`CollectorError`, `ResumeError`, `NotFound`, `Conflict`), raise
them where the problem is detected, and translate them to HTTP in one place
(`main.py` exception handlers). Catch narrowly:

```python
except (KeyError, TypeError, AttributeError) as exc:   # malformed posting: skip it
```
Never write a bare `except:`; it hides bugs.

## Modules, packages, imports

A folder with `__init__.py` is a package. Imports are absolute from the repo root
(`from backend.app.core.config import get_settings`), which is why you run commands from
the project root.

## Standard library tools worth knowing

| Module | Used for |
|---|---|
| `re` | keyword and skill matching (`matching/keyword_matcher.py`) |
| `hashlib` | content hashes, embedding cache keys |
| `html`, `html.parser` | turning job HTML into text (`collectors/base.py`) |
| `datetime` | timezone-aware UTC timestamps (`database/base.py`) |
| `pathlib` | file paths |
| `smtplib`, `email` | optional email (`services/notification_service.py`) |
| `logging` | structured diagnostics (`core/logging.py`) |

## Always use timezone-aware datetimes

Store UTC (`datetime.now(timezone.utc)`), convert to local time only for display.
Mixing naive and aware datetimes raises `TypeError` when you compare them.

## Virtual environments

`python3.12 -m venv .venv` creates an isolated set of packages for this project, so
different projects can use different versions. `requirements.txt` records what to install.

## Interview questions

- List vs tuple vs set vs dict: when each, and their lookup complexity?
- What is a generator? What is the difference between `return` and `yield`?
- What does `with` do under the hood? (`__enter__` / `__exit__`)
- Why is a mutable default argument dangerous?
- What is the GIL and does it matter for this project? (Collectors are I/O-bound and run one company at a time, so the GIL is not a bottleneck here.)
- `is` vs `==`?
