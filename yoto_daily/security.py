"""Security helpers for the Yoto Daily service.

Three jobs live here.

**Fetching a caller-supplied URL.**  :func:`safe_fetch` refuses to fetch
anything that points back at the machine the service runs on: only ``http``
and ``https`` are allowed, the host is resolved and every address it
resolves to has to be publicly routable, and each redirect is re-checked
before it is followed.  Without this, a caller could name the loopback
interface, a cloud metadata endpoint, or a service on the local network and
have the service fetch it and hand back the body.

**Turning a caller-supplied path into a safe path.**
:func:`resolve_within` returns an absolute path that is provably inside one
of the configured content directories.  Absolute paths and ``..`` are
resolved first and then checked, so neither traversal nor a symlink pointing
out of the directory can escape.

**Deciding whether a request may proceed.**  The service exposes a personal
account, so the guards here are the perimeter: a bearer token that the
operator has to present, a Host allowlist that stops a rebound DNS name from
reaching the service, and an Origin check that stops another site from
posting to it.
"""

from __future__ import annotations

import hmac
import ipaddress
import os
import re
import socket
import threading
import time
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse

import requests

__all__ = [
    "SecurityError",
    "UnsafePathError",
    "UnsafeURLError",
    "RateLimiter",
    "RateLimited",
    "safe_fetch",
    "read_capped",
    "resolve_within",
    "load_api_token",
    "presented_token",
    "token_matches",
    "host_allowed",
    "origin_allowed",
    "scrub_paths",
]


class SecurityError(Exception):
    """Base class for the guards in this module."""


class UnsafeURLError(SecurityError):
    """The URL is not one the service is willing to fetch."""


class UnsafePathError(SecurityError):
    """The path is not inside one of the configured content directories."""


class RateLimited(SecurityError):
    """The caller has used up its allowance for this window."""


#: An absolute path, with or without a drive letter.
_ABSOLUTE_PATH = re.compile(r"(?:[A-Za-z]:)?(?:[\\/][^\s:,;'\"]+)+")

#: A URL, which is put aside while the paths around it are scrubbed.
_URL = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*://[^\s'\"]+")


def scrub_paths(message: str) -> str:
    """Hide the absolute paths in a message.

    An error usually names the file it was about, and a full path says
    where the account and the machine live.  The name of the file is
    enough for whoever reads it; the full path stays in the service log.
    """
    text = str(message or "")

    # The URLs come out first: their slashes are not paths.
    urls: list[str] = []

    def stash(match: "re.Match[str]") -> str:
        urls.append(match.group(0))
        return f"\x00{len(urls) - 1}\x00"

    text = _URL.sub(stash, text)

    def replace(match: "re.Match[str]") -> str:
        name = re.split(r"[\\/]", match.group(0))[-1]
        return name or match.group(0)

    text = _ABSOLUTE_PATH.sub(replace, text)

    return re.sub(
        r"\x00(\d+)\x00", lambda match: urls[int(match.group(1))], text
    )


# ----------------------------------------------------------------------
# fetching
# ----------------------------------------------------------------------

#: How many redirects :func:`safe_fetch` will follow.
MAX_REDIRECTS = 5

#: How long a single request may take, in seconds.
DEFAULT_TIMEOUT = 30.0


def _parse_url(url: str) -> tuple[str, str]:
    """Return ``(scheme, host)`` for a URL the service is willing to fetch."""
    parsed = urlparse(str(url).strip())
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise UnsafeURLError(f"the '{scheme or 'empty'}' scheme is not allowed")
    try:
        host = parsed.hostname
    except ValueError as exc:
        raise UnsafeURLError("the URL has no usable host") from exc
    if not host:
        raise UnsafeURLError("the URL has no host")
    return scheme, host.lower()


def _resolve(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Every address ``host`` resolves to."""
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"could not resolve {host!r}") from exc
    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for info in infos:
        try:
            addresses.append(ipaddress.ip_address(info[4][0]))
        except ValueError:  # pragma: no cover - defensive
            continue
    if not addresses:
        raise UnsafeURLError(f"{host!r} does not resolve to an address")
    return addresses


def _address_is_public(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Whether an address is safe to send a request to."""
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    ):
        return False
    return bool(address.is_global)


