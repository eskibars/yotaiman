"""The JSON API.

Every route lives at module level so the blueprint can be registered on more
than one application in the same process -- which the tests do.
"""

from __future__ import annotations

from typing import Any

from flask import Blueprint, current_app, jsonify, request

from yoto.errors import SessionExpired, YotoError

from .capabilities import base as caps
from .content.books import describe_formats
from .content.text import topic_suggestions
from .tracks import TrackError, TrackRequest

api = Blueprint("api", __name__, url_prefix="/api")


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------
def _yoto():
    return current_app.extensions["yoto"]


def _registry():
    return current_app.extensions["generators"]


def _settings():
    return current_app.config["YOTO_SETTINGS"]


def _state():
    return current_app.config["YOTO_STATE"]


def _token_refresh() -> dict[str, Any]:
    """What the background token refresher is doing."""
    refresher = current_app.extensions.get("token_refresher")
    if refresher is None:
        return {"enabled": False, "running": False}
    return refresher.status()


def _error(message: str, status: int = 400, **extra: Any):
    payload = {"ok": False, "error": message}
    payload.update(extra)
    return jsonify(payload), status


def _guard(fn):
    """Turn SDK errors into clean JSON responses."""

    def wrapper(*args: Any, **kwargs: Any):
        try:
            return fn(*args, **kwargs)
        except SessionExpired as exc:
            return _error(str(exc), 401, instructions=exc.relogin_instructions)
        except TrackError as exc:
            return _error(str(exc), 400)
        except YotoError as exc:
            return _error(str(exc), getattr(exc, "status", 502) or 502)
        except Exception as exc:  # pragma: no cover - defensive
            current_app.logger.exception("unhandled error")
            return _error(f"{type(exc).__name__}: {exc}", 500)

    wrapper.__name__ = fn.__name__
    return wrapper


def _body() -> dict[str, Any]:
    data = request.get_json(silent=True)
    if data is None and request.form:
        data = {k: v for k, v in request.form.items()}
    return data or {}


def _card_payload(card) -> dict[str, Any]:
    return {
        "card_id": card.card_id,
        "title": card.title,
        "description": card.description,
        "cover": card.cover_url,
        "duration": card.duration,
        "file_size": card.file_size,
        "updated_at": card.updated_at,
        "options": {
            "always_play_from_start": card.content.config.get("resumeTimeout") == 0,
            "shuffle": bool(card.content.config.get("shuffle")),
            "hide_track_numbers": (
                (card.content.edit_settings or {}).get("autoOverlayLabels")
                == "disabled"
            ),
        },
        "chapters": [
            {
                "key": c.key,
                "title": c.title,
                "duration": c.duration,
                "overlay_label": c.overlay_label,
                "tracks": [
                    {
                        "key": t.key,
                        "title": t.title,
                        "media_id": t.media_id,
                        "track_url": t.track_url,
                        "duration": t.duration,
                        "format": t.format,
                        "type": t.type,
                    }
                    for t in c.tracks
                ],
            }
            for c in card.content.chapters
        ],
    }


# ----------------------------------------------------------------------
# status
# ----------------------------------------------------------------------
@api.get("/")
@_guard
def index():
    state = _state()

    session: dict[str, Any] = {
        "configured": _settings().cookie_file.exists() or state.read() != {}
    }
    try:
        claims = _yoto().auth.whoami()
        session.update(
            {
                "ok": True,
                "subject": claims.get("sub"),
                "scopes": claims.get("scope"),
                "expires_in": claims.get("exp", 0) - claims.get("iat", 0),
            }
        )
    except Exception as exc:
        session.update({"ok": False, "error": str(exc)})

    return jsonify(
        {
            "ok": True,
            "service": "yotaiman",
            "session": session,
            "token_refresh": _token_refresh(),
            "daily_card_id": state.get("daily_card_id", ""),
            "last_run": state.get("last_run", ""),
            "capabilities": caps.names(),
            "generators": _registry().info(),
            "endpoints": [
                "GET    /api/health",
                "GET    /api/cards",
                "GET    /api/cards/<card_id>",
                "DELETE /api/cards/<card_id>",
                "DELETE /api/cards/<card_id>/<key>",
                "PUT    /api/cards/<card_id>",
                "POST   /api/cards/<card_id>/cover",
                "POST   /api/cards/<card_id>/tracks",
                "GET    /api/generators",
                "GET    /api/generators/music",
                "GET    /api/generators/speech",
                "GET    /api/capabilities",
                "POST   /api/capabilities/<name>",
                "GET    /api/topics",
                "GET    /api/daily",
                "POST   /api/daily",
            ],
        }
    )


@api.get("/health")
@_guard
def health():
    state = _state()

    session: dict[str, Any] = {
        "configured": _settings().cookie_file.exists() or state.read() != {}
    }
    try:
        claims = _yoto().auth.whoami()
        session.update(
            {
                "ok": True,
                "subject": claims.get("sub"),
                "scopes": claims.get("scope"),
                "expires_in": claims.get("exp", 0) - claims.get("iat", 0),
            }
        )
    except Exception as exc:
        session.update({"ok": False, "error": str(exc)})

    return jsonify(
        {
            "ok": True,
            "service": "yotaiman",
            "session": session,
            "token_refresh": _token_refresh(),
            "daily_card_id": state.get("daily_card_id", ""),
            "last_run": state.get("last_run", ""),
            "capabilities": caps.names(),
            "generators": _registry().info(),
        }
    )


