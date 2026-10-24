"""Live integration test against the real Yoto API.

This exercises the whole pipeline the SDK depends on:

    upload -> transcode -> media id -> card write -> read back -> signed URL

It creates a scratch card and deletes it again, so it is safe to run against a
real account.  Run it with::

    python -m pytest tests/test_live.py -v

or directly::

    python tests/test_live.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from yoto import Yoto  # noqa: E402
from yoto.errors import ApiError  # noqa: E402

RUN_LIVE = os.environ.get("YOTO_LIVE_TESTS", "1") not in ("0", "false", "no")

pytestmark = pytest.mark.skipif(
    not RUN_LIVE, reason="set YOTO_LIVE_TESTS=1 to run against the real API"
)


def _make_audio(tmp: Path, seconds: int = 3) -> Path:
    """Render a short spoken test clip with macOS ``say`` + ffmpeg."""
    aiff = tmp / "clip.aiff"
    mp3 = tmp / "clip.mp3"
    text = "Yoto daily card integration test. One, two, three."

    say = subprocess.run(
        ["say", "-o", str(aiff), text], capture_output=True, check=False
    )
    if say.returncode == 0 and aiff.exists():
        subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error", "-i", str(aiff),
                "-c:a", "libmp3lame", "-b:a", "64k", str(mp3),
            ],
            capture_output=True,
            check=True,
        )
        return mp3

    # Fallback: a pure tone, so the test still runs without `say`.
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
            "-i", f"sine=frequency=440:duration={seconds}",
            "-c:a", "libmp3lame", "-b:a", "64k", str(mp3),
        ],
        capture_output=True,
        check=True,
    )
    return mp3


@pytest.fixture(scope="module")
def yoto():
    client = Yoto()
    client.cards.list()  # forces auth; fails loudly if the session is dead
    return client


def test_list_cards(yoto):
    cards = yoto.cards.list()
    assert cards, "expected at least one card on the account"
    assert all(c.card_id for c in cards)


def test_upload_transcode_and_write(yoto, tmp_path):
    """The full round trip: audio in, playable track on a card."""
    audio = _make_audio(tmp_path)

    scratch = yoto.cards.create(title="SDK Integration Scratch")
    scratch_id = scratch.card_id
    assert scratch_id

    try:
        upload = yoto.media.upload_audio(audio, title="SDK Test Clip")
        assert upload.media_id.startswith("yoto:#")
        assert upload.duration > 0, "transcode should report a duration"
        assert len(upload.transcoded_sha256) == 43, "media id is a 43-char sha256"

        track = yoto.cards.build_track(
            "01",
            "SDK Test Clip",
            upload.media_id,
            duration=upload.duration,
            file_size=upload.file_size,
            fmt=upload.format,
        )
        chapter = yoto.cards.build_chapter("00", "Integration", [track])
        content = yoto.cards.build_content([chapter])

        saved = yoto.cards.update_content(scratch_id, content, title="SDK Integration Scratch")
        assert saved.card_id == scratch_id

        fetched = yoto.cards.get(scratch_id)
        assert len(fetched.content.chapters) == 1
        got_track = fetched.content.chapters[0].tracks[0]
        assert got_track.title == "SDK Test Clip"
        assert got_track.track_url == upload.media_id
        # The server re-derives duration from the transcoded Opus file and may
        # round it differently than the transcode status did (Opus padding).
        # The persisted value is the server's.
        assert abs(got_track.duration - upload.duration) <= 2
        assert got_track.file_size > 0

        url = yoto.cards.media_url(scratch_id, upload.media_id_bare)
        assert url.startswith("https://")

        import requests

        resp = requests.get(url, timeout=60, stream=True)
        assert resp.status_code == 200, resp.text[:200]
        first_chunk = next(resp.iter_content(4096), b"")
        assert first_chunk, "media file was empty"
        resp.close()

    finally:
        yoto.cards.delete(scratch_id)

    assert not yoto.cards.exists(scratch_id), "scratch card should be gone"


def test_upload_rejects_missing_file(yoto):
    from yoto.errors import TranscodeError

    with pytest.raises((FileNotFoundError, TranscodeError)):
        yoto.media.upload_audio("/nonexistent/definitely-not-here.mp3")


def test_unknown_card_raises(yoto):
    from yoto.errors import NotFound

    with pytest.raises((NotFound, ApiError)):
        yoto.cards.get("zzzzz")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-s"]))
