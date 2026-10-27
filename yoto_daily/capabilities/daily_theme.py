"""The daily-theme capability.

This is the full morning, end to end:

    theme -> research -> plan -> voice -> music -> upload -> card
                                        \\-> a folder for the day

A theme is one topic -- exoplanets, dinosaurs, the sea -- and the card
carries it whole: the stories, the songs, the explainer and the checked
facts behind them, all in one voice.  The card it writes to is the same
card every morning; the theme is what changes.

The words come from the content library when it has the topic, and from a
local model when it does not.  The library is first on purpose: a story
somebody wrote by hand is worth more than a story a small model produced
at seven in the morning, and a card built from the library is a long one
-- two stories, two songs, an explainer and a fact corner.

Everything the run produces is written to a folder of its own, named for
the day and the theme.  The transcripts and the audio sit next to a
manifest that says how the card was put together, so any morning can be
put back on the card later, exactly as it was.
"""

from __future__ import annotations

from typing import Any

from yoto import Yoto

from ..config import Settings
from ..content import library
from ..content.plan import Plan, filter_plan, plan_from_authored, plan_from_theme
from ..content.theme import slugify
from ..content.tts import TTSBackend, build_tts_backend
from ..daily_card import daily_card_id
from ..days import (
    day_folder,
    now_stamp,
    prune_day,
    save_transcript,
    today_slug,
    track_basename,
    write_manifest,
)
from ..generators import build_registry
from ..generators.base import MusicSpec
from ..icons import IconLibrary
from ..numbers import spell_numbers
from ..pixelart import cover as draw_cover
from ..research import research
from ..state import StateStore
from .base import Capability, CapabilityResult, register


