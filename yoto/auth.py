"""Auth0 (PKCE, silent) authentication for the Yoto API.

Yoto's web app is an Auth0 SPA. It asks for::

    openid email family:view family:library:view family:library:share-card
    family:library:card-audio user:content:manage user:account:view

against the audience ``https://api.yotoplay.com``.

Auth0 issues *no refresh token* here (the scope set omits ``offline_access``),
so the SPA silently re-authorizes on every page load using ``prompt=none`` plus
``response_mode=web_message``.  This module reproduces that exchange without a
browser: it replays the ``login.yotoplay.com`` session cookies, asks Auth0 for
an authorization code, and swaps that code for an access token.

The only prerequisite is a cookie jar captured from a logged-in browser; see
``python -m yoto.auth bootstrap``.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from .errors import AuthError, SessionExpired

LOGIN_BASE = "https://login.yotoplay.com"
CLIENT_ID = "cR9ffsEW9mQKgyVhpvyZpq5AX4gnd3p2"
AUDIENCE = "https://api.yotoplay.com"
REDIRECT_URI = "https://my.yotoplay.com/authorization/callback"

#: ``user:account:view`` is not pre-approved for silent auth and makes Auth0
#: reject the whole request with ``access_denied``.  The scope set below is the
#: subset the SPA actually needs; Auth0 still grants ``user:account:view`` in
#: the resulting token because the user already approved it interactively.
SCOPES = (
    "openid email family:view family:library:view family:library:share-card "
    "family:library:card-audio user:content:manage"
)

#: Cookies that must be replayed for the silent exchange to succeed.  The
#: ``auth0`` cookie alone is not enough -- ``auth0_compat`` carries the tenant
#: hint that lets Auth0 match the existing SSO session.
REQUIRED_COOKIE_DOMAINS = ("login.yotoplay.com",)

def default_state_dir() -> Path:
    """Where the cookie jar, the cached token and the service state live.

    ``~/.config/yotaiman`` is the current location.  The pre-rename
    ``~/.config/yoto-daily`` directory is still used when it exists and the
    current one does not, so upgrading does not force a fresh login.
    """
    override = os.environ.get("YOTO_STATE_DIR")
    if override:
        return Path(override).expanduser()

    current = Path.home() / ".config" / "yotaiman"
    legacy = Path.home() / ".config" / "yoto-daily"
    if not current.exists() and legacy.exists():
        return legacy
    return current


#: Where the cookie jar and cached token live by default.  The same default
#: is used by ``yoto_daily.config.Settings`` so the SDK and the service
#: always agree on one location.
DEFAULT_STATE_DIR = default_state_dir()


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _pkce_pair() -> tuple[str, str]:
    verifier = _b64url(secrets.token_bytes(64))
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge


@dataclass(frozen=True)
class CachedToken:
    """An access token together with its absolute expiry."""

    access_token: str
    expires_at: float
    scope: str = ""
    id_token: str = ""

    @property
    def seconds_left(self) -> float:
        return self.expires_at - time.time()


class YotoAuth:
    """Mints and caches Yoto access tokens."""

    def __init__(
        self,
        *,
        state_dir: Path | str | None = None,
        cookies_file: Path | str | None = None,
        cache_file: Path | str | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.state_dir = Path(state_dir or DEFAULT_STATE_DIR)
        self.cookies_file = Path(cookies_file or self.state_dir / "cookies.json")
        self.cache_file = Path(cache_file or self.state_dir / "token.json")
        self._session = session or requests.Session()
        self._cached: CachedToken | None = None

    # ------------------------------------------------------------------
    # cookie jar
    # ------------------------------------------------------------------
    def load_cookies(self) -> list[dict[str, Any]]:
        """Return the stored cookie jar, or an empty list."""
        if not self.cookies_file.exists():
            return []
        try:
            data = json.loads(self.cookies_file.read_text())
        except (json.JSONDecodeError, OSError):
            return []
        return data if isinstance(data, list) else []

    def save_cookies(self, cookies: list[dict[str, Any]]) -> None:
        """Persist a cookie jar captured from a browser."""
        self.cookies_file.parent.mkdir(parents=True, exist_ok=True)
        self.cookies_file.write_text(json.dumps(cookies, indent=2))
        try:
            self.cookies_file.chmod(0o600)
        except OSError:  # pragma: no cover - platform dependent
            pass

    def _session_with_cookies(self) -> requests.Session:
        sess = requests.Session()
        cookies = self.load_cookies()
        if not cookies:
            raise SessionExpired(
                f"No Yoto cookie jar at {self.cookies_file}. "
                "Run `python -m yoto.auth bootstrap` while logged in to Yoto in Chrome."
            )
        for cookie in cookies:
            domain = cookie.get("domain", "")
            if not any(d in domain for d in REQUIRED_COOKIE_DOMAINS):
                continue
            sess.cookies.set(
                cookie["name"],
                cookie["value"],
                domain=domain,
                path=cookie.get("path", "/"),
            )
        return sess

    # ------------------------------------------------------------------
    # token cache
    # ------------------------------------------------------------------
    def load_cached_token(self) -> CachedToken | None:
        if self._cached is not None:
            return self._cached
        if not self.cache_file.exists():
            return None
        try:
            data = json.loads(self.cache_file.read_text())
            token = CachedToken(
                access_token=data["access_token"],
                expires_at=float(data["expires_at"]),
                scope=data.get("scope", ""),
                id_token=data.get("id_token", ""),
            )
        except (json.JSONDecodeError, KeyError, OSError, ValueError):
            return None
        self._cached = token
        return token

    def _store_token(self, data: dict[str, Any]) -> CachedToken:
        expires_in = float(data.get("expires_in", 28800))
        token = CachedToken(
            access_token=data["access_token"],
            expires_at=time.time() + expires_in,
            scope=data.get("scope", ""),
            id_token=data.get("id_token", ""),
        )
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        self.cache_file.write_text(
            json.dumps(
                {
                    "access_token": token.access_token,
                    "expires_at": token.expires_at,
                    "scope": token.scope,
                    "id_token": token.id_token,
                },
                indent=2,
            )
        )
        try:
            self.cache_file.chmod(0o600)
        except OSError:  # pragma: no cover
            pass
        self._cached = token
        return token

    # ------------------------------------------------------------------
    # the actual flow
    # ------------------------------------------------------------------
    def _authorize(self, sess: requests.Session) -> tuple[str, str]:
        """Run the silent authorization-code exchange; return (code, verifier)."""
        verifier, challenge = _pkce_pair()
        params = {
            "client_id": CLIENT_ID,
            "scope": SCOPES,
            "redirect_uri": REDIRECT_URI,
            "audience": AUDIENCE,
            "prompt": "none",
            "response_type": "code",
            "response_mode": "web_message",
            "state": _b64url(secrets.token_bytes(16)),
            "nonce": _b64url(secrets.token_bytes(16)),
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "auth0Client": json.dumps({"name": "auth0-spa-js", "version": "2.24.1"}),
        }
        resp = sess.get(
            f"{LOGIN_BASE}/authorize",
            params=params,
            timeout=30,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html"},
        )
        if resp.status_code != 200:
            raise AuthError(f"authorize returned HTTP {resp.status_code}")

        match = re.search(r"authorizationResponse\s*=\s*(\{.*?\});", resp.text, re.S)
        if not match:
            raise AuthError("could not parse the Auth0 web_message response")

        obj = match.group(1)
        resp_obj = re.search(r"response:\s*\{(.*?)\}\s*,\s*state:", obj, re.S)
        resp_obj = resp_obj.group(1) if resp_obj else obj

        def field(name: str) -> str | None:
            found = re.search(rf'"{name}"\s*:\s*"([^"]*)"', resp_obj)
            return found.group(1) if found else None

        error = field("error")
        if error:
            description = field("error_description") or error
            if error in ("login_required", "consent_required", "interaction_required"):
                raise SessionExpired(f"Auth0 silent auth failed: {description}")
            raise AuthError(f"Auth0 authorize failed: {error} ({description})")

        code = field("code")
        if not code:
            raise AuthError("Auth0 returned neither a code nor an error")
        return code, verifier

    def _exchange(self, sess: requests.Session, code: str, verifier: str) -> dict[str, Any]:
        resp = sess.post(
            f"{LOGIN_BASE}/oauth/token",
            data={
                "grant_type": "authorization_code",
                "client_id": CLIENT_ID,
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": REDIRECT_URI,
            },
            timeout=30,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            data = resp.json()
        except ValueError as exc:
            raise AuthError(f"token endpoint returned non-JSON: {resp.text[:200]}") from exc
        if "access_token" not in data:
            raise AuthError(f"token exchange failed: {data}")
        return data

    def get_token(self, *, force_refresh: bool = False) -> CachedToken:
        """Return a valid access token, refreshing it if needed."""
        if not force_refresh:
            cached = self.load_cached_token()
            if cached and cached.seconds_left > 300:
                return cached

        sess = self._session_with_cookies()
        code, verifier = self._authorize(sess)
        data = self._exchange(sess, code, verifier)
        return self._store_token(data)

    def get_access_token(self, *, force_refresh: bool = False) -> str:
        """Return just the bearer token string."""
        return self.get_token(force_refresh=force_refresh).access_token

    def whoami(self) -> dict[str, Any]:
        """Decode the JWT payload of the current token (no signature check)."""
        token = self.get_access_token()
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))


if __name__ == "__main__":
    import sys

    from .auth_cli import main

    sys.exit(main())
