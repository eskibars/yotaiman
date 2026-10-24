"""Cookie-jar bootstrap for the Yoto SDK.

The Yoto web app signs in with Auth0 and keeps the session in cookies on
``login.yotoplay.com``.  The SDK replays those cookies to mint access tokens
without a browser, so it needs a copy of that cookie jar on disk.

Usage::

    python -m yoto.auth bootstrap            # pull cookies from a running Chrome
    python -m yoto.auth bootstrap --cdp 9222
    python -m yoto.auth status               # show the current session
    python -m yoto.auth token                # print a fresh access token

``bootstrap`` needs Chrome started with a remote debugging port, e.g.::

    /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome \\
        --remote-debugging-port=9222
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .auth import YotoAuth


def _cdp_cookies(port: int, domain_filter: str = "login.yotoplay.com") -> list[dict[str, Any]]:
    """Pull cookies from a Chrome instance exposing CDP on ``port``."""
    import urllib.request

    from ._ws import WebSocket

    with urllib.request.urlopen(f"http://localhost:{port}/json/version", timeout=5) as resp:
        version = json.loads(resp.read())

    ws_url = version["webSocketDebuggerUrl"]
    with WebSocket(ws_url) as ws:
        ws.send_json({"id": 1, "method": "Storage.getCookies", "params": {}})
        while True:
            msg = ws.recv_json()
            if msg.get("id") == 1:
                cookies = msg.get("result", {}).get("cookies", [])
                break

    return [
        {
            "name": c["name"],
            "value": c["value"],
            "domain": c["domain"],
            "path": c.get("path", "/"),
        }
        for c in cookies
        if domain_filter in c.get("domain", "")
    ]


def cmd_bootstrap(args: argparse.Namespace) -> int:
    auth = YotoAuth(state_dir=args.state_dir)
    print(f"Looking for Chrome on CDP port {args.cdp_port} ...")
    try:
        cookies = _cdp_cookies(args.cdp_port)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"Could not reach Chrome via CDP: {exc}")
        print(
            "\nStart Chrome with remote debugging enabled:\n"
            "  /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome "
            "--remote-debugging-port=9222"
        )
        return 1

    if not cookies:
        print("No login.yotoplay.com cookies found. Is Chrome signed in to Yoto?")
        return 1

    auth.save_cookies(cookies)
    print(f"Saved {len(cookies)} cookies to {auth.cookies_file}:")
    for c in cookies:
        print(f"  {c['name']} ({c['domain']})")

    try:
        token = auth.get_token(force_refresh=True)
    except Exception as exc:
        print(f"\nCookies saved, but the first token exchange failed: {exc}")
        return 1
    print(f"\nAuthenticated. Token expires in {token.seconds_left / 3600:.1f} h")
    print(f"Scopes: {token.scope}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    auth = YotoAuth(state_dir=args.state_dir)
    cookies = auth.load_cookies()
    print(f"cookie jar : {auth.cookies_file} ({len(cookies)} cookies)")
    cached = auth.load_cached_token()
    if cached:
        print(f"token      : cached, {cached.seconds_left / 3600:.1f} h left")
    else:
        print("token      : not cached")
    try:
        claims = auth.whoami()
    except Exception as exc:
        print(f"session    : cannot mint a token ({exc})")
        return 1
    print(f"subject    : {claims.get('sub')}")
    print(f"scopes     : {claims.get('scope')}")
    return 0


def cmd_token(args: argparse.Namespace) -> int:
    auth = YotoAuth(state_dir=args.state_dir)
    print(auth.get_access_token(force_refresh=args.force))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="yoto.auth", description=__doc__)
    parser.add_argument("--state-dir", default=None, help="Where cookies/token live")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("bootstrap", help="Copy login cookies out of a running Chrome")
    p.add_argument("--cdp-port", type=int, default=9222)
    p.set_defaults(func=cmd_bootstrap)

    p = sub.add_parser("status", help="Show the cached session")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("token", help="Print an access token")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_token)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
