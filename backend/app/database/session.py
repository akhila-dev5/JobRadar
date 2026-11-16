"""Engine and session handling.

Safety rule: when APP_ENV=test the engine is built from TEST_DATABASE_URL only,
and it must differ from DATABASE_URL. A test run can therefore never touch the
database that holds your real data.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


class DatabaseConfigError(RuntimeError):
    pass


def resolve_database_url(settings: Settings) -> str:
    if settings.is_test:
        if not settings.test_database_url:
            raise DatabaseConfigError("APP_ENV=test requires TEST_DATABASE_URL.")
        if settings.database_url and settings.test_database_url == settings.database_url:
            raise DatabaseConfigError(
                "TEST_DATABASE_URL must differ from DATABASE_URL; refusing to run tests "
                "against the real database."
            )
        return settings.test_database_url
    if not settings.database_url:
        raise DatabaseConfigError(
            "DATABASE_URL is not set. Copy .env.example to .env and add your Supabase "
            "session-pooler connection string."
        )
    return settings.database_url


def build_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        # Only used by the automated tests (in-memory). One shared connection.
        engine = create_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _record):  # SQLite ignores FKs unless enabled
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

        return engine

    return create_engine(
        url,
        pool_size=3,  # Supabase free tier has a small connection budget
        max_overflow=2,
        pool_pre_ping=True,  # survive the free project pausing / idle disconnects
        pool_recycle=1800,
        # Required when going through Supabase's transaction pooler (pgbouncer):
        # server-side prepared statements are not supported there.
        connect_args={"prepare_threshold": None, "connect_timeout": 15},
    )


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def init_engine(url: str | None = None) -> Engine:
    global _engine, _session_factory
    resolved = url or resolve_database_url(get_settings())
    _engine = build_engine(resolved)
    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False, autoflush=False)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        init_engine()
    assert _engine is not None
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    if _session_factory is None:
        init_engine()
    assert _session_factory is not None
    return _session_factory


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request, rolled back on error."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Same idea for background jobs and scripts that run outside a request."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