def _assert_public_host(host: str) -> None:
    """Refuse a host that points anywhere but the public internet."""
    # A literal address in the URL is checked directly; a name is resolved
    # and every address it can become is checked.
    literal = host.strip("[]")
    try:
        addresses = [ipaddress.ip_address(literal)]
    except ValueError:
        addresses = _resolve(host)
    for address in addresses:
        if not _address_is_public(address):
            raise UnsafeURLError(
                f"{host!r} resolves to {address}, which is not a public address"
            )


def safe_fetch(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    session: requests.Session | None = None,
) -> requests.Response:
    """Fetch ``url`` after checking that it cannot reach the local network.

    Redirects are followed by hand rather than by ``requests`` so that every
    hop is checked: a public URL that redirects to ``http://127.0.0.1/`` is
    refused rather than followed.

    The response is streamed, so the caller can cap how much it reads.
    """
    current = str(url).strip()
    if not current:
        raise UnsafeURLError("no URL given")

    owns_session = session is None
    http = session or requests.Session()
    try:
        for _ in range(MAX_REDIRECTS + 1):
            _, host = _parse_url(current)
            _assert_public_host(host)

            response = http.request(
                method.upper(),
                current,
                headers=headers,
                timeout=timeout,
                allow_redirects=False,
                stream=True,
            )

            if response.is_redirect or response.is_permanent_redirect:
                location = response.headers.get("Location", "")
                response.close()
                if not location:
                    raise UnsafeURLError("the redirect had no destination")
                current = urljoin(current, location)
                continue

            return response

        raise UnsafeURLError("too many redirects")
    finally:
        if owns_session:
            http.close()


