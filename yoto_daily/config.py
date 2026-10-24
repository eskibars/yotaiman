"""Runtime configuration for the Yoto Daily service.

Two sources are merged:

* ``config.yaml`` in the project root -- the file you edit to choose which
  music and speech generators run, and to point them at model servers.
* environment variables -- for secrets, ports and paths.

Environment variables win over the YAML file, so a key can be supplied at run
time without being written to disk.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from yoto.auth import default_state_dir

DEFAULT_STATE_DIR = default_state_dir()

#: Where the service looks for its ``config.yaml``.
DEFAULT_CONFIG_FILE = Path(
    os.environ.get("YOTO_CONFIG_FILE", Path(__file__).resolve().parent.parent / "config.yaml")
)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    try:
        return int(raw) if raw is not None else default
    except ValueError:
        return default


def load_config_file(path: Path | str) -> dict[str, Any]:
    """Read a YAML config file, returning ``{}`` if it is absent or broken."""
    path = Path(path)
    if not path.exists():
        return {}
    try:
        import yaml
    except ImportError:
        return {}
    try:
        data = yaml.safe_load(path.read_text())
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


@dataclass
class Settings:
    """Everything the service needs to know."""

    state_dir: Path = field(default_factory=lambda: DEFAULT_STATE_DIR)
    config_file: Path = field(default_factory=lambda: DEFAULT_CONFIG_FILE)
    raw_config: dict[str, Any] = field(default_factory=dict)

    host: str = field(default_factory=lambda: os.environ.get("YOTO_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: _env_int("YOTO_PORT", 8787))
    debug: bool = field(default_factory=lambda: _env_bool("YOTO_DEBUG", False))

    #: The card that the daily job rewrites.  Created on first use when unset.
    daily_card_id: str = field(
        default_factory=lambda: os.environ.get("YOTO_DAILY_CARD_ID", "")
    )

    #: ``replace`` -> one story per day; ``history`` -> keep the last N days.
    daily_mode: str = field(
        default_factory=lambda: os.environ.get("YOTO_DAILY_MODE", "replace")
    )
    history_days: int = field(default_factory=lambda: _env_int("YOTO_HISTORY_DAYS", 7))

    #: macOS ``say`` voice used for narration.
    tts_voice: str = field(
        default_factory=lambda: os.environ.get("YOTO_TTS_VOICE", "Karen")
    )
    tts_command: str = field(
        default_factory=lambda: os.environ.get("YOTO_TTS_COMMAND", "say")
    )
    ffmpeg_command: str = field(
        default_factory=lambda: os.environ.get("YOTO_FFMPEG_COMMAND", "ffmpeg")
    )

    #: ``auto`` picks the first configured LLM backend that works.
    llm_backend: str = field(
        default_factory=lambda: os.environ.get("YOTO_LLM_BACKEND", "auto")
    )
    llm_model: str = field(
        default_factory=lambda: os.environ.get("YOTO_LLM_MODEL", "minimax/MiniMax-M3.1-Flash")
    )
    #: Path to the local ``llm-call`` helper used by the ``script`` backend.
    #: Empty by default: the helper ships with a particular agent runtime, not
    #: with this package, so it is opt-in via ``YOTO_LLM_SCRIPT``.
    llm_script: str = field(
        default_factory=lambda: os.environ.get("YOTO_LLM_SCRIPT", "")
    )
    openai_api_key: str = field(
        default_factory=lambda: os.environ.get("OPENAI_API_KEY", "")
    )
    openai_model: str = field(
        default_factory=lambda: os.environ.get("YOTO_OPENAI_MODEL", "gpt-4o-mini")
    )

    #: Restrict the Flask API to localhost unless explicitly opened up.
    allow_remote: bool = field(
        default_factory=lambda: _env_bool("YOTO_ALLOW_REMOTE", False)
    )

    @classmethod
    def load(cls, path: Path | str | None = None) -> "Settings":
        """Build settings from a config file plus the environment."""
        config_file = Path(path) if path else DEFAULT_CONFIG_FILE
        raw = load_config_file(config_file)
        settings = cls(config_file=config_file, raw_config=raw)

        service = raw.get("service") or {}
        if service.get("host") and not os.environ.get("YOTO_HOST"):
            settings.host = str(service["host"])
        if service.get("port") and not os.environ.get("YOTO_PORT"):
            settings.port = int(service["port"])
        if service.get("debug") is not None and not os.environ.get("YOTO_DEBUG"):
            settings.debug = bool(service["debug"])

        daily = raw.get("daily") or {}
        if daily.get("card_id") and not os.environ.get("YOTO_DAILY_CARD_ID"):
            settings.daily_card_id = str(daily["card_id"])
        if daily.get("mode") and not os.environ.get("YOTO_DAILY_MODE"):
            settings.daily_mode = str(daily["mode"])
        if daily.get("history_days") and not os.environ.get("YOTO_HISTORY_DAYS"):
            settings.history_days = int(daily["history_days"])

        speech = ((raw.get("generators") or {}).get("speech") or {})
        say_options = ((speech.get("options") or {}).get("say") or {})
        if say_options.get("voice") and not os.environ.get("YOTO_TTS_VOICE"):
            settings.tts_voice = str(say_options["voice"])

        return settings

    @property
    def state_file(self) -> Path:
        return self.state_dir / "state.json"

    @property
    def work_dir(self) -> Path:
        return self.state_dir / "work"

    @property
    def cookie_file(self) -> Path:
        return self.state_dir / "cookies.json"

    def ensure_dirs(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.work_dir.mkdir(parents=True, exist_ok=True)
