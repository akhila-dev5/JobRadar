"""Shared pytest fixtures.

Test safety: APP_ENV=test is forced BEFORE the application is imported, DATABASE_URL
is cleared, and every test gets a brand-new in-memory SQLite database. Nothing here
can reach Supabase, the real network or your real SMTP server.
"""

import os

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = ""
os.environ["TEST_DATABASE_URL"] = "sqlite://"
os.environ["API_KEY"] = ""
os.environ["SMTP_HOST"] = ""
os.environ["SCHEDULER_ENABLED"] = "false"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.app.core.config import get_settings  # noqa: E402

get_settings.cache_clear()

from backend.app.collectors import HttpFetcher  # noqa: E402
from backend.app.database import session as db_session  # noqa: E402
from backend.app.database.base import Base  # noqa: E402
from backend.app.main import create_app  # noqa: E402
from backend.app.matching.embeddings import HashingEmbedder, set_embedder  # noqa: E402
from backend.app.services.notification_service import EmailNotifier  # noqa: E402
from backend.app.services.search_service import SearchDeps  # noqa: E402
from tests.helpers import FakeBoards, FakeSMTP  # noqa: E402


@pytest.fixture(autouse=True)
def database():
    engine = db_session.init_engine("sqlite://")
    import backend.app.models  # noqa: F401

    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db(database):
    session = db_session.get_session_factory()()
    yield session
    session.close()


@pytest.fixture
def boards() -> FakeBoards:
    return FakeBoards()


@pytest.fixture
def smtp():
    return FakeSMTP()


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("RESUME_DIR", str(tmp_path / "resumes"))
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


@pytest.fixture
def client(boards, smtp, settings, monkeypatch):
    app = create_app()
    set_embedder(HashingEmbedder())
    monkeypatch.setenv("SMTP_HOST", "smtp.test")
    monkeypatch.setenv("SMTP_FROM", "jobradar@test")
    get_settings.cache_clear()

    def factory() -> SearchDeps:
        return SearchDeps(
            http=HttpFetcher(
                transport=boards.transport(), min_interval=0, max_retries=1, sleep=lambda _s: None
            ),
            embedder_factory=lambda: HashingEmbedder(),
            notifier=EmailNotifier(get_settings(), smtp_factory=smtp),
        )

    app.state.deps_factory = factory
    with TestClient(app) as c:
        yield c
    set_embedder(None)
    get_settings.cache_clear()
