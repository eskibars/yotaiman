"""The plan for a day: what goes on the card, in what order.

A theme is written as pieces -- a story, a song, an explainer, a fact
corner.  A card needs them as numbered tracks with keys, titles and
lengths.  This is the step in between.

Both writers end up here.  The hand-written library and the model are
asked for the same thing -- pieces -- and the plan is what turns those
pieces into the playlist that actually gets published, so the two paths
produce a card in exactly the same shape.

The order matters as much as the content.  A story is followed by the
song that goes with it, and the true parts come last, so a child gets a
story, a song, another story, another song, and then the facts they can
go and check.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

#: The kinds of piece a theme is made of.
SEGMENT_KINDS = ("story", "song", "facts", "explainer")

#: The key of the first track.  Yoto sorts tracks by key, so they are
#: zero padded.
FIRST_KEY = 1


@dataclass
class PlannedTrack:
    """One track on the card, before it has any audio."""

    key: str
    title: str
    #: ``speech`` is narrated, ``music`` is sung.
    kind: str
    #: The kind of piece it came from: story, song, facts, explainer.
    segment: str
    #: The words that get read out.
    text: str = ""
    #: The words that get sung.
    lyrics: str = ""
    #: How the song should sound.
    prompt: str = ""
    #: The world the piece is about, when it helps to say so.
    subject: str = ""
    #: The picture to show next to the track: book, note, star, telescope,
    #: suns, clock or planet.  Empty lets the kind of piece decide.
    icon: str = ""
    #: How long the song should be, in seconds.
    seconds: float = 0.0

    @property
    def is_song(self) -> bool:
        return self.kind == "music"

    @property
    def words(self) -> int:
        return len((self.text or self.lyrics).split())

    @property
    def icon_kind(self) -> str:
        """Which picture suits this track."""
        return self.icon or self.segment

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "kind": self.kind,
            "segment": self.segment,
            "text": self.text,
            "lyrics": self.lyrics,
            "prompt": self.prompt,
            "subject": self.subject,
            "icon": self.icon,
            "seconds": self.seconds,
        }


@dataclass
class Plan:
    """Everything that goes on the card for one day."""

    slug: str
    name: str
    title: str
    tracks: list[PlannedTrack] = field(default_factory=list)
    #: Where the words came from: ``library`` or the name of a writer.
    backend: str = ""
    #: The source the facts were checked against.
    source: str = ""
    #: Anything else worth remembering about how this was made.
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def words(self) -> int:
        return sum(track.words for track in self.tracks)

    @property
    def song_seconds(self) -> float:
        return sum(track.seconds for track in self.tracks if track.is_song)

    @property
    def narration_seconds(self) -> float:
        """Roughly how long the spoken parts run, at a storybook pace.

        This is an estimate from the word count; the real length is
        whatever the narrator produces.
        """
        return self.words / (WORDS_PER_MINUTE / 60.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "name": self.name,
            "title": self.title,
            "backend": self.backend,
            "source": self.source,
            "meta": dict(self.meta),
            "tracks": [track.to_dict() for track in self.tracks],
        }


#: The pace a story is read at when a grown-up reads it to a child who is
#: not quite ready for bed.
WORDS_PER_MINUTE = 145


def _key(index: int) -> str:
    return f"{index:02d}"


def _piece(
    kind: str,
    title: str,
    *,
    text: str = "",
    lyrics: str = "",
    prompt: str = "",
    subject: str = "",
    icon: str = "",
    seconds: float = 0.0,
) -> dict[str, Any]:
    """One piece, in the shape both writers describe their work in."""
    return {
        "kind": kind,
        "title": title,
        "text": text,
        "lyrics": lyrics,
        "prompt": prompt,
        "subject": subject,
        "icon": icon,
        "seconds": seconds,
    }


def build_plan(
    pieces: Iterable[dict[str, Any]],
    *,
    slug: str,
    name: str,
    title: str = "",
    backend: str = "",
    source: str = "",
    meta: dict[str, Any] | None = None,
    song_seconds: float = 120.0,
) -> Plan:
    """Turn a list of pieces into a plan.

    Songs are the only pieces with a length of their own, and a song
    that does not say how long it wants to be gets the default.
    """
    tracks: list[PlannedTrack] = []
    for index, piece in enumerate(pieces, start=FIRST_KEY):
        kind = str(piece.get("kind") or "story")
        seconds = float(piece.get("seconds") or 0.0)
        if kind == "song" and seconds <= 0:
            seconds = float(song_seconds)
        tracks.append(
            PlannedTrack(
                key=_key(index),
                title=str(piece.get("title") or f"Track {index}"),
                kind="music" if kind == "song" else "speech",
                segment=kind,
                text=str(piece.get("text") or ""),
                lyrics=str(piece.get("lyrics") or ""),
                prompt=str(piece.get("prompt") or ""),
                subject=str(piece.get("subject") or ""),
                icon=str(piece.get("icon") or ""),
                seconds=seconds,
            )
        )

    return Plan(
        slug=slug,
        name=name,
        title=title or name,
        tracks=tracks,
        backend=backend,
        source=source,
        meta=dict(meta or {}),
    )


def plan_from_authored(
    theme: Any,
    *,
    song_seconds: float = 120.0,
    source: str = "",
) -> Plan:
    """The plan for a theme written by hand.

    The pieces are used exactly as they were written.  This is the whole
    point of the library: the words were chosen by somebody, and they do
    not get sent through a model on the way to the card.
    """
    pieces = []
    for segment in theme.segments:
        pieces.append(
            _piece(
                segment.kind,
                segment.title,
                text=segment.text,
                lyrics=segment.lyrics,
                prompt=segment.prompt,
                subject=segment.subject,
                icon=getattr(segment, "icon", ""),
                seconds=getattr(segment, "seconds", 0.0),
            )
        )
    return build_plan(
        pieces,
        slug=theme.slug,
        name=theme.name,
        title=theme.title,
        backend="library",
        source=source or getattr(theme, "source", ""),
        meta={"cover_icon": getattr(theme, "icon", "")},
        song_seconds=song_seconds,
    )


def plan_from_theme(
    theme: Any,
    *,
    song_seconds: float = 120.0,
    source: str = "",
) -> Plan:
    """The plan for a theme written by a model.

    A model writes one story, one song and one set of facts, so the plan
    has three tracks.  It is a shorter card than a library theme, and
    that is worth knowing: the library exists to make the long one.
    """
    pieces = []
    if theme.story.strip():
        pieces.append(_piece("story", theme.title, text=theme.story))
    if theme.song_lyrics.strip():
        pieces.append(
            _piece(
                "song",
                theme.song_title or f"The {theme.name} Song",
                lyrics=theme.song_lyrics,
                prompt=theme.song_prompt,
            )
        )
    if theme.facts.strip():
        pieces.append(_piece("facts", "Fact Corner", text=theme.facts))

    return build_plan(
        pieces,
        slug=theme.slug,
        name=theme.name,
        title=theme.title,
        backend=getattr(theme, "backend", "") or "model",
        source=source,
        meta={"text_meta": dict(getattr(theme, "meta", {}) or {})},
        song_seconds=song_seconds,
    )


def filter_plan(plan: Plan, *, songs: bool = True, facts: bool = True) -> Plan:
    """Drop the songs or the true parts, and number what is left again."""
    tracks = []
    for track in plan.tracks:
        if track.is_song and not songs:
            continue
        if track.segment in ("facts", "explainer") and not facts:
            continue
        tracks.append(track)

    for index, track in enumerate(tracks, start=FIRST_KEY):
        track.key = _key(index)

    plan.tracks = tracks
    return plan


__all__ = [
    "FIRST_KEY",
    "Plan",
    "PlannedTrack",
    "SEGMENT_KINDS",
    "WORDS_PER_MINUTE",
    "build_plan",
    "filter_plan",
    "plan_from_authored",
    "plan_from_theme",
]
