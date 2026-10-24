"""Card (content) operations against the Yoto API."""

from __future__ import annotations

from typing import Any

from .client import YotoClient
from .errors import NotFound
from .models import Card, CardContent, Chapter, Track, media_id_to_track_url


def shuffle_range(chapter_count: int) -> list[dict[str, Any]]:
    """The shuffle range the Yoto app writes for ``chapter_count`` chapters.

    The app's own builder is ``[{start: 0, end: n - 1, limit: n}]``.  It emits
    nothing for an empty card, but an empty card can still have shuffle
    *switched on*, so a minimum range is used to keep the intent.
    """
    count = max(int(chapter_count), 0)
    if count < 1:
        return [{"start": 0, "end": 0, "limit": 1}]
    return [{"start": 0, "end": count - 1, "limit": count}]


def refresh_shuffle(content: CardContent) -> CardContent:
    """Keep an enabled shuffle range in step with the chapter count.

    The range covers chapter indices, so it has to be recomputed whenever
    chapters are added or removed.
    """
    config = dict(content.config)
    shuffle = config.get("shuffle")
    if shuffle:
        config["shuffle"] = shuffle_range(len(content.chapters))
    content.config = config
    return content


def apply_playback_options(
    content: CardContent,
    *,
    always_play_from_start: bool | None = None,
    shuffle: bool | None = None,
    hide_track_numbers: bool | None = None,
) -> CardContent:
    """Apply the three playback switches, the way the Yoto web app does.

    ``always_play_from_start``
        ``config.resumeTimeout = 0``.  The default is 2592000 seconds (30
        days), after which the player forgets its position.

    ``shuffle``
        ``config.shuffle = [{start: 0, end: n-1, limit: n}]`` over the
        chapters, where ``n`` is the chapter count.  The range is recomputed
        on every save, so switching shuffle on for an empty card keeps the
        switch on once tracks arrive.

    ``hide_track_numbers``
        Removes the ``overlayLabel`` from every chapter and track and sets
        ``editSettings.autoOverlayLabels`` to ``"disabled"``.
    """
    config = dict(content.config)

    if always_play_from_start is not None:
        config["resumeTimeout"] = 0 if always_play_from_start else 2592000

    if shuffle is not None:
        config["shuffle"] = shuffle_range(len(content.chapters)) if shuffle else []

    content.config = config

    if hide_track_numbers is not None:
        edit = dict(content.edit_settings or {})
        if hide_track_numbers:
            edit["autoOverlayLabels"] = "disabled"
            for chapter in content.chapters:
                chapter.overlay_label = None
                for track in chapter.tracks:
                    track.overlay_label = None
        else:
            edit.pop("autoOverlayLabels", None)
            for index, chapter in enumerate(content.chapters):
                label = str(index + 1)
                chapter.overlay_label = label
                for track_index, track in enumerate(chapter.tracks):
                    track.overlay_label = label if track_index == 0 else track.overlay_label
        content.edit_settings = edit or None

    return content


