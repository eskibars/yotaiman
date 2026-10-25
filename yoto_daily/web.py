"""The HTML interface.

A small control desk for the same operations the JSON API exposes.  The API
is untouched; this is a second front end over the same services.

    /                     the shelf: every card, and the daily card's status
    /cards/<id>           one card: its programme, options and actions
    /cards/<id>/add       add a track (GET the form, POST the submission)
    /cards/<id>/options   save the playback options
    /cards/<id>/delete    delete the card
    /cards/<id>/tracks/<key>/delete   delete one track
    /generators           the configured music and speech generators
    /daily                publish today's story

Forms use POST-redirect-GET, so a refresh never republishes.
"""

from __future__ import annotations

from typing import Any

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from .capabilities import base as caps
from .content.books import describe_formats
from .tracks import TrackError, TrackRequest

web = Blueprint("web", __name__)


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------
def _duration(seconds: int) -> str:
    """Human duration: ``1h 21m``, ``4m 12s``, ``47s``."""
    seconds = int(seconds or 0)
    if seconds <= 0:
        return "—"
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    """``1 chapter`` / ``2 chapters``."""
    word = singular if count == 1 else (plural or singular + "s")
    return f"{count} {word}"


def _card_edge(card_id: str) -> str:
    """A deterministic accent for a card, from its id.

    Physical Yoto cards have coloured faces; this gives each card a stable
    edge colour so it is recognisable at a glance.
    """
    palette = ["#0f5132", "#7a4a12", "#1f4c6b", "#6b2d3f", "#4a4a12", "#3c2d5c"]
    total = sum(ord(c) for c in card_id) if card_id else 0
    return palette[total % len(palette)]


def _yoto():
    return current_app.extensions["yoto"]


def _registry():
    return current_app.extensions["generators"]


def _settings():
    return current_app.config["YOTO_SETTINGS"]


def _state():
    return current_app.config["YOTO_STATE"]


# ----------------------------------------------------------------------
# pages
# ----------------------------------------------------------------------
@web.get("/")
def index():
    yoto = _yoto()
    state = _state()
    # A lapsed session must not turn the desk into an error page: the point
    # of the page is to say what is wrong, so the shelf is fetched defensively
    # and the banner below explains the rest.
    try:
        cards = yoto.cards.list()
    except Exception:
        cards = []

    daily_id = state.get("daily_card_id", "") or _settings().daily_card_id
    daily_card = None
    if daily_id:
        try:
            daily_card = yoto.cards.get(daily_id)
        except Exception:
            daily_card = None

    try:
        yoto.auth.whoami()
        session_ok = True
        session_error = ""
    except Exception as exc:
        session_ok = False
        session_error = str(exc)

    # The background refresher reports what it last managed to do, so a
    # session that has lapsed is visible before it turns into a failed
    # request.
    refresher = current_app.extensions.get("token_refresher")
    refresh = refresher.status() if refresher is not None else {"enabled": False}
    refresh_error = refresh.get("error", "") if refresh.get("last_ok") is False else ""

    return render_template(
        "index.html",
        cards=cards,
        daily_card=daily_card,
        daily_id=daily_id,
        last_story=state.get("last_story", {}),
        last_run=state.get("last_run", ""),
        session_ok=session_ok,
        session_error=session_error,
        refresh=refresh,
        refresh_error=refresh_error,
        duration=_duration,
        edge=_card_edge,
        plural=_plural,
    )


@web.get("/cards/<card_id>")
def card(card_id: str):
    found = _yoto().cards.get(card_id)
    return render_template(
        "card.html",
        card=found,
        total=found.duration or 1,
        duration=_duration,
        edge=_card_edge,
        plural=_plural,
    )


@web.get("/cards/<card_id>/add")
def add_track(card_id: str):
    registry = _registry()
    return render_template(
        "add_track.html",
        card_id=card_id,
        music=[
            g.to_dict(is_default=(g.name == registry.default_music_name))
            for g in registry.music_generators()
        ],
        speech=[
            g.to_dict(is_default=(g.name == registry.default_speech_name))
            for g in registry.speech_generators()
        ],
        music_default=registry.default_music_name,
        speech_default=registry.default_speech_name,
        book_formats=describe_formats(),
    )


def _first_filled(form: Any, name: str) -> str:
    """The first non-empty value of a form field.

    The add-track form shows an instruction field in more than one panel,
    and a browser submits all of them; ``form.get`` would return the first
    one even when it is the empty one.
    """
    for value in form.getlist(name):
        value = (value or "").strip()
        if value:
            return value
    return ""


