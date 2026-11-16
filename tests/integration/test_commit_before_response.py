"""Regression test: data must be COMMITTED before the client receives its response.

In recent FastAPI versions the exit code of a `yield` dependency runs *after* the response
is sent unless the dependency is declared with scope="function". Our get_db commits in that
exit code, so with the wrong scope the API would answer "201 Created" and only then commit:
a failed commit would go unnoticed and an immediate follow-up request could see stale data.

In-process TestClient cannot show this (it waits for the whole ASGI call), so this test runs
a real uvicorn server, makes COMMIT deliberately slow, and checks the client had to wait.
"""

import socket
import threading
import time

import httpx
import pytest
import uvicorn
from sqlalchemy.orm import Session

from backend.app.main import create_app

COMMIT_DELAY = 0.5


@pytest.fixture
def live_server(monkeypatch):
    committed_at: list[float] = []
    original_commit = Session.commit

    def slow_commit(self):
        time.sleep(COMMIT_DELAY)
        result = original_commit(self)
        committed_at.append(time.monotonic())
        return result

    monkeypatch.setattr(Session, "commit", slow_commit)

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}", committed_at
    server.should_exit = True
    thread.join(timeout=5)


def test_commit_finishes_before_the_client_gets_its_response(live_server):
    base, committed_at = live_server
    started = time.monotonic()
    resp = httpx.post(f"{base}/keywords", json={"keyword": "Python"}, timeout=10)
    answered = time.monotonic()

    assert resp.status_code == 201
    assert committed_at, "commit never ran"
    assert committed_at[-1] <= answered, "response was sent before the commit finished"
    assert answered - started >= COMMIT_DELAY * 0.9
