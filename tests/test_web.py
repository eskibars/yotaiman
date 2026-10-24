"""Tests for the HTML interface.

The rendering checks that need a card live in ``test_live_tracks.py``; these
cover the parts that work without an account.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from yoto_daily.app import create_app  # noqa: E402
from yoto_daily.config import Settings  # noqa: E402


@pytest.fixture
def app(tmp_path):
    application = create_app(Settings.load())
    application.config["TESTING"] = True
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def test_both_front_ends_are_registered(app):
    rules = {str(r.rule) for r in app.url_map.iter_rules()}
    # The JSON API.
    assert "/api/health" in rules
    assert "/api/cards" in rules
    assert "/api/cards/<card_id>/tracks" in rules
    assert "/api/generators/music" in rules
    # The HTML desk.
    assert "/" in rules
    assert "/cards/<card_id>" in rules
    assert "/cards/<card_id>/add" in rules
    assert "/generators" in rules


def test_api_index_lists_the_endpoints(client):
    body = client.get("/api/").get_json()
    assert body["service"] == "yotaiman"
    assert "GET    /api/health" in body["endpoints"]
    assert "POST   /api/cards/<card_id>/tracks" in body["endpoints"]


def test_static_assets_are_served(client):
    css = client.get("/static/style.css")
    assert css.status_code == 200
    assert b"--accent" in css.data

    js = client.get("/static/composer.js")
    assert js.status_code == 200
    assert b"disabled" in js.data


def test_generators_page_renders(client):
    resp = client.get("/generators")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Music" in body
    assert "Speech" in body
    assert "Books" in body
    assert "ace-step" in body or "synth" in body


def test_templates_are_all_present():
    root = Path(__file__).resolve().parent.parent / "yoto_daily" / "templates"
    for name in ("base.html", "index.html", "card.html", "add_track.html", "generators.html"):
        assert (root / name).exists(), f"missing template {name}"


def test_duration_and_plural_helpers():
    from yoto_daily.web import _duration, _plural

    assert _duration(0) == "—"
    assert _duration(47) == "47s"
    assert _duration(252) == "4m 12s"
    assert _duration(4864) == "1h 21m"

    assert _plural(1, "chapter") == "1 chapter"
    assert _plural(2, "chapter") == "2 chapters"
    assert _plural(0, "track") == "0 tracks"


def test_card_edge_is_deterministic():
    from yoto_daily.web import _card_edge

    # The same id always gets the same edge colour.
    assert _card_edge("card-one") == _card_edge("card-one")
    assert _card_edge("card-one").startswith("#")

    # Different ids are spread across the palette rather than all identical.
    edges = {_card_edge(f"card-{name}") for name in ("one", "two", "three", "four")}
    assert len(edges) > 1
