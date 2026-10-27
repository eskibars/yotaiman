"""Live tests for the card and track API.

Exercises the whole CRUD surface against the real API on a scratch card:

    reset -> add track -> list -> delete track -> cover -> delete card
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from yoto import Yoto  # noqa: E402
from yoto_daily.config import Settings  # noqa: E402

RUN_LIVE = os.environ.get("YOTO_LIVE_TESTS", "1") not in ("0", "false", "no")

pytestmark = pytest.mark.skipif(
    not RUN_LIVE, reason="set YOTO_LIVE_TESTS=1 to run against the real API"
)


@pytest.fixture(scope="module")
def client():
    from yoto_daily.app import create_app
    from yoto_daily.config import Settings

    app = create_app(Settings.load())
    app.config["TESTING"] = True
    test_client = app.test_client()
    # The service asks for a token before it does anything.
    test_client.environ_base["HTTP_AUTHORIZATION"] = (
        f"Bearer {app.config['YOTO_TOKEN']}"
    )
    return test_client


@pytest.fixture(scope="module")
def scratch(client):
    """A scratch card, deleted when the module finishes."""
    resp = client.post("/api/cards", json={}) if False else None
    del resp
    y = Yoto()
    card = y.cards.create(title="API Scratch")
    yield card.card_id
    try:
        y.cards.delete(card.card_id)
    except Exception:
        pass


def _sample_audio(tmp_path: Path) -> Path:
    aiff = tmp_path / "clip.aiff"
    mp3 = tmp_path / "clip.mp3"
    say = subprocess.run(
        ["say", "-o", str(aiff), "This is a test of the track pipeline."],
        capture_output=True,
        check=False,
    )
    if say.returncode == 0 and aiff.exists():
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(aiff),
             "-c:a", "libmp3lame", "-b:a", "64k", str(mp3)],
            capture_output=True, check=True,
        )
        return mp3
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", "sine=frequency=440:duration=2", "-c:a", "libmp3lame",
         "-b:a", "64k", str(mp3)],
        capture_output=True, check=True,
    )
    return mp3


# ----------------------------------------------------------------------
def test_add_file_track(client, scratch, tmp_path):
    audio = _sample_audio(tmp_path)
    resp = client.post(
        f"/api/cards/{scratch}/tracks",
        json={"type": "file", "path": str(audio), "title": "File Track"},
    )
    body = resp.get_json()
    assert resp.status_code == 200, body
    assert body["ok"] is True
    assert len(body["tracks"]) == 1
    track = body["tracks"][0]
    assert track["media_id"].startswith("yoto:#")
    assert track["duration"] > 0


def test_add_generated_speech_track(client, scratch):
    resp = client.post(
        f"/api/cards/{scratch}/tracks",
        json={
            "type": "generate",
            "kind": "text-to-speech",
            "params": {"text": "Once upon a time there was a small robot."},
        },
    )
    body = resp.get_json()
    assert resp.status_code == 200, body
    assert body["generator"] == "say"
    assert body["tracks"][0]["media_id"].startswith("yoto:#")


def test_add_stream_track(client, scratch):
    resp = client.post(
        f"/api/cards/{scratch}/tracks",
        json={"type": "stream", "url": "https://example.com/stream.mp3"},
    )
    body = resp.get_json()
    assert resp.status_code == 200, body
    assert body["tracks"][0]["type"] == "stream"
    assert body["tracks"][0]["track_url"] == "https://example.com/stream.mp3"


def test_card_contents_reflect_the_new_tracks(client, scratch):
    body = client.get(f"/api/cards/{scratch}").get_json()
    assert body["ok"] is True
    titles = [
        t["title"]
        for chapter in body["card"]["chapters"]
        for t in chapter["tracks"]
    ]
    assert "File Track" in titles
    assert any("https://example.com/stream.mp3" == t for t in titles)


def test_put_resets_tracks_and_sets_options(client, scratch):
    resp = client.put(
        f"/api/cards/{scratch}",
        json={
            "title": "Reset Scratch",
            "description": "A description",
            "options": {
                "always_play_from_start": True,
                "shuffle": True,
                "hide_track_numbers": True,
            },
        },
    )
    body = resp.get_json()
    assert resp.status_code == 200, body
    card = body["card"]
    assert card["title"] == "Reset Scratch"
    assert card["description"] == "A description"
    assert card["chapters"] == []
    assert card["options"]["always_play_from_start"] is True
    assert card["options"]["shuffle"] is True
    assert card["options"]["hide_track_numbers"] is True

    # The options must survive a fresh read, not just the POST response.
    again = client.get(f"/api/cards/{scratch}").get_json()["card"]
    assert again["options"]["always_play_from_start"] is True
    assert again["options"]["shuffle"] is True
    assert again["options"]["hide_track_numbers"] is True


def test_delete_track(client, scratch):
    # Put a track back so there is something to delete.
    resp = client.post(
        f"/api/cards/{scratch}/tracks",
        json={"type": "stream", "url": "https://example.com/other.mp3"},
    )
    assert resp.status_code == 200

    body = client.get(f"/api/cards/{scratch}").get_json()["card"]
    track = body["chapters"][0]["tracks"][0]
    assert track["key"] == "01"

    resp = client.delete(f"/api/cards/{scratch}/01")
    body = resp.get_json()
    assert resp.status_code == 200, body
    assert body["ok"] is True


def test_delete_unknown_track_reports_cleanly(client, scratch):
    resp = client.delete(f"/api/cards/{scratch}/nope")
    assert resp.status_code == 404
    assert resp.get_json()["ok"] is False


def test_delete_card(client, scratch):
    y = Yoto()
    card = y.cards.create(title="Delete Me")
    resp = client.delete(f"/api/cards/{card.card_id}")
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    assert not y.cards.exists(card.card_id)


def test_add_generated_music_track(client, scratch):
    """Generate music and publish it.

    Uses the procedural generator so the test does not need a GPU; the
    ACE-Step client has its own protocol tests.
    """
    resp = client.post(
        f"/api/cards/{scratch}/tracks",
        json={
            "type": "generate",
            "kind": "music",
            "generator": "synth",
            "params": {
                "prompt": "gentle arpeggio",
                "bpm": 120,
                "duration": 6,
                "tags": ["calm"],
            },
        },
    )
    body = resp.get_json()
    assert resp.status_code == 200, body
    assert body["generator"] == "synth"
    assert body["spec"]["bpm"] == 120
    track = body["tracks"][0]
    assert track["media_id"].startswith("yoto:#")
    assert track["duration"] > 0


def test_generate_music_without_a_prompt_is_rejected(client, scratch):
    resp = client.post(
        f"/api/cards/{scratch}/tracks",
        json={"type": "generate", "kind": "music", "params": {"bpm": 90}},
    )
    assert resp.status_code == 400
    assert "prompt" in resp.get_json()["error"]


def test_generators_endpoints(client):
    music = client.get("/api/generators/music").get_json()
    assert music["kind"] == "music"
    assert music["generators"]
    assert any(g["name"] == "synth" for g in music["generators"])

    speech = client.get("/api/generators/speech").get_json()
    assert speech["kind"] == "speech"
    assert speech["generators"]
    # The default is whatever config.yaml says, which is not necessarily
    # the same on every machine.
    configured = (
        Settings.load().raw_config.get("generators", {})
        .get("speech", {})
        .get("default", "")
    )
    assert speech["default"] == configured
    assert any(g["name"] == speech["default"] for g in speech["generators"])


# ----------------------------------------------------------------------
# the HTML desk
# ----------------------------------------------------------------------
def test_index_page_lists_the_cards(client, scratch):
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "The shelf" in body
    assert scratch in body
    assert "Publish today" in body


def test_card_page_shows_the_programme(client, scratch):
    resp = client.get(f"/cards/{scratch}")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Programme" in body
    assert "Options" in body
    assert scratch in body


def test_add_track_page_offers_every_kind(client, scratch):
    resp = client.get(f"/cards/{scratch}/add")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    for label in ("Generate", "File", "Stream", "Music", "Text to speech", "Read a book"):
        assert label in body, f"missing {label!r}"


def test_add_a_stream_track_through_the_form(client, scratch):
    resp = client.post(
        f"/cards/{scratch}/add",
        data={"type": "stream", "url": "https://example.com/form.mp3"},
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith(f"/cards/{scratch}")

    body = client.get(f"/cards/{scratch}").get_data(as_text=True)
    assert "https://example.com/form.mp3" in body


def test_the_form_reports_a_bad_request(client, scratch):
    resp = client.post(
        f"/cards/{scratch}/add",
        data={"type": "stream", "url": "not-a-url"},
    )
    assert resp.status_code == 302

    body = client.get(f"/cards/{scratch}/add").get_data(as_text=True)
    assert "flash-error" in body


def test_saving_options_through_the_form(client, scratch):
    resp = client.post(
        f"/cards/{scratch}/options",
        data={
            "title": "Renamed By Form",
            "description": "Set from the desk",
            "always_play_from_start": "on",
            "shuffle": "on",
            "hide_track_numbers": "on",
        },
    )
    assert resp.status_code == 302

    card = client.get(f"/cards/{scratch}").get_data(as_text=True)
    assert "Renamed By Form" in card
    assert "Set from the desk" in card

    options = client.get(f"/api/cards/{scratch}").get_json()["card"]["options"]
    assert options["always_play_from_start"] is True
    assert options["shuffle"] is True
    assert options["hide_track_numbers"] is True


def test_deleting_a_track_through_the_form(client, scratch):
    client.post(
        f"/cards/{scratch}/add",
        data={"type": "stream", "url": "https://example.com/gone.mp3"},
    )
    body = client.get(f"/api/cards/{scratch}").get_json()["card"]
    key = body["chapters"][0]["tracks"][0]["key"]

    resp = client.post(f"/cards/{scratch}/tracks/{key}/delete")
    assert resp.status_code == 302

    after = client.get(f"/api/cards/{scratch}").get_json()["card"]
    assert after["chapters"] == [] or after["chapters"][0]["tracks"] == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-s"]))