# ----------------------------------------------------------------------
# cards
# ----------------------------------------------------------------------
@api.get("/cards")
@_guard
def list_cards():
    cards = _yoto().cards.list()
    return jsonify(
        {
            "ok": True,
            "cards": [
                {
                    "card_id": c.card_id,
                    "title": c.title,
                    "description": c.description,
                    "cover": c.cover_url,
                    "duration": c.duration,
                    "file_size": c.file_size,
                    "updated_at": c.updated_at,
                }
                for c in cards
            ],
        }
    )


@api.get("/cards/<card_id>")
@_guard
def get_card(card_id: str):
    card = _yoto().cards.get(card_id)
    return jsonify({"ok": True, "card": _card_payload(card)})


@api.delete("/cards/<card_id>")
@_guard
def delete_card(card_id: str):
    _yoto().cards.delete(card_id)
    state = _state()
    if state.get("daily_card_id") == card_id:
        state.set("daily_card_id", "")
    return jsonify(
        {"ok": True, "message": f"Deleted card {card_id}", "card_id": card_id}
    )


@api.delete("/cards/<card_id>/<key>")
@_guard
def delete_track(card_id: str, key: str):
    chapter = request.args.get("chapter") or None
    card = _yoto().cards.delete_track(card_id, key, chapter=chapter)
    return jsonify(
        {
            "ok": True,
            "message": f"Deleted track {key} from card {card_id}",
            "card_id": card_id,
            "card": _card_payload(card),
        }
    )


@api.put("/cards/<card_id>")
@_guard
def reset_card(card_id: str):
    """Reset a card: remove every track, optionally rename or reconfigure."""
    data = _body()
    options = data.get("options")
    if not isinstance(options, dict):
        options = {}
    # Accept the option names at the top level too.
    for name in (
        "always_play_from_start",
        "shuffle",
        "hide_track_numbers",
    ):
        if name in data and name not in options:
            options[name] = data[name]

    card = _yoto().cards.reset(
        card_id,
        title=data.get("title"),
        description=data.get("description"),
        options=options or None,
    )
    return jsonify(
        {
            "ok": True,
            "message": f"Reset card {card_id}",
            "card_id": card_id,
            "card": _card_payload(card),
        }
    )


@api.post("/cards/<card_id>/cover")
@_guard
def set_cover(card_id: str):
    """Set the card's cover image from an uploaded file or a URL."""
    data = _body()
    url = str(data.get("url") or "").strip()
    path = str(data.get("path") or "").strip()

    cover: dict[str, Any]
    if request.files:
        uploaded = next(iter(request.files.values()))
        import os
        import tempfile

        with tempfile.NamedTemporaryFile(
            suffix="." + (uploaded.filename or "png").rsplit(".", 1)[-1],
            delete=False,
        ) as handle:
            uploaded.save(handle)
            temp_path = handle.name
        try:
            cover = _yoto().media.upload_cover_image(temp_path)
        finally:
            os.unlink(temp_path)
    elif url or path:
        import os
        import tempfile

        import requests

        source = url or path
        if not source.startswith(("http://", "https://")):
            local = source
        else:
            resp = requests.get(source, timeout=120)
            resp.raise_for_status()
            suffix = "." + source.split("?")[0].rsplit(".", 1)[-1]
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
                handle.write(resp.content)
                local = handle.name
        try:
            cover = _yoto().media.upload_cover_image(local)
        finally:
            if local != source:
                os.unlink(local)
    else:
        return _error("provide an image file, a 'url' or a 'path'")

    card = _yoto().cards.get(card_id)
    return jsonify(
        {
            "ok": True,
            "message": f"Set cover for card {card_id}",
            "card_id": card_id,
            "cover": cover,
            "card": _card_payload(card),
        }
    )


@api.post("/cards/<card_id>/tracks")
@_guard
def add_track(card_id: str):
    """Add a track: stream, file, or generated."""
    track_request = TrackRequest.from_dict(_body())
    result = current_app.extensions["tracks"].add(card_id, track_request)
    return jsonify(result)


# ----------------------------------------------------------------------
# generators
# ----------------------------------------------------------------------
@api.get("/generators")
@_guard
def list_generators():
    info = _registry().info()
    info["ok"] = True
    info["book_formats"] = describe_formats()
    return jsonify(info)


@api.get("/generators/music")
@_guard
def list_music_generators():
    info = _registry().music_info()
    info["ok"] = True
    return jsonify(info)


@api.get("/generators/speech")
@_guard
def list_speech_generators():
    info = _registry().speech_info()
    info["ok"] = True
    return jsonify(info)


# ----------------------------------------------------------------------
# capabilities
# ----------------------------------------------------------------------
@api.get("/capabilities")
@_guard
def list_capabilities():
    return jsonify(
        {
            "ok": True,
            "capabilities": [c.info().to_dict() for c in caps.all_capabilities()],
        }
    )


@api.post("/capabilities/<name>")
@_guard
def run_capability(name: str):
    result = caps.run_safely(name, **_body())
    return jsonify(result.to_dict()), (200 if result.ok else 400)


@api.get("/topics")
@_guard
def list_topics():
    return jsonify({"ok": True, "topics": topic_suggestions()})


@api.get("/daily")
@_guard
def daily_status():
    state = _state()
    card_id = state.get("daily_card_id", "") or _settings().daily_card_id
    payload: dict[str, Any] = {
        "ok": True,
        "card_id": card_id,
        "last_run": state.get("last_run", ""),
        "last_story": state.get("last_story", {}),
        "mode": _settings().daily_mode,
    }
    if card_id:
        try:
            payload["card"] = _card_payload(_yoto().cards.get(card_id))
        except Exception as exc:
            payload["card_error"] = str(exc)
    return jsonify(payload)


@api.post("/daily")
@_guard
def publish_daily():
    result = caps.run_safely("daily-story", **_body())
    return jsonify(result.to_dict()), (200 if result.ok else 400)
