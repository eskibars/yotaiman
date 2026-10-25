"""Live test for the Ming-3.0-tts speech generator.

This renders a real story with the real checkpoint and a real reference
clip, so it needs the whole runtime in place.  It is skipped unless
everything is there:

    * the Ming-3.0-tts checkout (``YOTO_MING_TTS_CODE_PATH`` or a sibling
      directory of this project)
    * the checkpoint (``YOTO_MING_TTS_MODEL_PATH``, or the one inside the
      checkout)
    * a reference clip and its transcript (``YOTO_MING_TTS_REFERENCE_WAV``
      and ``YOTO_MING_TTS_REFERENCE_TEXT``)

Run it with::

    python -m pytest tests/test_live_ming_tts.py -v

The clip and its transcript are what a user has to record; a short clip of
clean speech and the exact words in it.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from yoto_daily.generators import build_registry  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent

STORY = (
    "The lantern was still warm when Tomas reached the dock. "
    "His sister had a dry coat ready, and the lake was quiet again."
)


def _code_path() -> Path | None:
    env = os.environ.get("YOTO_MING_TTS_CODE_PATH", "").strip()
    candidates = [Path(env)] if env else []
    candidates += [
        PROJECT_ROOT.parent / "Ming-3.0-tts",
        PROJECT_ROOT / "Ming-3.0-tts",
        Path.home() / "git-repos" / "Ming-3.0-tts",
    ]
    for candidate in candidates:
        if (candidate / "ming_tts.py").exists():
            return candidate
    return None


def _model_path(code_path: Path | None) -> Path | None:
    env = os.environ.get("YOTO_MING_TTS_MODEL_PATH", "").strip()
    if env:
        candidate = Path(env)
        if (candidate / "config.json").exists():
            return candidate
    if code_path is not None:
        candidate = code_path / "models" / "Ming-3.0-tts-0.5b"
        if (candidate / "config.json").exists():
            return candidate
    return None


def _reference() -> tuple[Path | None, str]:
    env = os.environ.get("YOTO_MING_TTS_REFERENCE_WAV", "").strip()
    text = os.environ.get("YOTO_MING_TTS_REFERENCE_TEXT", "").strip()
    if not env:
        return None, ""
    path = Path(env)
    return (path if path.exists() else None), text


CODE_PATH = _code_path()
MODEL_PATH = _model_path(CODE_PATH)
REFERENCE_WAV, REFERENCE_TEXT = _reference()

pytestmark = pytest.mark.skipif(
    CODE_PATH is None or MODEL_PATH is None or not REFERENCE_WAV or not REFERENCE_TEXT,
    reason=(
        "the Ming-3.0-tts runtime is not in place; set "
        "YOTO_MING_TTS_CODE_PATH, YOTO_MING_TTS_MODEL_PATH, "
        "YOTO_MING_TTS_REFERENCE_WAV and YOTO_MING_TTS_REFERENCE_TEXT"
    ),
)


def _registry() -> dict:
    return {
        "generators": {
            "speech": {
                "default": "voice",
                "options": {
                    "voice": {
                        "type": "ming-tts",
                        "code_path": str(CODE_PATH),
                        "model_path": str(MODEL_PATH),
                        "reference_wav": str(REFERENCE_WAV),
                        "reference_text": REFERENCE_TEXT,
                        "language_id": "English",
                        "device": "cpu",
                        "auto_download": False,
                    }
                },
            }
        }
    }


def test_the_generator_is_available_and_reports_the_checkpoint():
    generator = build_registry(_registry()).get_speech()
    assert generator.type == "ming-tts"
    assert generator.available() is True
    assert "checkpoint at" in generator.detail()


def test_it_narrates_a_story(tmp_path):
    generator = build_registry(_registry()).get_speech()
    out = tmp_path / "story.mp3"

    started = time.time()
    result = generator.synthesize(STORY, out)
    elapsed = time.time() - started

    assert out.exists()
    assert out.stat().st_size > 1000
    assert result.duration > 1.0
    assert result.backend == "voice"
    assert result.metadata["fragments"] >= 1
    print(
        f"\nrendered {result.duration:.1f}s of audio in {elapsed:.1f}s "
        f"({elapsed / result.duration:.1f}x realtime)"
    )


def test_a_request_can_change_the_delivery(tmp_path):
    """The request instruction replaces the configured one."""
    generator = build_registry(_registry()).get_speech()

    plain = generator.synthesize(STORY, tmp_path / "plain.mp3")
    assert plain.metadata["instruction"] == ""
    assert plain.metadata["task"] == "TTS"

    warm = generator.synthesize(
        STORY,
        tmp_path / "warm.mp3",
        instruction="Speak in a warm, intimate storytelling voice, unhurried.",
    )
    assert warm.metadata["task"] == "FREEFORM"
    assert "storytelling" in warm.metadata["instruction"]
    assert warm.duration > 1.0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
