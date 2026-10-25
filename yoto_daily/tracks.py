"""Adding tracks to a card.

Three track types, matching the Yoto web app's own vocabulary:

``stream``
    A track that plays from a URL.  No media is uploaded; the URL goes
    straight into ``trackUrl``.

``file``
    An audio file on disk, or one fetched from a URL.  It is uploaded,
    transcoded by Yoto and becomes a normal media track.

``generate``
    The audio is produced first and then uploaded like a file.  Three kinds:

    ``music``
        A :class:`MusicSpec` of structured metadata goes to a music
        generator.
    ``text-to-speech``
        A transcript goes to a speech generator.
    ``read-book``
        A book is converted to text and then read aloud, which usually
        produces several tracks.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from yoto import Yoto
from yoto.models import Track

from .config import Settings
from .content.books import BookError, read_book
from .generators import GeneratorRegistry, MusicSpec
from .generators.base import AudioResult


class TrackError(RuntimeError):
    """Raised when a track request cannot be satisfied."""


@dataclass
class TrackRequest:
    """A parsed ``POST /api/cards/<card_id>/tracks`` body."""

    type: str
    kind: str = ""
    generator: str = ""
    params: dict[str, Any] = None  # type: ignore[assignment]
    title: str = ""
    chapter: str = ""
    chapter_key: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TrackRequest":
        kind = str(data.get("kind") or "").strip().lower()
        params = dict(data.get("params") or {})
        # Allow the common fields at the top level too, so a simple request
        # does not need the nested "params" object.
        for key in ("text", "prompt", "source", "url", "path", "voice", "duration",
                    "bpm", "tags", "lyrics", "key_scale", "time_signature", "seed",
                    "instruction"):
            if key in data and key not in params:
                params[key] = data[key]

        return cls(
            type=str(data.get("type") or "").strip().lower(),
            kind=kind,
            generator=str(data.get("generator") or "").strip(),
            params=params,
            title=str(data.get("title") or "").strip(),
            chapter=str(data.get("chapter") or "").strip(),
            chapter_key=(str(data["chapter_key"]) if data.get("chapter_key") else None),
        )


@dataclass
class AddedTrack:
    """One track that was published."""

    key: str
    title: str
    media_id: str = ""
    track_url: str = ""
    duration: int = 0
    format: str = ""
    type: str = "audio"
    chapter: str = ""
    generator: str = ""
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "media_id": self.media_id,
            "track_url": self.track_url,
            "duration": self.duration,
            "format": self.format,
            "type": self.type,
            "chapter": self.chapter,
            "generator": self.generator,
            "source": self.source,
        }


class TrackService:
    """Turns track requests into published tracks."""

    def __init__(
        self,
        yoto: Yoto,
        registry: GeneratorRegistry,
        settings: Settings,
    ) -> None:
        self.yoto = yoto
        self.registry = registry
        self.settings = settings

    # ------------------------------------------------------------------
    def add(self, card_id: str, request: TrackRequest) -> dict[str, Any]:
        """Handle one track request."""
        if request.type == "stream":
            return self._add_stream(card_id, request)
        if request.type == "file":
            return self._add_file(card_id, request)
        if request.type == "generate":
            return self._add_generated(card_id, request)
        raise TrackError(
            f"unknown track type {request.type!r}; expected stream, file or generate"
        )

    # ------------------------------------------------------------------
    # stream
    # ------------------------------------------------------------------
    def _add_stream(self, card_id: str, request: TrackRequest) -> dict[str, Any]:
        url = str(request.params.get("url") or request.params.get("streamUrl") or "").strip()
        if not url:
            raise TrackError("a stream track needs a 'url'")
        if not url.startswith(("http://", "https://")):
            raise TrackError(f"stream url must be http(s), got {url!r}")

        track = self.yoto.cards.build_stream_track(
            "01",
            url,
            title=request.title or url,
            fmt=str(request.params.get("format") or "mp3"),
        )
        card = self.yoto.cards.add_tracks(
            card_id,
            [track],
            chapter_title=request.chapter or "Stream",
        )
        return {
            "ok": True,
            "message": f"Added stream {url}",
            "card_id": card_id,
            "chapters": len(card.content.chapters),
            "tracks": [
                AddedTrack(
                    key=track.key,
                    title=track.title,
                    track_url=track.track_url,
                    type="stream",
                    chapter=request.chapter or "Stream",
                    source=url,
                ).to_dict()
            ],
        }

    # ------------------------------------------------------------------
    # file
    # ------------------------------------------------------------------
    def _add_file(self, card_id: str, request: TrackRequest) -> dict[str, Any]:
        path = request.params.get("path")
        url = request.params.get("url")

        if path:
            source = Path(str(path)).expanduser()
            if not source.exists():
                raise TrackError(f"no such file: {source}")
            title = request.title or source.stem
            cleanup = False
        elif url:
            source = self._download(str(url))
            title = request.title or Path(str(url)).stem
            cleanup = True
        else:
            raise TrackError("a file track needs a 'path' or a 'url'")

        try:
            upload = self.yoto.media.upload_audio(source, title=title)
            track = self.yoto.cards.build_track(
                "01",
                title,
                upload.media_id,
                duration=upload.duration,
                file_size=upload.file_size,
                fmt=upload.format,
            )
            card = self.yoto.cards.add_tracks(
                card_id,
                [track],
                chapter_title=request.chapter or title,
            )
        finally:
            if cleanup:
                source.unlink(missing_ok=True)

        return {
            "ok": True,
            "message": f"Added file {title}",
            "card_id": card_id,
            "chapters": len(card.content.chapters),
            "tracks": [
                AddedTrack(
                    key=track.key,
                    title=track.title,
                    media_id=upload.media_id,
                    track_url=upload.track_url,
                    duration=upload.duration,
                    format=upload.format,
                    type="audio",
                    chapter=request.chapter or title,
                    source=str(source),
                ).to_dict()
            ],
        }

    def _download(self, url: str) -> Path:
        import requests

        try:
            resp = requests.get(url, timeout=300, stream=True)
        except Exception as exc:
            raise TrackError(f"could not fetch {url}: {exc}") from exc
        if resp.status_code >= 400:
            raise TrackError(f"fetching {url} returned HTTP {resp.status_code}")

        suffix = Path(url.split("?")[0]).suffix or ".mp3"
        handle = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        try:
            for chunk in resp.iter_content(1024 * 64):
                if chunk:
                    handle.write(chunk)
        finally:
            handle.close()
        return Path(handle.name)

    # ------------------------------------------------------------------
    # generate
    # ------------------------------------------------------------------
    def _add_generated(self, card_id: str, request: TrackRequest) -> dict[str, Any]:
        kind = request.kind
        if kind in ("tts", "speech", "text-to-speech", "text_to_speech"):
            return self._generate_speech(card_id, request)
        if kind == "music":
            return self._generate_music(card_id, request)
        if kind in ("read-book", "book", "read_book"):
            return self._generate_book(card_id, request)
        raise TrackError(
            f"unknown generate kind {kind!r}; "
            "expected music, text-to-speech or read-book"
        )

    def _work_dir(self) -> Path:
        path = self.settings.work_dir / "tracks"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _generate_music(self, card_id: str, request: TrackRequest) -> dict[str, Any]:
        generator = self.registry.pick_music(request.generator or None)
        spec = MusicSpec.from_dict(request.params)
        if not spec.to_prompt() and not spec.lyrics:
            raise TrackError("a music track needs a prompt, tags or lyrics")

        out_path = self._work_dir() / f"music-{abs(hash(spec.to_prompt())) % 10**8}.mp3"
        result: AudioResult = generator.generate(spec, out_path)

        title = (
            request.title
            or spec.prompt
            or (spec.tags[0] if spec.tags else "")
            or "Untitled music"
        )

        upload = self.yoto.media.upload_audio(result.path, title=title)
        track = self.yoto.cards.build_track(
            "01",
            title,
            upload.media_id,
            duration=upload.duration,
            file_size=upload.file_size,
            fmt=upload.format,
        )
        card = self.yoto.cards.add_tracks(
            card_id, [track], chapter_title=request.chapter or title
        )

        return {
            "ok": True,
            "message": f"Generated music '{title}' with {generator.name}",
            "card_id": card_id,
            "chapters": len(card.content.chapters),
            "generator": generator.name,
            "spec": spec.to_dict(),
            "tracks": [
                AddedTrack(
                    key=track.key,
                    title=title,
                    media_id=upload.media_id,
                    track_url=upload.track_url,
                    duration=upload.duration,
                    format=upload.format,
                    type="audio",
                    chapter=request.chapter or title,
                    generator=generator.name,
                ).to_dict()
            ],
        }

    def _generate_speech(self, card_id: str, request: TrackRequest) -> dict[str, Any]:
        text = str(request.params.get("text") or "").strip()
        if not text:
            raise TrackError("a text-to-speech track needs a 'text'")

        generator = self.registry.pick_speech(request.generator or None)
        voice = str(request.params.get("voice") or "")
        instruction = str(request.params.get("instruction") or "")

        out_path = self._work_dir() / "speech.mp3"
        result = generator.synthesize(text, out_path, voice=voice, instruction=instruction)

        title = request.title or (text.split("\n", 1)[0].strip()[:60] or "Read aloud")
        upload = self.yoto.media.upload_audio(result.path, title=title)
        track = self.yoto.cards.build_track(
            "01",
            title,
            upload.media_id,
            duration=upload.duration,
            file_size=upload.file_size,
            fmt=upload.format,
        )
        card = self.yoto.cards.add_tracks(
            card_id, [track], chapter_title=request.chapter or title
        )

        return {
            "ok": True,
            "message": f"Generated speech '{title}' with {generator.name}",
            "card_id": card_id,
            "chapters": len(card.content.chapters),
            "generator": generator.name,
            "characters": len(text),
            "tracks": [
                AddedTrack(
                    key=track.key,
                    title=title,
                    media_id=upload.media_id,
                    track_url=upload.track_url,
                    duration=upload.duration,
                    format=upload.format,
                    type="audio",
                    chapter=request.chapter or title,
                    generator=generator.name,
                ).to_dict()
            ],
        }

    def _generate_book(self, card_id: str, request: TrackRequest) -> dict[str, Any]:
        source = request.params.get("source") or request.params.get("path") or request.params.get("url")
        if not source:
            raise TrackError("a read-book track needs a 'source'")

        max_words = int(request.params.get("max_words") or 1800)
        limit = request.params.get("chapters")
        limit = int(limit) if limit else None

        try:
            book = read_book(str(source), max_words=max_words)
        except BookError as exc:
            raise TrackError(str(exc)) from exc

        generator = self.registry.pick_speech(request.generator or None)
        voice = str(request.params.get("voice") or "")
        instruction = str(request.params.get("instruction") or "")

        sections = book.chapters or [book.text]
        if limit:
            sections = sections[:limit]

        tracks: list[Track] = []
        added: list[AddedTrack] = []

        for index, section in enumerate(sections):
            out_path = self._work_dir() / f"book-{index:03d}.mp3"
            result = generator.synthesize(
                section, out_path, voice=voice, instruction=instruction
            )
            title = request.title or f"{book.title} - Part {index + 1}"

            upload = self.yoto.media.upload_audio(result.path, title=title)
            track = self.yoto.cards.build_track(
                f"{index + 1:02d}",
                title,
                upload.media_id,
                duration=upload.duration,
                file_size=upload.file_size,
                fmt=upload.format,
            )
            tracks.append(track)
            added.append(
                AddedTrack(
                    key=track.key,
                    title=title,
                    media_id=upload.media_id,
                    track_url=upload.track_url,
                    duration=upload.duration,
                    format=upload.format,
                    type="audio",
                    chapter=request.chapter or book.title,
                    generator=generator.name,
                    source=book.source,
                )
            )

        chapter_title = request.chapter or book.title
        card = self.yoto.cards.add_tracks(
            card_id,
            tracks,
            chapter_title=chapter_title,
            chapter_key=request.chapter_key,
        )

        return {
            "ok": True,
            "message": (
                f"Read '{book.title}' ({book.word_count} words, "
                f"{len(sections)} part{'s' if len(sections) != 1 else ''}) "
                f"with {generator.name}"
            ),
            "card_id": card_id,
            "chapters": len(card.content.chapters),
            "generator": generator.name,
            "book": {
                "title": book.title,
                "format": book.fmt,
                "source": book.source,
                "words": book.word_count,
                "parts": len(sections),
            },
            "tracks": [t.to_dict() for t in added],
        }
