"""Media upload and server-side transcoding.

The pipeline the Yoto web app uses is:

1. ``GET /media/transcode/audio/uploadUrl?sha256=..&filename=..&mediaAccount=..``
   returns a short-lived presigned S3 ``PUT`` URL plus an ``uploadId``.
2. ``PUT <uploadUrl>`` the raw audio bytes (with a ``Content-Disposition`` header).
3. Poll ``GET /media/upload/{uploadId}/transcoded`` until the server finishes
   transcoding to OGG/Opus (mono/stereo, -16 LUFS).
4. The media id is the *base64url SHA-256 of the transcoded file* --
   ``"yoto:#" + transcodedSha256``.  It is what ``trackUrl`` must contain.

Step 4 is the non-obvious one: the id is not returned by any endpoint, it is
derived from the ``transcodedSha256`` field of the transcode status.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from .client import YotoClient
from .errors import TranscodeError
from .models import media_id_to_track_url

#: MIME types the Yoto uploader accepts.
ACCEPTED_MIME_TYPES = (
    "audio/mpeg",
    "audio/mp3",
    "audio/wav",
    "audio/x-wav",
    "audio/flac",
    "audio/x-flac",
    "audio/aac",
    "audio/mp4",
    "audio/x-m4a",
    "audio/ogg",
    "audio/opus",
    "audio/webm",
    "audio/x-ms-wma",
    "audio/x-ape",
    "audio/x-wavpack",
)

_MIME_BY_SUFFIX = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".flac": "audio/flac",
    ".aac": "audio/aac",
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
    ".ogg": "audio/ogg",
    ".opus": "audio/opus",
    ".webm": "audio/webm",
    ".wma": "audio/x-ms-wma",
    ".ape": "audio/x-ape",
    ".wv": "audio/x-wavpack",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def guess_mime(path: Path) -> str:
    """Best-effort MIME type for an audio file."""
    return _MIME_BY_SUFFIX.get(path.suffix.lower(), "application/octet-stream")


def sha256_file(path: Path) -> str:
    """Hex SHA-256 of a file's bytes."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class UploadResult:
    """Everything the SDK learned about one uploaded audio file."""

    upload_id: str
    media_id: str
    track_url: str
    duration: int = 0
    file_size: int = 0
    channels: str = "mono"
    format: str = "opus"
    title: str = ""
    transcoded_sha256: str = ""
    raw: dict[str, Any] | None = None

    @property
    def media_id_bare(self) -> str:
        from .models import track_url_to_media_id

        return track_url_to_media_id(self.media_id)


