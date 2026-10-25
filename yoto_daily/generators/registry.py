"""The generator registry.

Reads the ``generators`` section of ``config.yaml`` and builds the generator
objects the API exposes under ``/api/generators``.

Configuration shape::

    generators:
      music:
        default: ace-step-local
        options:
          ace-step-local:
            type: ace-step
            enabled: true
            endpoint: http://127.0.0.1:8001
            api_key_env: ACESTEP_API_KEY
            defaults:
              inference_steps: 8
      speech:
        default: say
        options:
          say:
            type: say
            enabled: true
            voice: Karen
          ming-tts:
            type: ming-tts
            enabled: false
            code_path: ../Ming-3.0-tts
            reference_wav: ~/yotaiman/my_voice.wav
            reference_text: "the exact words spoken in the clip"
"""

from __future__ import annotations

import os
from typing import Any, TypeVar

from .base import Generator, MusicGenerator, MusicSpec, SpeechGenerator
from .ming_tts import MingTTSSpeechGenerator, build_ming_tts_generator
from .music import AceStepMusicGenerator, SynthMusicGenerator
from .speech import HTTPSpeechGenerator, SaySpeechGenerator

#: Either kind of generator, for the shared lookup helper.
_G = TypeVar("_G", bound=Generator)


class GeneratorError(RuntimeError):
    """Raised when a requested generator does not exist or cannot be used."""


class GeneratorRegistry:
    """Holds the configured music and speech generators."""

    def __init__(
        self,
        *,
        music: list[MusicGenerator] | None = None,
        speech: list[SpeechGenerator] | None = None,
        default_music: str = "",
        default_speech: str = "",
    ) -> None:
        self._music = list(music or [])
        self._speech = list(speech or [])
        self.default_music_name = default_music
        self.default_speech_name = default_speech

    # ------------------------------------------------------------------
    # lookup
    # ------------------------------------------------------------------
    def music_generators(self) -> list[MusicGenerator]:
        return list(self._music)

    def speech_generators(self) -> list[SpeechGenerator]:
        return list(self._speech)

    def get_music(self, name: str | None = None) -> MusicGenerator:
        """Look a music generator up.

        Without a name this is the configured default, whatever its
        availability -- callers use this to inspect a generator.  Use
        :meth:`pick_music` when the generator is about to render something.
        """
        return self._pick(self._music, name, self.default_music_name, "music")

    def get_speech(self, name: str | None = None) -> SpeechGenerator:
        """Look a speech generator up.

        Without a name this is the configured default, whatever its
        availability -- callers use this to inspect a generator.  Use
        :meth:`pick_speech` when the generator is about to narrate something.
        """
        return self._pick(self._speech, name, self.default_speech_name, "speech")

    def pick_music(self, name: str | None = None) -> MusicGenerator:
        """The music generator to actually render with.

        An explicit name is honoured exactly.  Without one the configured
        default is used when it can run, and otherwise the first generator
        that can -- a config written on macOS points at ACE-Step, which needs
        a local server that is not always up.
        """
        return self._pick(self._music, name, self.default_music_name, "music", usable=True)

    def pick_speech(self, name: str | None = None) -> SpeechGenerator:
        """The speech generator to actually narrate with.

        An explicit name is honoured exactly.  Without one the configured
        default is used when it can run, and otherwise the first generator
        that can -- a config written on macOS points at ``say``, which does
        not exist on Windows or Linux.
        """
        return self._pick(self._speech, name, self.default_speech_name, "speech", usable=True)

    @staticmethod
    def _pick(
        generators: list[_G],
        name: str | None,
        default: str,
        kind: str,
        *,
        usable: bool = False,
    ) -> _G:
        """Choose a generator.

        With ``usable`` the choice has to be one that can run right now;
        without it the configured default is returned even when it cannot,
        so a caller can look at it and ask why.
        """
        if not generators:
            raise GeneratorError(f"no {kind} generators are configured")

        if name:
            for gen in generators:
                if gen.name == name:
                    return gen
            raise GeneratorError(
                f"unknown {kind} generator {name!r}; "
                f"available: {', '.join(g.name for g in generators)}"
            )

        wanted = default or generators[0].name
        chosen = next((g for g in generators if g.name == wanted), None)
        if chosen is None:
            chosen = generators[0]

        if not usable:
            return chosen
        if chosen.available():
            return chosen

        for gen in generators:
            if gen.available():
                return gen

        details = "; ".join(f"{g.name}: {g.detail() or 'not available'}" for g in generators)
        raise GeneratorError(
            f"no usable {kind} generator ({details}). Enable one of the others "
            f"in config.yaml, or set generators.{kind}.default to one that works."
        )

    # ------------------------------------------------------------------
    # listings
    # ------------------------------------------------------------------
    def music_info(self) -> dict[str, Any]:
        default = self.default_music_name or (self._music[0].name if self._music else "")
        return {
            "kind": "music",
            "default": default,
            "generators": [
                g.to_dict(is_default=(g.name == default)) for g in self._music
            ],
        }

    def speech_info(self) -> dict[str, Any]:
        default = self.default_speech_name or (self._speech[0].name if self._speech else "")
        return {
            "kind": "speech",
            "default": default,
            "generators": [
                g.to_dict(is_default=(g.name == default)) for g in self._speech
            ],
        }

    def info(self) -> dict[str, Any]:
        return {"music": self.music_info(), "speech": self.speech_info()}


