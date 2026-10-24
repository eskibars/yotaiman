"""Low-level HTTP client for the Yoto API."""

from __future__ import annotations

import time
from typing import Any

import requests

from .auth import YotoAuth
from .errors import ApiError, AuthError, NotFound, ValidationError

API_BASE = "https://api.yotoplay.com"

#: The API only accepts browser-originated calls; it rejects requests with no
#: ``Origin``/``Referer`` pair.
BROWSER_HEADERS = {
    "Origin": "https://my.yotoplay.com",
    "Referer": "https://my.yotoplay.com/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
}


class YotoClient:
    """A thin, retrying wrapper around ``https://api.yotoplay.com``."""

    def __init__(
        self,
        auth: YotoAuth | None = None,
        *,
        base_url: str = API_BASE,
        session: requests.Session | None = None,
        timeout: float = 60.0,
        max_retries: int = 3,
    ) -> None:
        self.auth = auth or YotoAuth()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self._session = session or requests.Session()

    # ------------------------------------------------------------------
    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = dict(BROWSER_HEADERS)
        headers["Authorization"] = f"Bearer {self.auth.get_access_token()}"
        if extra:
            headers.update(extra)
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        headers: dict[str, str] | None = None,
        raw: bool = False,
    ) -> Any:
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        last_error: Exception | None = None

        for attempt in range(self.max_retries):
            try:
                resp = self._session.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    headers=self._headers(headers),
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                last_error = exc
                time.sleep(2**attempt)
                continue

            if resp.status_code == 401:
                # The token may have expired mid-flight: refresh once and retry.
                self.auth.get_token(force_refresh=True)
                last_error = AuthError("Unauthorized")
                continue

            if resp.status_code == 429 or resp.status_code >= 500:
                last_error = ApiError(resp.status_code, resp.text[:200])
                time.sleep(2**attempt)
                continue

            if resp.status_code == 404:
                raise NotFound(404, f"{method} {path} -> not found")

            if resp.status_code >= 400:
                message = resp.text[:300]
                payload: Any = None
                try:
                    payload = resp.json()
                    err = payload.get("error", {})
                    if isinstance(err, dict):
                        message = err.get("message", message)
                    elif isinstance(err, str):
                        message = err
                    else:
                        message = payload.get("message", message)
                except ValueError:
                    pass
                if resp.status_code == 422 or resp.status_code == 400:
                    raise ValidationError(resp.status_code, message, payload=payload)
                raise ApiError(resp.status_code, message, payload=payload)

            if raw:
                return resp.content
            if not resp.content:
                return {}
            try:
                return resp.json()
            except ValueError:
                return resp.text

        raise ApiError(599, f"{method} {path} failed after {self.max_retries} attempts: {last_error}")

    # ------------------------------------------------------------------
    def get(self, path: str, **kwargs: Any) -> Any:
        return self._request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Any:
        return self._request("POST", path, **kwargs)

    def post_bytes(
        self,
        path: str,
        payload: bytes,
        *,
        content_type: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """POST raw bytes to the API (image uploads and similar)."""
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        resp = self._session.post(
            url,
            data=payload,
            params=params,
            headers=self._headers({"Content-Type": content_type}),
            timeout=self.timeout,
        )
        if resp.status_code >= 400:
            raise ApiError(resp.status_code, resp.text[:300])
        try:
            return resp.json()
        except ValueError:
            return resp.text

    def delete(self, path: str, **kwargs: Any) -> Any:
        return self._request("DELETE", path, **kwargs)
