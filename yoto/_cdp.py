"""Finding a Chrome DevTools Protocol endpoint.

Chrome can be attached to in two ways, and which one is available depends on
how the browser was started:

``--remote-debugging-port`` with a *non-default* ``--user-data-dir``
    Chrome serves the HTTP discovery endpoints (``/json/version``) *and* the
    WebSocket endpoint.

``chrome://inspect/#remote-debugging``
    Since Chrome 136 the ``--remote-debugging-port`` switch is ignored for the
    default profile directory, so this toggle is the only way to attach to an
    everyday profile.  A browser started this way publishes the WebSocket
    endpoint but answers ``404`` on every ``/json/*`` path.

Reading the WebSocket URL out of ``/json/version`` therefore only works in the
first case.  The second case is resolved from the ``DevToolsActivePort`` file
Chrome writes into the profile directory: it holds the port and the browser
target path, which is all a client needs.

The lookup tries every route and keeps the first one that answers, so the same
code works on a stock macOS install, on a Windows box and inside CI.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from ._ws import WebSocket, WebSocketError, WebSocketTimeout

#: The port Chrome's remote debugging server uses by default.
DEFAULT_CDP_PORT = 9222

#: How long to wait for the DevTools server to answer.
DEFAULT_TIMEOUT = 30.0

#: How long to wait for the WebSocket handshake.  Chrome accepts the TCP
#: connection straight away and only then works out whether it will serve the
#: session, so a busy endpoint shows up as a handshake that never finishes.
CONNECT_TIMEOUT = 10.0


class CdpError(RuntimeError):
    """Raised when no usable DevTools endpoint could be reached."""


# ----------------------------------------------------------------------
# discovery
# ----------------------------------------------------------------------
def chrome_user_data_dirs() -> list[Path]:
    """Where Chrome keeps its profile directories, per platform."""
    override = os.environ.get("YOTO_CHROME_USER_DATA_DIR") or os.environ.get(
        "CHROME_USER_DATA_DIR"
    )
    candidates: list[Path] = []
    if override:
        candidates.append(Path(override).expanduser())

    home = Path.home()
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA") or str(home / "AppData" / "Local")
        base = Path(local)
        candidates += [
            base / "Google" / "Chrome" / "User Data",
            base / "Chromium" / "User Data",
            base / "Microsoft" / "Edge" / "User Data",
            base / "BraveSoftware" / "Brave-Browser" / "User Data",
        ]
    elif sys.platform == "darwin":
        support = home / "Library" / "Application Support"
        candidates += [
            support / "Google" / "Chrome" / "User Data",
            support / "Chromium" / "User Data",
            support / "Microsoft Edge" / "User Data",
            support / "BraveSoftware" / "Brave-Browser" / "User Data",
        ]
    else:
        config = home / ".config"
        candidates += [
            config / "google-chrome",
            config / "chromium",
            config / "microsoft-edge",
            config / "BraveSoftware" / "Brave-Browser",
        ]
    return candidates


def devtools_active_port_files() -> list[Path]:
    """Every ``DevToolsActivePort`` file Chrome has written."""
    found: list[Path] = []
    for directory in chrome_user_data_dirs():
        candidate = directory / "DevToolsActivePort"
        if candidate.is_file():
            found.append(candidate)
    return found


def read_active_port(path: Path | str) -> tuple[int, str] | None:
    """Read ``(port, browser_target_path)`` from a ``DevToolsActivePort`` file.

    The file holds the port on the first line and the browser target path on
    the second, e.g. ``/devtools/browser/<uuid>``.
    """
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    if not lines:
        return None
    try:
        port = int(lines[0].strip())
    except ValueError:
        return None
    target = lines[1].strip() if len(lines) > 1 else ""
    if not target:
        return None
    return port, target


def _http_json(port: int, path: str, timeout: float = 5.0) -> dict[str, Any] | None:
    """GET a JSON document from the DevTools HTTP server, or ``None``."""
    import urllib.request

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=timeout) as resp:
            body = resp.read()
    except Exception:
        return None
    try:
        data = json.loads(body)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def candidate_ws_urls(port: int = DEFAULT_CDP_PORT) -> list[str]:
    """Every WebSocket URL that might be the DevTools endpoint, best first.

    The order is deliberate: the HTTP discovery endpoint when it exists, then
    the ``DevToolsActivePort`` file for the requested port, then the same file
    for any other browser we know about, then the bare browser path.
    """
    urls: list[str] = []

    version = _http_json(port, "/json/version")
    if version:
        ws_url = version.get("webSocketDebuggerUrl")
        if isinstance(ws_url, str) and ws_url:
            urls.append(ws_url)

    entries: list[tuple[int, str]] = []
    for file in devtools_active_port_files():
        entry = read_active_port(file)
        if entry:
            entries.append(entry)

    for file_port, target in entries:
        if file_port == port:
            urls.append(f"ws://127.0.0.1:{file_port}{target}")
    for file_port, target in entries:
        if file_port != port:
            urls.append(f"ws://127.0.0.1:{file_port}{target}")

    # Some builds accept the browser path without the target id.
    urls.append(f"ws://127.0.0.1:{port}/devtools/browser")

    seen: set[str] = set()
    unique: list[str] = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            unique.append(url)
    return unique


# ----------------------------------------------------------------------
# talking to it
# ----------------------------------------------------------------------
def _send(ws: WebSocket, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Send one CDP command and wait for its reply."""
    ws.send_json({"id": 1, "method": method, "params": params or {}})
    while True:
        message = ws.recv_json()
        if isinstance(message, dict) and message.get("id") == 1:
            return message


