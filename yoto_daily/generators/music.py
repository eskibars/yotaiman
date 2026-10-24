"""Music generators.

:class:`AceStepMusicGenerator` talks to a local ACE-Step 1.5 API server.
That server is asynchronous -- it queues a task, then polls for the result --
so the generator implements that dance:

    POST /release_task   -> task_id
    POST /query_result   -> status (0 running, 1 done, 2 failed)
    GET  /v1/audio?path= -> the audio bytes

:class:`SynthMusicGenerator` is a procedural fallback that needs no model at
all.  It is not music in any meaningful sense, but it renders a real audio
file of the requested length, which keeps the whole pipeline exercisable when
no model server is running.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from .base import AudioResult, MusicGenerator, MusicSpec


class AceStepMusicGenerator(MusicGenerator):
    """A local ACE-Step 1.5 API server."""

    type = "ace-step"
    description = "Local ACE-Step 1.5 music generation server."

    def __init__(
        self,
        name: str,
        *,
        endpoint: str = "http://127.0.0.1:8001",
        api_key: str = "",
        model: str = "",
        timeout: float = 900.0,
        poll_interval: float = 5.0,
        defaults: dict[str, Any] | None = None,
    ) -> None:
        self.name = name
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.defaults = defaults or {}
        self.options = {
            "endpoint": self.endpoint,
            "model": self.model,
            "timeout": self.timeout,
            **self.defaults,
        }

    # ------------------------------------------------------------------
    def available(self) -> bool:
        import requests

        try:
            resp = requests.get(f"{self.endpoint}/health", timeout=5)
            return resp.status_code < 500
        except Exception:
            return False

    def detail(self) -> str:
        if self.available():
            return f"reachable at {self.endpoint}"
        return f"no response from {self.endpoint}"

    # ------------------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _unwrap(self, payload: dict[str, Any]) -> Any:
        """ACE-Step wraps every response in ``{data, code, error, ...}``."""
        if isinstance(payload, dict) and "data" in payload:
            if payload.get("error"):
                raise RuntimeError(f"ACE-Step error: {payload['error']}")
            return payload["data"]
        return payload

    def build_payload(self, spec: MusicSpec) -> dict[str, Any]:
        """Turn a :class:`MusicSpec` into an ACE-Step request body."""
        payload: dict[str, Any] = dict(self.defaults)

        prompt = spec.to_prompt()
        if prompt:
            payload["prompt"] = prompt
        if spec.lyrics:
            payload["lyrics"] = spec.lyrics
        if spec.bpm is not None:
            payload["bpm"] = spec.bpm
        if spec.key_scale:
            payload["key_scale"] = spec.key_scale
        if spec.time_signature:
            payload["time_signature"] = spec.time_signature
        if spec.duration:
            payload["audio_duration"] = spec.duration
        if spec.instrumental:
            payload["instrumental"] = True
        if spec.seed is not None:
            payload["seed"] = spec.seed
            payload["use_random_seed"] = False
        if self.model:
            payload.setdefault("model", self.model)

        payload.update(spec.extra)
        return payload

    # ------------------------------------------------------------------
    def generate(self, spec: MusicSpec, out_path: Path) -> AudioResult:
        import requests

        payload = self.build_payload(spec)
        resp = requests.post(
            f"{self.endpoint}/release_task",
            data=json.dumps(payload),
            headers=self._headers(),
            timeout=60,
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                f"ACE-Step release_task failed: HTTP {resp.status_code} {resp.text[:200]}"
            )
        data = self._unwrap(resp.json())
        task_id = data.get("task_id")
        if not task_id:
            raise RuntimeError(f"ACE-Step returned no task_id: {resp.text[:200]}")

        result = self._wait(task_id)
        audio_path = self._download(result, out_path)
        return AudioResult(
            path=audio_path,
            backend=self.name,
            metadata={
                "task_id": task_id,
                "prompt": payload.get("prompt", ""),
                "metas": result.get("metas", {}),
                "seed_value": result.get("seed_value", ""),
                "dit_model": result.get("dit_model", ""),
                "lm_model": result.get("lm_model", ""),
                "generation_info": result.get("generation_info", ""),
            },
        )

    def _wait(self, task_id: str) -> dict[str, Any]:
        """Poll ``/query_result`` until the task succeeds or fails."""
        import requests

        deadline = time.time() + self.timeout
        last: dict[str, Any] = {}
        while time.time() < deadline:
            resp = requests.post(
                f"{self.endpoint}/query_result",
                data=json.dumps({"task_id_list": [task_id]}),
                headers=self._headers(),
                timeout=60,
            )
            if resp.status_code >= 400:
                raise RuntimeError(
                    f"ACE-Step query_result failed: HTTP {resp.status_code} {resp.text[:200]}"
                )
            entries = self._unwrap(resp.json()) or []
            if not entries:
                time.sleep(self.poll_interval)
                continue

            entry = entries[0]
            status = entry.get("status")
            if status == 2:
                raise RuntimeError(f"ACE-Step task {task_id} failed")
            if status == 1:
                raw = entry.get("result")
                if isinstance(raw, str):
                    try:
                        raw = json.loads(raw)
                    except json.JSONDecodeError:
                        pass
                if isinstance(raw, list) and raw:
                    last = raw[0]
                    return last
                raise RuntimeError(f"ACE-Step returned an empty result for {task_id}")

            time.sleep(self.poll_interval)

        raise RuntimeError(
            f"ACE-Step task {task_id} did not finish within {self.timeout:.0f}s"
        )

    def _download(self, result: dict[str, Any], out_path: Path) -> Path:
        """Fetch the generated audio and write it to ``out_path``."""
        import requests
        from urllib.parse import quote

        file_ref = result.get("file") or ""
        if not file_ref:
            raise RuntimeError("ACE-Step result contained no file reference")

        if file_ref.startswith("http"):
            url = file_ref
        else:
            # The server returns either a bare path or "/v1/audio?path=...".
            if file_ref.startswith("/v1/audio"):
                url = f"{self.endpoint}{file_ref}"
            else:
                url = f"{self.endpoint}/v1/audio?path={quote(file_ref, safe='')}"

        resp = requests.get(url, headers=self._headers(), timeout=300)
        if resp.status_code >= 400:
            raise RuntimeError(
                f"ACE-Step audio download failed: HTTP {resp.status_code} {resp.text[:200]}"
            )

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(resp.content)
        return out_path


class SynthMusicGenerator(MusicGenerator):
    """A procedural placeholder that renders a silent-ish tone bed.

    This is not a music model.  It exists so the track pipeline can be
    exercised end to end -- upload, transcode, publish -- without a GPU.
    """

    type = "synth"
    description = "Procedural tone generator; no model required."

    def __init__(
        self,
        name: str,
        *,
        ffmpeg_command: str = "ffmpeg",
        base_frequency: float = 220.0,
    ) -> None:
        self.name = name
        self.ffmpeg_command = ffmpeg_command
        self.base_frequency = base_frequency
        self.options = {"base_frequency": base_frequency}

    def available(self) -> bool:
        return bool(shutil.which(self.ffmpeg_command))

    def detail(self) -> str:
        return "uses ffmpeg; no model required" if self.available() else "ffmpeg not on PATH"

    def generate(self, spec: MusicSpec, out_path: Path) -> AudioResult:
        if not self.available():
            raise RuntimeError(f"{self.ffmpeg_command} is not on PATH")

        duration = max(1, int(spec.duration or 30))
        bpm = spec.bpm or 90
        beat = 60.0 / bpm
        # A simple arpeggio built from sine partials, so the result is
        # recognisably audio rather than silence.
        scale = [0, 2, 4, 7, 9, 12]
        notes: list[str] = []
        for index in range(max(1, int(duration / beat))):
            semitone = scale[index % len(scale)]
            freq = self.base_frequency * (2 ** (semitone / 12))
            notes.append(f"sine=frequency={freq:.2f}:duration={beat:.3f}")

        out_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            stem = Path(tmp) / "synth"
            cmd = [self.ffmpeg_command, "-y", "-loglevel", "error"]
            for note in notes:
                cmd += ["-f", "lavfi", "-i", note]
            graph = "".join(f"[{i}:a]" for i in range(len(notes)))
            graph += f"concat=n={len(notes)}:v=0:a=1[out]"
            cmd += [
                "-filter_complex", graph,
                "-map", "[out]",
                "-ac", "2", "-ar", "44100",
                "-c:a", "libmp3lame", "-b:a", "128k",
                str(stem) + ".mp3",
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if proc.returncode != 0:
                raise RuntimeError(f"ffmpeg failed: {(proc.stderr or proc.stdout)[:300]}")
            shutil.copyfile(str(stem) + ".mp3", out_path)

        return AudioResult(
            path=out_path,
            duration=float(duration),
            backend=self.name,
            metadata={"bpm": bpm, "notes": len(notes), "synthetic": True},
        )
