"""The JSON API.

Every route lives at module level so the blueprint can be registered on more
than one application in the same process -- which the tests do.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from flask import Blueprint, current_app, jsonify, request

from yoto.errors import SessionExpired, YotoError

from .capabilities import base as caps
from .content.books import describe_formats
from .content.text import topic_suggestions
from .gate import rate_limited
from .security import scrub_paths
from .tracks import TrackError, TrackRequest

api = Blueprint("api", __name__, url_prefix="/api")

#: How large a fetched cover image may be, in bytes.
MAX_COVER_BYTES = 20 * 1024 * 1024


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
    status = dict(refresher.status())
    status["error"] = scrub_paths(str(status.get("error") or ""))
    return status


def _scrubbed(value: Any) -> Any:
    """A value with the absolute paths taken out of it."""
    if isinstance(value, str):
        return scrub_paths(value)
    return value


def _capability_payload(result: Any) -> dict[str, Any]:
    """A capability result, without the absolute paths in it."""
    payload = result.to_dict()
    payload["message"] = scrub_paths(str(payload.get("message") or ""))
    payload["data"] = {
        key: _scrubbed(value) for key, value in (payload.get("data") or {}).items()
    }
    return payload


def _error(message: str, status: int = 400, **extra: Any):
    payload = {"ok": False, "error": message}
    payload.update(extra)
    return jsonify(payload), status


def _guard(fn):
    """Turn SDK errors into clean JSON responses.

    The detail of an unexpected failure goes to the service log rather than
    to the caller: a traceback names the files and the directories the
    service runs in, which is nobody else's business.  The caller gets a
    reference to look up in the log.
    """

    def wrapper(*args: Any, **kwargs: Any):
        try:
            return fn(*args, **kwargs)
        except SessionExpired as exc:
            return _error(
                "the Yoto session has expired; refresh the cookie jar",
                401,
                instructions=exc.relogin_instructions,
            )
        except TrackError as exc:
            return _error(scrub_paths(str(exc)), 400)
        except YotoError as exc:
            return _error(scrub_paths(str(exc)), getattr(exc, "status", 502) or 502)
        except Exception:  # pragma: no cover - defensive
            reference = uuid.uuid4().hex[:12]
            current_app.logger.exception("unhandled error (reference %s)", reference)
            return _error(
                "something went wrong; the service log has the detail "
                f"(reference {reference})",
                500,
            )

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

        from .security import (
            SecurityError,
            UnsafePathError,
            UnsafeURLError,
            read_capped,
            resolve_within,
            safe_fetch,
        )

        source = url or path
        # Only http and https are fetched.  Anything else with a scheme --
        # file:, ftp:, data: -- is refused rather than treated as a path.
        # The check is on "://" rather than on the colon, so that a Windows
        # drive letter is still a drive letter.
        fetched = False

        if "://" in source and not source.lower().startswith(("http://", "https://")):
            return _error("only http and https URLs are allowed", 400)

        if source.lower().startswith(("http://", "https://")):
            try:
                resp = safe_fetch(source, timeout=120)
            except UnsafeURLError as exc:
                return _error(f"refusing to fetch that URL: {exc}", 400)
            except Exception as exc:
                return _error(f"could not fetch that URL: {exc}", 400)
            if resp.status_code >= 400:
                resp.close()
                return _error(
                    f"fetching that URL returned HTTP {resp.status_code}", 400
                )
            suffix = Path(source.split("?")[0]).suffix or ".img"
            try:
                payload = read_capped(resp, MAX_COVER_BYTES)
            except SecurityError as exc:
                return _error(str(exc), 400)
            finally:
                resp.close()
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
                handle.write(payload)
                local = handle.name
            fetched = True
        else:
            # A local path is confined to the content directories, so the
            # endpoint cannot be used to read an arbitrary file.
            try:
                local = str(resolve_within(_settings().content_dirs, source))
            except UnsafePathError as exc:
                return _error(str(exc), 400)
            if not Path(local).exists():
                return _error("no such file", 400)

        try:
            cover = _yoto().media.upload_cover_image(local)
        finally:
            # Only the copy this endpoint made is removed; a file the
            # operator pointed at is left alone.
            if fetched:
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
    if track_request.type == "generate" and rate_limited():
        return _error("too many generated tracks; slow down", 429)
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
    if rate_limited():
        return _error("too many requests; slow down", 429)
    result = caps.run_safely(name, **_body())
    return jsonify(_capability_payload(result)), (200 if result.ok else 400)


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
        except Exception:
            current_app.logger.exception("could not read the daily card")
            payload["card_error"] = "the daily card could not be read"
    return jsonify(payload)


@api.post("/daily")
@_guard
def publish_daily():
    if rate_limited():
        return _error("too many requests; slow down", 429)
    result = caps.run_safely("daily-story", **_body())
    return jsonify(_capability_payload(result)), (200 if result.ok else 400)
