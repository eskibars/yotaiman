"""Capability registry.

Importing this module registers every shipped capability.
"""

from __future__ import annotations

from .base import (
    Capability,
    CapabilityInfo,
    CapabilityResult,
    all_capabilities,
    get,
    names,
    register,
    run_safely,
)

# Import for the registration side effect.
from . import daily_story  # noqa: F401,E402
from . import daily_theme  # noqa: F401,E402
from . import read_aloud  # noqa: F401,E402
from . import restore_day  # noqa: F401,E402

__all__ = [
    "Capability",
    "CapabilityInfo",
    "CapabilityResult",
    "all_capabilities",
    "get",
    "names",
    "register",
    "run_safely",
]
