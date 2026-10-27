"""Turning a long recording into a clip a voice model can actually use.

Ming-3.0-tts conditions on a reference clip and its exact transcript, and it
shares one 512-position budget between the clip, the transcript and the words
it has to speak.  A clip that is too long does not merely sound worse: it
eats the budget, and what is left is enough for a handful of words.

So the recording a person actually makes -- a minute and a half of them
reading a script -- has to be cut down to a clip the model can carry, and the
transcript has to be cut to match that clip exactly.

:func:`prepare_reference` does that.  It transcribes the recording with word
timings, picks a window of speech in the right length range, and writes the
trimmed clip next to the words that were said in it.

The words come from the transcript the person already has, not from the
speech recogniser, whenever one is supplied.  The recogniser only supplies
the *timings*; the spelling, the punctuation and the capitalisation are the
author's own.  A model that conditions on a mis-heard word reproduces the
mis-heard word.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: The range a reference clip should fall in.  Below three seconds the voice
#: is not described well enough; above eight it starts eating the budget.
MIN_SECONDS = 3.0
MAX_SECONDS = 8.0

#: A pause longer than this inside a clip is a sign the clip is stitched
#: together from separate sentences, which the model hears as a jump.
MAX_PAUSE = 0.7


@dataclass
class Word:
    """One word, and when it was said."""

    text: str
    start: float
    end: float

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass
class Window:
    """The stretch of the recording that was chosen."""

    start: float
    end: float
    words: list[Word] = field(default_factory=list)
    score: float = 0.0

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words).strip()

    def describe(self) -> str:
        return (
            f"{self.start:.2f}s to {self.end:.2f}s "
            f"({self.duration:.1f}s, {len(self.words)} words)"
        )


@dataclass
class Reference:
    """What :func:`prepare_reference` produced."""

    wav: Path
    text: Path
    window: Window
    transcript_source: str = "speech-recognition"
    model: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "wav": str(self.wav),
            "text": str(self.text),
            "start": round(self.window.start, 3),
            "end": round(self.window.end, 3),
            "duration": round(self.window.duration, 2),
            "words": len(self.window.words),
            "transcript_source": self.transcript_source,
            "model": self.model,
            "notes": self.notes,
            "text_content": self.text.read_text(encoding="utf-8").strip()
            if self.text.exists()
            else "",
        }


#: The sample rate the speech recogniser wants.
TARGET_SAMPLE_RATE = 16000


def load_audio(path: Path | str, *, sample_rate: int = TARGET_SAMPLE_RATE):
    """A recording as mono float32 at the sample rate the recogniser wants.

    The audio is decoded here rather than handed to the recogniser as a
    file, because the recogniser's own file decoding goes through PyAV,
    whose interface changes between releases.  ``soundfile`` is already a
    dependency of the project and does the same job without that.
    """
    import numpy as np
    import soundfile as sf

    data, rate = sf.read(str(path), dtype="float32", always_2d=True)
    if data.ndim > 1:
        # ``always_2d`` hands back (samples, channels), so a mono file
        # arrives as (samples, 1) and has to be flattened as well.
        data = data.mean(axis=1)

    if rate != sample_rate:
        data = _resample(data, rate, sample_rate)

    return np.ascontiguousarray(data, dtype="float32")


def _resample(data, rate: int, target: int):
    """Resample mono audio to another rate."""
    import numpy as np

    try:
        import torch
        import torchaudio

        # torchaudio wants a batch dimension, even for one signal.
        tensor = torch.from_numpy(data).unsqueeze(0)
        moved = torchaudio.functional.resample(tensor, rate, target)
        return moved.squeeze(0).numpy().astype("float32")
    except ImportError:
        # Linear interpolation.  Good enough for speech, and it keeps the
        # tool working on a machine without torch.
        frames = int(round(len(data) * target / rate))
        if frames <= 0:
            return data
        positions = np.linspace(0, len(data) - 1, frames)
        return np.interp(positions, np.arange(len(data)), data).astype("float32")


# ----------------------------------------------------------------------
# speech recognition
# ----------------------------------------------------------------------
def transcribe_words(
    wav: Path | str,
    *,
    model_size: str = "small.en",
    device: str = "auto",
    compute_type: str = "int8",
) -> list[Word]:
    """Transcribe a recording, with a time for every word.

    The recogniser is only here to say *when* things were said.  Its
    spelling is thrown away in favour of the author's own words.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:  # pragma: no cover - depends on the env
        raise RuntimeError(
            "faster-whisper is needed to find the words in a recording; "
            "install it with 'pip install faster-whisper'"
        ) from exc

    if device == "auto":
        device = "cpu"

    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    audio = load_audio(wav)
    segments, _ = model.transcribe(
        audio,
        word_timestamps=True,
        vad_filter=True,
        beam_size=5,
    )

    words: list[Word] = []
    for segment in segments:
        for word in segment.words or []:
            text = (word.word or "").strip()
            if text:
                words.append(
                    Word(text=text, start=float(word.start), end=float(word.end))
                )
    if not words:
        raise RuntimeError(f"no speech was found in {wav}")
    return words


