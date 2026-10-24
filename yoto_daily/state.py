"""A tiny JSON-backed state store.

The service only needs to remember a handful of things between runs: which
card is the daily card, when it was last written, and what was on it.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any


class StateStore:
    """Reads and writes a single JSON file, safely across threads."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

    def write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2, default=str))
            tmp.replace(self.path)

    def get(self, key: str, default: Any = None) -> Any:
        return self.read().get(key, default)

    def set(self, key: str, value: Any) -> None:
        data = self.read()
        data[key] = value
        self.write(data)

    def update(self, **values: Any) -> dict[str, Any]:
        data = self.read()
        data.update(values)
        self.write(data)
        return data
