import numpy as np
import pytest

from backend.app.core.config import Settings
from backend.app.database.session import DatabaseConfigError, resolve_database_url
from backend.app.matching.embeddings import HashingEmbedder
from backend.app.repositories.job_repos import EmbeddingCacheRepository
from backend.app.services.matching_service import MatchingService


def S(**kw):
    # Explicit defaults: conftest sets APP_ENV/TEST_DATABASE_URL in the environment and
    # those must not leak into these tests.
    base = {"app_env": "development", "database_url": "", "test_database_url": ""}
    return Settings(_env_file=None, **{**base, **kw})


def test_test_mode_refuses_real_database_url():
    with pytest.raises(DatabaseConfigError, match="must differ"):
        resolve_database_url(
            S(app_env="test", database_url="postgresql://x/prod", test_database_url="postgresql://x/prod")
        )
    with pytest.raises(DatabaseConfigError, match="requires TEST_DATABASE_URL"):
        resolve_database_url(S(app_env="test", database_url="postgresql://x/prod"))
    assert (
        resolve_database_url(
            S(app_env="test", database_url="postgresql://x/prod", test_database_url="sqlite://")
        )
        == "sqlite://"
    )


def test_normal_mode_needs_database_url_and_ignores_test_url():
    with pytest.raises(DatabaseConfigError, match="DATABASE_URL is not set"):
        resolve_database_url(S(app_env="development"))
    assert (
        resolve_database_url(S(database_url="postgresql://a", test_database_url="sqlite://"))
        == "postgresql://a"
    )


class CountingEmbedder:
    name, cacheable, calibration = "counting", True, (0.1, 0.6)

    def __init__(self):
        self.encoded = 0
        self.inner = HashingEmbedder()

    def encode(self, texts):
        self.encoded += len(texts)
        return self.inner.encode(texts)


def test_embeddings_are_cached_and_not_recomputed(db):
    emb = CountingEmbedder()
    svc = MatchingService(db, emb, S())
    first = svc._embed(["alpha beta", "gamma delta"])
    db.commit()
    assert emb.encoded == 2
    second = svc._embed(["gamma delta", "alpha beta", "new text"])
    assert emb.encoded == 3  # only "new text" was computed
    assert np.allclose(second[0], first[1]) and np.allclose(second[1], first[0])
    assert EmbeddingCacheRepository(db).get_many([], "counting") == {}


def test_hashing_fallback_is_not_cached(db):
    emb = HashingEmbedder()
    MatchingService(db, emb, S())._embed(["some text"])
    from backend.app.models import EmbeddingCache

    assert db.query(EmbeddingCache).count() == 0


def test_keyword_matcher_module_does_not_depend_on_scoring_or_embeddings():
    """Qualification must stay independent of AI scores: enforced via imports."""
    import ast
    import inspect

    from backend.app.matching import keyword_matcher

    tree = ast.parse(inspect.getsource(keyword_matcher))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
    forbidden = {
        m
        for m in imported
        if any(x in m for x in ("scoring", "embeddings", "sentence", "sklearn", "numpy", "sqlalchemy"))
    }
    assert not forbidden, forbidden
