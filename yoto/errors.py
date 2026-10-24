"""Exception hierarchy for the Yoto SDK."""

from __future__ import annotations


class YotoError(Exception):
    """Base class for every error raised by this SDK."""


class AuthError(YotoError):
    """Authentication failed or the stored session is no longer usable."""


class SessionExpired(AuthError):
    """The cached Auth0 session can no longer mint tokens silently.

    Raise ``relogin_instructions`` to the operator: the cookie jar has to be
    refreshed from a browser that is still signed in to Yoto.
    """

    def __init__(self, message: str = "Yoto session expired") -> None:
        super().__init__(message)
        self.relogin_instructions = (
            "Open https://my.yotoplay.com in a logged-in Chrome, then run "
            "`python -m yoto.auth bootstrap` to refresh the cookie jar."
        )


class ApiError(YotoError):
    """The API returned a non-2xx response."""

    def __init__(self, status: int, message: str, *, payload: object = None) -> None:
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.message = message
        self.payload = payload


class NotFound(ApiError):
    """The requested card, media or track does not exist."""


class ValidationError(ApiError):
    """The API rejected the submitted payload."""


class TranscodeError(YotoError):
    """The server-side transcode of an uploaded audio file failed."""

    def __init__(self, message: str, *, details: object = None) -> None:
        super().__init__(message)
        self.details = details