# ----------------------------------------------------------------------
# choosing the window
# ----------------------------------------------------------------------
def pick_window(
    words: list[Word],
    *,
    min_seconds: float = MIN_SECONDS,
    max_seconds: float = MAX_SECONDS,
) -> Window:
    """Choose the stretch of speech to use as the reference.

    The best stretch is not simply the longest one.  It is a stretch that
    starts at the beginning of a sentence, runs without a long pause, and
    is long enough to describe a voice without eating the model's budget.
    """
    if not words:
        raise ValueError("there are no words to choose from")

    best: Window | None = None

    for start_index in range(len(words)):
        start = words[start_index]
        for end_index in range(start_index, len(words)):
            end = words[end_index]
            duration = end.end - start.start
            if duration > max_seconds:
                break
            if duration < min_seconds:
                continue

            span = words[start_index : end_index + 1]
            score = _score(span, start_index)
            if best is None or score > best.score:
                best = Window(
                    start=start.start,
                    end=end.end,
                    words=list(span),
                    score=score,
                )

    if best is None:
        # Nothing long enough: take what there is and let the caller decide.
        span = words
        return Window(
            start=span[0].start,
            end=span[-1].end,
            words=list(span),
            score=0.0,
        )
    return best


def _score(span: list[Word], start_index: int) -> float:
    """How good a stretch of speech is as a reference clip."""
    if not span:
        return 0.0

    score = float(len(span))

    # A pause inside the clip means the clip is really several sentences
    # stitched together.
    for previous, current in zip(span, span[1:]):
        gap = current.start - previous.end
        if gap > MAX_PAUSE:
            score -= gap * 10

    # Starting at the beginning of a sentence is much better than starting
    # in the middle of one.
    first = span[0].text.strip("\"'()[]")
    if first and first[0].isupper():
        score += 6

    # Very short words at the edges are usually half-swallowed.
    if len(span[0].text) <= 2:
        score -= 3
    if len(span[-1].text) <= 2:
        score -= 3

    # A window that starts near the very beginning of the recording often
    # has a click or a held breath in front of it.
    if start_index == 0:
        score -= 2

    return score


# ----------------------------------------------------------------------
# recovering the author's own words
# ----------------------------------------------------------------------
def _normalise(word: str) -> str:
    return re.sub(r"[^a-z0-9']", "", word.lower())


def slice_transcript(transcript: str, window: Window) -> tuple[str, float]:
    """The part of the author's transcript that was said in the window.

    The speech recogniser gives the timings; the author gives the words.
    The two are lined up, and the author's words are returned for the
    stretch that matches -- so spelling, punctuation and capitalisation are
    the ones the author wrote.

    The second value is how much of the window the alignment covered; a low
    number means the recogniser and the author disagree, and the caller
    should not trust the slice.
    """
    author_words = transcript.split()
    if not author_words:
        return "", 0.0

    recognised = [_normalise(w.text) for w in window.words]
    written = [_normalise(w) for w in author_words]

    matcher = difflib.SequenceMatcher(None, recognised, written, autojunk=False)
    low: int | None = None
    high: int | None = None
    matched = 0

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "equal":
            continue
        matched += i2 - i1
        if low is None or j1 < low:
            low = j1
        if high is None or j2 > high:
            high = j2

    if low is None:
        return "", 0.0

    coverage = matched / max(1, len(recognised))
    return " ".join(author_words[low:high]).strip(), coverage


