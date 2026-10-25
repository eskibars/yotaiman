"""Loading the project's ``.env`` file.

The project documents its environment variables in ``.env.example`` and keeps
the real values in ``.env``.  Reading that file is what makes the service
behave the same on every machine: a macOS shell profile can export the
variables, Windows has nowhere to put them.

``python-dotenv`` is a hard dependency, but the loader still degrades quietly
if it is missing -- the variables are then expected to be in the environment
already.
"""

from __future__ import annotations

from pathlib import Path

#: ``.env`` next to the package, which is the project root in a checkout.
_PROJECT_ENV = Path(__file__).resolve().parent.parent / ".env"

_loaded = False


def load_env_files() -> bool:
    """Put the values from ``.env`` into the environment.

    Returns whether anything was loaded.  Variables already in the
    environment win, so ``YOTO_PORT=9000`` in a shell overrides the file.
    """
    global _loaded
    if _loaded:
        return False
    _loaded = True

    try:
        from dotenv import load_dotenv
    except ImportError:
        return False

    loaded = False
    for candidate in (_PROJECT_ENV, Path.cwd() / ".env"):
        try:
            if candidate.is_file() and load_dotenv(candidate, override=False):
                loaded = True
        except OSError:
            continue
    return loaded


__all__ = ["load_env_files"]