class MediaService:
    """Uploads audio files and waits for the server-side transcode."""

    def __init__(self, client: YotoClient) -> None:
        self.client = client

    # ------------------------------------------------------------------
    def request_upload_url(
        self,
        *,
        filename: str,
        sha256: str,
        media_account: str | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        """Ask the API for a presigned upload URL.

        The endpoint is idempotent per ``(sha256, filename, mediaAccount)``.
        When the same content was uploaded before, the API returns the
        *existing* ``uploadId`` with ``uploadUrl`` set to ``None`` -- there is
        nothing left to upload.
        """
        params: dict[str, Any] = {"filename": filename, "sha256": sha256}
        if media_account:
            params["mediaAccount"] = media_account
        params.update(extra)
        data = self.client.get("/media/transcode/audio/uploadUrl", params=params)
        upload = data.get("upload") or {}
        if not upload.get("uploadId"):
            raise TranscodeError(f"no upload id returned: {data}")
        return upload

    def upload_bytes(
        self,
        payload: bytes,
        *,
        filename: str,
        content_type: str,
        upload_url: str,
        progress: Any = None,
    ) -> None:
        """PUT the raw bytes to the presigned URL."""
        headers = {
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": content_type,
        }
        resp = requests.put(
            upload_url,
            data=payload,
            headers=headers,
            timeout=600,
        )
        if resp.status_code >= 400:
            raise TranscodeError(
                f"upload failed with HTTP {resp.status_code}: {resp.text[:200]}"
            )

    def transcode_status(self, upload_id: str) -> dict[str, Any]:
        """Return the current transcode status for an upload."""
        data = self.client.get(f"/media/upload/{upload_id}/transcoded")
        return data.get("transcode") or {}

    def wait_for_transcode(
        self,
        upload_id: str,
        *,
        timeout: float = 600.0,
        interval: float = 3.0,
    ) -> dict[str, Any]:
        """Poll until the transcode completes or fails."""
        deadline = time.time() + timeout
        last: dict[str, Any] = {}
        while time.time() < deadline:
            last = self.transcode_status(upload_id)
            if last.get("error"):
                raise TranscodeError(
                    f"transcode failed for upload {upload_id}: {last.get('error')}",
                    details=last,
                )
            if last.get("transcodedSha256"):
                return last
            time.sleep(interval)
        raise TranscodeError(
            f"transcode did not finish within {timeout:.0f}s for upload {upload_id}",
            details=last,
        )

    # ------------------------------------------------------------------
    def upload_cover_image(
        self,
        path: Path | str,
        *,
        cover_type: str = "default",
        user_scope: str = "me",
    ) -> dict[str, Any]:
        """Upload a card cover image and return the stored cover descriptor."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(path)
        content_type = guess_mime(path)
        if content_type == "application/octet-stream":
            content_type = "image/png"
        data = self.client.post_bytes(
            f"/media/coverImage/user/{user_scope}/upload",
            path.read_bytes(),
            content_type=content_type,
            params={"coverType": cover_type},
        )
        cover = data.get("coverImage")
        if not cover:
            raise TranscodeError(f"no cover image returned: {data}")
        return cover

    # ------------------------------------------------------------------
    def upload_display_icon(
        self,
        png: bytes,
        *,
        user_scope: str = "me",
        auto_convert: bool = False,
    ) -> dict[str, Any]:
        """Upload a 16x16 pixel-art icon and return its descriptor.

        The icon is the little picture the Yoto app and the player show
        next to a track.  It is a 16x16 PNG with a 24-bit RGBA colour
        format and alpha transparency, and the id it comes back with is
        what goes into a track's ``display.icon16x16``.

        The same endpoint serves the built-in Yoto icon library, so a
        card can also use one of those instead.
        """
        if not png.startswith(b"\x89PNG"):
            raise TranscodeError("a display icon has to be a PNG")
        data = self.client.post_bytes(
            f"/media/displayIcons/user/{user_scope}/upload",
            png,
            content_type="image/png",
            params={"autoConvert": str(auto_convert).lower()},
        )
        icon = data.get("displayIcon")
        if not icon:
            raise TranscodeError(f"no display icon returned: {data}")
        return icon

    def list_display_icons(self, *, user_scope: str = "me") -> list[dict[str, Any]]:
        """The icons this account can use.

        The ``yoto`` scope is Yoto's own library; the ``me`` scope is
        whatever has been uploaded to this account.
        """
        data = self.client.get(f"/media/displayIcons/user/{user_scope}")
        return list(data.get("displayIcons") or [])

    def delete_display_icon(self, media_id: str) -> None:
        """Remove an uploaded icon.

        The delete endpoint is keyed by the icon's ``displayIconId``, not
        by the media id that a track points at, so the media id is looked
        up first.
        """
        display_icon_id = ""
        for icon in self.list_display_icons(user_scope="me"):
            if str(icon.get("mediaId") or "") == str(media_id):
                display_icon_id = str(icon.get("displayIconId") or "")
                break
        if not display_icon_id:
            raise TranscodeError(f"no display icon with the media id {media_id}")
        self.client.delete(f"/media/displayIcon/{display_icon_id}")

    # ------------------------------------------------------------------
    def upload_audio(
        self,
        path: Path | str,
        *,
        media_account: str | None = None,
        title: str | None = None,
        timeout: float = 600.0,
        progress: Any = None,
    ) -> UploadResult:
        """Upload one audio file end to end and return its media id.

        Re-uploading byte-identical content is free: the API recognises the
        hash and returns the already-transcoded media id without transferring
        anything.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(path)

        content_type = guess_mime(path)
        digest = sha256_file(path)
        upload = self.request_upload_url(
            filename=path.name,
            sha256=digest,
            media_account=media_account,
        )
        upload_url = upload.get("uploadUrl")

        if upload_url:
            self.upload_bytes(
                path.read_bytes(),
                filename=path.name,
                content_type=content_type,
                upload_url=upload_url,
                progress=progress,
            )
            status = self.wait_for_transcode(upload["uploadId"], timeout=timeout)
        else:
            # Dedup hit: the content is already on the server.  If the earlier
            # upload finished we can use it straight away.
            status = self.transcode_status(upload["uploadId"])
            if not status.get("transcodedSha256"):
                raise TranscodeError(
                    f"upload {upload['uploadId']} exists but was never transcoded, "
                    "and the API did not issue an upload URL. Re-upload under a "
                    "different filename.",
                    details=status,
                )

        info = status.get("transcodedInfo") or {}
        sha = status.get("transcodedSha256", "")
        media_id = media_id_to_track_url(sha)

        return UploadResult(
            upload_id=upload["uploadId"],
            media_id=media_id,
            track_url=media_id,
            duration=int(info.get("duration") or 0),
            file_size=int(info.get("fileSize") or 0),
            channels=info.get("channels") or "mono",
            format=info.get("format") or "opus",
            title=title or status.get("uploadFilename") or path.stem,
            transcoded_sha256=sha,
            raw=status,
        )