# ----------------------------------------------------------------------
# construction
# ----------------------------------------------------------------------
def _api_key(entry: dict[str, Any]) -> str:
    """Resolve an API key from the entry or from a named environment variable."""
    key = str(entry.get("api_key") or "")
    if key:
        return key
    env_name = entry.get("api_key_env")
    if env_name:
        return os.environ.get(str(env_name), "")
    return ""


def _build_music(name: str, entry: dict[str, Any]) -> MusicGenerator | None:
    kind = str(entry.get("type") or "").lower()

    if kind == "ace-step":
        return AceStepMusicGenerator(
            name,
            endpoint=str(entry.get("endpoint") or "http://127.0.0.1:8001"),
            api_key=_api_key(entry),
            model=str(entry.get("model") or ""),
            timeout=float(entry.get("timeout") or 900),
            poll_interval=float(entry.get("poll_interval") or 5),
            defaults=dict(entry.get("defaults") or {}),
        )
    if kind == "synth":
        return SynthMusicGenerator(
            name,
            ffmpeg_command=str(entry.get("ffmpeg_command") or "ffmpeg"),
            base_frequency=float(entry.get("base_frequency") or 220.0),
        )
    return None


def _build_speech(name: str, entry: dict[str, Any]) -> SpeechGenerator | None:
    kind = str(entry.get("type") or "").lower()

    if kind == "say":
        return SaySpeechGenerator(
            name,
            say_command=str(entry.get("say_command") or "say"),
            ffmpeg_command=str(entry.get("ffmpeg_command") or "ffmpeg"),
            voice=str(entry.get("voice") or ""),
            rate=int(entry.get("rate") or 0),
        )
    if kind == "http":
        return HTTPSpeechGenerator(
            name,
            url=str(entry.get("url") or ""),
            api_key=_api_key(entry),
            voice=str(entry.get("voice") or ""),
            headers=dict(entry.get("headers") or {}),
            timeout=float(entry.get("timeout") or 300),
            response_format=str(entry.get("response_format") or ""),
            ffmpeg_command=str(entry.get("ffmpeg_command") or "ffmpeg"),
        )
    if kind == "ming-tts":
        return build_ming_tts_generator(name, entry)
    return None


def build_registry(config: dict[str, Any] | None) -> GeneratorRegistry:
    """Build a registry from the ``generators`` section of a config file."""
    generators = (config or {}).get("generators") or {}

    music_cfg = generators.get("music") or {}
    speech_cfg = generators.get("speech") or {}

    music: list[MusicGenerator] = []
    for name, entry in (music_cfg.get("options") or {}).items():
        if not isinstance(entry, dict):
            continue
        if entry.get("enabled") is False:
            continue
        built = _build_music(str(name), entry)
        if built is not None:
            music.append(built)

    speech: list[SpeechGenerator] = []
    for name, entry in (speech_cfg.get("options") or {}).items():
        if not isinstance(entry, dict):
            continue
        if entry.get("enabled") is False:
            continue
        built = _build_speech(str(name), entry)
        if built is not None:
            speech.append(built)

    return GeneratorRegistry(
        music=music,
        speech=speech,
        default_music=str(music_cfg.get("default") or ""),
        default_speech=str(speech_cfg.get("default") or ""),
    )


def default_registry() -> GeneratorRegistry:
    """A registry that works with no configuration at all.

    The procedural synth for music and macOS ``say`` for speech, so the API
    is never empty even before ``config.yaml`` is written.  ``say`` only runs
    on macOS; elsewhere it stays listed but reports itself as unavailable,
    and the lookup falls back to any generator that does work.
    """
    return GeneratorRegistry(
        music=[SynthMusicGenerator("synth")],
        speech=[SaySpeechGenerator("say", voice="Karen")],
        default_music="synth",
        default_speech="say",
    )


__all__ = [
    "GeneratorError",
    "GeneratorRegistry",
    "MusicSpec",
    "build_registry",
    "default_registry",
]