def read_capped(response: requests.Response, limit: int) -> bytes:
    """Read at most ``limit`` bytes from a streamed response."""
    if limit <= 0:
        return b""
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > limit:
            raise SecurityError(f"the response is larger than {limit} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


# ----------------------------------------------------------------------
# paths
# ----------------------------------------------------------------------


def _normalised(path: Path) -> Path:
    return Path(os.path.normcase(str(path)))


def _is_within(child: Path, parent: Path) -> bool:
    try:
        return _normalised(child) == _normalised(parent) or _normalised(
            parent
        ) in _normalised(child).parents
    except (ValueError, OSError):  # pragma: no cover - defensive
        return False


def resolve_within(roots: Iterable[Path | str], candidate: str | Path) -> Path:
    """Resolve ``candidate`` to an absolute path inside one of ``roots``.

    The path is resolved before it is checked, so ``..`` segments and
    symlinks are followed first and then rejected if they land outside.
    """
    roots = [Path(root).expanduser() for root in roots if str(root).strip()]
    if not roots:
        raise UnsafePathError("no content directory is configured")

    raw = str(candidate or "").strip()
    if not raw:
        raise UnsafePathError("no path given")
    if "://" in raw:
        # A URL, not a path.  Treating it as one would put the scheme in
        # the file name.
        raise UnsafePathError(f"{raw!r} is a URL, not a path")

    path = Path(raw).expanduser()
    if path.is_absolute():
        attempts = [path]
    else:
        attempts = [root / path for root in roots]

    for attempt in attempts:
        try:
            resolved = attempt.resolve()
        except OSError as exc:  # pragma: no cover - defensive
            raise UnsafePathError(f"could not resolve {raw!r}") from exc
        for root in roots:
            try:
                root_resolved = root.resolve()
            except OSError:  # pragma: no cover - defensive
                continue
            if _is_within(resolved, root_resolved):
                return resolved

    raise UnsafePathError(
        f"{raw!r} is not inside the content directory; "
        "put the file in one of the configured content directories "
        "or point YOTO_CONTENT_DIRS at it"
    )


# ----------------------------------------------------------------------
# the request guards
# ----------------------------------------------------------------------

#: Environment variable holding the API token.
TOKEN_ENV = "YOTO_API_TOKEN"

#: Environment variable holding extra allowed Host names.
ALLOWED_HOSTS_ENV = "YOTO_ALLOWED_HOSTS"

#: The names that always mean "this machine".
LOOPBACK_NAMES = ("localhost", "127.0.0.1", "::1", "0.0.0.0", "::")


def _write_private_file(path: Path, text: str) -> None:
    """Write a file that only its owner can read, from the first byte."""
    from yoto.auth import write_private_file

    path.parent.mkdir(parents=True, exist_ok=True)
    write_private_file(path, text)


def load_api_token(state_dir: Path | str, *, generate: bool = True) -> str:
    """The token the service expects, from the environment or the state dir.

    The environment wins so a token can be supplied at run time without being
    written to disk.  Otherwise one is generated once and kept beside the
    rest of the service state, readable only by its owner.
    """
    from_env = (os.environ.get(TOKEN_ENV) or "").strip()
    if from_env:
        return from_env

    path = Path(state_dir).expanduser() / "api-token"
    try:
        if path.exists():
            existing = path.read_text().strip()
            if existing:
                return existing
    except OSError:  # pragma: no cover - platform dependent
        pass

    if not generate:
        return ""

    token = os.urandom(24).hex()
    _write_private_file(path, token + "\n")
    return token


def presented_token(request: Any) -> str:
    """The token a request carries, if any.

    A header is preferred; the query string is accepted as well so that the
    HTML desk can be opened straight from a phone, which cannot set headers.
    """
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        candidate = header[7:].strip()
        if candidate:
            return candidate

    for name in ("X-Yoto-Token", "X-Yoto-Api-Token"):
        candidate = (request.headers.get(name) or "").strip()
        if candidate:
            return candidate

    candidate = (request.args.get("token") or "").strip()
    if candidate:
        return candidate

    return ""


def token_matches(candidate: str, expected: str) -> bool:
    """Compare two tokens without leaking their length through timing."""
    if not candidate or not expected:
        return False
    return hmac.compare_digest(candidate, expected)


def allowed_hosts(settings: Any) -> set[str]:
    """The Host names the service answers to."""
    names = {"localhost", "127.0.0.1", "::1"}
    configured = str(getattr(settings, "host", "") or "").strip().lower()
    if configured and configured not in ("0.0.0.0", "::"):
        names.add(configured)
    extra = os.environ.get(ALLOWED_HOSTS_ENV, "")
    for name in extra.replace(";", ",").split(","):
        name = name.strip().lower()
        if name:
            names.add(name)
    return names


def host_allowed(request: Any, settings: Any) -> bool:
    """Whether the request's Host header is one we answer to.

    A rebound DNS name -- one that points at this machine -- would arrive
    with the attacker's own Host header, so this is what stops a name the
    operator never intended to expose from reaching the service.
    """
    host = (request.headers.get("Host") or "").strip().lower()
    if not host:
        return False
    if host.startswith("["):
        name = host.split("]", 1)[0].lstrip("[")
    else:
        name = host.split(":", 1)[0]
    return name in allowed_hosts(settings)


def origin_allowed(request: Any, settings: Any) -> bool:
    """Whether a mutating request came from this service.

    A browser sends ``Origin`` on every POST it makes.  A request that
    carries one from somewhere else is another site trying to use the
    service, and is refused.  ``Referer`` is the fallback for the browsers
    that leave ``Origin`` off.
    """
    origin = (request.headers.get("Origin") or "").strip()
    if origin and origin.lower() != "null":
        parsed = urlparse(origin)
        host = (parsed.hostname or "").lower()
        return bool(host) and host in allowed_hosts(settings)

    referer = (request.headers.get("Referer") or "").strip()
    if referer:
        parsed = urlparse(referer)
        host = (parsed.hostname or "").lower()
        return bool(host) and host in allowed_hosts(settings)

    return False


# ----------------------------------------------------------------------
# a rate limit
# ----------------------------------------------------------------------


class RateLimiter:
    """A sliding-window limit on how often a caller may ask for work.

    The capabilities call out to paid services -- an LLM, a speech
    synthesiser -- so an unbounded caller would spend the operator's money.
    The limit is per caller and per window.
    """

    def __init__(self, limit: int, window: float = 60.0) -> None:
        self.limit = max(0, int(limit))
        self.window = float(window)
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str = "default") -> bool:
        """Whether the caller may proceed.  ``False`` means it may not."""
        if self.limit <= 0:
            return True
        now = time.monotonic()
        with self._lock:
            hits = [t for t in self._hits.get(key, []) if now - t < self.window]
            if len(hits) >= self.limit:
                self._hits[key] = hits
                return False
            hits.append(now)
            self._hits[key] = hits
            return True

    def reset(self, key: str | None = None) -> None:
        """Forget the recorded hits."""
        with self._lock:
            if key is None:
                self._hits.clear()
            else:
                self._hits.pop(key, None)