def get_cookies(
    port: int = DEFAULT_CDP_PORT,
    domain_filter: str = "",
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> list[dict[str, Any]]:
    """Read cookies out of a running Chrome over CDP.

    ``domain_filter`` keeps only the cookies whose domain contains it; an
    empty filter keeps everything.
    """
    errors: list[str] = []
    stalled = False
    for url in candidate_ws_urls(port):
        try:
            ws = WebSocket(url, timeout=CONNECT_TIMEOUT)
        except WebSocketTimeout as exc:
            errors.append(f"{url}: {exc}")
            stalled = True
            continue
        except (OSError, WebSocketError) as exc:
            errors.append(f"{url}: {exc}")
            continue

        ws.set_timeout(timeout)
        try:
            reply = _send(ws, "Storage.getCookies")
            if "error" in reply:
                errors.append(f"{url}: {reply['error']}")
                continue
            cookies = (reply.get("result") or {}).get("cookies") or []
        except (OSError, WebSocketError, ValueError) as exc:
            errors.append(f"{url}: {exc}")
            continue
        finally:
            ws.close()

        return [
            {
                "name": c.get("name", ""),
                "value": c.get("value", ""),
                "domain": c.get("domain", ""),
                "path": c.get("path", "/"),
            }
            for c in cookies
            if not domain_filter or domain_filter in c.get("domain", "")
        ]

    detail = "\n  ".join(errors) if errors else "no DevTools endpoint found"
    if stalled:
        detail += (
            "\n\nChrome accepted the connection but never completed the DevTools "
            "handshake.\nIts remote debugging server is holding an earlier "
            "session and is not taking new ones yet.\nIt clears by itself, but "
            "it wants the browser left alone -- ten quiet minutes is what it "
            "took here. Retrying straight away keeps Chrome busy.\nIf it does "
            "not clear, turn remote debugging off and on again:\n"
            "  chrome://inspect/#remote-debugging  ->  Disable, then Enable"
        )
    raise CdpError(f"could not read cookies from Chrome over CDP:\n  {detail}")


# ----------------------------------------------------------------------
# instructions
# ----------------------------------------------------------------------
def chrome_launch_hint(port: int = DEFAULT_CDP_PORT) -> str:
    """Platform-appropriate instructions for exposing a DevTools endpoint."""
    if sys.platform == "win32":
        binaries = [
            r'"C:\Program Files\Google\Chrome\Application\chrome.exe"',
            r'"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"',
        ]
    elif sys.platform == "darwin":
        binaries = [
            "/Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome",
            "google-chrome",
        ]
    else:
        binaries = ["google-chrome", "chromium"]

    launch = "\n".join(f"  {b} --remote-debugging-port={port} --user-data-dir=<empty dir>"
                       for b in binaries)
    return (
        "Turn on Chrome's remote debugging, then sign in to Yoto in that Chrome:\n"
        "  chrome://inspect/#remote-debugging  ->  Enable\n"
        "\n"
        "That is the route that works with your everyday profile: since Chrome 136\n"
        "--remote-debugging-port is ignored for the default profile directory.\n"
        "\n"
        "Or start a separate Chrome on a throwaway profile:\n"
        f"{launch}\n"
        "\n"
        "A throwaway profile is not signed in, so sign in to Yoto in it first."
    )


__all__ = [
    "CdpError",
    "DEFAULT_CDP_PORT",
    "candidate_ws_urls",
    "chrome_launch_hint",
    "chrome_user_data_dirs",
    "devtools_active_port_files",
    "get_cookies",
    "read_active_port",
]
