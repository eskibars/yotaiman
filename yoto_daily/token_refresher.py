"""Keep the Yoto access token fresh while the service runs.

An access token lasts eight hours.  Minting a new one is plain HTTP: the
stored ``login.yotoplay.com`` cookies are replayed, Auth0 is asked for an
authorization code with ``prompt=none``, and the code is swapped for a
token.  No browser is involved, so no browser has to be running and none
has to be kept open.  Only the one-off cookie bootstrap needs Chrome, and
that is a command an operator runs by hand.

This worker does that on a timer while ``yotaiman serve`` is up.  It buys
two things: a long run never trips over an expired token, and a session
that has genuinely lapsed is noticed while there is still time to fix it
rather than in the middle of a request.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable

#: How often the token is refreshed, in seconds.  The token lasts eight
#: hours, so an hourly refresh keeps it warm without asking Auth0 for
#: anything it would not have given us anyway.
DEFAULT_INTERVAL = 3600.0


def _stamp(when: float | None) -> str:
    """An ISO timestamp for a unix time, or an empty string."""
    if when is None:
        return ""
    return datetime.fromtimestamp(when, tz=timezone.utc).isoformat(timespec="seconds")


class TokenRefresher:
    """Refreshes the access token on a timer, in a background thread.

    The thread is a daemon, so it never keeps the process alive, and every
    failure is recorded rather than raised: a session that has lapsed is a
    fact to report, not a reason to take the service down.
    """

    def __init__(
        self,
        auth: Any,
        *,
        interval: float = DEFAULT_INTERVAL,
        report: Callable[[str], None] | None = None,
    ) -> None:
        self.auth = auth
        self.interval = float(interval)
        #: Called with one line per refresh outcome.  The service uses it to
        #: say what happened on the console.
        self._report = report
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._last_attempt: float | None = None
        self._last_ok: bool | None = None
        self._last_error: str = ""
        self._instructions: str = ""
        self._expires_at: float | None = None
        self._next_attempt: float | None = None

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    @property
    def enabled(self) -> bool:
        """Whether the refresher should run at all."""
        return self.interval > 0

    def start(self) -> bool:
        """Start the worker.

        Returns ``False`` when the refresher is disabled or already
        running.
        """
        if not self.enabled or self._thread is not None:
            return False
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="yoto-token-refresh",
            daemon=True,
        )
        self._thread.start()
        return True

    def stop(self, timeout: float = 5.0) -> None:
        """Ask the worker to finish and wait for it."""
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
        self._thread = None

    def set_report(self, report: Callable[[str], None] | None) -> None:
        """Send refresh outcomes to ``report`` from now on."""
        self._report = report

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ------------------------------------------------------------------
    # the work
    # ------------------------------------------------------------------
    def refresh_now(self) -> bool:
        """Mint a token right now.

        Returns ``True`` when the token was minted.  A failure is recorded
        in the status and reported, never raised.
        """
        try:
            token = self.auth.get_token(force_refresh=True)
        except Exception as exc:
            with self._lock:
                self._last_attempt = time.time()
                self._last_ok = False
                self._last_error = f"{type(exc).__name__}: {exc}"
                self._instructions = getattr(exc, "relogin_instructions", "") or ""
                self._next_attempt = self._last_attempt + self.interval
            self._say(
                f"token refresh failed: {self._last_error}"
                + (f" -- {self._instructions}" if self._instructions else "")
            )
            return False

        with self._lock:
            self._last_attempt = time.time()
            self._last_ok = True
            self._last_error = ""
            self._instructions = ""
            self._expires_at = token.expires_at
            self._next_attempt = self._last_attempt + self.interval
            expires_in = token.seconds_left
        self._say(f"token refreshed, valid for {expires_in / 3600:.1f} h")
        return True

    def _run(self) -> None:
        """Refresh once straight away, then on every tick."""
        # The first refresh happens right away: it proves the session still
        # works, and it means the first request does not have to wait for a
        # token to be minted.
        self.refresh_now()
        while not self._stop.wait(self.interval):
            self.refresh_now()

    def _say(self, message: str) -> None:
        """Hand a line to the reporter, if there is one."""
        if self._report is None:
            return
        try:
            self._report(message)
        except Exception:  # pragma: no cover - a reporter must not break the worker
            pass

    # ------------------------------------------------------------------
    # status
    # ------------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        """What the refresher is doing, for the health endpoint."""
        with self._lock:
            expires_at = self._expires_at
            return {
                "enabled": self.enabled,
                "running": self.running,
                "interval": int(self.interval),
                "last_refresh": _stamp(self._last_attempt),
                "last_ok": self._last_ok,
                "error": self._last_error,
                "instructions": self._instructions,
                "next_refresh": _stamp(self._next_attempt),
                "expires_at": _stamp(expires_at),
                "expires_in": int(expires_at - time.time()) if expires_at else 0,
            }
