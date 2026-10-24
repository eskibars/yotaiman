"""Data model for Yoto card content.

The wire format is the shape returned by ``GET /content/{cardId}``.  A card is
``card -> content -> chapters[] -> tracks[]``; each track points at an uploaded
media file through ``trackUrl = "yoto:#" + media_id``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator

YOTO_PREFIX = "yoto:#"

#: Accepted by the player for ``track.format``.
TRACK_FORMATS = ("aac", "opus", "ogg", "mp3", "m4a", "wav")

#: Accepted by the player for ``card.content.activity``.
ACTIVITIES = ("yoto_Player",)


def media_id_to_track_url(media_id: str) -> str:
    """Turn a bare media id into the ``yoto:#`` form used by ``trackUrl``."""
    return media_id if media_id.startswith(YOTO_PREFIX) else f"{YOTO_PREFIX}{media_id}"


def track_url_to_media_id(track_url: str) -> str:
    """Strip the ``yoto:#`` prefix from a track URL."""
    return track_url[len(YOTO_PREFIX):] if track_url.startswith(YOTO_PREFIX) else track_url


@dataclass
class Track:
    """One playable audio item inside a chapter."""

    key: str
    title: str
    track_url: str
    format: str = "aac"
    type: str = "audio"
    duration: int = 0
    file_size: int = 0
    channels: str = "mono"
    display: dict[str, Any] = field(default_factory=dict)
    overlay_label: str | None = None
    ambient: dict[str, Any] | None = None

    @property
    def media_id(self) -> str:
        """The bare media id this track resolves to."""
        return track_url_to_media_id(self.track_url)

    @property
    def icon_media_id(self) -> str | None:
        """The 16x16 cover icon, if one is set."""
        icon = self.display.get("icon16x16")
        return track_url_to_media_id(icon) if icon else None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Track":
        return cls(
            key=data.get("key", ""),
            title=data.get("title", ""),
            track_url=data.get("trackUrl", ""),
            format=data.get("format", "aac"),
            type=data.get("type", "audio"),
            duration=int(data.get("duration") or 0),
            file_size=int(data.get("fileSize") or 0),
            channels=data.get("channels", "mono"),
            display=data.get("display") or {},
            overlay_label=data.get("overlayLabel"),
            ambient=data.get("ambient"),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "key": self.key,
            "title": self.title,
            "trackUrl": self.track_url,
            "format": self.format,
            "type": self.type,
            "duration": self.duration,
            "fileSize": self.file_size,
            "channels": self.channels,
        }
        if self.display:
            out["display"] = self.display
        if self.overlay_label is not None:
            out["overlayLabel"] = self.overlay_label
        if self.ambient is not None:
            out["ambient"] = self.ambient
        return out


@dataclass
class Chapter:
    """A group of tracks, shown as one entry in the player's chapter list."""

    key: str
    title: str
    tracks: list[Track] = field(default_factory=list)
    display: dict[str, Any] = field(default_factory=dict)
    overlay_label: str | None = None
    duration: int = 0
    file_size: int = 0
    ambient: dict[str, Any] | None = None
    default_track_display: dict[str, Any] | None = None
    default_track_ambient: dict[str, Any] | None = None

    @property
    def total_duration(self) -> int:
        return sum(t.duration for t in self.tracks)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Chapter":
        return cls(
            key=data.get("key", ""),
            title=data.get("title", ""),
            tracks=[Track.from_dict(t) for t in data.get("tracks", [])],
            display=data.get("display") or {},
            overlay_label=data.get("overlayLabel"),
            duration=int(data.get("duration") or 0),
            file_size=int(data.get("fileSize") or 0),
            ambient=data.get("ambient"),
            default_track_display=data.get("defaultTrackDisplay"),
            default_track_ambient=data.get("defaultTrackAmbient"),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "key": self.key,
            "title": self.title,
            "tracks": [t.to_dict() for t in self.tracks],
        }
        if self.display:
            out["display"] = self.display
        if self.overlay_label is not None:
            out["overlayLabel"] = self.overlay_label
        if self.ambient is not None:
            out["ambient"] = self.ambient
        if self.default_track_display is not None:
            out["defaultTrackDisplay"] = self.default_track_display
        if self.default_track_ambient is not None:
            out["defaultTrackAmbient"] = self.default_track_ambient
        return out


