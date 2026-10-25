"""The Ming-3.0-tts speech generator.

Reads text aloud in a cloned voice with the local Ming-3.0-tts checkpoint.
It is the only generator in the project that imports a model into the
service process, so everything heavy happens lazily: the checkpoint is only
fetched when a story is actually narrated, and it stays warm between calls.

Two things make this different from the other speech backends.

**The checkpoint is pulled on demand.** The inference code lives in the
Ming-3.0-tts GitHub checkout (``code_path``) and the weights live on the Hub
(``repo_id``). Point ``model_path`` at a local copy and nothing is
downloaded; leave it empty and the generator fetches the checkpoint into
``cache_dir`` the first time it is used.

**The voice is a recording, not a name.** ``reference_wav`` is a short clip
of the voice to clone and ``reference_text`` is the exact transcript of
that clip -- the model conditions on the words, so a summary will not do.
Several voices can be configured side by side and picked by name at request
time through the ``voice`` parameter, which is how the rest of the project
already talks about voices.

The model is small enough to run on a CPU (about three times slower than
realtime), so a local narration works on a machine with no GPU at all.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from .base import AudioResult, SpeechGenerator

#: Where the weights land when they have to be downloaded.
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "yotaiman" / "models"

#: The Hub repository holding the dense 0.5B checkpoint.
DEFAULT_REPO_ID = "inclusionAI/Ming-3.0-tts-0.5b"

#: One latent frame is this many seconds of audio. The checkpoint packs
#: ``patch_size`` frames of ``hop_size`` samples into one latent, so a decode
#: step is 80 ms, not 20 ms.
FRAMES_PER_SECOND = 12.5

#: The model caps one generation at this many positions, and the reference
#: clip, the transcript and the text all share them.
MAX_CACHE_LEN = 512

#: Positions spent on the instruction, the contract and the stop tokens.
PROMPT_OVERHEAD_TOKENS = 64

#: English narration pace, used to turn a frame budget into a word budget.
WORDS_PER_SECOND = 2.7

#: Leave some headroom so a fragment never overruns the budget.
SAFETY_MARGIN = 0.85


# ----------------------------------------------------------------------
# module level caches
# ----------------------------------------------------------------------
# The model and the encoded prompt are expensive to build and are reused by
# every request the service makes.

_MODEL_CACHE: dict[tuple, Any] = {}
_PROMPT_CACHE: dict[tuple, Any] = {}


def _project_root() -> Path:
    """The directory the service is installed from."""
    return Path(__file__).resolve().parents[2]


def _candidate_code_paths() -> list[Path]:
    """Where the Ming-3.0-tts inference code might live.

    The checkpoint on the Hub ships weights only, so the inference code has
    to come from the GitHub checkout. Sibling directories of this project are
    the usual place for it.
    """
    root = _project_root()
    candidates = [
        root.parent / "Ming-3.0-tts",
        root / "Ming-3.0-tts",
        Path.home() / "git-repos" / "Ming-3.0-tts",
    ]
    env = os.environ.get("YOTO_MING_TTS_CODE_PATH", "").strip()
    if env:
        candidates.insert(0, Path(env).expanduser())
    seen: list[Path] = []
    for candidate in candidates:
        if candidate not in seen:
            seen.append(candidate)
    return seen


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


class MingTTSSpeechGenerator(SpeechGenerator):
    """Narrates text in a cloned voice using Ming-3.0-tts."""

    type = "ming-tts"
    description = "Ming-3.0-tts with zero-shot voice cloning; local checkpoint."

    def __init__(
        self,
        name: str = "ming-tts",
        *,
        code_path: str = "",
        repo_id: str = DEFAULT_REPO_ID,
        model_path: str = "",
        cache_dir: str = "",
        auto_download: bool = True,
        device: str = "auto",
        reference_wav: str = "",
        reference_text: str = "",
        language_id: str = "English",
        instruction: str = "",
        use_spk_emb: bool = True,
        text_normalization: bool = False,
        ffmpeg_command: str = "ffmpeg",
        voice: str = "",
        voices: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.name = name
        self.code_path = code_path
        self.repo_id = repo_id
        self.model_path = model_path
        self.cache_dir = cache_dir
        self.auto_download = auto_download
        self.device = device
        self.reference_wav = reference_wav
        self.reference_text = reference_text
        self.language_id = language_id
        self.instruction = instruction
        self.use_spk_emb = use_spk_emb
        self.text_normalization = text_normalization
        self.ffmpeg_command = ffmpeg_command
        self.default_voice = voice
        self.voices = dict(voices or {})
        self.options = {
            "repo_id": repo_id,
            "model_path": model_path,
            "device": device,
            "language_id": language_id,
            "instruction": instruction,
            "use_spk_emb": use_spk_emb,
            "text_normalization": text_normalization,
            "auto_download": auto_download,
            "voices": sorted(self.voices) or ([self.default_voice] if self.default_voice else []),
        }

    # ------------------------------------------------------------------
    # configuration
    # ------------------------------------------------------------------
    def voice_config(self, voice: str = "") -> dict[str, Any]:
        """The settings for one voice.

        A named voice overrides the generator defaults, so one checkpoint can
        serve several voices with different clips and instructions.  The
        returned ``voice_name`` is the voice that will actually be used: a
        request for a name that is not configured falls back to the default
        rather than silently doing nothing.
        """
        chosen = voice or self.default_voice
        named = self.voices.get(chosen) if chosen else None
        config = {
            "reference_wav": self.reference_wav,
            "reference_text": self.reference_text,
            "instruction": self.instruction,
            "language_id": self.language_id,
        }
        if named:
            config.update({k: v for k, v in named.items() if v not in (None, "")})
        reference = str(config.get("reference_wav") or "")
        if reference:
            reference = str(self._resolve_path(reference))
            config["reference_wav"] = reference

        if named:
            effective = chosen
        elif self.default_voice in self.voices:
            effective = self.default_voice
        else:
            # One cloned voice, named after the clip it was made from.
            effective = Path(reference).stem if reference else ""
        config["voice_name"] = effective
        return config

    def _resolve_path(self, value: str) -> Path:
        """A configured path, relative ones taken from the project root."""
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = _project_root() / candidate
        return candidate

    def _resolved_code_path(self) -> Path | None:
        """The Ming-3.0-tts checkout, if it can be found."""
        if self.code_path:
            candidate = self._resolve_path(self.code_path)
            return candidate if (candidate / "ming_tts.py").exists() else None
        for candidate in _candidate_code_paths():
            if (candidate / "ming_tts.py").exists():
                return candidate
        return None

    def _resolved_model_path(self) -> Path | None:
        """The local checkpoint, if it is already on disk."""
        if self.model_path:
            candidate = self._resolve_path(self.model_path)
            if (candidate / "config.json").exists():
                return candidate
        target = Path(self.cache_dir or DEFAULT_CACHE_DIR).expanduser()
        candidate = target / self.repo_id.replace("/", "--")
        if (candidate / "config.json").exists():
            return candidate
        return None

    def _ensure_model_path(self) -> Path:
        """The checkpoint, downloading it when that is allowed."""
        existing = self._resolved_model_path()
        if existing is not None:
            return existing
        if not self.auto_download:
            raise RuntimeError(
                f"the Ming-3.0-tts checkpoint is not at {self.model_path or self.cache_dir} "
                f"and auto_download is off"
            )
        try:
            from huggingface_hub import snapshot_download
        except ImportError as exc:  # pragma: no cover - depends on the env
            raise RuntimeError(
                "huggingface_hub is needed to download the Ming-3.0-tts "
                "checkpoint; install it or set model_path"
            ) from exc

        target = Path(self.cache_dir or DEFAULT_CACHE_DIR).expanduser()
        target = target / self.repo_id.replace("/", "--")
        target.mkdir(parents=True, exist_ok=True)
        print(f"[ming-tts] pulling {self.repo_id} into {target} ...")
        snapshot_download(repo_id=self.repo_id, local_dir=str(target))
        return target

    def _resolve_device(self) -> str:
        if self.device and self.device.lower() != "auto":
            return self.device
        try:
            import torch
        except ImportError:
            return "cpu"
        if torch.cuda.is_available():
            return "cuda:0"
        return "cpu"

    # ------------------------------------------------------------------
    # availability
    # ------------------------------------------------------------------
    def available(self) -> bool:
        """Whether this generator can be used right now.

        The check stays cheap on purpose: it must not download a checkpoint
        just to answer a listing request.
        """
        if self._resolved_code_path() is None:
            return False
        config = self.voice_config()
        reference = str(config.get("reference_wav") or "")
        if not reference or not Path(reference).expanduser().exists():
            return False
        try:
            import torch  # noqa: F401
        except ImportError:
            return False
        if self._resolved_model_path() is None and not self.auto_download:
            return False
        return True

    def detail(self) -> str:
        if self._resolved_code_path() is None:
            return (
                "the Ming-3.0-tts checkout was not found; set code_path or "
                "YOTO_MING_TTS_CODE_PATH"
            )
        config = self.voice_config()
        reference = str(config.get("reference_wav") or "")
        if not reference:
            return "no reference_wav is configured"
        if not Path(reference).expanduser().exists():
            # The path itself is not echoed: this note is shown to whoever
            # asks the service about its generators.
            return "the reference clip does not exist"
        model = self._resolved_model_path()
        if model is None:
            return f"the checkpoint will be pulled from {self.repo_id} on first use"
        return f"the checkpoint is in place, cloning {Path(reference).name}"

    # ------------------------------------------------------------------
    # model plumbing
    # ------------------------------------------------------------------
    def _import_model(self):
        """Import the Ming-3.0-tts inference code."""
        code_path = self._resolved_code_path()
        if code_path is None:
            raise RuntimeError(
                "the Ming-3.0-tts checkout was not found; set code_path or "
                "YOTO_MING_TTS_CODE_PATH"
            )
        entry = str(code_path)
        if entry not in sys.path:
            sys.path.insert(0, entry)
        from ming_tts import MingTTS

        return MingTTS

    def _load_model(self):
        """The loaded model, keyed by the things that change it."""
        code_path = self._resolved_code_path()
        model_path = self._ensure_model_path()
        device = self._resolve_device()
        key = (str(code_path), str(model_path), device)
        cached = _MODEL_CACHE.get(key)
        if cached is not None:
            return cached

        MingTTS = self._import_model()
        print(f"[ming-tts] loading {model_path} on {device} ...")
        model = MingTTS(
            str(model_path),
            device=device,
            text_normalization=self.text_normalization,
        )
        _MODEL_CACHE[key] = model
        return model

    def _prompt(self, model, config: dict[str, Any]):
        """The encoded reference clip, keyed by the clip that produced it."""
        reference = str(config.get("reference_wav") or "")
        key = (id(model), reference, bool(self.use_spk_emb))
        cached = _PROMPT_CACHE.get(key)
        if cached is not None:
            return cached
        prompt_latent, spk_emb = model.prepare_prompt(
            reference, use_spk_emb=bool(self.use_spk_emb)
        )
        _PROMPT_CACHE[key] = (prompt_latent, spk_emb)
        return prompt_latent, spk_emb

    def _frames_per_second(self, model) -> float:
        audio = model.model.config.audio_tokenizer_config
        return audio.sample_rate / (audio.enc_kwargs["hop_size"] * audio.patch_size)

    def _fragment_budget(self, model, prompt_latent, reference_text: str) -> int:
        """How many words one generation may speak."""
        fps = self._frames_per_second(model)
        prompt_frames = int(prompt_latent.shape[1])
        tokens = len(model.model.tokenizer(reference_text or "")["input_ids"])
        budget = max(32, MAX_CACHE_LEN - prompt_frames - tokens - PROMPT_OVERHEAD_TOKENS)
        seconds = budget / fps
        return max(4, int(seconds * WORDS_PER_SECOND * SAFETY_MARGIN))

    def _split_text(self, text: str, max_length: int) -> list[str]:
        """Split the text into fragments that fit one generation.

        The split happens on clause boundaries so a fragment never ends
        mid-sentence, and the fragments are normalized the same way the
        model normalizes them internally.
        """
        from frontend.text_segment_cut import cut_text_by_semantic_length
        from frontend.toolkit import add_period, normalize_text_kit, preprosess_text

        fragments = cut_text_by_semantic_length(
            add_period(preprosess_text(text)), max_length
        )["fragments"]
        prepared = []
        for fragment in fragments:
            fragment = fragment.strip()
            if fragment:
                prepared.append(normalize_text_kit(fragment))
        return prepared or [text.strip()]

    # ------------------------------------------------------------------
    # synthesis
    # ------------------------------------------------------------------
    def synthesize(
        self,
        text: str,
        out_path: Path,
        *,
        voice: str = "",
        instruction: str = "",
    ) -> AudioResult:
        text = (text or "").strip()
        if not text:
            raise RuntimeError("there is no text to read")

        config = self.voice_config(voice)
        reference_wav = str(config.get("reference_wav") or "")
        reference_text = str(config.get("reference_text") or "")
        language_id = str(config.get("language_id") or self.language_id)

        # A request may ask for a different delivery than the configured
        # default; the voice itself stays the same.
        delivery = (instruction or "").strip() or str(config.get("instruction") or "")

        if not reference_wav:
            raise RuntimeError(
                "ming-tts clones a voice, so it needs a reference_wav; "
                "configure one or pick another speech generator"
            )
        if not reference_text:
            raise RuntimeError(
                "the reference clip needs its exact transcript in "
                "reference_text; the model conditions on the words"
            )

        model = self._load_model()
        prompt_latent, spk_emb = self._prompt(model, config)
        max_length = self._fragment_budget(model, prompt_latent, reference_text)
        fragments = self._split_text(text, max_length)

        task = "FREEFORM" if delivery else "TTS"
        sample_rate = model.sample_rate
        chunks = []
        for fragment in fragments:
            waveform = model.synthesize(
                task=task,
                text=fragment,
                language_id=language_id,
                instruction=delivery or None,
                prompt_wav_path=reference_wav,
                prompt_text=reference_text,
                use_spk_emb=bool(self.use_spk_emb),
                max_length=max_length,
                raw_text=True,
            )
            chunks.append(waveform.detach().cpu().float())

        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        if out_path.suffix.lower() == ".wav":
            self._write_wav(out_path, chunks, sample_rate)
        else:
            with tempfile.TemporaryDirectory() as tmp:
                wav_path = Path(tmp) / "speech.wav"
                self._write_wav(wav_path, chunks, sample_rate)
                proc = subprocess.run(
                    [
                        self.ffmpeg_command, "-y", "-loglevel", "error",
                        "-i", str(wav_path),
                        "-ac", "1", "-ar", "44100",
                        "-c:a", "libmp3lame", "-b:a", "64k",
                        str(out_path),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=1800,
                )
                if proc.returncode != 0:
                    raise RuntimeError(
                        f"ffmpeg failed: {(proc.stderr or proc.stdout)[:300]}"
                    )

        return AudioResult(
            path=out_path,
            duration=_probe_duration(out_path, self.ffmpeg_command),
            voice=str(config.get("voice_name") or ""),
            backend=self.name,
            metadata={
                "fragments": len(fragments),
                "task": task,
                "instruction": delivery,
            },
        )

    def _write_wav(self, path: Path, chunks: list, sample_rate: int) -> None:
        """Join the fragments into one waveform with a short pause between."""
        import torch

        gap = torch.zeros(1, int(0.12 * sample_rate), dtype=torch.float32)
        pieces = []
        for index, chunk in enumerate(chunks):
            if index:
                pieces.append(gap)
            pieces.append(chunk)
        waveform = torch.cat(pieces, dim=-1)

        import soundfile as sf

        sf.write(str(path), waveform.squeeze(0).numpy(), sample_rate)


def build_ming_tts_generator(name: str, entry: dict[str, Any]) -> MingTTSSpeechGenerator:
    """Build the generator from one ``config.yaml`` entry."""
    return MingTTSSpeechGenerator(
        name,
        code_path=str(entry.get("code_path") or ""),
        repo_id=str(entry.get("repo_id") or DEFAULT_REPO_ID),
        model_path=str(entry.get("model_path") or ""),
        cache_dir=str(entry.get("cache_dir") or ""),
        auto_download=bool(entry.get("auto_download", True)),
        device=str(entry.get("device") or "auto"),
        reference_wav=str(entry.get("reference_wav") or ""),
        reference_text=str(entry.get("reference_text") or ""),
        language_id=str(entry.get("language_id") or "English"),
        instruction=str(entry.get("instruction") or ""),
        use_spk_emb=bool(entry.get("use_spk_emb", True)),
        text_normalization=bool(entry.get("text_normalization", False)),
        ffmpeg_command=str(entry.get("ffmpeg_command") or "ffmpeg"),
        voice=str(entry.get("voice") or ""),
        voices=dict(entry.get("voices") or {}),
    )


__all__ = [
    "MingTTSSpeechGenerator",
    "build_ming_tts_generator",
    "DEFAULT_REPO_ID",
]