def _expand_to_sentences(words: list[str], low: int, high: int) -> tuple[int, int]:
    """Grow a span out to the nearest sentence edges."""
    start = low
    while start > 0 and not re.search(r"[.!?]$", words[start - 1]):
        start -= 1
    end = high
    while end < len(words) and not re.search(r"[.!?]$", words[end - 1]):
        end += 1
    return start, end


# ----------------------------------------------------------------------
# cutting the audio
# ----------------------------------------------------------------------
def cut_audio(
    source: Path | str,
    target: Path | str,
    start: float,
    end: float,
    *,
    sample_rate: int = 0,
) -> Path:
    """Write the stretch of a recording between two timestamps.

    The clip starts and ends on a word, with no silence at either end: the
    model continues from the tail of the prompt, so trailing quiet would be
    what it carried into the first syllable it spoke.
    """
    import soundfile as sf

    source = Path(source)
    target = Path(target)

    waveform, rate = sf.read(str(source), always_2d=True)
    if waveform.ndim > 1:
        waveform = waveform.mean(axis=1)

    first = max(0, int(start * rate))
    last = min(waveform.shape[0], int(end * rate))
    if last <= first:
        raise RuntimeError(f"the chosen window ({start:.2f}-{end:.2f}s) is empty")

    clip = waveform[first:last]
    if sample_rate and sample_rate != rate:
        import numpy as np

        target_frames = int(round(len(clip) * sample_rate / rate))
        positions = np.linspace(0, len(clip) - 1, target_frames)
        clip = np.interp(positions, np.arange(len(clip)), clip).astype("float32")

    target.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(target), clip, sample_rate or rate)
    return target


# ----------------------------------------------------------------------
# the whole job
# ----------------------------------------------------------------------
def prepare_reference(
    wav: Path | str,
    out_wav: Path | str,
    out_text: Path | str,
    *,
    transcript: str = "",
    model_size: str = "small.en",
    device: str = "auto",
    min_seconds: float = MIN_SECONDS,
    max_seconds: float = MAX_SECONDS,
    sample_rate: int = 0,
) -> Reference:
    """Cut a usable reference clip and its transcript out of a recording.

    ``transcript`` is the full transcript of the recording, if it is known.
    The words of the clip are then taken from it rather than from the speech
    recogniser.
    """
    wav = Path(wav)
    if not wav.exists():
        raise FileNotFoundError(f"the recording is not at {wav}")

    words = transcribe_words(wav, model_size=model_size, device=device)
    window = pick_window(words, min_seconds=min_seconds, max_seconds=max_seconds)

    source = "speech-recognition"
    text = window.text
    notes = ""

    if transcript.strip():
        sliced, coverage = slice_transcript(transcript, window)
        if sliced and coverage >= 0.6:
            # Prefer the author's own sentence edges around the matched
            # words, so the clip does not start mid-sentence.
            author_words = transcript.split()
            recognised = [_normalise(w.text) for w in window.words]
            written = [_normalise(w) for w in author_words]
            matcher = difflib.SequenceMatcher(
                None, recognised, written, autojunk=False
            )
            for tag, i1, i2, j1, j2 in matcher.get_opcodes():
                if tag == "equal" and i2 > 0 and i1 < len(recognised):
                    low, high = _expand_to_sentences(author_words, j1, j2)
                    sliced = " ".join(author_words[low:high]).strip()
                    break
            text = sliced
            source = "author transcript, aligned to the recording"
            notes = (
                f"The recogniser and the transcript agreed on {coverage:.0%} of "
                f"the words in the window."
            )
        else:
            notes = (
                "The supplied transcript did not line up with the recording "
                f"({coverage:.0%} overlap), so the recogniser's own words were "
                "used instead."
            )

    out_wav = Path(out_wav)
    out_text = Path(out_text)
    cut_audio(wav, out_wav, window.start, window.end, sample_rate=sample_rate)
    out_text.parent.mkdir(parents=True, exist_ok=True)
    out_text.write_text(text.strip() + "\n", encoding="utf-8")

    return Reference(
        wav=out_wav,
        text=out_text,
        window=window,
        transcript_source=source,
        model=model_size,
        notes=notes,
    )


__all__ = [
    "MAX_PAUSE",
    "MAX_SECONDS",
    "MIN_SECONDS",
    "TARGET_SAMPLE_RATE",
    "Reference",
    "Window",
    "Word",
    "cut_audio",
    "load_audio",
    "pick_window",
    "prepare_reference",
    "slice_transcript",
    "transcribe_words",
]
