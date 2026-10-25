"""Offline tests for the platform-sensitive parts of the project.

Chrome DevTools discovery, the generator lookup and the ``.env`` loader all
behave differently depending on the machine they run on.  None of these need
a running Chrome, and none touch the Yoto API.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from yoto import _cdp, _env  # noqa: E402
from yoto_daily.generators.base import (  # noqa: E402
    AudioResult,
    MusicGenerator,
    SpeechGenerator,
)
from yoto_daily.generators.registry import (  # noqa: E402
    GeneratorError,
    GeneratorRegistry,
)


# ----------------------------------------------------------------------
# DevToolsActivePort
# ----------------------------------------------------------------------
def test_read_active_port_parses_port_and_target(tmp_path):
    path = tmp_path / "DevToolsActivePort"
    path.write_text("9222\n/devtools/browser/13bb552f-2765-46b0-9c86\n")
    assert _cdp.read_active_port(path) == (
        9222,
        "/devtools/browser/13bb552f-2765-46b0-9c86",
    )


def test_read_active_port_rejects_garbage(tmp_path):
    missing = tmp_path / "nope"
    assert _cdp.read_active_port(missing) is None

    empty = tmp_path / "empty"
    empty.write_text("")
    assert _cdp.read_active_port(empty) is None

    bad_port = tmp_path / "bad"
    bad_port.write_text("not-a-port\n/devtools/browser/x\n")
    assert _cdp.read_active_port(bad_port) is None

    no_target = tmp_path / "no-target"
    no_target.write_text("9222\n")
    assert _cdp.read_active_port(no_target) is None


def test_candidate_urls_prefer_the_active_port_file(tmp_path, monkeypatch):
    """A browser started through chrome://inspect has no /json/version."""
    profile = tmp_path / "User Data"
    profile.mkdir()
    (profile / "DevToolsActivePort").write_text(
        "9222\n/devtools/browser/13bb552f-2765-46b0-9c86\n"
    )
    monkeypatch.setattr(_cdp, "chrome_user_data_dirs", lambda: [profile])
    monkeypatch.setattr(_cdp, "_http_json", lambda *a, **k: None)

    urls = _cdp.candidate_ws_urls(9222)
    assert "ws://127.0.0.1:9222/devtools/browser/13bb552f-2765-46b0-9c86" in urls
    # The bare path is the last resort.
    assert urls[-1] == "ws://127.0.0.1:9222/devtools/browser"


def test_candidate_urls_prefer_http_discovery_when_available(tmp_path, monkeypatch):
    monkeypatch.setattr(_cdp, "chrome_user_data_dirs", lambda: [])
    monkeypatch.setattr(
        _cdp,
        "_http_json",
        lambda *a, **k: {"webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser/abc"},
    )
    urls = _cdp.candidate_ws_urls(9222)
    assert urls[0] == "ws://127.0.0.1:9222/devtools/browser/abc"


def test_candidate_urls_fall_back_to_another_port(tmp_path, monkeypatch):
    """Chrome may pick its own port; the file says which one."""
    profile = tmp_path / "User Data"
    profile.mkdir()
    (profile / "DevToolsActivePort").write_text("9333\n/devtools/browser/xyz\n")
    monkeypatch.setattr(_cdp, "chrome_user_data_dirs", lambda: [profile])
    monkeypatch.setattr(_cdp, "_http_json", lambda *a, **k: None)

    urls = _cdp.candidate_ws_urls(9222)
    assert "ws://127.0.0.1:9333/devtools/browser/xyz" in urls


def test_launch_hint_explains_the_way_in():
    hint = _cdp.chrome_launch_hint(9222)
    assert "chrome://inspect/#remote-debugging" in hint
    assert "9222" in hint


# ----------------------------------------------------------------------
# generator lookup
# ----------------------------------------------------------------------
class _FakeSpeech(SpeechGenerator):
    def __init__(self, name, *, ready=True):
        self.name = name
        self.type = "fake"
        self._ready = ready

    def available(self):
        return self._ready

    def detail(self):
        return "ready" if self._ready else "not installed"

    def synthesize(self, text, out_path, *, voice="", instruction=""):
        return AudioResult(path=out_path, backend=self.name)


class _FakeMusic(MusicGenerator):
    def __init__(self, name, *, ready=True):
        self.name = name
        self.type = "fake"
        self._ready = ready

    def available(self):
        return self._ready

    def detail(self):
        return "ready" if self._ready else "not installed"

    def generate(self, spec, out_path):
        return AudioResult(path=out_path, backend=self.name)


def test_default_speech_falls_back_when_it_cannot_run():
    """A config written on macOS points at `say`, which is not on Windows."""
    registry = GeneratorRegistry(
        speech=[_FakeSpeech("say", ready=False), _FakeSpeech("other", ready=True)],
        default_speech="say",
    )
    assert registry.pick_speech().name == "other"


def test_default_speech_is_used_when_it_can_run():
    registry = GeneratorRegistry(
        speech=[_FakeSpeech("say", ready=True), _FakeSpeech("other", ready=True)],
        default_speech="say",
    )
    assert registry.pick_speech().name == "say"


def test_lookup_returns_the_default_even_when_it_cannot_run():
    """Lookup is for inspecting a generator; it must not raise."""
    registry = GeneratorRegistry(
        speech=[_FakeSpeech("say", ready=False)],
        default_speech="say",
    )
    generator = registry.get_speech()
    assert generator.name == "say"
    assert generator.available() is False
    assert generator.detail() == "not installed"


def test_explicit_speech_choice_is_honoured():
    """An explicit request is never silently swapped out."""
    registry = GeneratorRegistry(
        speech=[_FakeSpeech("say", ready=False), _FakeSpeech("other", ready=True)],
        default_speech="say",
    )
    assert registry.pick_speech("say").name == "say"


def test_unknown_generator_name_is_an_error():
    registry = GeneratorRegistry(speech=[_FakeSpeech("say")], default_speech="say")
    with pytest.raises(GeneratorError):
        registry.get_speech("nope")


def test_no_usable_generator_explains_why():
    registry = GeneratorRegistry(
        speech=[_FakeSpeech("say", ready=False)],
        default_speech="say",
    )
    with pytest.raises(GeneratorError) as excinfo:
        registry.pick_speech()
    assert "say" in str(excinfo.value)


def test_music_default_falls_back_too():
    registry = GeneratorRegistry(
        music=[_FakeMusic("ace-step", ready=False), _FakeMusic("synth", ready=True)],
        default_music="ace-step",
    )
    assert registry.pick_music().name == "synth"


# ----------------------------------------------------------------------
# .env
# ----------------------------------------------------------------------
def test_env_file_is_loaded(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("YOTO_TEST_VALUE=from-the-file\n")
    monkeypatch.setattr(_env, "_PROJECT_ENV", env)
    monkeypatch.setattr(_env, "_loaded", False)
    monkeypatch.delenv("YOTO_TEST_VALUE", raising=False)
    try:
        assert _env.load_env_files() is True
        assert os.environ["YOTO_TEST_VALUE"] == "from-the-file"
    finally:
        os.environ.pop("YOTO_TEST_VALUE", None)


def test_the_environment_wins_over_the_file(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("YOTO_TEST_VALUE=from-the-file\n")
    monkeypatch.setattr(_env, "_PROJECT_ENV", env)
    monkeypatch.setattr(_env, "_loaded", False)
    monkeypatch.setenv("YOTO_TEST_VALUE", "from-the-shell")
    _env.load_env_files()
    assert os.environ["YOTO_TEST_VALUE"] == "from-the-shell"
