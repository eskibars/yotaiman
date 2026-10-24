"""Offline tests for the generator registry, book readers and card options."""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from yoto.cards import apply_playback_options, refresh_shuffle, shuffle_range  # noqa: E402
from yoto.models import CardContent, Chapter, Track  # noqa: E402
from yoto_daily.config import Settings, load_config_file  # noqa: E402
from yoto_daily.content.books import (  # noqa: E402
    BookError,
    describe_formats,
    normalise,
    read_book,
    split_chapters,
)
from yoto_daily.generators import (  # noqa: E402
    MusicSpec,
    build_registry,
    default_registry,
)
from yoto_daily.generators.base import GeneratorInfo  # noqa: E402
from yoto_daily.tracks import TrackRequest  # noqa: E402


# ----------------------------------------------------------------------
# playback options
# ----------------------------------------------------------------------
def _content(chapters: int = 2) -> CardContent:
    return CardContent(
        chapters=[
            Chapter(
                f"{i:02d}",
                f"Chapter {i}",
                [Track(f"{i:02d}", f"Track {i}", f"yoto:#m{i}", overlay_label=str(i + 1))],
                overlay_label=str(i + 1),
            )
            for i in range(chapters)
        ]
    )


def test_always_play_from_start_maps_to_resume_timeout():
    content = _content()
    apply_playback_options(content, always_play_from_start=True)
    assert content.config["resumeTimeout"] == 0

    apply_playback_options(content, always_play_from_start=False)
    assert content.config["resumeTimeout"] == 2592000


def test_shuffle_matches_the_yoto_app_shape():
    content = _content(3)
    apply_playback_options(content, shuffle=True)
    assert content.config["shuffle"] == [{"start": 0, "end": 2, "limit": 3}]

    apply_playback_options(content, shuffle=False)
    assert content.config["shuffle"] == []


def test_shuffle_range_for_an_empty_card_keeps_the_intent():
    content = CardContent(chapters=[])
    apply_playback_options(content, shuffle=True)
    assert content.config["shuffle"] == [{"start": 0, "end": 0, "limit": 1}]


def test_shuffle_range_is_recomputed_when_chapters_change():
    content = CardContent(chapters=[])
    apply_playback_options(content, shuffle=True)

    content.chapters = _content(4).chapters
    refresh_shuffle(content)
    assert content.config["shuffle"] == [{"start": 0, "end": 3, "limit": 4}]


def test_shuffle_range_helper():
    assert shuffle_range(0) == [{"start": 0, "end": 0, "limit": 1}]
    assert shuffle_range(1) == [{"start": 0, "end": 0, "limit": 1}]
    assert shuffle_range(5) == [{"start": 0, "end": 4, "limit": 5}]


def test_hide_track_numbers_clears_overlay_labels():
    content = _content(2)
    apply_playback_options(content, hide_track_numbers=True)

    assert content.edit_settings["autoOverlayLabels"] == "disabled"
    for chapter in content.chapters:
        assert chapter.overlay_label is None
        for track in chapter.tracks:
            assert track.overlay_label is None


def test_hide_track_numbers_off_restores_labels():
    content = _content(2)
    apply_playback_options(content, hide_track_numbers=True)
    apply_playback_options(content, hide_track_numbers=False)

    assert "autoOverlayLabels" not in (content.edit_settings or {})
    assert [c.overlay_label for c in content.chapters] == ["1", "2"]
    assert content.chapters[0].tracks[0].overlay_label == "1"


# ----------------------------------------------------------------------
# generators
# ----------------------------------------------------------------------
def test_music_spec_from_dict_accepts_aliases():
    spec = MusicSpec.from_dict(
        {
            "prompt": "gentle piano",
            "bpm": 90,
            "keyscale": "C Major",
            "timesignature": "4",
            "duration": 45,
            "tags": ["calm", "bedtime"],
        }
    )
    assert spec.bpm == 90
    assert spec.key_scale == "C Major"
    assert spec.time_signature == "4"
    assert spec.duration == 45
    assert "calm, bedtime" in spec.to_prompt()


def test_music_spec_keeps_unknown_fields_as_extra():
    spec = MusicSpec.from_dict({"prompt": "x", "inference_steps": 20})
    assert spec.extra["inference_steps"] == 20


def test_default_registry_has_both_kinds():
    registry = default_registry()
    assert registry.get_music().kind == "music"
    assert registry.get_speech().kind == "speech"
    assert registry.get_speech().available() in (True, False)


def test_build_registry_from_config(tmp_path):
    config = {
        "generators": {
            "music": {
                "default": "synth",
                "options": {
                    "synth": {"type": "synth"},
                    "off": {"type": "synth", "enabled": False},
                },
            },
            "speech": {
                "default": "say",
                "options": {
                    "say": {"type": "say", "voice": "Daniel"},
                    "remote": {"type": "http", "url": "http://127.0.0.1:9/tts"},
                },
            },
        }
    }
    registry = build_registry(config)

    assert [g.name for g in registry.music_generators()] == ["synth"]
    assert registry.get_music().name == "synth"

    speech = registry.get_speech()
    assert speech.name == "say"
    assert speech.options["voice"] == "Daniel"

    info = registry.music_info()
    assert info["default"] == "synth"
    assert info["generators"][0]["is_default"] is True


