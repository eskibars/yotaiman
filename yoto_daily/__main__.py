"""Run the service: ``yotaiman`` or ``python -m yoto_daily``.

Subcommands::

    yotaiman serve                       start the service
    yotaiman daily [--topic T]           publish today's story now
    yotaiman theme <THEME>               build today's themed card
    yotaiman days                        list the saved days
    yotaiman restore [--date D]          put a saved day back on the card
    yotaiman prepare-voice --wav W       cut a usable voice reference clip
    yotaiman token                       print the token the service expects
    yotaiman status                      show the service state
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

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


def cmd_theme(args: argparse.Namespace) -> int:
    """Build today's themed card."""
    settings = Settings.load()
    settings.ensure_dirs()

    caps.set_context(
        yoto=Yoto(auth=YotoAuth(state_dir=settings.state_dir)),
        settings=settings,
        state=StateStore(settings.state_file),
    )

    params: dict = {"theme": args.theme}
    for name in ("audience", "voice", "instruction", "date"):
        value = getattr(args, name, None)
        if value:
            params[name] = value
    if args.no_song:
        params["song"] = False
    if args.no_facts:
        params["facts"] = False
    if args.plan_only:
        params["plan_only"] = True
    if args.dry_run:
        params["dry_run"] = True

    result = caps.run_safely("daily-theme", **params)
    print(json.dumps(result.to_dict(), indent=2))
    return 0 if result.ok else 1


def cmd_days(args: argparse.Namespace) -> int:
    """List the days that were saved."""
    settings = Settings.load()
    settings.ensure_dirs()

    result = caps.run_safely("restore-day", list=True)
    print(json.dumps(result.to_dict(), indent=2))
    return 0 if result.ok else 1


def cmd_restore(args: argparse.Namespace) -> int:
    """Put a saved day back on the card."""
    settings = Settings.load()
    settings.ensure_dirs()

    caps.set_context(
        yoto=Yoto(auth=YotoAuth(state_dir=settings.state_dir)),
        settings=settings,
        state=StateStore(settings.state_file),
    )

    params: dict = {}
    if args.date:
        params["date"] = args.date
    if args.slug:
        params["slug"] = args.slug
    if args.card_id:
        params["card_id"] = args.card_id

    result = caps.run_safely("restore-day", **params)
    print(json.dumps(result.to_dict(), indent=2))
    return 0 if result.ok else 1


def cmd_prepare_voice(args: argparse.Namespace) -> int:
    """Cut a usable voice reference clip out of a recording."""
    from .voice import prepare_reference

    settings = Settings.load()
    settings.ensure_dirs()

    transcript = ""
    if args.transcript:
        transcript = Path(args.transcript).read_text(encoding="utf-8")
    elif args.transcript_text:
        transcript = args.transcript_text

    try:
        reference = prepare_reference(
            args.wav,
            args.out_wav,
            args.out_text,
            transcript=transcript,
            model_size=args.model,
            min_seconds=args.min_seconds,
            max_seconds=args.max_seconds,
        )
    except Exception as exc:
        print(f"could not prepare the voice reference: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(reference.to_dict(), indent=2))
    return 0


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

    p = sub.add_parser("theme", help="Build today's themed card")
    p.add_argument("theme", help="The topic, e.g. 'exoplanets'")
    p.add_argument("--audience", help="Who is listening")
    p.add_argument("--voice", help="Which voice to narrate in")
    p.add_argument("--instruction", help="How to read it")
    p.add_argument("--date", help="Which day's folder to write")
    p.add_argument("--no-song", dest="no_song", action="store_true")
    p.add_argument("--no-facts", dest="no_facts", action="store_true")
    p.add_argument(
        "--plan-only",
        dest="plan_only",
        action="store_true",
        help="Show what would go on the card, without making any of it",
    )
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_theme)

    p = sub.add_parser("days", help="List the saved days")
    p.set_defaults(func=cmd_days)

    p = sub.add_parser("restore", help="Put a saved day back on the card")
    p.add_argument("--date", help="The day to restore, e.g. 2026-10-26")
    p.add_argument("--slug", help="The theme of the day, e.g. exoplanets")
    p.add_argument("--card-id", dest="card_id", help="Which card to restore onto")
    p.set_defaults(func=cmd_restore)

    p = sub.add_parser(
        "prepare-voice", help="Cut a usable voice reference clip out of a recording"
    )
    p.add_argument("--wav", required=True, help="The recording to cut from")
    p.add_argument("--out-wav", dest="out_wav", required=True)
    p.add_argument("--out-text", dest="out_text", required=True)
    p.add_argument(
        "--transcript",
        help="A file holding the full transcript of the recording",
    )
    p.add_argument(
        "--transcript-text",
        dest="transcript_text",
        help="The full transcript of the recording, given directly",
    )
    p.add_argument("--model", default="small.en", help="The speech recognition model")
    p.add_argument("--min-seconds", dest="min_seconds", type=float, default=3.0)
    p.add_argument("--max-seconds", dest="max_seconds", type=float, default=8.0)
    p.set_defaults(func=cmd_prepare_voice)

    p = sub.add_parser("token", help="Print the API token")
    p.set_defaults(func=cmd_token)

    p = sub.add_parser("status", help="Show the service state")
    p.set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
