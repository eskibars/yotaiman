"""Speech generators.

:class:`SaySpeechGenerator` uses macOS ``say``, which needs no credentials and
ships with dozens of voices.

:class:`HTTPSpeechGenerator` covers the other two shapes: a local
model server (Kokoro, MLX-Audio, a fine-tuned endpoint) and a hosted service.
Both speak the same tiny protocol -- POST JSON ``{"text": ..., "voice": ...}``,
receive audio bytes back -- so one implementation serves both.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .base import AudioResult, SpeechGenerator


def _probe_duration(path: Path, ffmpeg_command: str = "ffmpeg") -> float:
    """Best-effort duration of an audio file in seconds."""
    proc = subprocess.run(
        [ffmpeg_command, "-i", str(path), "-f", "null", "-"],
        capture_output=True,
        text=True,
    )
    text = proc.stderr or ""
    if "time=" in text:
        tail = text.rsplit("time=", 1)[1].split(" ", 1)[0]
        try:
            hours, minutes, seconds = tail.split(":")
            return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        except (ValueError, IndexError):
            pass
    return 0.0


class SaySpeechGenerator(SpeechGenerator):
    """macOS ``say`` followed by an ffmpeg conversion to MP3."""

    type = "say"
    description = "macOS say; no credentials required."

    def __init__(
        self,
        name: str = "say",
        *,
        say_command: str = "say",
        ffmpeg_command: str = "ffmpeg",
        voice: str = "",
        rate: int = 0,
    ) -> None:
        self.name = name
        self.say_command = say_command
        self.ffmpeg_command = ffmpeg_command
        self.voice = voice
        self.rate = rate
        self.options = {
            "voice": voice,
            "rate": rate,
            "say_command": say_command,
        }

    def available(self) -> bool:
        return bool(shutil.which(self.say_command))

    def detail(self) -> str:
        if not self.available():
            return f"{self.say_command} is not on PATH"
        return f"voice {self.voice or '(system default)'}"

    def synthesize(self, text: str, out_path: Path, *, voice: str = "") -> AudioResult:
        if not self.available():
            raise RuntimeError(f"{self.say_command} is not on PATH")

        out_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            aiff = Path(tmp) / "speech.aiff"
            cmd = [self.say_command, "-o", str(aiff)]
            chosen = voice or self.voice
            if chosen:
                cmd += ["-v", chosen]
            if self.rate:
                cmd += ["-r", str(self.rate)]
            cmd.append(text)

            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
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
                timeout=600,
            )
            if proc.returncode != 0:
                raise RuntimeError(f"ffmpeg failed: {(proc.stderr or proc.stdout)[:300]}")

        return AudioResult(
            path=out_path,
            duration=_probe_duration(out_path, self.ffmpeg_command),
            voice=chosen,
            backend=self.name,
        )


class HTTPSpeechGenerator(SpeechGenerator):
    """A speech endpoint that returns audio bytes.

    Works for a local model server and for a hosted service alike.  The URL
    may contain ``{voice}`` and ``{text}`` placeholders; otherwise the text
    and voice go in the JSON body.
    """

    type = "http"
    description = "HTTP speech endpoint; local model server or hosted API."

    def __init__(
        self,
        name: str,
        *,
        url: str,
        api_key: str = "",
        voice: str = "",
        headers: dict[str, str] | None = None,
        timeout: float = 300.0,
        response_format: str = "",
        ffmpeg_command: str = "ffmpeg",
    ) -> None:
        self.name = name
        self.url = url
        self.api_key = api_key
        self.voice = voice
        self.headers = headers or {}
        self.timeout = timeout
        self.response_format = response_format
        self.ffmpeg_command = ffmpeg_command
        self.options = {
            "url": url,
            "voice": voice,
            "timeout": timeout,
            **({"response_format": response_format} if response_format else {}),
        }

    def available(self) -> bool:
        import requests

        if not self.url:
            return False
        try:
            resp = requests.get(self.url, timeout=5, stream=True)
            resp.close()
            return resp.status_code < 500
        except Exception:
            return False

    def detail(self) -> str:
        return f"HTTP endpoint at {self.url}"

    def synthesize(self, text: str, out_path: Path, *, voice: str = "") -> AudioResult:
        import json

        import requests

        if not self.url:
            raise RuntimeError(f"{self.name} has no endpoint configured")

        chosen = voice or self.voice
        headers = {"Content-Type": "application/json", **self.headers}
        if self.api_key:
            headers.setdefault("Authorization", f"Bearer {self.api_key}")

        url = self.url
        body: dict[str, Any] = {"text": text, "voice": chosen, "input": text}
        if "{voice}" in url:
            url = url.replace("{voice}", chosen)
        if "{text}" in url:
            url = url.replace("{text}", requests.utils.quote(text))
            body = {}
        if self.response_format:
            body["response_format"] = self.response_format

        resp = requests.post(
            url,
            data=json.dumps(body) if body else None,
            headers=headers,
            timeout=self.timeout,
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                f"speech endpoint returned HTTP {resp.status_code}: {resp.text[:200]}"
            )

        content_type = resp.headers.get("Content-Type", "")
        if content_type.startswith("application/json"):
            payload = resp.json()
            audio_b64 = payload.get("audio") or payload.get("data") or ""
            if not audio_b64:
                raise RuntimeError(f"speech endpoint returned no audio: {str(payload)[:200]}")
            import base64

            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(base64.b64decode(audio_b64))
        else:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(resp.content)

        return AudioResult(
            path=out_path,
            duration=_probe_duration(out_path, self.ffmpeg_command),
            voice=chosen,
            backend=self.name,
        )