def test_registry_reports_unknown_generator():
    registry = default_registry()
    with pytest.raises(Exception):
        registry.get_music("nope")


def test_generator_info_shape():
    info = GeneratorInfo(name="x", kind="music", type="synth").to_dict()
    assert info["name"] == "x"
    assert info["kind"] == "music"
    assert info["available"] is False


# ----------------------------------------------------------------------
# config
# ----------------------------------------------------------------------
def test_config_file_is_loaded(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "service:\n  port: 9999\ngenerators:\n  speech:\n    default: say\n"
    )
    raw = load_config_file(path)
    assert raw["service"]["port"] == 9999

    settings = Settings.load(path)
    assert settings.port == 9999


def test_missing_config_file_is_not_fatal(tmp_path):
    assert load_config_file(tmp_path / "nope.yaml") == {}
    settings = Settings.load(tmp_path / "nope.yaml")
    assert settings.port == 8787


# ----------------------------------------------------------------------
# books
# ----------------------------------------------------------------------
def test_split_chapters_respects_the_word_budget():
    text = "\n\n".join("word " * 40 for _ in range(20))
    chapters = split_chapters(text, max_words=100)
    assert len(chapters) > 1
    assert all(len(c.split()) <= 120 for c in chapters)


def test_split_chapters_handles_a_single_huge_paragraph():
    text = " ".join(f"word{i}" for i in range(500))
    chapters = split_chapters(text, max_words=100)
    assert len(chapters) >= 4
    assert all(c.strip() for c in chapters)


def test_normalise_collapses_whitespace():
    assert normalise("a  \t b\r\n\r\n\r\nc") == "a b\n\nc"


def _make_epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "mimetype", "application/epub+zip"
        )
        archive.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
            <container version="1.0"
              xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
              <rootfiles><rootfile full-path="OEBPS/content.opf"
                media-type="application/oebps-package+xml"/></rootfiles>
            </container>""",
        )
        archive.writestr(
            "OEBPS/content.opf",
            """<?xml version="1.0"?>
            <package xmlns="http://www.idpf.org/2007/opf" version="3.0">
              <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
                <dc:title>The Test Whale</dc:title>
              </metadata>
              <manifest>
                <item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
                <item id="c2" href="ch2.xhtml" media-type="application/xhtml+xml"/>
              </manifest>
              <spine><itemref idref="c1"/><itemref idref="c2"/></spine>
            </package>""",
        )
        archive.writestr(
            "OEBPS/ch1.xhtml",
            "<html><body><h1>Chapter One</h1><p>The whale sang at dawn.</p>"
            "<p>Then it was quiet.</p></body></html>",
        )
        archive.writestr(
            "OEBPS/ch2.xhtml",
            "<html><body><h1>Chapter Two</h1><p>They sailed for weeks.</p>"
            "<p>Home was a small island.</p></body></html>",
        )


def test_read_epub_follows_the_spine(tmp_path):
    epub = tmp_path / "whale.epub"
    _make_epub(epub)

    book = read_book(epub)
    assert book.title == "The Test Whale"
    assert book.fmt == "epub"
    assert "The whale sang at dawn." in book.text
    assert book.text.index("Chapter One") < book.text.index("Chapter Two")
    assert book.chapters


def test_read_html(tmp_path):
    page = tmp_path / "page.html"
    page.write_text(
        "<html><head><title>A Page</title></head><body>"
        "<script>ignore()</script><p>Hello there.</p><p>Second line.</p>"
        "</body></html>"
    )
    book = read_book(page)
    assert book.title == "A Page"
    assert "Hello there." in book.text
    assert "ignore" not in book.text


def test_read_missing_file_raises():
    with pytest.raises(BookError):
        read_book("/nonexistent/nope.epub")


def test_describe_formats_lists_everything():
    formats = {f["format"]: f for f in describe_formats()}
    assert set(formats) == {"epub", "mobi", "pdf", "html", "url"}
    assert formats["epub"]["available"] is True


# ----------------------------------------------------------------------
# track requests
# ----------------------------------------------------------------------
def test_track_request_accepts_nested_and_flat_params():
    req = TrackRequest.from_dict(
        {"type": "generate", "kind": "music", "params": {"bpm": 90}, "duration": 30}
    )
    assert req.type == "generate"
    assert req.kind == "music"
    assert req.params["bpm"] == 90
    assert req.params["duration"] == 30


def test_track_request_keeps_explicit_params():
    req = TrackRequest.from_dict(
        {"type": "generate", "kind": "music", "params": {"bpm": 90}, "bpm": 120}
    )
    assert req.params["bpm"] == 90


def test_track_request_defaults():
    req = TrackRequest.from_dict({"type": "stream"})
    assert req.kind == ""
    assert req.params == {}
