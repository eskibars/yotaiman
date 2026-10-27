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


def _default_content_dirs() -> list[Path]:
    """Where a caller-supplied file path may point by default.

    ``~/yotaiman`` is where the project already keeps its media -- the
    sample configuration points ``reference_wav`` at ``~/yotaiman/*.wav`` --
    so it is the one directory every installation already has.
    """
    try:
        return [Path.home() / "yotaiman"]
    except RuntimeError:  # pragma: no cover - no home directory
        return []


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

    state_dir: Path = field(default_factory=default_state_dir)
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

    #: Which backend the capabilities narrate with: ``auto``, ``say``,
    #: ``http`` or ``ming-tts``.  When the configured default speech
    #: generator is a Ming-3.0-tts one, this follows it automatically.
    tts_backend: str = field(
        default_factory=lambda: os.environ.get("YOTO_TTS_BACKEND", "auto")
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

    #: How often the background worker refreshes the access token, in
    #: seconds.  The token lasts eight hours, so the default of an hour
    #: keeps it warm.  Zero turns the refresher off.
    token_refresh_interval: int = field(
        default_factory=lambda: _env_int("YOTO_TOKEN_REFRESH_INTERVAL", 3600)
    )

    #: Whether a caller has to present the API token.  On by default: the
    #: service drives a personal account, so an unauthenticated caller could
    #: read the shelf and rewrite the daily card.  Turning this off is only
    #: safe on a network nobody else can reach.
    auth_enabled: bool = field(
        default_factory=lambda: _env_bool("YOTO_AUTH", True)
    )

    #: The token itself.  Empty means "use the one in the state directory",
    #: which is generated on first run.
    api_token: str = field(
        default_factory=lambda: os.environ.get("YOTO_API_TOKEN", "").strip()
    )

    #: Where a caller-supplied file path is allowed to point.  A path that
    #: resolves outside every one of these is refused.
    content_dirs: list[Path] = field(default_factory=_default_content_dirs)

    #: The longest text a caller may send to be narrated or turned into a
    #: story.  Long enough for a chapter, short enough that the speech
    #: synthesiser cannot be turned into a way of spending money.
    max_text_length: int = field(
        default_factory=lambda: _env_int("YOTO_MAX_TEXT", 5000)
    )

    #: How many times a minute one caller may ask for a generated track or a
    #: story.  Zero removes the limit.
    rate_limit: int = field(
        default_factory=lambda: _env_int("YOTO_RATE_LIMIT", 30)
    )

    #: Who the daily card is written for.  The theme writer uses this to
    #: pitch the words at the right age.
    theme_audience: str = field(
        default_factory=lambda: os.environ.get(
            "YOTO_THEME_AUDIENCE", "two children, one about five years old and one about ten"
        )
    )

    #: The named voice the daily capabilities narrate in.  Empty means the
    #: speech generator's own default.
    theme_voice: str = field(
        default_factory=lambda: os.environ.get("YOTO_THEME_VOICE", "")
    )

    #: How long the theme song should be, in seconds.
    theme_song_seconds: int = field(
        default_factory=lambda: _env_int("YOTO_THEME_SONG_SECONDS", 60)
    )

    #: Which theme writer to use: ``auto``, ``ollama`` or ``template``.
    theme_backend: str = field(
        default_factory=lambda: os.environ.get("YOTO_THEME_BACKEND", "auto")
    )

    #: The local Ollama server.
    ollama_endpoint: str = field(
        default_factory=lambda: os.environ.get("YOTO_OLLAMA_ENDPOINT", "http://127.0.0.1:11434")
    )
    ollama_model: str = field(
        default_factory=lambda: os.environ.get("YOTO_OLLAMA_MODEL", "qwen3:1.7b")
    )
    ollama_timeout: float = field(
        default_factory=lambda: float(os.environ.get("YOTO_OLLAMA_TIMEOUT", "600"))
    )

    #: How many times to ask the model for a story before falling back to
    #: the hand-written themes.
    theme_attempts: int = field(
        default_factory=lambda: _env_int("YOTO_THEME_ATTEMPTS", 3)
    )

    #: How many planets to pull facts about for a themed card.
    research_fact_count: int = field(
        default_factory=lambda: _env_int("YOTO_RESEARCH_FACTS", 8)
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
        if service.get("token_refresh_interval") is not None and not os.environ.get(
            "YOTO_TOKEN_REFRESH_INTERVAL"
        ):
            settings.token_refresh_interval = int(service["token_refresh_interval"])

        # Where a caller-supplied path may point.  The environment wins over
        # the file so it can be changed without editing the config.
        raw_dirs = os.environ.get("YOTO_CONTENT_DIRS", "")
        if not raw_dirs:
            configured = service.get("content_dirs")
            if isinstance(configured, str):
                raw_dirs = configured
            elif isinstance(configured, (list, tuple)):
                raw_dirs = os.pathsep.join(str(part) for part in configured)
        if raw_dirs.strip():
            settings.content_dirs = [
                Path(part.strip()).expanduser()
                for part in raw_dirs.split(os.pathsep)
                if part.strip()
            ]

        daily = raw.get("daily") or {}
        if daily.get("card_id") and not os.environ.get("YOTO_DAILY_CARD_ID"):
            settings.daily_card_id = str(daily["card_id"])
        if daily.get("mode") and not os.environ.get("YOTO_DAILY_MODE"):
            settings.daily_mode = str(daily["mode"])
        if daily.get("history_days") and not os.environ.get("YOTO_HISTORY_DAYS"):
            settings.history_days = int(daily["history_days"])
        if daily.get("voice") and not os.environ.get("YOTO_THEME_VOICE"):
            settings.theme_voice = str(daily["voice"])

        theme = raw.get("theme") or {}
        if theme.get("audience") and not os.environ.get("YOTO_THEME_AUDIENCE"):
            settings.theme_audience = str(theme["audience"])
        if theme.get("voice") and not os.environ.get("YOTO_THEME_VOICE"):
            settings.theme_voice = str(theme["voice"])
        if theme.get("song_seconds") and not os.environ.get("YOTO_THEME_SONG_SECONDS"):
            settings.theme_song_seconds = int(theme["song_seconds"])
        if theme.get("backend") and not os.environ.get("YOTO_THEME_BACKEND"):
            settings.theme_backend = str(theme["backend"])
        if theme.get("ollama_endpoint") and not os.environ.get("YOTO_OLLAMA_ENDPOINT"):
            settings.ollama_endpoint = str(theme["ollama_endpoint"])
        if theme.get("ollama_model") and not os.environ.get("YOTO_OLLAMA_MODEL"):
            settings.ollama_model = str(theme["ollama_model"])
        if theme.get("ollama_timeout") and not os.environ.get("YOTO_OLLAMA_TIMEOUT"):
            settings.ollama_timeout = float(theme["ollama_timeout"])
        if theme.get("attempts") and not os.environ.get("YOTO_THEME_ATTEMPTS"):
            settings.theme_attempts = int(theme["attempts"])
        if theme.get("research_facts") and not os.environ.get("YOTO_RESEARCH_FACTS"):
            settings.research_fact_count = int(theme["research_facts"])

        speech = ((raw.get("generators") or {}).get("speech") or {})
        say_options = ((speech.get("options") or {}).get("say") or {})
        if say_options.get("voice") and not os.environ.get("YOTO_TTS_VOICE"):
            settings.tts_voice = str(say_options["voice"])

        # A Ming-3.0-tts default speech generator also narrates the
        # capabilities, so one switch moves the whole service over.
        # "auto" means exactly that, so it is not a forced choice and does
        # not stop the default from being followed.
        if os.environ.get("YOTO_TTS_BACKEND", "auto").strip().lower() in ("", "auto"):
            default = str(speech.get("default") or "")
            entry = (speech.get("options") or {}).get(default)
            if isinstance(entry, dict) and str(entry.get("type") or "").lower() == "ming-tts":
                settings.tts_backend = "ming-tts"

        return settings

    @property
    def ming_tts_options(self) -> dict[str, Any]:
        """The ``ming-tts`` entry of the speech generator configuration."""
        speech = ((self.raw_config or {}).get("generators") or {}).get("speech") or {}
        for entry in (speech.get("options") or {}).values():
            if isinstance(entry, dict) and str(entry.get("type") or "").lower() == "ming-tts":
                return dict(entry)
        return {}

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
        # The state directory holds the cookie jar, the access token and the
        # API token, so nobody else on the machine needs to see it.  On
        # Windows the mode does not apply, but it does no harm either.
        for path in (self.state_dir, self.work_dir):
            try:
                path.chmod(0o700)
            except OSError:  # pragma: no cover - platform dependent
                pass
