"""The Flask application.

Two front ends over the same services:

``/api``
    The JSON API -- see :mod:`yoto_daily.api`.

``/``
    The HTML control desk -- see :mod:`yoto_daily.web`.
"""

from __future__ import annotations

import os
import secrets

from flask import Flask

from yoto import Yoto
from yoto.auth import YotoAuth, write_private_file

from .api import api
from .capabilities import base as caps
from .config import Settings
from .gate import install_request_guard
from .generators import build_registry, default_registry
from .security import RateLimiter, load_api_token
from .state import StateStore
from .token_refresher import TokenRefresher
from .tracks import TrackService
from .web import web


def _secret_key(settings: Settings) -> str:
    """A stable secret key for the session cookie.

    The flash messages that carry the result of a form submission live in the
    session, so the key has to survive a restart.  It is generated once and
    kept beside the rest of the service state.
    """
    path = settings.state_dir / "secret.key"
    if path.exists():
        try:
            key = path.read_text().strip()
            if key:
                return key
        except OSError:
            pass

    key = secrets.token_hex(32)
    try:
        settings.state_dir.mkdir(parents=True, exist_ok=True)
        # Owner-only from the first byte: the key signs the session cookie.
        write_private_file(path, key)
    except OSError:  # pragma: no cover - platform dependent
        pass
    return key


def create_app(settings: Settings | None = None) -> Flask:
    """Build the Flask application."""
    settings = settings or Settings.load()
    settings.ensure_dirs()

    app = Flask(__name__)
    app.secret_key = os.environ.get("YOTO_SECRET_KEY") or _secret_key(settings)
    app.config["YOTO_SETTINGS"] = settings
    app.config["YOTO_STATE"] = StateStore(settings.state_file)

    # The session cookie carries the sign-in, so it is kept to itself: no
    # JavaScript, and no cross-site use.
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )

    # The token the service expects.  It is generated on first run and kept
    # beside the rest of the service state, readable only by its owner.
    token = settings.api_token or load_api_token(settings.state_dir)
    app.config["YOTO_TOKEN"] = token

    # One caller may only ask for so much generated work per minute; the
    # generators call out to paid services.
    app.config["YOTO_RATE_LIMITER"] = RateLimiter(settings.rate_limit)

    yoto = Yoto(auth=YotoAuth(state_dir=settings.state_dir))
    registry = build_registry(settings.raw_config)
    if not registry.music_generators() and not registry.speech_generators():
        registry = default_registry()

    app.extensions["yoto"] = yoto
    app.extensions["generators"] = registry
    app.extensions["tracks"] = TrackService(yoto, registry, settings)
    # The refresher is built here but only started by `serve`, so an
    # application that is imported by a test never keeps a thread running.
    app.extensions["token_refresher"] = TokenRefresher(
        yoto.auth,
        interval=settings.token_refresh_interval,
    )

    # Capabilities share this process's Yoto client and settings.
    caps.set_context(
        yoto=yoto,
        settings=settings,
        state=app.config["YOTO_STATE"],
    )

    app.register_blueprint(api)
    app.register_blueprint(web)

    # The perimeter goes on last, so it sees every request.
    install_request_guard(app)

    return app
