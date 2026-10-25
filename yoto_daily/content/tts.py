"""Text-to-speech backends.

The Yoto transcoder accepts many audio formats, so the only hard requirement
is that the backend produces a file the transcoder can read.

``say`` is the default because macOS ships it: it needs no API key, has
dozens of voices, and is fast enough for a daily job.  The HTTP backend is
there for when a cloud voice is preferred.

``say`` only exists on macOS.  On Windows and Linux, enable one of the other
backends -- ``ming-tts``, a local model server or a hosted voice -- or
:func:`build_tts_backend` raises rather than narrating with nothing.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class AudioResult:
    """A rendered narration."""

    path: Path
    duration: float = 0.0
    voice: str = ""
    backend: str = ""


class TTSBackend(ABC):
    """Turns text into an audio file."""

    name = "base"

    @abstractmethod
    def synthesize(
        self,
        text: str,
        out_path: Path,
        *,
        voice: str = "",
        instruction: str = "",
    ) -> AudioResult:
        """Render ``text`` into ``out_path``.

        ``instruction`` describes the delivery and overrides whatever the
        backend was configured with.
        """

    def available(self) -> bool:
        return True

    def describe(self) -> dict[str, Any]:
        return {"backend": self.name, "available": self.available()}


class MacSayBackend(TTSBackend):
    """macOS ``say`` followed by an ffmpeg conversion to MP3.

    ``say`` writes AIFF natively; ffmpeg turns that into a small mono MP3,
    which is what the Yoto transcoder wants.
    """

    name = "say"

    def __init__(self, say_command: str = "say", ffmpeg_command: str = "ffmpeg") -> None:
        self.say_command = say_command
        self.ffmpeg_command = ffmpeg_command

    def available(self) -> bool:
        return bool(shutil.which(self.say_command))

    def synthesize(
        self,
        text: str,
        out_path: Path,
        *,
        voice: str = "",
        instruction: str = "",
    ) -> AudioResult:
        if not self.available():
            raise RuntimeError(f"{self.say_command} is not on PATH")

        out_path.parent.mkdir(parents=True, exist_ok=True)
        aiff = out_path.with_suffix(".aiff")

        # The text goes in a file rather than on the command line, so that a
        # caller who controls it cannot make `say` treat it as one of its
        # own options.  The file has a name of its own, so two requests
        # narrating at once do not tread on each other.
        with tempfile.NamedTemporaryFile(
            suffix=".say.txt", delete=False, dir=str(out_path.parent)
        ) as handle:
            handle.write(text.encode("utf-8"))
        script = Path(handle.name)

        cmd = [self.say_command, "-o", str(aiff)]
        if voice:
            cmd += ["-v", voice]
        cmd += ["-f", str(script)]

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        finally:
            script.unlink(missing_ok=True)
        if proc.returncode != 0:
            raise RuntimeError(f"say failed: {(proc.stderr or proc.stdout)[:300]}")
        if not aiff.exists():
            raise RuntimeError("say produced no audio file")

        proc = subprocess.run(
            [
                self.ffmpeg_command, "-y", "-loglevel", "error",
                "-i", str(aiff),
                "-ac", "1", "-ar", "44100",
                "-c:a", "libmp3lame", "-b:a", "64k",
                str(out_path),
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {(proc.stderr or proc.stdout)[:300]}")
        aiff.unlink(missing_ok=True)

        return AudioResult(
            path=out_path,
            duration=_probe_duration(out_path, self.ffmpeg_command),
            voice=voice,
            backend=self.name,
        )


class HTTPVoiceBackend(TTSBackend):
    """Calls an HTTP endpoint that returns an audio file.

    The request is a JSON POST with ``{"text": ..., "voice": ...}`` and the
    response body is the audio bytes.  That shape covers most hosted TTS
    providers after a thin adapter.
    """

    name = "http"

    def __init__(self, url: str, *, api_key: str = "", timeout: float = 120.0) -> None:
        self.url = url
        self.api_key = api_key
        self.timeout = timeout

    def available(self) -> bool:
        return bool(self.url)

    def synthesize(
        self,
        text: str,
        out_path: Path,
        *,
        voice: str = "",
        instruction: str = "",
    ) -> AudioResult:
        import json

        import requests

        if not self.url:
            raise RuntimeError(
                "no HTTP TTS endpoint is configured; set the url option or "
                "generators.speech.options.<name>.url"
            )

        out_path.parent.mkdir(parents=True, exist_ok=True)
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload: dict[str, Any] = {"text": text, "voice": voice}
        if instruction:
            payload["instruction"] = instruction

        resp = requests.post(
            self.url,
            data=json.dumps(payload),
            headers=headers,
            timeout=self.timeout,
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"tts endpoint returned HTTP {resp.status_code}: {resp.text[:200]}")
        out_path.write_bytes(resp.content)
        return AudioResult(
            path=out_path,
            duration=_probe_duration(out_path),
            voice=voice,
            backend=self.name,
        )


class MingTTSBackend(TTSBackend):
    """Narrates with the Ming-3.0-tts checkpoint and a cloned voice.

    The heavy lifting lives in the speech generator; this is the thin
    adapter the capabilities speak to.  The generator keeps the model warm
    between calls, so the second story of the day costs nothing extra to
    load.
    """

    name = "ming-tts"

    def __init__(self, generator: Any) -> None:
        self.generator = generator

    def available(self) -> bool:
        try:
            return bool(self.generator.available())
        except Exception:
            return False

    def synthesize(
        self,
        text: str,
        out_path: Path,
        *,
        voice: str = "",
        instruction: str = "",
    ) -> AudioResult:
        result = self.generator.synthesize(
            text, out_path, voice=voice, instruction=instruction
        )
        return AudioResult(
            path=result.path,
            duration=result.duration,
            voice=result.voice,
            backend=result.backend,
        )

    def describe(self) -> dict[str, Any]:
        info = {"backend": self.name, "available": self.available()}
        try:
            info["detail"] = self.generator.detail()
        except Exception:
            info["detail"] = ""
        return info


def _probe_duration(path: Path, ffmpeg_command: str = "ffmpeg") -> float:
    """Best-effort duration of an audio file in seconds."""
    proc = subprocess.run(
        [
            ffmpeg_command, "-i", str(path), "-f", "null", "-",
        ],
        capture_output=True,
        text=True,
    )
    text = proc.stderr or ""
    marker = "time="
    if marker in text:
        tail = text.rsplit(marker, 1)[1].split(" ", 1)[0]
        try:
            hours, minutes, seconds = tail.split(":")
            return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        except (ValueError, IndexError):
            pass
    return 0.0


def build_tts_backend(
    *,
    prefer: str = "auto",
    say_command: str = "say",
    ffmpeg_command: str = "ffmpeg",
    http_url: str = "",
    http_api_key: str = "",
    ming_options: dict[str, Any] | None = None,
) -> TTSBackend:
    """Pick a TTS backend."""
    if prefer == "ming-tts":
        from ..generators.ming_tts import build_ming_tts_generator

        return MingTTSBackend(build_ming_tts_generator("ming-tts", dict(ming_options or {})))
    if prefer == "http" and http_url:
        return HTTPVoiceBackend(http_url, api_key=http_api_key)
    say = MacSayBackend(say_command, ffmpeg_command)
    if prefer == "say":
        return say
    if say.available():
        return say
    if http_url:
        return HTTPVoiceBackend(http_url, api_key=http_api_key)
    raise RuntimeError(
        "no TTS backend is available: macOS `say` is not on PATH and no HTTP "
        "endpoint is configured. Enable a speech generator in config.yaml "
        "(ming-tts, local-model or hosted) or point YOTO_TTS_BACKEND at one."
    )
