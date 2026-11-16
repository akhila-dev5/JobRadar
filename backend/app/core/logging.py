import logging
import sys


def configure_logging(level: int = logging.INFO) -> None:
    """Idempotent logging setup used by the API, scripts and the scheduler."""
    root = logging.getLogger()
    if any(getattr(h, "_jobradar", False) for h in root.handlers):
        return
    handler = logging.StreamHandler(sys.stderr)
    handler._jobradar = True  # type: ignore[attr-defined]
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root.addHandler(handler)
    root.setLevel(level)
    # Keep third-party chatter down.
    for noisy in ("httpx", "httpcore", "urllib3", "sentence_transformers"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
