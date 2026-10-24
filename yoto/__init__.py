"""A Python SDK for the Yoto API.

Quick start::

    from yoto import Yoto

    y = Yoto()
    for card in y.cards.list():
        print(card.card_id, card.title)

    upload = y.media.upload_audio("story.mp3")
    y.cards.update_content("CARD_ID", ...)

See ``README.md`` for the full walkthrough.
"""

from __future__ import annotations

from .auth import CachedToken, YotoAuth
from .cards import CardService
from .client import API_BASE, YotoClient
from .errors import (
    ApiError,
    AuthError,
    NotFound,
    SessionExpired,
    TranscodeError,
    ValidationError,
    YotoError,
)
from .media import MediaService, UploadResult
from .models import Card, CardContent, Chapter, Track

__version__ = "0.1.0"

__all__ = [
    "Yoto",
    "YotoAuth",
    "YotoClient",
    "CachedToken",
    "CardService",
    "MediaService",
    "UploadResult",
    "Card",
    "CardContent",
    "Chapter",
    "Track",
    "API_BASE",
    "YotoError",
    "ApiError",
    "AuthError",
    "SessionExpired",
    "NotFound",
    "ValidationError",
    "TranscodeError",
]


class Yoto:
    """Facade that bundles the API services together."""

    def __init__(self, auth: YotoAuth | None = None, client: YotoClient | None = None) -> None:
        self.auth = auth or YotoAuth()
        self.client = client or YotoClient(self.auth)
        self.cards = CardService(self.client)
        self.media = MediaService(self.client)

    @classmethod
    def from_token(cls, token: str) -> "Yoto":
        """Build a client around an existing access token (no login needed)."""

        class _StaticAuth(YotoAuth):
            def get_access_token(self, *, force_refresh: bool = False) -> str:  # type: ignore[override]
                return token

            def get_token(self, *, force_refresh: bool = False) -> CachedToken:  # type: ignore[override]
                import time

                return CachedToken(access_token=token, expires_at=time.time() + 3600)

        return cls(auth=_StaticAuth())  # type: ignore[arg-type]
