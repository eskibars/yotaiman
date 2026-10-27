"""One folder per day, holding everything a card needs to be rebuilt.

A card on Yoto is a pointer to media that lives on somebody else's server.
That is a thin thing to own a year of mornings with.  So every run writes
the day out to disk: the transcripts, the audio, and a manifest saying how
the card was put together.

    work/
      2026-10-26-exoplanets/
        manifest.json
        01-the-planets-next-door.txt
        01-the-planets-next-door.mp3
        02-the-exoplanets-song.txt
        02-the-exoplanets-song.mp3
        03-fact-corner.txt
        03-fact-corner.mp3

With that folder on disk, any morning can be put back on the card exactly as
it was -- see :func:`yoto_daily.capabilities.restore_day.RestoreDayCapability`.
The manifest is the recipe; the audio next to it is the ingredient.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

#: The manifest format version.  Bumped when the shape changes in a way an
#: older reader could not understand.
MANIFEST_VERSION = 1

#: The file that holds a day's recipe.
MANIFEST_NAME = "manifest.json"


@dataclass
class DayRecord:
    """A day that was written out."""

    date: str
    slug: str
    folder: Path
    manifest: dict[str, Any] = field(default_factory=dict)

    @property
    def name(self) -> str:
        """The folder name: ``2026-10-26-exoplanets``."""
        return f"{self.date}-{self.slug}"

    @property
    def theme(self) -> str:
        return str(self.manifest.get("theme") or self.slug.replace("-", " ").title())

    @property
    def title(self) -> str:
        return str(self.manifest.get("title") or self.theme)

    @property
    def created(self) -> str:
        return str(self.manifest.get("created") or "")

    @property
    def card_id(self) -> str:
        return str(self.manifest.get("card_id") or "")

    @property
    def tracks(self) -> list[dict[str, Any]]:
        tracks = self.manifest.get("tracks")
        return list(tracks) if isinstance(tracks, list) else []

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "slug": self.slug,
            "name": self.name,
            "theme": self.theme,
            "title": self.title,
            "created": self.created,
            "folder": str(self.folder),
            "card_id": self.card_id,
            "tracks": [
                {
                    "key": t.get("key", ""),
                    "title": t.get("title", ""),
                    "kind": t.get("kind", ""),
                    "file": t.get("file", ""),
                    "duration": t.get("duration", 0),
                }
                for t in self.tracks
            ],
        }


# ----------------------------------------------------------------------
# paths
# ----------------------------------------------------------------------
def day_folder(work_dir: Path | str, day: str, slug: str) -> Path:
    """The folder a day is written to."""
    return Path(work_dir) / f"{day}-{slug}"


def today_slug() -> str:
    """Today, as ``YYYY-MM-DD``."""
    return date.today().isoformat()


def now_stamp() -> str:
    """The current time, as an ISO timestamp with a timezone."""
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


# ----------------------------------------------------------------------
# manifests
# ----------------------------------------------------------------------
def write_manifest(folder: Path | str, manifest: dict[str, Any]) -> Path:
    """Write a day's manifest."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / MANIFEST_NAME
    payload = dict(manifest)
    payload.setdefault("version", MANIFEST_VERSION)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)
    return path


def read_manifest(folder: Path | str) -> dict[str, Any]:
    """Read a day's manifest, or ``{}`` when there is not one."""
    path = Path(folder) / MANIFEST_NAME
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def track_basename(key: str, title: str) -> str:
    """The file stem a track's audio and transcript share.

    ``("01", "The Planets Next Door")`` -> ``01-the-planets-next-door``.
    """
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in title).strip("-")
    return f"{key}-{safe.lower() or 'track'}"


def save_transcript(folder: Path | str, key: str, title: str, text: str) -> Path:
    """Write the words of one track next to its audio.

    The transcript is what makes the folder restorable by hand: it says what
    was said, so the audio can be re-recorded, re-edited or just read.
    """
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{track_basename(key, title)}.txt"
    header = f"{title}\n{'=' * len(title)}\n\n"
    path.write_text(header + (text or "").strip() + "\n", encoding="utf-8")
    return path


# ----------------------------------------------------------------------
# finding days
# ----------------------------------------------------------------------
def prune_day(folder: Path | str, keep: list[str]) -> list[str]:
    """Remove the files a day no longer uses.

    A day's folder is rebuilt from scratch each time the theme is written
    again, and a story that gets rewritten leaves its old audio behind.
    The manifest says what the day is made of; anything else in the folder
    is a leftover, and is removed so that the folder describes the card
    exactly.
    """
    folder = Path(folder)
    if not folder.exists():
        return []

    wanted = set(keep)
    removed: list[str] = []
    for path in folder.iterdir():
        if not path.is_file():
            continue
        if path.name == MANIFEST_NAME or path.name in wanted:
            continue
        try:
            path.unlink()
            removed.append(path.name)
        except OSError:  # pragma: no cover - platform dependent
            continue
    return removed


def list_days(work_dir: Path | str) -> list[DayRecord]:
    """Every day that was written out, newest first."""
    work_dir = Path(work_dir)
    if not work_dir.exists():
        return []

    records: list[DayRecord] = []
    for folder in work_dir.iterdir():
        if not folder.is_dir():
            continue
        manifest = read_manifest(folder)
        if not manifest:
            continue
        records.append(
            DayRecord(
                date=str(manifest.get("date") or folder.name.split("-")[0:3] and "-".join(folder.name.split("-")[0:3])),
                slug=str(manifest.get("slug") or folder.name.split("-", 3)[-1]),
                folder=folder,
                manifest=manifest,
            )
        )
    records.sort(key=lambda r: (r.date, r.slug), reverse=True)
    return records


def find_day(
    work_dir: Path | str,
    *,
    day: str = "",
    slug: str = "",
) -> DayRecord | None:
    """Find one saved day.

    ``day`` is the date (``2026-10-26``); ``slug`` is the theme
    (``exoplanets``).  With neither, the most recent day is returned.
    """
    records = list_days(work_dir)
    if day:
        records = [r for r in records if r.date == day]
    if slug:
        records = [r for r in records if r.slug == slug]
    return records[0] if records else None


__all__ = [
    "MANIFEST_NAME",
    "MANIFEST_VERSION",
    "DayRecord",
    "day_folder",
    "find_day",
    "list_days",
    "now_stamp",
    "prune_day",
    "read_manifest",
    "save_transcript",
    "today_slug",
    "track_basename",
    "write_manifest",
]
