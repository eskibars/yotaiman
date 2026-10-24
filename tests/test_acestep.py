"""Tests for the ACE-Step client against a stub that speaks its protocol.

The real ACE-Step server needs a GPU, so these tests drive the client against
a small local HTTP server that reproduces ACE-Step's exact wire format:
the ``{data, code, error, timestamp, extra}`` wrapper, the asynchronous
release/query/download dance, and the fact that ``result`` comes back as a
JSON *string*.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from yoto_daily.generators.music import AceStepMusicGenerator  # noqa: E402
from yoto_daily.generators.base import MusicSpec  # noqa: E402


def _wrapper(data, code: int = 200, error=None) -> dict:
    return {
        "data": data,
        "code": code,
        "error": error,
        "timestamp": 1700000000000,
        "extra": None,
    }


class StubHandler(BaseHTTPRequestHandler):
    """Speaks just enough ACE-Step to exercise the client."""

    state = {"polls": 0, "released": None, "task_id": "stub-task-1"}

    def log_message(self, *args):  # noqa: D102 - silence the test output
        pass

    def _json(self, payload, status: int = 200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/health"):
            self._json(_wrapper({"status": "ok", "service": "ACE-Step API"}))
            return
        if self.path.startswith("/v1/audio"):
            # Return a tiny real mp3 so the download path is exercised.
            source = Path(__file__).resolve().parent.parent / "tests" / "_stub_audio.bin"
            if source.exists():
                body = source.read_bytes()
            else:
                body = b"ID3\x03\x00\x00\x00\x00\x00\x00stub"
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._json(_wrapper(None, 404, "not found"), 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {}

        if self.path.startswith("/release_task"):
            self.state["released"] = payload
            self._json(
                _wrapper(
                    {
                        "task_id": self.state["task_id"],
                        "status": "queued",
                        "queue_position": 1,
                    }
                )
            )
            return

        if self.path.startswith("/query_result"):
            self.state["polls"] += 1
            # Report running twice, then succeed.
            if self.state["polls"] < 3:
                self._json(_wrapper([{"task_id": self.state["task_id"], "status": 0}]))
                return
            result = [
                {
                    "file": "/v1/audio?path=%2Ftmp%2Fstub.mp3",
                    "wave": "",
                    "status": 1,
                    "create_time": 1700000000,
                    "env": "development",
                    "prompt": "gentle solo piano",
                    "lyrics": "",
                    "metas": {"bpm": 80, "duration": 30, "keyscale": "C Major"},
                    "generation_info": "stub",
                    "seed_value": "12345",
                    "lm_model": "",
                    "dit_model": "acestep-v15-turbo",
                }
            ]
            self._json(
                _wrapper(
                    [
                        {
                            "task_id": self.state["task_id"],
                            "status": 1,
                            # ACE-Step returns the result as a JSON string.
                            "result": json.dumps(result),
                        }
                    ]
                )
            )
            return

        self._json(_wrapper(None, 404, "not found"), 404)


@pytest.fixture(scope="module")
def stub_server():
    StubHandler.state = {"polls": 0, "released": None, "task_id": "stub-task-1"}
    server = HTTPServer(("127.0.0.1", 0), StubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_generator_reports_available(stub_server):
    gen = AceStepMusicGenerator("stub", endpoint=stub_server)
    assert gen.available() is True
    assert "reachable" in gen.detail()


def test_generator_reports_unavailable_when_down():
    gen = AceStepMusicGenerator("stub", endpoint="http://127.0.0.1:9")
    assert gen.available() is False
    assert "no response" in gen.detail()


def test_build_payload_maps_structured_metadata(stub_server):
    gen = AceStepMusicGenerator("stub", endpoint=stub_server, model="acestep-v15-turbo")
    spec = MusicSpec.from_dict(
        {
            "prompt": "gentle solo piano",
            "bpm": 80,
            "key_scale": "C Major",
            "time_signature": "4",
            "duration": 30,
            "tags": ["calm"],
        }
    )
    payload = gen.build_payload(spec)

    assert payload["prompt"] == "gentle solo piano, calm"
    assert payload["bpm"] == 80
    assert payload["key_scale"] == "C Major"
    assert payload["time_signature"] == "4"
    assert payload["audio_duration"] == 30
    assert payload["model"] == "acestep-v15-turbo"


def test_generate_walks_the_whole_protocol(stub_server, tmp_path):
    gen = AceStepMusicGenerator(
        "stub", endpoint=stub_server, poll_interval=0.05, timeout=30
    )
    spec = MusicSpec(
        prompt="gentle solo piano",
        duration=30,
        bpm=80,
        key_scale="C Major",
        time_signature="4",
    )

    result = gen.generate(spec, tmp_path / "music.mp3")

    assert result.path.exists()
    assert result.path.read_bytes().startswith((b"ID3", b"stub"))
    assert result.metadata["task_id"] == "stub-task-1"
    assert result.metadata["metas"]["bpm"] == 80
    assert result.metadata["dit_model"] == "acestep-v15-turbo"

    # The client must have sent the structured metadata, not just a prompt.
    released = StubHandler.state["released"]
    assert released["bpm"] == 80
    assert released["key_scale"] == "C Major"
    assert released["audio_duration"] == 30


def test_failed_task_raises(stub_server, tmp_path, monkeypatch):
    gen = AceStepMusicGenerator(
        "stub", endpoint=stub_server, poll_interval=0.05, timeout=10
    )

    original_do_post = StubHandler.do_POST

    # Make the stub report a failed task.
    def failing_do_post(self):
        if self.path.startswith("/query_result"):
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                self.rfile.read(length)
            self._json(_wrapper([{"task_id": "stub-task-1", "status": 2}]))
            return
        original_do_post(self)

    monkeypatch.setattr(StubHandler, "do_POST", failing_do_post)

    with pytest.raises(RuntimeError, match="failed"):
        gen.generate(MusicSpec(prompt="x"), tmp_path / "out.mp3")


def test_synth_generator_renders_audio(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not available")

    from yoto_daily.generators.music import SynthMusicGenerator

    gen = SynthMusicGenerator("synth")
    assert gen.available() is True

    out = tmp_path / "tone.mp3"
    result = gen.generate(MusicSpec(prompt="test", duration=4, bpm=120), out)

    assert out.exists()
    assert out.stat().st_size > 1000
    assert result.duration == 4
    assert result.metadata["synthetic"] is True


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-s"]))