class CardService:
    """Create, read, update and delete the cards ("content") of an account.

    The API exposes card writes as an *upsert*: ``POST /content`` with a
    ``cardId`` in the body updates that card, and without one creates a new
    card.  ``PUT /content/{id}`` is a different (S3-backed) operation and is
    rejected for normal use -- always go through :meth:`save`.
    """

    def __init__(self, client: YotoClient) -> None:
        self.client = client

    # ------------------------------------------------------------------
    # reads
    # ------------------------------------------------------------------
    def list(self) -> list[Card]:
        """Return every card owned by the authenticated user."""
        data = self.client.get("/content/mine")
        return [Card.from_dict(c) for c in (data or {}).get("cards", [])]

    def get(self, card_id: str) -> Card:
        """Return one card by id."""
        data = self.client.get(f"/content/{card_id}")
        return Card.from_dict(data.get("card") or data)

    def exists(self, card_id: str) -> bool:
        """Return whether a card currently exists.

        This checks ``/content/mine`` rather than fetching the card directly:
        the API serves reads of *deleted* cards from an edge cache for a short
        while after the delete, so a direct ``GET`` is not a reliable test of
        existence.
        """
        return any(c.card_id == card_id for c in self.list())

    def media_url(self, card_id: str, media_id: str, *, accel: bool = False) -> str:
        """Return a time-limited signed URL for a media file on this card."""
        from urllib.parse import quote

        data = self.client.get(
            f"/card/{card_id}/media/{quote(media_id, safe='')}",
            params={"accel": str(accel).lower()},
        )
        url = (data.get("media") or {}).get("url")
        if not url:
            raise NotFound(404, f"no media url for {media_id}")
        return url

    # ------------------------------------------------------------------
    # writes
    # ------------------------------------------------------------------
    def create(self, title: str = "", content: CardContent | None = None) -> Card:
        """Create a new card and return it."""
        body: dict[str, Any] = {"content": (content or CardContent()).to_dict()}
        if title:
            body["title"] = title
        data = self.client.post("/content", json_body=body)
        return Card.from_dict(data.get("card") or data)

    def save(self, card: Card) -> Card:
        """Persist a card (create or update, depending on ``card_id``).

        The API echoes the submitted payload back rather than the persisted
        state: it normalises track durations and file sizes asynchronously
        after the write.  Use :meth:`save_and_refresh` when you need the
        server's authoritative values.
        """
        body: dict[str, Any] = {
            "title": card.title,
            "content": card.content.to_dict(),
        }
        if card.card_id:
            body["cardId"] = card.card_id
        data = self.client.post("/content", json_body=body)
        return Card.from_dict(data.get("card") or data)

    def save_and_refresh(self, card: Card) -> Card:
        """Save a card and re-read it, returning the persisted state."""
        self.save(card)
        return self.get(card.card_id)

    def update_content(self, card_id: str, content: CardContent, *, title: str | None = None) -> Card:
        """Replace the chapters of an existing card."""
        refresh_shuffle(content)
        card = Card(card_id=card_id, title=title or "", content=content)
        return self.save(card)

    def update_metadata(
        self,
        card_id: str,
        *,
        description: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> Card:
        """Update the card's metadata (its description lives there)."""
        card = self.get(card_id)
        metadata = dict(card.metadata or {})
        if description is not None:
            metadata["description"] = description
        if extra:
            metadata.update(extra)

        body: dict[str, Any] = {
            "cardId": card_id,
            "title": card.title,
            "content": card.content.to_dict(),
            "metadata": metadata,
        }
        data = self.client.post("/content", json_body=body)
        return Card.from_dict(data.get("card") or data)

    # ------------------------------------------------------------------
    # reset / delete
    # ------------------------------------------------------------------
    def reset(
        self,
        card_id: str,
        *,
        title: str | None = None,
        description: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> Card:
        """Clear every track from a card, keeping the card itself.

        ``options`` accepts the playback switches: ``always_play_from_start``,
        ``shuffle`` and ``hide_track_numbers``.
        """
        card = self.get(card_id)
        content = CardContent(
            chapters=[],
            activity=card.content.activity,
            playback_type=card.content.playback_type,
            version=card.content.version,
            config=dict(card.content.config),
            edit_settings=dict(card.content.edit_settings or {}) or None,
        )

        if options:
            apply_playback_options(content, **options)

        body: dict[str, Any] = {
            "cardId": card_id,
            "title": title if title is not None else card.title,
            "content": content.to_dict(),
        }
        if description is not None:
            metadata = dict(card.metadata or {})
            metadata["description"] = description
            body["metadata"] = metadata

        data = self.client.post("/content", json_body=body)
        return Card.from_dict(data.get("card") or data)

    def delete_track(
        self,
        card_id: str,
        key: str,
        *,
        chapter: str | None = None,
    ) -> Card:
        """Delete one track from a card by its key.

        ``chapter`` narrows the search when the same key appears in more than
        one chapter.  Empty chapters left behind are removed.
        """
        card = self.get(card_id)
        chapters = list(card.content.chapters)

        removed = False
        for chapter_obj in chapters:
            if chapter is not None and chapter_obj.key != chapter:
                continue
            before = len(chapter_obj.tracks)
            chapter_obj.tracks = [t for t in chapter_obj.tracks if t.key != key]
            if len(chapter_obj.tracks) != before:
                removed = True
                if chapter is not None:
                    break

        if not removed:
            raise NotFound(
                404, f"no track with key {key!r} on card {card_id}"
            )

        chapters = [c for c in chapters if c.tracks]
        content = CardContent(
            chapters=chapters,
            activity=card.content.activity,
            playback_type=card.content.playback_type,
            version=card.content.version,
            config=dict(card.content.config),
            edit_settings=card.content.edit_settings,
        )
        return self.update_content(card_id, content, title=card.title)

    def add_tracks(
        self,
        card_id: str,
        tracks: list[Track],
        *,
        chapter_title: str = "",
        chapter_key: str | None = None,
        append_to_chapter: str | None = None,
    ) -> Card:
        """Append tracks to a card, creating a chapter when needed."""
        card = self.get(card_id)
        chapters = [Chapter.from_dict(c.to_dict()) for c in card.content.chapters]

        if append_to_chapter:
            for chapter_obj in chapters:
                if chapter_obj.key == append_to_chapter:
                    chapter_obj.tracks.extend(tracks)
                    break
            else:
                chapters.append(
                    self.build_chapter(
                        append_to_chapter, chapter_title or append_to_chapter, tracks
                    )
                )
        else:
            key = chapter_key or f"{len(chapters):02d}"
            chapters.append(self.build_chapter(key, chapter_title or key, tracks))

        content = CardContent(
            chapters=chapters,
            activity=card.content.activity,
            playback_type=card.content.playback_type,
            version=card.content.version,
            config=dict(card.content.config),
            edit_settings=card.content.edit_settings,
        )
        return self.update_content(card_id, content, title=card.title)

    def set_options(
        self,
        card_id: str,
        *,
        always_play_from_start: bool | None = None,
        shuffle: bool | None = None,
        hide_track_numbers: bool | None = None,
    ) -> Card:
        """Change a card's playback options."""
        card = self.get(card_id)
        content = CardContent(
            chapters=card.content.chapters,
            activity=card.content.activity,
            playback_type=card.content.playback_type,
            version=card.content.version,
            config=dict(card.content.config),
            edit_settings=card.content.edit_settings,
        )
        apply_playback_options(
            content,
            always_play_from_start=always_play_from_start,
            shuffle=shuffle,
            hide_track_numbers=hide_track_numbers,
        )
        return self.update_content(card_id, content, title=card.title)

    def delete(self, card_id: str) -> bool:
        """Delete a card."""
        self.client.delete(f"/content/{card_id}")
        return True

    # ------------------------------------------------------------------
    # convenience builders
    # ------------------------------------------------------------------
    @staticmethod
    def build_content(
        chapters: list[Chapter],
        *,
        cover: dict[str, Any] | None = None,
        playback_type: str = "linear",
    ) -> CardContent:
        """Assemble a :class:`CardContent` from chapters."""
        return CardContent(
            chapters=chapters,
            cover=cover,
            playback_type=playback_type,
            config={"resumeTimeout": 2592000, "onlineOnly": False},
        )

    @staticmethod
    def build_chapter(
        key: str,
        title: str,
        tracks: list[Track],
        *,
        display: dict[str, Any] | None = None,
        overlay_label: str | None = None,
    ) -> Chapter:
        """Assemble a :class:`Chapter` and recompute its aggregates."""
        chapter = Chapter(
            key=key,
            title=title,
            tracks=tracks,
            display=display or {},
            overlay_label=overlay_label,
        )
        chapter.duration = sum(t.duration for t in tracks)
        chapter.file_size = sum(t.file_size for t in tracks)
        return chapter

    @staticmethod
    def build_stream_track(
        key: str,
        url: str,
        *,
        title: str = "",
        fmt: str = "mp3",
    ) -> Track:
        """Build a track that streams from a URL.

        The Yoto app puts the URL itself in both ``trackUrl`` and ``title``;
        a stream track carries no media id.
        """
        return Track(
            key=key,
            title=title or url,
            track_url=url,
            format=fmt,
            type="stream",
            duration=0,
            file_size=0,
        )

    @staticmethod
    def build_track(
        key: str,
        title: str,
        media_id: str,
        *,
        duration: int = 0,
        file_size: int = 0,
        fmt: str = "aac",
        icon_media_id: str | None = None,
        channels: str = "mono",
    ) -> Track:
        """Assemble a :class:`Track` pointing at an uploaded media file."""
        display: dict[str, Any] = {}
        if icon_media_id:
            display["icon16x16"] = media_id_to_track_url(icon_media_id)
        return Track(
            key=key,
            title=title,
            track_url=media_id_to_track_url(media_id),
            format=fmt,
            duration=duration,
            file_size=file_size,
            channels=channels,
            display=display,
        )
