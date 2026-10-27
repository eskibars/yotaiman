"""The restore-day capability.

A card is a pointer to media that lives on somebody else's server, which is
a thin thing to own a year of mornings with.  So every run also writes the
day out to disk -- the transcripts, the audio, and a manifest saying how the
card was put together.

This is the other half of that arrangement: it reads a saved day's folder,
uploads the audio it holds, and rebuilds the card exactly as it was.  The
Exoplanets card of two weeks ago can come back tomorrow, and the folder is
what makes that possible.
"""

from __future__ import annotations

from typing import Any

from yoto import Yoto

from ..config import Settings
from ..days import DayRecord, find_day, list_days, now_stamp, read_manifest, write_manifest
from ..icons import IconLibrary
from ..state import StateStore
from .base import Capability, CapabilityResult, register


@register
class RestoreDayCapability(Capability):
    """Puts a saved day back on the card."""

    name = "restore-day"
    description = (
        "Rebuild the daily card from a saved day's folder: the transcripts, "
        "the audio and the manifest are all that is needed."
    )
    parameters = [
        {"name": "date", "type": "string", "required": False,
         "description": "The day to restore, e.g. '2026-10-26'. Defaults to the latest."},
        {"name": "slug", "type": "string", "required": False,
         "description": "The theme of the day, e.g. 'exoplanets'."},
        {"name": "card_id", "type": "string", "required": False,
         "description": "Which card to restore onto. Defaults to the daily card."},
        {"name": "list", "type": "boolean", "required": False,
         "description": "List the saved days instead of restoring one."},
    ]

    def __init__(
        self,
        settings: Settings | None = None,
        state: StateStore | None = None,
        *,
        yoto: Yoto | None = None,
    ) -> None:
        from .base import get_context

        context = get_context()
        self.settings = settings or context.get("settings") or Settings()
        self.state = state or context.get("state") or StateStore(self.settings.state_file)
        self._yoto = yoto or context.get("yoto")
        self._icons: IconLibrary | None = None

    # ------------------------------------------------------------------
    @property
    def yoto(self) -> Yoto:
        if self._yoto is None:
            self._yoto = Yoto()
        return self._yoto

    @property
    def icons(self) -> IconLibrary:
        if self._icons is None:
            self._icons = IconLibrary(self.yoto, self.state)
        return self._icons

    # ------------------------------------------------------------------
    def run(self, **params: Any) -> CapabilityResult:
        if params.get("list"):
            days = [d.to_dict() for d in list_days(self.settings.work_dir)]
            return CapabilityResult(
                ok=True,
                message=f"{len(days)} saved day(s)",
                data={"days": days, "work_dir": str(self.settings.work_dir)},
            )

        day = str(params.get("date") or "").strip()
        slug = str(params.get("slug") or "").strip()

        record = find_day(self.settings.work_dir, day=day, slug=slug)
        if record is None:
            known = [d.name for d in list_days(self.settings.work_dir)]
            return CapabilityResult(
                ok=False,
                message=(
                    f"no saved day for {day or slug or 'the latest day'}"
                    + (f"; saved days: {', '.join(known)}" if known else "")
                ),
                data={"saved_days": known},
            )

        return self._restore(record, str(params.get("card_id") or "").strip())

    # ------------------------------------------------------------------
    def _restore(self, record: DayRecord, card_id: str) -> CapabilityResult:
        manifest = record.manifest or read_manifest(record.folder)
        tracks = manifest.get("tracks") or []
        if not tracks:
            return CapabilityResult(
                ok=False,
                message=f"the manifest for {record.name} lists no tracks",
                data={"folder": str(record.folder)},
            )

        # The card to restore onto: the one asked for, the daily card, or
        # whichever card this day was published to last time.
        target = card_id or self.settings.daily_card_id or self.state.get(
            "daily_card_id", ""
        ) or record.card_id
        if not target or not self.yoto.cards.exists(target):
            card = self.yoto.cards.create(title=str(manifest.get("card_title") or record.theme))
            target = card.card_id

        built: list[Any] = []
        restored: list[dict[str, Any]] = []
        for track in sorted(tracks, key=lambda t: str(t.get("key") or "")):
            name = str(track.get("file") or "")
            path = record.folder / name
            if not path.exists():
                raise RuntimeError(
                    f"the audio for '{track.get('title')}' is missing from {record.folder}"
                )
            upload = self.yoto.media.upload_audio(path, title=str(track.get("title") or ""))
            icon_media_id = self.icons.media_id(
                str(track.get("segment") or "story"),
                str(track.get("subject") or ""),
                str(track.get("title") or ""),
                str(track.get("icon") or ""),
            )
            built.append(
                self.yoto.cards.build_track(
                    str(track.get("key") or "01"),
                    str(track.get("title") or ""),
                    upload.media_id,
                    duration=upload.duration,
                    file_size=upload.file_size,
                    fmt=upload.format,
                    icon_media_id=icon_media_id or None,
                )
            )
            restored.append(
                {
                    "key": track.get("key", ""),
                    "title": track.get("title", ""),
                    "kind": track.get("kind", ""),
                    "segment": track.get("segment", ""),
                    "icon": track.get("icon", ""),
                    "file": name,
                    "media_id": upload.media_id,
                    "icon_media_id": icon_media_id,
                    "duration": upload.duration,
                }
            )

        theme_name = str(manifest.get("theme") or record.theme)
        chapter = self.yoto.cards.build_chapter("00", theme_name, built)
        content = self.yoto.cards.build_content([chapter])
        saved = self.yoto.cards.update_content(target, content, title=theme_name)

        manifest["card_id"] = target
        manifest["card_title"] = theme_name
        manifest["restored"] = now_stamp()
        write_manifest(record.folder, manifest)

        self.state.update(
            daily_card_id=target,
            last_run=now_stamp(),
            last_theme={
                "theme": record.slug,
                "name": theme_name,
                "title": manifest.get("title", ""),
                "date": record.date,
                "folder": str(record.folder),
                "tracks": [t["title"] for t in restored],
                "restored": True,
            },
        )

        return CapabilityResult(
            ok=True,
            message=(
                f"Restored '{theme_name}' from {record.name} "
                f"({len(restored)} tracks) onto card {target}"
            ),
            data={
                "day": record.name,
                "date": record.date,
                "theme": theme_name,
                "folder": str(record.folder),
                "card_id": target,
                "card_title": theme_name,
                "chapters": len(saved.content.chapters),
                "tracks": restored,
            },
        )


__all__ = ["RestoreDayCapability"]
