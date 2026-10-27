"""The little pictures that sit next to each track.

A Yoto card can carry a 16x16 picture for every track: a book for a
story, a note for a song, a star for the facts.  The player and the app
both show it, and it is most of what makes a card feel like it was made
for the person listening to it.

The pictures are drawn by :mod:`yoto_daily.pixelart`.  This module is the
half of the job that talks to Yoto: it uploads a picture once, remembers
the id it came back with, and hands the same id to every track that wants
the same picture.  A card with six tracks does not need six copies of the
same book.

The ids are remembered in the state file, so the next morning reuses them
instead of filling the account with duplicates.
"""

from __future__ import annotations

import hashlib
from typing import Any

from . import pixelart


class IconLibrary:
    """The pixel art on Yoto's servers, one copy per picture."""

    def __init__(self, yoto: Any, state: Any = None) -> None:
        self.yoto = yoto
        self.state = state
        self._known: dict[str, str] = {}
        self._uploaded: set[str] = set()
        self._listed = False

    # ------------------------------------------------------------------
    def _state_key(self) -> str:
        return "display_icons"

    def _load(self) -> None:
        if self._known or self._listed:
            return
        self._listed = True
        if self.state is None:
            return
        stored = self.state.get(self._state_key(), "") or {}
        if isinstance(stored, dict):
            self._known = {str(k): str(v) for k, v in stored.items() if v}

    def _save(self) -> None:
        if self.state is None:
            return
        self.state.set(self._state_key(), dict(self._known))

    # ------------------------------------------------------------------
    def _account_icons(self) -> set[str]:
        """The ids of the icons this account already has."""
        try:
            icons = self.yoto.media.list_display_icons(user_scope="me")
        except Exception:
            return set()
        found = set()
        for icon in icons:
            media_id = str(icon.get("mediaId") or "")
            if media_id:
                found.add(media_id)
        return found

    # ------------------------------------------------------------------
    def media_id(self, kind: str, subject: str = "", title: str = "", icon: str = "") -> str:
        """The id of the icon for a track, uploading the picture if needed.

        An empty string means the icon could not be uploaded; the track is
        then published without one rather than not at all.
        """
        png = pixelart.icon_for(kind, subject, title, icon)
        digest = hashlib.sha256(png).hexdigest()

        self._load()
        if digest in self._known and digest not in self._uploaded:
            known = self._known[digest]
            if known in self._account_icons():
                self._uploaded.add(digest)
                return known

        try:
            icon = self.yoto.media.upload_display_icon(
                png, user_scope="me", auto_convert=False
            )
        except Exception:
            return ""

        media_id = str(icon.get("mediaId") or "")
        if not media_id:
            return ""
        self._known[digest] = media_id
        self._uploaded.add(digest)
        self._save()
        return media_id

    # ------------------------------------------------------------------
    def describe(self) -> dict[str, Any]:
        """What the library knows, for the manifest."""
        self._load()
        return {
            "shapes": pixelart.names(),
            "uploaded": len(self._known),
        }


__all__ = ["IconLibrary"]