@dataclass
class CardContent:
    """The playable body of a card.

    ``config`` carries the playback options the Yoto web app exposes:

    ``resumeTimeout``
        ``0`` means "always play from start"; the default is 2592000 (30
        days), after which the player forgets where it was.
    ``shuffle``
        A list of ``{start, end, limit}`` ranges.  The app writes a single
        range covering every chapter, with ``limit`` equal to the chapter
        count.
    ``trackNumberOverlayTimeout``
        ``0`` hides the track-number overlay.
    """

    chapters: list[Chapter] = field(default_factory=list)
    activity: str = "yoto_Player"
    playback_type: str = "linear"
    version: str = "1"
    config: dict[str, Any] = field(
        default_factory=lambda: {"resumeTimeout": 2592000, "onlineOnly": False}
    )
    cover: dict[str, Any] | None = None
    edit_settings: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CardContent":
        return cls(
            chapters=[Chapter.from_dict(c) for c in data.get("chapters", [])],
            activity=data.get("activity", "yoto_Player"),
            playback_type=data.get("playbackType", "linear"),
            version=str(data.get("version", "1")),
            config=data.get("config") or {"resumeTimeout": 2592000, "onlineOnly": False},
            cover=data.get("cover"),
            edit_settings=data.get("editSettings"),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "activity": self.activity,
            "playbackType": self.playback_type,
            "version": self.version,
            "config": self.config,
            "chapters": [c.to_dict() for c in self.chapters],
        }
        if self.cover:
            out["cover"] = self.cover
        if self.edit_settings:
            out["editSettings"] = self.edit_settings
        return out

    def iter_tracks(self) -> Iterator[Track]:
        for chapter in self.chapters:
            yield from chapter.tracks

    @property
    def total_duration(self) -> int:
        return sum(t.duration for t in self.iter_tracks())


@dataclass
class Card:
    """A card plus its metadata.

    ``GET /content/mine`` returns summaries: it carries ``metadata.media``
    (the card's total duration and size) but no chapters.  ``GET /content/{id}``
    returns the full body.  :attr:`duration` copes with both.
    """

    card_id: str
    title: str = ""
    content: CardContent = field(default_factory=CardContent)
    metadata: dict[str, Any] = field(default_factory=dict)
    user_id: str = ""
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Card":
        return cls(
            card_id=data.get("cardId", ""),
            title=data.get("title", ""),
            content=CardContent.from_dict(data.get("content") or {}),
            metadata=data.get("metadata") or {},
            user_id=data.get("userId", ""),
            created_at=data.get("createdAt", ""),
            updated_at=data.get("updatedAt", ""),
        )

    @property
    def duration(self) -> int:
        """Total playtime in seconds.

        Prefers the chapter total when the chapters are loaded, and falls back
        to the metadata summary for list responses.
        """
        if self.content.chapters:
            return self.content.total_duration
        media = self.metadata.get("media") or {}
        return int(media.get("duration") or 0)

    @property
    def file_size(self) -> int:
        if self.content.chapters:
            return sum(c.file_size for c in self.content.chapters)
        media = self.metadata.get("media") or {}
        return int(media.get("fileSize") or 0)

    @property
    def is_summary(self) -> bool:
        """Whether this card came back without its chapters."""
        return not self.content.chapters

    @property
    def description(self) -> str:
        """The card's description, which lives in the metadata."""
        return str((self.metadata or {}).get("description") or "")

    @property
    def cover_url(self) -> str:
        """The card's cover image URL, if it has one."""
        cover = (self.metadata or {}).get("cover") or {}
        return str(cover.get("imageL") or "")

    def chapter_titles(self) -> Iterable[str]:
        return (c.title for c in self.content.chapters)