@register
class DailyThemeCapability(Capability):
    """Builds a themed card: the stories, the songs and the facts."""

    name = "daily-theme"
    description = (
        "Write a themed set for today -- stories, songs, an explainer and "
        "the checked facts -- narrate it in one voice, and publish it as the "
        "daily card. Everything is written to a folder for the day so it can "
        "be put back later."
    )
    parameters = [
        {"name": "theme", "type": "string", "required": True,
         "description": "The topic the card is about, e.g. 'exoplanets'."},
        {"name": "audience", "type": "string", "required": False,
         "description": "Who is listening. Defaults to the configured audience."},
        {"name": "voice", "type": "string", "required": False,
         "description": "Which voice to narrate in. Defaults to the configured one."},
        {"name": "instruction", "type": "string", "required": False,
         "description": "How to read it, e.g. 'warm and unhurried'."},
        {"name": "reuse", "type": "boolean", "required": False,
         "description": "Reuse audio already in the day's folder. Defaults to true."},
        {"name": "plan_only", "type": "boolean", "required": False,
         "description": "Show what would go on the card, without making any of it."},
        {"name": "date", "type": "string", "required": False,
         "description": "Which day's folder to write. Defaults to today."},
        {"name": "dry_run", "type": "boolean", "required": False,
         "description": "Make everything, but do not touch the card."},
    ]

    def __init__(
        self,
        settings: Settings | None = None,
        state: StateStore | None = None,
        *,
        yoto: Yoto | None = None,
        theme_writer: Any = None,
        tts: TTSBackend | None = None,
    ) -> None:
        from .base import get_context

        context = get_context()
        self.settings = settings or context.get("settings") or Settings()
        self.state = state or context.get("state") or StateStore(self.settings.state_file)
        self._yoto = yoto or context.get("yoto")
        self._writer = theme_writer
        self._tts = tts
        self._icons: IconLibrary | None = None

    # ------------------------------------------------------------------
    @property
    def yoto(self) -> Yoto:
        if self._yoto is None:
            self._yoto = Yoto()
        return self._yoto

    @property
    def theme_writer(self) -> Any:
        if self._writer is None:
            from ..content.theme import build_theme_writer

            self._writer = build_theme_writer(
                backend=self.settings.theme_backend,
                ollama_endpoint=self.settings.ollama_endpoint,
                ollama_model=self.settings.ollama_model,
                ollama_timeout=self.settings.ollama_timeout,
                attempts=self.settings.theme_attempts,
            )
        return self._writer

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

    @property
    def music(self):
        registry = build_registry(self.settings.raw_config)
        return registry.pick_music()

    @property
    def icons(self) -> IconLibrary:
        if self._icons is None:
            self._icons = IconLibrary(self.yoto, self.state)
        return self._icons

    # ------------------------------------------------------------------
    def run(self, **params: Any) -> CapabilityResult:
        theme_name = str(params.get("theme") or "").strip()
        if not theme_name:
            return CapabilityResult(
                ok=False, message="a theme is required", data={}
            )

        day = str(params.get("date") or "").strip() or today_slug()
        audience = str(params.get("audience") or "").strip() or self.settings.theme_audience
        voice = str(params.get("voice") or "").strip() or self.settings.theme_voice
        instruction = str(params.get("instruction") or "").strip()
        reuse = params.get("reuse") is not False
        plan_only = bool(params.get("plan_only"))
        dry_run = bool(params.get("dry_run"))

        limit = int(getattr(self.settings, "max_text_length", 0) or 0)
        if limit and len(theme_name) > limit:
            return CapabilityResult(
                ok=False,
                message=(
                    f"the theme is {len(theme_name)} characters long; "
                    f"the limit is {limit}"
                ),
                data={},
            )

        # -- the plan --------------------------------------------------
        plan, notes = self._plan(theme_name, audience=audience)
        plan = filter_plan(
            plan,
            songs=params.get("song") is not False,
            facts=params.get("facts") is not False,
        )

        if plan_only:
            return CapabilityResult(
                ok=True,
                message=f"Planned '{plan.title}' ({len(plan.tracks)} tracks)",
                data={
                    "theme": plan.slug,
                    "theme_name": plan.name,
                    "title": plan.title,
                    "text_backend": plan.backend,
                    "research_source": notes.get("source", "") or plan.source,
                    "narration_minutes": round(plan.narration_seconds / 60.0, 1),
                    "song_minutes": round(plan.song_seconds / 60.0, 1),
                    "tracks": [
                        {
                            "key": track.key,
                            "title": track.title,
                            "kind": track.kind,
                            "segment": track.segment,
                            "words": track.words,
                            "seconds": track.seconds,
                        }
                        for track in plan.tracks
                    ],
                },
            )

        # -- the folder for the day ------------------------------------
        folder = day_folder(self.settings.work_dir, day, plan.slug)
        folder.mkdir(parents=True, exist_ok=True)

        result: dict[str, Any] = {
            "theme": plan.slug,
            "theme_name": plan.name,
            "title": plan.title,
            "date": day,
            "folder": str(folder),
            "audience": audience,
            "text_backend": plan.backend,
            "research_source": notes.get("source", "") or plan.source,
            "planned_seconds": round(plan.narration_seconds + plan.song_seconds, 1),
            "tracks": [],
        }

        tracks: list[dict[str, Any]] = []

        for planned in plan.tracks:
            tracks.append(
                self._make_track(
                    planned,
                    folder=folder,
                    voice=voice,
                    instruction=instruction,
                    reuse=reuse,
                )
            )

        result["tracks"] = tracks

        # -- the cover, and the manifest, written before the card --------
        cover_path = self._cover(plan, folder)

        keep = [track["file"] for track in tracks] + [
            track["transcript"] for track in tracks
        ]
        if cover_path is not None:
            keep.append(cover_path.name)
        removed = prune_day(folder, keep)

        manifest = {
            "version": 1,
            "date": day,
            "slug": plan.slug,
            "theme": plan.name,
            "title": plan.title,
            "created": now_stamp(),
            "audience": audience,
            "voice": voice,
            "plan": plan.to_dict(),
            "text": {
                track["key"]: track["text"]
                for track in tracks
            },
            "tracks": tracks,
            "source": {
                "theme_backend": plan.backend,
                "research_source": notes.get("source", "") or plan.source,
                "research_notes": notes.get("notes", ""),
                "text_meta": plan.meta.get("text_meta", {}),
            },
        }
        write_manifest(folder, manifest)
        result["manifest"] = str(folder / "manifest.json")
        if removed:
            result["removed"] = removed

        if dry_run:
            result["dry_run"] = True
            return CapabilityResult(
                ok=True,
                message=f"Built '{plan.title}' (dry run)",
                data=result,
            )

        # -- the card ----------------------------------------------------
        card_id = daily_card_id(
            self.yoto, self.state, self.settings, title=plan.name
        )
        built: list[Any] = []
        for track in tracks:
            path = folder / track["file"]
            if not path.exists():
                raise RuntimeError(f"the audio for {track['title']} is missing")
            upload = self.yoto.media.upload_audio(path, title=track["title"])
            track["media_id"] = upload.media_id
            track["upload_duration"] = upload.duration

            icon_media_id = ""
            if track.get("icon_media_id"):
                icon_media_id = track["icon_media_id"]
            else:
                icon_media_id = self.icons.media_id(
                    track.get("segment", "story"),
                    track.get("subject", ""),
                    track.get("title", ""),
                    track.get("icon", ""),
                )
                track["icon_media_id"] = icon_media_id

            built.append(
                self.yoto.cards.build_track(
                    track["key"],
                    track["title"],
                    upload.media_id,
                    duration=upload.duration,
                    file_size=upload.file_size,
                    fmt=upload.format,
                    icon_media_id=icon_media_id or None,
                )
            )

        chapter = self.yoto.cards.build_chapter("00", plan.name, built)

        # The cover is nice to have; a card without one is still a card.
        cover = {}
        if cover_path is not None:
            try:
                uploaded = self.yoto.media.upload_cover_image(cover_path)
                # The card wants the picture's address under "imageL".
                url = str(uploaded.get("mediaUrl") or uploaded.get("url") or "")
                if url:
                    cover = {"imageL": url}
                    result["cover"] = cover
            except Exception as exc:
                result["cover_error"] = str(exc)[:200]

        content = self.yoto.cards.build_content([chapter])
        saved = self.yoto.cards.update_content(card_id, content, title=plan.name)
        if cover:
            try:
                self.yoto.cards.update_metadata(card_id, extra={"cover": cover})
            except Exception as exc:
                result["cover_error"] = str(exc)[:200]

        # The manifest now knows where the card is.
        manifest["card_id"] = card_id
        manifest["card_title"] = plan.name
        write_manifest(folder, manifest)

        total = sum(
            float(track.get("upload_duration") or track.get("duration") or 0)
            for track in tracks
        )
        self.state.update(
            daily_card_id=card_id,
            last_run=now_stamp(),
            last_theme={
                "theme": plan.slug,
                "name": plan.name,
                "title": plan.title,
                "date": day,
                "folder": str(folder),
                "tracks": [t["title"] for t in tracks],
            },
        )

        result["card_id"] = card_id
        result["card_title"] = plan.name
        result["chapters"] = len(saved.content.chapters)
        result["total_seconds"] = round(total, 1)
        result["total_minutes"] = round(total / 60.0, 1)

        return CapabilityResult(
            ok=True,
            message=(
                f"Published '{plan.title}' ({len(tracks)} tracks, "
                f"{round(total / 60.0, 1)} min) to card {card_id}"
            ),
            data=result,
        )

    # ------------------------------------------------------------------
    def _plan(self, theme_name: str, *, audience: str) -> tuple[Plan, dict[str, Any]]:
        """What goes on the card, and the notes it came from.

        The library is asked first.  It has the topic written by hand, and
        that is always better than asking a small model for one at seven
        in the morning.  The model is for the topics the library does not
        cover.
        """
        slug = slugify(theme_name)
        authored = library.find(slug)
        if authored is not None:
            notes = self._research(theme_name)
            plan = plan_from_authored(
                authored,
                song_seconds=float(self.settings.theme_song_seconds),
                source=str(notes.get("source") or authored.source),
            )
            return plan, notes

        notes = self._research(theme_name)
        fact_lines = [line for group in notes.get("facts", []) for line in group]
        theme = self.theme_writer.write(
            theme_name,
            audience=audience,
            notes=notes.get("notes", ""),
            fact_lines=fact_lines,
            fact_text=notes.get("fact_text", ""),
            fact_corner=notes.get("fact_corner", ""),
            focus=notes.get("focus", ""),
            focus_detail=notes.get("focus_detail", ""),
            claims=notes.get("claims", []),
            life_claims=notes.get("life_claims", []),
        )
        plan = plan_from_theme(
            theme,
            song_seconds=float(self.settings.theme_song_seconds),
            source=str(notes.get("source", "")),
        )
        return plan, notes

    # ------------------------------------------------------------------
    def _research(self, theme_name: str) -> dict[str, Any]:
        """The checked facts, or nothing when the archive cannot be reached.

        A morning should not fail because a website is down.  The library
        does not need the archive to be published, and the model can write
        without it -- it just has less to work with.
        """
        try:
            return research(theme_name, limit=self.settings.research_fact_count)
        except Exception as exc:  # pragma: no cover - depends on the network
            return {"source": "", "notes": "", "facts": [], "error": str(exc)}

    # ------------------------------------------------------------------
    def _make_track(
        self,
        planned: Any,
        *,
        folder: Any,
        voice: str,
        instruction: str,
        reuse: bool,
    ) -> dict[str, Any]:
        """The audio, the transcript and the picture for one track."""
        base = track_basename(planned.key, planned.title)
        path = folder / f"{base}.mp3"
        text = planned.lyrics if planned.is_song else planned.text
        # The numbers are written out before anything else, so the words
        # that are spoken are the words in the transcript.
        text = spell_numbers(text)

        reused = False
        duration = 0.0
        backend = ""
        used_voice = voice

        if reuse and path.exists() and path.stat().st_size > 0:
            reused = True
            duration = self._duration(path)
            backend = "reused"
        elif planned.is_song:
            spec = MusicSpec(
                prompt=planned.prompt,
                lyrics=planned.lyrics,
                duration=int(planned.seconds or self.settings.theme_song_seconds),
                instrumental=False,
                tags=[planned.subject or planned.title],
            )
            generator = self.music
            audio = generator.generate(spec, path)
            duration = audio.duration
            backend = generator.name
        else:
            audio = self.tts.synthesize(
                text, path, voice=voice, instruction=instruction
            )
            duration = audio.duration
            backend = audio.backend
            used_voice = audio.voice or voice

        if not path.exists():
            raise RuntimeError(
                f"text-to-speech produced no audio file for '{planned.title}'"
            )

        transcript_path = save_transcript(folder, planned.key, planned.title, text)

        return {
            "key": planned.key,
            "title": planned.title,
            "kind": planned.kind,
            "segment": planned.segment,
            "subject": planned.subject,
            "icon": planned.icon_kind,
            "file": path.name,
            "transcript": transcript_path.name,
            "duration": round(duration, 2),
            "words": planned.words,
            "voice": used_voice,
            "backend": backend,
            "reused": reused,
            "text": text,
        }

    # ------------------------------------------------------------------
    def _cover(self, plan: Plan, folder: Any) -> Any:
        """The card's cover picture, drawn and written to the day's folder.

        It is the theme's own picture, blown up on a night sky, so the card
        looks like it was made for the thing it is about.
        """
        if not plan.tracks:
            return None
        first = plan.tracks[0]
        icon = str(plan.meta.get("cover_icon") or first.icon_kind)
        try:
            png = draw_cover(first.segment, first.subject, first.title, icon)
        except Exception:
            return None
        path = folder / "cover.png"
        path.write_bytes(png)
        return path

    # ------------------------------------------------------------------
    def _duration(self, path: Any) -> float:
        """How long an audio file runs, in seconds."""
        try:
            import soundfile as sf

            with sf.SoundFile(str(path)) as handle:
                return float(len(handle)) / float(handle.samplerate)
        except Exception:
            return 0.0


__all__ = ["DailyThemeCapability"]
