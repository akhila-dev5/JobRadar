"""Text embeddings behind a small interface (Dependency Inversion).

Backends:
  * SentenceTransformerEmbedder - all-MiniLM-L6-v2 on CPU (the real thing)
  * HashingEmbedder             - lightweight, dependency-free fallback used when the
                                  model cannot be loaded (e.g. offline first run)

Both return L2-normalised float32 vectors, so cosine similarity is a dot product.
Each backend carries its own calibration, because raw cosine values mean different
things for different models (see docs/07-ai-and-semantic-matching.md).
"""

from __future__ import annotations

import logging
from typing import Protocol

import numpy as np

logger = logging.getLogger(__name__)


class Embedder(Protocol):
    name: str
    cacheable: bool  # worth persisting vectors in the DB?
    calibration: tuple[float, float]  # cosine range mapped onto 0..1

    def encode(self, texts: list[str]) -> np.ndarray: ...


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denom) if denom else 0.0


class SentenceTransformerEmbedder:
    cacheable = True
    calibration = (0.10, 0.60)

    def __init__(self, model_name: str):
        # Imported lazily: loading torch takes seconds and ~hundreds of MB of RAM.
        from sentence_transformers import SentenceTransformer

        self.name = model_name
        self._model = SentenceTransformer(model_name, device="cpu")

    def encode(self, texts: list[str]) -> np.ndarray:
        vectors = self._model.encode(texts, batch_size=16, normalize_embeddings=True, show_progress_bar=False)
        return np.asarray(vectors, dtype=np.float32)


class HashingEmbedder:
    """Bag of word 1-2 grams hashed into a fixed vector. No model download."""

    name = "hashing-4096"
    cacheable = False
    calibration = (0.02, 0.30)

    def __init__(self, n_features: int = 4096):
        from sklearn.feature_extraction.text import HashingVectorizer

        self._vec = HashingVectorizer(
            n_features=n_features,
            ngram_range=(1, 2),
            alternate_sign=False,
            norm="l2",
            lowercase=True,
            stop_words="english",
        )

    def encode(self, texts: list[str]) -> np.ndarray:
        return self._vec.transform(texts).toarray().astype(np.float32)


_embedder: Embedder | None = None


def build_embedder(backend: str, model_name: str) -> Embedder:
    if backend == "hashing":
        return HashingEmbedder()
    if backend == "sentence-transformers":
        return SentenceTransformerEmbedder(model_name)
    try:  # auto
        return SentenceTransformerEmbedder(model_name)
    except Exception as exc:
        logger.warning(
            "Could not load %s (%s). Falling back to the hashing embedder; semantic "
            "scores will be coarser. See docs/07-ai-and-semantic-matching.md.",
            model_name,
            exc,
        )
        return HashingEmbedder()


def get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        from backend.app.core.config import get_settings

        s = get_settings()
        _embedder = build_embedder(s.embedding_backend, s.embedding_model)
    return _embedder


def set_embedder(embedder: Embedder | None) -> None:
    """Used by tests to inject a fake and by the app to reset."""
    global _embedder
    _embedder = embedder
