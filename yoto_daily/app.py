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
from yoto.auth import YotoAuth

from .api import api
from .capabilities import base as caps
from .config import Settings
from .generators import build_registry, default_registry
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
        path.write_text(key)
        path.chmod(0o600)
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
    return app