@web.post("/cards/<card_id>/add")
def add_track_submit(card_id: str):
    form = request.form
    track_type = form.get("type", "generate")
    kind = form.get("kind", "")

    params: dict[str, Any] = {}
    if track_type == "stream":
        params["url"] = form.get("url", "").strip()
        params["format"] = form.get("format", "mp3")
    elif track_type == "file":
        if form.get("path", "").strip():
            params["path"] = form["path"].strip()
        else:
            params["url"] = form.get("url", "").strip()
    else:
        kind = kind or "text-to-speech"
        if kind == "music":
            params = {
                "prompt": form.get("prompt", "").strip(),
                "bpm": form.get("bpm", "").strip(),
                "key_scale": form.get("key_scale", "").strip(),
                "time_signature": form.get("time_signature", "").strip(),
                "duration": form.get("duration", "").strip(),
                "tags": [
                    t.strip() for t in form.get("tags", "").split(",") if t.strip()
                ],
            }
        elif kind == "read-book":
            params = {
                "source": form.get("source", "").strip(),
                "chapters": form.get("chapters", "").strip(),
                "instruction": _first_filled(form, "instruction"),
            }
        else:
            kind = "text-to-speech"
            params = {
                "text": form.get("text", "").strip(),
                "voice": form.get("voice", "").strip(),
                "instruction": _first_filled(form, "instruction"),
            }
        params = {k: v for k, v in params.items() if v not in ("", None)}

    track_request = TrackRequest(
        type=track_type,
        kind=kind,
        generator=form.get("generator", "").strip(),
        params=params,
        title=form.get("title", "").strip(),
        chapter=form.get("chapter", "").strip(),
    )

    try:
        result = current_app.extensions["tracks"].add(card_id, track_request)
    except TrackError as exc:
        flash(str(exc), "error")
        return redirect(url_for("web.add_track", card_id=card_id))
    except Exception as exc:  # pragma: no cover - defensive
        flash(f"{type(exc).__name__}: {exc}", "error")
        return redirect(url_for("web.add_track", card_id=card_id))

    flash(result.get("message", "Added the track."), "success")
    return redirect(url_for("web.card", card_id=card_id))


@web.post("/cards/<card_id>/options")
def save_options(card_id: str):
    form = request.form
    try:
        found = _yoto().cards.reset(
            card_id,
            title=form.get("title", "").strip() or None,
            description=form.get("description", "").strip(),
            options={
                "always_play_from_start": form.get("always_play_from_start") == "on",
                "shuffle": form.get("shuffle") == "on",
                "hide_track_numbers": form.get("hide_track_numbers") == "on",
            },
        )
    except Exception as exc:
        flash(f"Could not save the options: {exc}", "error")
        return redirect(url_for("web.card", card_id=card_id))

    if form.get("clear_tracks") == "on":
        flash(f"Cleared the tracks on {found.title}.", "success")
    else:
        flash(f"Saved the options for {found.title}.", "success")
    return redirect(url_for("web.card", card_id=card_id))


@web.post("/cards/<card_id>/tracks/<key>/delete")
def delete_track(card_id: str, key: str):
    try:
        _yoto().cards.delete_track(card_id, key)
        flash(f"Deleted track {key}.", "success")
    except Exception as exc:
        flash(f"Could not delete track {key}: {exc}", "error")
    return redirect(url_for("web.card", card_id=card_id))


@web.post("/cards/<card_id>/delete")
def delete_card(card_id: str):
    try:
        _yoto().cards.delete(card_id)
        state = _state()
        if state.get("daily_card_id") == card_id:
            state.set("daily_card_id", "")
        flash(f"Deleted card {card_id}.", "success")
    except Exception as exc:
        flash(f"Could not delete the card: {exc}", "error")
    return redirect(url_for("web.index"))


@web.post("/daily")
def publish_daily():
    result = caps.run_safely("daily-story", **request.form.to_dict())
    flash(result.message, "success" if result.ok else "error")
    return redirect(url_for("web.index"))


@web.get("/generators")
def generators():
    registry = _registry()
    return render_template(
        "generators.html",
        music=registry.music_info(),
        speech=registry.speech_info(),
        book_formats=describe_formats(),
        config_file=str(_settings().config_file),
    )
