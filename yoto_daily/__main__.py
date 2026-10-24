"""Run the service: ``yotaiman`` or ``python -m yoto_daily``.

Subcommands::

    yotaiman serve                       start the service
    yotaiman daily [--topic T]           publish today's story now
    yotaiman status                      show the service state
"""

from __future__ import annotations

import argparse
import json
import sys

from .app import create_app
from .capabilities import base as caps
from .config import Settings
from .state import StateStore
from yoto import Yoto
from yoto.auth import YotoAuth


def cmd_serve(args: argparse.Namespace) -> int:
    settings = Settings.load()
    app = create_app(settings)
    print(f"yotaiman listening on http://{settings.host}:{settings.port}")
    app.run(
        host="0.0.0.0" if settings.allow_remote else settings.host,
        port=settings.port,
        debug=settings.debug,
    )
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

    p = sub.add_parser("status", help="Show the service state")
    p.set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
