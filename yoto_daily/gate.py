"""The perimeter around the service.

The service drives a personal Yoto account: it can read the shelf, rewrite
the daily card and spend money on speech and text generation.  Nothing here
is meant to be reachable by a page the operator happens to be reading.

Four things stand between a request and the account:

* a **bearer token**, which the operator has to present -- either in a
  header or, for a phone that cannot set headers, in the query string;
* a **Host allowlist**, which stops a rebound DNS name from reaching the
  service at all;
* an **Origin check**, which stops another site from posting to it; and
* a **CSRF token** on the forms, for the requests that ride on the session
  cookie.

A request that carries the bearer token has already proved who it is, and a
browser cannot set a header on another site's behalf, so those requests skip
the Origin and CSRF checks.  Everything else has to pass them.
"""

from __future__ import annotations

import secrets
from typing import Any
from urllib.parse import urlencode

from flask import (
    Flask,
    current_app,
    jsonify,
    redirect,
    request,
    session,
    url_for,
)

from .security import (
    host_allowed,
    origin_allowed,
    presented_token,
    token_matches,
)

#: Session key recording that the caller has unlocked the service.
SESSION_KEY = "yoto_authed"

#: Session key holding the CSRF token.
CSRF_KEY = "csrf_token"

#: The methods that change something.
MUTATING = ("POST", "PUT", "PATCH", "DELETE")


def csrf_token() -> str:
    """The CSRF token for this session's forms."""
    token = session.get(CSRF_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[CSRF_KEY] = token
    return token


def _json_error(message: str, status: int):
    return jsonify({"ok": False, "error": message}), status


def _csrf_ok() -> bool:
    """Whether the request carries this session's CSRF token."""
    expected = str(session.get(CSRF_KEY) or "")
    supplied = str(
        request.form.get("csrf_token")
        or request.headers.get("X-CSRF-Token")
        or ""
    )
    if not expected or not supplied:
        return False
    return secrets.compare_digest(supplied, expected)


def safe_next(target: str | None) -> str:
    """Where to send the caller once they have unlocked the service.

    Only a path on this service is followed, so a crafted ``next`` cannot
    turn the unlock page into a redirect to somewhere else.
    """
    candidate = str(target or "")
    if not candidate.startswith("/") or candidate.startswith("//"):
        return url_for("web.index")
    return candidate


def rate_limited() -> bool:
    """Whether the caller has used up its allowance.

    Generating a track or a story costs money -- a speech synthesiser, an
    LLM -- so the number of them one caller may ask for is capped.
    """
    limiter = current_app.config.get("YOTO_RATE_LIMITER")
    if limiter is None:
        return False
    return not limiter.check(request.remote_addr or "unknown")


def install_request_guard(app: Flask) -> None:
    """Put the perimeter in front of every request."""

    @app.before_request
    def _guard() -> Any:
        settings = app.config["YOTO_SETTINGS"]

        # The stylesheet has to load before the sign-in page can be read.
        if request.endpoint == "static":
            return None

        # Turning the guard off is an explicit choice, made by somebody who
        # knows the network the service is on.
        if not settings.auth_enabled:
            return None

        # A rebound DNS name arrives carrying the attacker's own Host
        # header, so the Host is checked before anything else.
        if not host_allowed(request, settings):
            return _json_error("this host is not allowed to reach the service", 403)

        token = str(app.config.get("YOTO_TOKEN") or "")
        supplied = presented_token(request)

        if token and token_matches(supplied, token):
            if request.args.get("token"):
                # The token came in through the address bar.  Move it into
                # the session and take it back out of the URL, so it does not
                # linger in the history or in the Referer of the next link.
                session[SESSION_KEY] = True
                rest = {
                    key: value
                    for key, value in request.args.items()
                    if key != "token"
                }
                target = request.path + (f"?{urlencode(rest)}" if rest else "")
                return redirect(target)
            return None

        mutating = request.method in MUTATING

        if mutating:
            # A browser sends Origin on every POST it makes; one from
            # somewhere else is another site trying to use this service.
            if not origin_allowed(request, settings):
                return _json_error("cross-site request refused", 403)
            if session.get(CSRF_KEY) and not _csrf_ok():
                return _json_error("the form token is missing or stale", 400)

        if session.get(SESSION_KEY):
            return None

        # The sign-in page itself, and the form that posts to it.
        if request.endpoint == "web.unlock":
            return None

        if request.path.startswith("/api/"):
            return _json_error(
                "this endpoint needs the API token: send it as "
                "'Authorization: Bearer <token>'",
                401,
            )

        return redirect(url_for("web.unlock", next=request.full_path))

    app.jinja_env.globals["csrf_token"] = csrf_token
