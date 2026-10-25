"""Offline tests for the background token refresher.

None of these touch the network: the auth object is a stand-in that counts
how often it was asked for a token.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from yoto.auth import CachedToken, YotoAuth  # noqa: E402
from yoto.errors import SessionExpired  # noqa: E402
from yoto_daily.config import Settings  # noqa: E402
from yoto_daily.token_refresher import TokenRefresher  # noqa: E402


class FakeAuth:
    """Stands in for :class:`yoto.auth.YotoAuth`."""

    def __init__(self, *, fails: bool = False) -> None:
        self.calls = 0
        self.fails = fails

    def get_token(self, *, force_refresh: bool = False) -> CachedToken:
        self.calls += 1
        if self.fails:
            raise SessionExpired("Auth0 silent auth failed: login_required")
        return CachedToken(
            access_token=f"token-{self.calls}",
            expires_at=time.time() + 28800,
            scope="openid",
        )


def _wait_for(predicate, timeout: float = 3.0) -> bool:
    """Wait until ``predicate`` is true, or the timeout runs out."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


# ----------------------------------------------------------------------
# the refresher
# ----------------------------------------------------------------------
def test_a_refresh_mints_a_token_and_records_it():
    auth = FakeAuth()
    refresher = TokenRefresher(auth, interval=60)

    assert refresher.refresh_now() is True

    status = refresher.status()
    assert auth.calls == 1
    assert status["last_ok"] is True
    assert status["error"] == ""
    assert status["last_refresh"]
    assert status["expires_in"] > 28000


def test_a_failed_refresh_is_recorded_rather_than_raised():
    auth = FakeAuth(fails=True)
    refresher = TokenRefresher(auth, interval=60)

    assert refresher.refresh_now() is False

    status = refresher.status()
    assert status["last_ok"] is False
    assert "SessionExpired" in status["error"]
    # The operator is told how to put it right.
    assert "bootstrap" in status["instructions"]


def test_the_worker_refreshes_on_its_interval():
    auth = FakeAuth()
    refresher = TokenRefresher(auth, interval=0.05)

    assert refresher.start() is True
    try:
        # One straight away, then one on the tick.
        assert _wait_for(lambda: auth.calls >= 2)
    finally:
        refresher.stop()

    assert auth.calls >= 2
    assert refresher.running is False


def test_a_disabled_refresher_never_starts():
    auth = FakeAuth()
    refresher = TokenRefresher(auth, interval=0)

    assert refresher.enabled is False
    assert refresher.start() is False
    assert auth.calls == 0
    assert refresher.status()["enabled"] is False


def test_the_worker_reports_what_it_did():
    lines: list[str] = []
    auth = FakeAuth()
    refresher = TokenRefresher(auth, interval=60, report=lines.append)

    refresher.refresh_now()

    assert lines and "token refreshed" in lines[0]


# ----------------------------------------------------------------------
# the token cache
# ----------------------------------------------------------------------
def test_a_token_written_by_another_process_is_picked_up(tmp_path):
    """A CLI run that refreshed the cache is seen by the running service."""
    cache = tmp_path / "token.json"
    cache.write_text(
        json.dumps(
            {
                "access_token": "fresh",
                "expires_at": time.time() + 3600,
                "scope": "openid",
            }
        )
    )

    auth = YotoAuth(state_dir=tmp_path)
    # This process is holding on to a token that has expired.
    auth._cached = CachedToken(access_token="stale", expires_at=time.time() - 10)

    token = auth.get_token()

    assert token.access_token == "fresh"


def test_the_token_cache_is_written_atomically(tmp_path):
    """No half-written token is left behind for a reader to find."""
    auth = YotoAuth(state_dir=tmp_path)

    auth._store_token({"access_token": "abc", "expires_in": 28800})

    assert json.loads((tmp_path / "token.json").read_text())["access_token"] == "abc"
    assert not list(tmp_path.glob("*.tmp"))


# ----------------------------------------------------------------------
# the service
# ----------------------------------------------------------------------
def test_the_service_knows_its_refresh_interval(tmp_path, monkeypatch):
    monkeypatch.setenv("YOTO_TOKEN_REFRESH_INTERVAL", "120")
    assert Settings().token_refresh_interval == 120

    monkeypatch.delenv("YOTO_TOKEN_REFRESH_INTERVAL")
    assert Settings().token_refresh_interval == 3600


def test_health_reports_the_refresher(tmp_path):
    from yoto_daily.app import create_app

    settings = Settings(state_dir=tmp_path / "state")
    app = create_app(settings)
    app.config["TESTING"] = True

    body = app.test_client().get("/api/health").get_json()

    refresh = body["token_refresh"]
    assert refresh["enabled"] is True
    assert refresh["interval"] == 3600
    # The refresher is built with the app but only started by `serve`.
    assert refresh["running"] is False
