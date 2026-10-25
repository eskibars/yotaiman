"""Run the service: ``yotaiman`` or ``python -m yoto_daily``.

Subcommands::

    yotaiman serve                       start the service
    yotaiman daily [--topic T]           publish today's story now
    yotaiman token                       print the token the service expects
    yotaiman status                      show the service state
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from .app import create_app
from .capabilities import base as caps
from .config import Settings
from .security import allowed_hosts as _allowed_hosts
from .security import load_api_token
from .state import StateStore
from yoto import Yoto
from yoto._env import load_env_files
from yoto.auth import YotoAuth


def _is_serving_process(debug: bool) -> bool:
    """Whether this process is the one that actually serves requests.

    With ``debug`` on, Werkzeug runs the command twice: once as a watcher
    that restarts the server on a code change, and once as the server
    itself.  Only the server should keep a token warm.
    """
    if not debug:
        return True
    return os.environ.get("WERKZEUG_RUN_MAIN") == "true"


def _interval_label(seconds: int) -> str:
    """``3600`` -> ``1 h``, ``90`` -> ``90 s``."""
    if seconds % 3600 == 0:
        return f"{seconds // 3600} h"
    if seconds % 60 == 0:
        return f"{seconds // 60} min"
    return f"{seconds} s"


def _bind_host(settings: Settings) -> str:
    """The address the service will listen on."""
    return "0.0.0.0" if settings.allow_remote else settings.host


def _check_debug_bind(settings: Settings) -> str | None:
    """Why the service refuses to start, if it should.

    The debugger hands whoever finds it a shell on the machine, so it is
    only ever allowed on a loopback bind.  A debug server on the network
    is remote code execution for anybody who can reach the port.
    """
    if not settings.debug:
        return None
    host = _bind_host(settings).strip().lower()
    if host in ("127.0.0.1", "localhost", "::1", "[::1]"):
        return None
    return (
        f"debug mode is on and the service would bind to {host}, which is not "
        "the loopback interface.  The debugger gives anybody who can reach "
        "the port a shell on this machine.  Set YOTO_DEBUG=false, or bind to "
        "127.0.0.1, before turning it on."
    )


def cmd_serve(args: argparse.Namespace) -> int:
    settings = Settings.load()

    refusal = _check_debug_bind(settings)
    if refusal:
        print(refusal, file=sys.stderr)
        return 2

    app = create_app(settings)
    bind = _bind_host(settings)
    print(f"yotaiman listening on http://{bind}:{settings.port}")

    token = str(app.config.get("YOTO_TOKEN") or "")
    if settings.auth_enabled and token:
        print(
            "This service asks for a token.  Print it with 'yotaiman token', "
            "or read it from the file next to the other service state."
        )
        if settings.allow_remote:
            allowed = ", ".join(sorted(_allowed_hosts(settings)))
            print(
                "The service is open to the network, so the Host header has "
                f"to be one of: {allowed}.  Set YOTO_ALLOWED_HOSTS to the "
                "address the phone will use."
            )

    # The token lasts eight hours; the refresher keeps a fresh one in hand
    # so a long run never trips over an expired session.  It mints tokens
    # over plain HTTP, so no browser is needed while the service runs.
    refresher = app.extensions["token_refresher"]
    refresher.set_report(lambda message: print(f"[token] {message}", flush=True))
    started = False
    if _is_serving_process(settings.debug) and refresher.start():
        started = True
        print(
            "Refreshing the access token every "
            f"{_interval_label(settings.token_refresh_interval)} in the background."
        )

    try:
        app.run(
            host=bind,
            port=settings.port,
            debug=settings.debug,
        )
    finally:
        if started:
            refresher.stop()
    return 0


def cmd_daily(args: argparse.Namespace) -> int:
    settings = Settings.load()
    settings.ensure_dirs()

    # Capabilities pull their shared objects from the registry context.
    caps.set_context(
        yoto=Yoto(auth=YotoAuth(state_dir=settings.state_dir)),
        settings=settings,
        state=StateStore(settings.state_file),
    )

    params: dict = {}
    if args.topic:
        params["topic"] = args.topic
    if args.child_name:
        params["child_name"] = args.child_name
    if args.voice:
        params["voice"] = args.voice
    if args.dry_run:
        params["dry_run"] = True

    result = caps.run_safely("daily-story", **params)
    print(json.dumps(result.to_dict(), indent=2))
    return 0 if result.ok else 1


def cmd_token(args: argparse.Namespace) -> int:
    """Print the token the service expects."""
    settings = Settings.load()
    settings.ensure_dirs()
    print(load_api_token(settings.state_dir))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    settings = Settings()
    state = settings.state_file
    payload: dict = {"state_file": str(state), "exists": state.exists()}
    if state.exists():
        payload["state"] = json.loads(state.read_text())
    payload["capabilities"] = caps.names()
    print(json.dumps(payload, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    # The project's ``.env`` is read here rather than at import time, so that
    # a library user -- or a test -- is not affected by it, while the command
    # line behaves the same on every platform.
    load_env_files()

    parser = argparse.ArgumentParser(prog="yotaiman", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("serve", help="Start the Flask API")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("daily", help="Publish today's story")
    p.add_argument("--topic")
    p.add_argument("--child-name", dest="child_name")
    p.add_argument("--voice")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_daily)

    p = sub.add_parser("token", help="Print the API token")
    p.set_defaults(func=cmd_token)

    p = sub.add_parser("status", help="Show the service state")
    p.set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
