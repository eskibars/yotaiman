"""The read-aloud capability.

Reads arbitrary text and puts it on a card.  This is the counterpart to
``daily-story``: instead of the service inventing the words, the caller
supplies them -- a story typed on a phone, a chapter of a book, a note.

It also demonstrates the second half of the capability contract: a capability
can target any card, not just the daily one, and can either replace the card
or append to it.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from yoto import Yoto

from ..config import Settings
from ..content.tts import TTSBackend, build_tts_backend
from ..state import StateStore
from .base import Capability, CapabilityResult, register


@register
class ReadAloudCapability(Capability):
    """Narrates supplied text and publishes it to a card."""

    name = "read-aloud"
    description = (
        "Read text aloud with text-to-speech and publish it to a card, "
        "either replacing the card or appending to it."
    )
    parameters = [
        {"name": "text", "type": "string", "required": True,
         "description": "The words to read."},
        {"name": "title", "type": "string", "required": False,
         "description": "Chapter and track title. Defaults to 'Read aloud'."},
        {"name": "card_id", "type": "string", "required": False,
         "description": "Target card. Defaults to the daily card."},
        {"name": "mode", "type": "string", "required": False,
         "description": "'replace' (default) or 'append'."},
        {"name": "voice", "type": "string", "required": False,
         "description": "TTS voice. Defaults to the configured one."},
        {"name": "instruction", "type": "string", "required": False,
         "description": "How to read it, e.g. 'unhurried and warm'. "
                        "Overrides the configured delivery."},
        {"name": "dry_run", "type": "boolean", "required": False,
         "description": "Render the audio but do not touch a card."},
    ]

    def __init__(
        self,
        settings: Settings | None = None,
        state: StateStore | None = None,
        *,
        yoto: Yoto | None = None,
        tts: TTSBackend | None = None,
    ) -> None:
        from .base import get_context

        context = get_context()
        self.settings = settings or context.get("settings") or Settings()
        self.state = state or context.get("state") or StateStore(self.settings.state_file)
        self._yoto = yoto or context.get("yoto")
        self._tts = tts

    @property
    def yoto(self) -> Yoto:
        if self._yoto is None:
            self._yoto = Yoto()
        return self._yoto

    @property
    def tts(self) -> TTSBackend:
        if self._tts is None:
            self._tts = build_tts_backend(
                prefer=self.settings.tts_backend,
                say_command=self.settings.tts_command,
                ffmpeg_command=self.settings.ffmpeg_command,
                ming_options=self.settings.ming_tts_options,
            )
        return self._tts

    # ------------------------------------------------------------------
    def run(self, **params: Any) -> CapabilityResult:
        text = (params.get("text") or "").strip()
        if not text:
            return CapabilityResult(
                ok=False, message="no text supplied", data={}
            )

        limit = int(getattr(self.settings, "max_text_length", 0) or 0)
        if limit and len(text) > limit:
            return CapabilityResult(
                ok=False,
                message=(
                    f"the text is {len(text)} characters long; "
                    f"the limit is {limit}"
                ),
                data={},
            )

        title = (params.get("title") or "Read aloud").strip()
        voice = (params.get("voice") or "").strip() or self.settings.tts_voice
        instruction = (params.get("instruction") or "").strip()
        mode = (params.get("mode") or "replace").strip().lower()
        dry_run = bool(params.get("dry_run"))

        work = self.settings.work_dir / "read-aloud"
        work.mkdir(parents=True, exist_ok=True)
        audio_path = work / "read-aloud.mp3"

        audio = self.tts.synthesize(
            text, audio_path, voice=voice, instruction=instruction
        )
        if not audio_path.exists():
            raise RuntimeError("text-to-speech produced no audio file")

        result: dict[str, Any] = {
            "title": title,
            "characters": len(text),
            "voice": audio.voice or voice,
            "instruction": instruction,
            "tts_backend": audio.backend,
            "audio_duration": round(audio.duration, 2),
            "audio_path": str(audio_path),
        }

        if dry_run:
            result["dry_run"] = True
            return CapabilityResult(
                ok=True, message=f"Rendered '{title}' (dry run)", data=result
            )

        upload = self.yoto.media.upload_audio(audio_path, title=title)
        result["media_id"] = upload.media_id
        result["duration"] = upload.duration

        card_id = (params.get("card_id") or "").strip() or self._daily_card_id()
        track = self.yoto.cards.build_track(
            "01",
            title,
            upload.media_id,
            duration=upload.duration,
            file_size=upload.file_size,
            fmt=upload.format,
        )

        if mode == "append":
            chapters = self._existing_chapters(card_id)
            chapter = self.yoto.cards.build_chapter(
                f"{len(chapters):02d}", title, [track]
            )
            chapters = [*chapters, chapter]
        else:
            chapter = self.yoto.cards.build_chapter("00", title, [track])
            chapters = [chapter]

        content = self.yoto.cards.build_content(chapters)
        card_title = self.yoto.cards.get(card_id).title if self.yoto.cards.exists(card_id) else title
        saved = self.yoto.cards.update_content(card_id, content, title=card_title)

        result["card_id"] = card_id
        result["chapters"] = len(saved.content.chapters)

        return CapabilityResult(
            ok=True,
            message=f"Published '{title}' to card {card_id}",
            data=result,
        )

    # ------------------------------------------------------------------
    def _daily_card_id(self) -> str:
        configured = self.settings.daily_card_id
        if configured:
            return configured
        stored = self.state.get("daily_card_id", "")
        if stored and self.yoto.cards.exists(stored):
            return stored
        card = self.yoto.cards.create(title=f"Daily - {date.today().isoformat()}")
        self.state.set("daily_card_id", card.card_id)
        return card.card_id

    def _existing_chapters(self, card_id: str) -> list[Any]:
        try:
            return list(self.yoto.cards.get(card_id).content.chapters)
        except Exception:
            return []
