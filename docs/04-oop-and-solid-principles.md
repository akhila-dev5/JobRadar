# 04 - OOP and SOLID Principles (as used in JobRadar AI)

## Classes in one minute

A class bundles data and the functions that work on it. Use one when objects have state
or when you want interchangeable implementations of the same behaviour. Plain functions are
better for stateless logic (`matching/scoring.py` is mostly functions on purpose).

## The four pillars, with local examples

| Pillar | Meaning | Where |
|---|---|---|
| Encapsulation | hide internals behind a small public API | `HttpFetcher` hides retries and throttling; callers just call `get_json()` |
| Abstraction | depend on a contract, not a concrete class | `JobCollector.fetch_jobs()` |
| Inheritance | specialise a base class | `GreenhouseCollector(JobCollector)` |
| Polymorphism | same call, different behaviour | `get_collector(company.platform, http).fetch_jobs(...)` works for any platform |

## SOLID

### S: Single Responsibility
Each class has one reason to change.
`KeywordMatcher` decides qualification; `MatchingService` computes scores;
`SearchService` orchestrates the run; `CompanyRepository` talks to the database.
If the Lever API changes, only `LeverCollector` changes.

### O: Open/Closed
Open for extension, closed for modification. Adding a platform:

```python
@register_collector
class WorkableCollector(JobCollector):
    platform = "workable"
    def fetch_jobs(self, company): ...
```
`SearchService` is untouched, because it only asks the registry for "the collector for this platform".

### L: Liskov Substitution
Any `JobCollector` must be usable wherever a `JobCollector` is expected: same method,
same return type (`list[NormalizedJob]`), same failure type (`CollectorError`). That is why
every collector converts vendor-specific errors into `CollectorError`.

### I: Interface Segregation
Keep interfaces small. `JobCollector` has one method. `Embedder` (a `Protocol`) has only
`encode()` plus three data attributes (`name`, `cacheable`, `calibration`), so a fake embedder in a test is short.

### D: Dependency Inversion
High-level code depends on abstractions, and concrete things are injected.

```python
@dataclass
class SearchDeps:
    http: HttpFetcher
    embedder_factory: Callable[[], Embedder]
    notifier: EmailNotifier
```
`SearchService` receives `SearchDeps`. Production passes real HTTP, MiniLM and SMTP;
tests pass `httpx.MockTransport`, the hashing embedder and `FakeSMTP`
(`tests/conftest.py`). Nothing in the service changes.

## Dependency injection, three flavours seen here

1. **Constructor injection**: `SearchService(db, settings, deps)`.
2. **FastAPI `Depends`**: `db: Session = DbSession`; tests override `app.state.deps_factory`.
3. **Factory callables**: `embedder_factory` delays loading the model until a job actually
   needs scoring, saving seconds and memory on empty searches.

## Patterns recap

| Pattern | Class / module |
|---|---|
| Strategy | collectors |
| Registry | `COLLECTORS` |
| Repository | `repositories/` |
| Facade | `ResumeService.upload()` hides validation, parsing, file saving and DB writes |
| Template of a pipeline | `SearchService._run` |

## When *not* to use OOP

The scoring formulas are pure functions: given the same input they return the same output,
with no hidden state, which makes them trivial to test. Do not wrap everything in classes
just because you can ("avoid unnecessary abstractions").

## Interview questions

- Explain SOLID with an example from a project you built.
- Inheritance vs composition: which would you prefer and why?
- What is dependency injection? How does it help testing?
- What is a Protocol (structural typing) compared with an abstract base class?
- Where would adding a new feature violate Open/Closed in this code, if anywhere?
