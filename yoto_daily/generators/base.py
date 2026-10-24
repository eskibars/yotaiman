"""The generator abstraction.

Two families of generator produce the audio that goes on a card:

* **music** -- takes a :class:`MusicSpec` (structured metadata, not just a
  prompt) and renders an instrumental.
* **speech** -- takes text and reads it aloud.

Both are configured in ``config.yaml`` and selected by name at request time,
so swapping a local model for a hosted service is a configuration change
rather than a code change.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AudioResult:
    """A rendered audio file."""

    path: Path
    duration: float = 0.0
    voice: str = ""
    backend: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class GeneratorInfo:
    """What a generator is and whether it can be used right now."""

    name: str
    kind: str
    type: str
    description: str = ""
    available: bool = False
    is_default: bool = False
    options: dict[str, Any] = field(default_factory=dict)
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "type": self.type,
            "description": self.description,
            "available": self.available,
            "is_default": self.is_default,
            "options": self.options,
            "detail": self.detail,
        }


@dataclass
class MusicSpec:
    """Structured metadata for a piece of music.

    ACE-Step and friends take a free-text prompt, but a caller usually knows
    the pieces separately: a tempo, a key, instruments, a mood.  This keeps
    those structured and lets each backend decide how to render them.
    """

    prompt: str = ""
    lyrics: str = ""
    bpm: int | None = None
    key_scale: str = ""
    time_signature: str = ""
    duration: int = 60
    instrumental: bool = True
    tags: list[str] = field(default_factory=list)
    seed: int | None = None
    #: Backend-specific pass-through parameters.
    extra: dict[str, Any] = field(default_factory=dict)

    def to_prompt(self) -> str:
        """Render the structured fields into a caption.

        The base implementation is a plain sentence; backends that understand
        tags override this.
        """
        parts = [self.prompt.strip()] if self.prompt.strip() else []
        if self.tags:
            parts.append(", ".join(self.tags))
        return ", ".join(p for p in parts if p)

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt": self.prompt,
            "lyrics": self.lyrics,
            "bpm": self.bpm,
            "key_scale": self.key_scale,
            "time_signature": self.time_signature,
            "duration": self.duration,
            "instrumental": self.instrumental,
            "tags": list(self.tags),
            "seed": self.seed,
            "extra": dict(self.extra),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MusicSpec":
        known = {
            "prompt", "lyrics", "bpm", "key_scale", "keyscale", "key",
            "time_signature", "timesignature", "duration", "instrumental",
            "tags", "seed",
        }
        extra = {k: v for k, v in data.items() if k not in known}
        return cls(
            prompt=str(data.get("prompt") or data.get("caption") or ""),
            lyrics=str(data.get("lyrics") or ""),
            bpm=data.get("bpm"),
            key_scale=str(
                data.get("key_scale") or data.get("keyscale") or data.get("key") or ""
            ),
            time_signature=str(
                data.get("time_signature") or data.get("timesignature") or ""
            ),
            duration=int(data.get("duration") or 60),
            instrumental=bool(data.get("instrumental", True)),
            tags=list(data.get("tags") or []),
            seed=data.get("seed"),
            extra=extra,
        )


class Generator(ABC):
    """Base class for music and speech generators."""

    #: The configured name of this generator.
    name: str = ""
    #: ``music`` or ``speech``.
    kind: str = ""
    #: The implementation family, e.g. ``ace-step``, ``say``, ``http``.
    type: str = ""
    description: str = ""
    #: Options echoed back by the listing endpoint.
    options: dict[str, Any] = field(default_factory=dict)

    @abstractmethod
    def available(self) -> bool:
        """Whether this generator can be used right now."""

    def detail(self) -> str:
        """A short note about availability, shown in the listing."""
        return ""

    def info(self, *, is_default: bool = False) -> GeneratorInfo:
        return GeneratorInfo(
            name=self.name,
            kind=self.kind,
            type=self.type,
            description=self.description,
            available=self.available(),
            is_default=is_default,
            options=dict(self.options),
            detail=self.detail(),
        )

    def to_dict(self, *, is_default: bool = False) -> dict[str, Any]:
        return self.info(is_default=is_default).to_dict()


class MusicGenerator(Generator):
    """Renders instrumental music from structured metadata."""

    kind = "music"

    @abstractmethod
    def generate(self, spec: MusicSpec, out_path: Path) -> AudioResult:
        """Render ``spec`` into an audio file at ``out_path``."""


class SpeechGenerator(Generator):
    """Reads text aloud."""

    kind = "speech"

    @abstractmethod
    def synthesize(self, text: str, out_path: Path, *, voice: str = "") -> AudioResult:
        """Render ``text`` into an audio file at ``out_path``."""


def parse_speech_result(payload: bytes, out_path: Path, backend: str) -> AudioResult:
    """Write raw audio bytes to disk and describe the result."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(payload)
    return AudioResult(path=out_path, backend=backend)


def safe_json(value: Any) -> str:
    """Compact JSON, for log lines."""
    try:
        return json.dumps(value, default=str)[:500]
    except (TypeError, ValueError):
        return str(value)[:500]
