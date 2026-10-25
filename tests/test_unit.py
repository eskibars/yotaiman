"""Offline tests: models, state, template writer, TTS and the Flask routes.

None of these touch the Yoto API.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from yoto.models import (  # noqa: E402
    Card,
    CardContent,
    Chapter,
    Track,
    media_id_to_track_url,
    track_url_to_media_id,
)
from yoto_daily.config import Settings  # noqa: E402
from yoto_daily.content.text import (  # noqa: E402
    TemplateTextSource,
    build_text_source,
)
from yoto_daily.state import StateStore  # noqa: E402
from yoto_daily.tracks import TrackRequest  # noqa: E402


# ----------------------------------------------------------------------
# models
# ----------------------------------------------------------------------
def test_media_id_round_trip():
    assert media_id_to_track_url("abc") == "yoto:#abc"
    assert media_id_to_track_url("yoto:#abc") == "yoto:#abc"
    assert track_url_to_media_id("yoto:#abc") == "abc"
    assert track_url_to_media_id("abc") == "abc"


def test_track_from_dict():
    track = Track.from_dict(
        {
            "key": "01",
            "title": "A Story",
            "trackUrl": "yoto:#" + "x" * 43,
            "format": "aac",
            "duration": 685,
            "fileSize": 8359661,
            "channels": "mono",
            "display": {"icon16x16": "yoto:#" + "y" * 43},
        }
    )
    assert track.media_id == "x" * 43
    assert track.icon_media_id == "y" * 43
    assert track.to_dict()["trackUrl"].startswith("yoto:#")


def test_track_request_carries_an_instruction():
    """A request may ask for a different delivery than the default."""
    request = TrackRequest.from_dict(
        {
            "type": "generate",
            "kind": "text-to-speech",
            "text": "Once upon a time",
            "instruction": "unhurried and warm",
        }
    )
    assert request.params["instruction"] == "unhurried and warm"

    nested = TrackRequest.from_dict(
        {
            "type": "generate",
            "kind": "text-to-speech",
            "params": {"text": "Once upon a time", "instruction": "excited"},
        }
    )
    assert nested.params["instruction"] == "excited"


def test_card_content_round_trip():
    track = Track(key="01", title="T", track_url="yoto:#z" * 1, duration=10, file_size=100)
    chapter = Chapter(key="00", title="C", tracks=[track])
    content = CardContent(chapters=[chapter])
    data = content.to_dict()

    assert data["chapters"][0]["tracks"][0]["title"] == "T"
    assert data["config"]["resumeTimeout"] == 2592000

    restored = CardContent.from_dict(data)
    assert restored.total_duration == 10
    assert len(list(restored.iter_tracks())) == 1


def test_card_duration_prefers_chapters_then_metadata():
    with_chapters = Card(
        card_id="a",
        content=CardContent(
            chapters=[Chapter(key="00", title="C", tracks=[Track("01", "T", "u", duration=12)])]
        ),
    )
    assert with_chapters.duration == 12

    summary_only = Card(card_id="b", metadata={"media": {"duration": 4864}})
    assert summary_only.duration == 4864
    assert summary_only.is_summary


# ----------------------------------------------------------------------
# state
# ----------------------------------------------------------------------
def test_state_store(tmp_path):
    store = StateStore(tmp_path / "state.json")
    assert store.read() == {}
    store.set("daily_card_id", "abc")
    assert store.get("daily_card_id") == "abc"
    store.update(last_run="now")
    assert store.get("last_run") == "now"
    assert json.loads((tmp_path / "state.json").read_text())["daily_card_id"] == "abc"


def test_state_store_survives_corruption(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not json")
    assert StateStore(path).read() == {}


# ----------------------------------------------------------------------
# text
# ----------------------------------------------------------------------
def test_template_source_generates_a_story():
    source = TemplateTextSource()
    story = source.generate("dolphins", child_name="Alex")
    assert story.topic == "dolphins"
    assert "Alex" in story.body
    assert story.title
    assert len(story.body) > 100


def test_template_source_handles_unknown_topic():
    story = TemplateTextSource().generate("quantum badgers")
    assert story.topic == "quantum badgers"
    assert "quantum badgers" in story.body


def test_template_source_rotates_by_day():
    source = TemplateTextSource()
    first = source.generate()
    second = source.generate()
    assert first.topic == second.topic  # stable within a day


def test_build_text_source_auto_falls_back_to_template():
    source = build_text_source(backend="auto", script="", script_model="")
    assert source.name == "fallback"
    story = source.generate("dolphins")
    assert story.backend == "template"


def test_fallback_skips_a_broken_backend_once():
    from yoto_daily.content.text import FallbackTextSource

    class Broken:
        name = "broken"

        def available(self):
            return True

        def generate(self, *a, **kw):
            raise RuntimeError("Error 401: token is required")

    chain = FallbackTextSource([Broken(), TemplateTextSource()])
    story = chain.generate("dolphins")
    assert story.backend == "template"
    assert chain.generate("dolphins").backend == "template"


# ----------------------------------------------------------------------
# tts
# ----------------------------------------------------------------------
def test_say_backend_renders_audio(tmp_path):
    import shutil

    if not shutil.which("say") or not shutil.which("ffmpeg"):
        pytest.skip("say/ffmpeg not available")

    from yoto_daily.content.tts import MacSayBackend

    backend = MacSayBackend()
    out = tmp_path / "clip.mp3"
    result = backend.synthesize("Hello there. One two three.", out, voice="Karen")

    assert out.exists()
    assert out.stat().st_size > 1000
    assert result.duration > 0.5
    assert result.backend == "say"


# ----------------------------------------------------------------------
# flask routes
# ----------------------------------------------------------------------
@pytest.fixture
def client(tmp_path, monkeypatch):
    from yoto_daily.app import create_app

    settings = Settings(state_dir=tmp_path / "state")
    app = create_app(settings)
    app.config["TESTING"] = True
    return app.test_client()


def test_index_lists_endpoints(client):
    # The JSON index lives at /api/; the HTML desk owns "/".
    body = client.get("/api/").get_json()
    assert body["service"] == "yotaiman"
    endpoints = {line.split()[0] + " " + line.split()[1] for line in body["endpoints"]}
    assert "GET /api/health" in endpoints
    assert "GET /api/daily" in endpoints
    assert "DELETE /api/cards/<card_id>" in endpoints
    assert "POST /api/cards/<card_id>/tracks" in endpoints
    assert "GET /api/generators/music" in endpoints
    assert "GET /api/generators/speech" in endpoints


def test_capabilities_are_registered(client):
    body = client.get("/api/capabilities").get_json()
    names = [c["name"] for c in body["capabilities"]]
    assert "daily-story" in names
    assert "read-aloud" in names


def test_the_add_track_form_offers_an_instruction_field(client):
    page = client.get("/cards/some-card/add").get_data(as_text=True)
    assert 'name="instruction"' in page
    assert "How to read it" in page


def test_topics_listing(client):
    body = client.get("/api/topics").get_json()
    assert len(body["topics"]) >= 5
    assert all("topic" in t and "title" in t for t in body["topics"])


def test_unknown_capability_reports_cleanly(client):
    resp = client.post("/api/capabilities/nope", json={})
    body = resp.get_json()
    assert resp.status_code == 400
    assert body["ok"] is False
    assert "available" in body["data"]


def test_read_aloud_requires_text(client):
    resp = client.post("/api/capabilities/read-aloud", json={})
    body = resp.get_json()
    assert resp.status_code == 400
    assert "no text supplied" in body["message"]
