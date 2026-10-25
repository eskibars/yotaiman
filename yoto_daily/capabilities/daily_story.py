"""The daily-story capability.

This is the end-to-end proof of the whole stack:

    topic -> text -> speech -> upload -> transcode -> card write

The card it writes to is remembered in the service state, so the first run
creates one and every later run rewrites it.  In ``history`` mode the card
keeps the last N days as separate chapters, which lets a child replay
yesterday's story.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any

from yoto import Yoto
from ..config import Settings
from ..content.text import TextSource, build_text_source
from ..content.tts import TTSBackend, build_tts_backend
from ..state import StateStore
from .base import Capability, CapabilityResult, register


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:48] or "story"


@register
class DailyStoryCapability(Capability):
    """Generates a fresh story every day and puts it on a Yoto card."""

    name = "daily-story"
    description = (
        "Write a short story about a topic, narrate it with text-to-speech, "
        "and publish it as the daily card."
    )
    parameters = [
        {"name": "topic", "type": "string", "required": False,
         "description": "What the story is about. Defaults to a rotating topic."},
        {"name": "child_name", "type": "string", "required": False,
         "description": "Name to address the listener as."},
        {"name": "voice", "type": "string", "required": False,
         "description": "TTS voice. Defaults to the configured one."},
        {"name": "instruction", "type": "string", "required": False,
         "description": "How to read the story, e.g. 'unhurried and warm'. "
                        "Overrides the configured delivery."},
        {"name": "title", "type": "string", "required": False,
         "description": "Override the generated title."},
        {"name": "dry_run", "type": "boolean", "required": False,
         "description": "Generate the story and audio but do not touch the card."},
    ]

    def __init__(
        self,
        settings: Settings | None = None,
        state: StateStore | None = None,
        *,
        yoto: Yoto | None = None,
        text_source: TextSource | None = None,
        tts: TTSBackend | None = None,
    ) -> None:
        from .base import get_context

        context = get_context()
        self.settings = settings or context.get("settings") or Settings()
        self.state = state or context.get("state") or StateStore(self.settings.state_file)
        self._yoto = yoto or context.get("yoto")
        self._text = text_source
        self._tts = tts

    # ------------------------------------------------------------------
    @property
    def yoto(self) -> Yoto:
        if self._yoto is None:
            self._yoto = Yoto()
        return self._yoto

    @property
    def text_source(self) -> TextSource:
        if self._text is None:
            self._text = build_text_source(
                backend=self.settings.llm_backend,
                script=self.settings.llm_script,
                script_model=self.settings.llm_model,
                openai_key=self.settings.openai_api_key,
                openai_model=self.settings.openai_model,
            )
        return self._text

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
        topic = (params.get("topic") or "").strip() or None
        child_name = (params.get("child_name") or "").strip()
        voice = (params.get("voice") or "").strip() or self.settings.tts_voice
        instruction = (params.get("instruction") or "").strip()
        dry_run = bool(params.get("dry_run"))

        limit = int(getattr(self.settings, "max_text_length", 0) or 0)
        if limit:
            for name, value in (("topic", topic), ("child_name", child_name),
                                ("instruction", instruction)):
                if value and len(value) > limit:
                    return CapabilityResult(
                        ok=False,
                        message=(
                            f"the {name} is {len(value)} characters long; "
                            f"the limit is {limit}"
                        ),
                        data={},
                    )

        story = self.text_source.generate(topic, child_name=child_name)
        if params.get("title"):
            story.title = str(params["title"])

        work = self.settings.work_dir / f"{date.today().isoformat()}-{_slug(story.title)}"
        work.mkdir(parents=True, exist_ok=True)
        audio_path = work / "story.mp3"

        audio = self.tts.synthesize(
            story.body, audio_path, voice=voice, instruction=instruction
        )
        if not audio_path.exists():
            raise RuntimeError("text-to-speech produced no audio file")

        result: dict[str, Any] = {
            "topic": story.topic,
            "title": story.title,
            "text": story.body,
            "text_backend": story.backend,
            "voice": audio.voice or voice,
            "instruction": instruction,
            "tts_backend": audio.backend,
            "audio_duration": round(audio.duration, 2),
            "audio_path": str(audio_path),
        }

        if dry_run:
            result["dry_run"] = True
            return CapabilityResult(
                ok=True, message=f"Generated '{story.title}' (dry run)", data=result
            )

        upload = self.yoto.media.upload_audio(audio_path, title=story.title)
        result["media_id"] = upload.media_id
        result["duration"] = upload.duration

        card_id = self._daily_card_id()
        mode = self.settings.daily_mode
        title = f"Daily - {date.today().isoformat()}"

        if mode == "history":
            chapters = self._history_chapters(card_id, story, upload, title)
            content = self.yoto.cards.build_content(chapters)
        else:
            track = self.yoto.cards.build_track(
                "01",
                story.title,
                upload.media_id,
                duration=upload.duration,
                file_size=upload.file_size,
                fmt=upload.format,
            )
            chapter = self.yoto.cards.build_chapter("00", story.title, [track])
            content = self.yoto.cards.build_content([chapter])

        saved = self.yoto.cards.update_content(card_id, content, title=title)

        self.state.update(
            daily_card_id=card_id,
            last_run=datetime.now(timezone.utc).isoformat(),
            last_story={
                "topic": story.topic,
                "title": story.title,
                "media_id": upload.media_id,
                "duration": upload.duration,
                "card_title": title,
            },
        )

        result["card_id"] = card_id
        result["card_title"] = title
        result["chapters"] = len(saved.content.chapters)
        result["mode"] = mode

        return CapabilityResult(
            ok=True,
            message=f"Published '{story.title}' to card {card_id}",
            data=result,
        )

    # ------------------------------------------------------------------
    def _daily_card_id(self) -> str:
        """Return the daily card id, creating the card on first use."""
        configured = self.settings.daily_card_id
        if configured:
            return configured

        stored = self.state.get("daily_card_id", "")
        if stored and self.yoto.cards.exists(stored):
            return stored

        card = self.yoto.cards.create(title=f"Daily - {date.today().isoformat()}")
        self.state.set("daily_card_id", card.card_id)
        return card.card_id

    def _history_chapters(self, card_id: str, story: Any, upload: Any, title: str) -> list[Any]:
        """Rebuild the chapter list: today's story first, older ones after."""
        existing: list[Any] = []
        try:
            current = self.yoto.cards.get(card_id)
            existing = list(current.content.chapters)
        except Exception:
            existing = []

        track = self.yoto.cards.build_track(
            "01",
            story.title,
            upload.media_id,
            duration=upload.duration,
            file_size=upload.file_size,
            fmt=upload.format,
        )
        today = self.yoto.cards.build_chapter(
            "00",
            f"{date.today().isoformat()} - {story.title}",
            [track],
        )

        keep = self.settings.history_days - 1
        older = existing[:keep] if keep > 0 else []
        chapters = [today, *older]
        return chapters[: max(self.settings.history_days, 1)]
