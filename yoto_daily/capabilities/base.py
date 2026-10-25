"""The capability framework.

A *capability* is one thing the service can do on a Yoto card -- a daily
story, a bird-of-the-day, a library read-aloud.  Each capability is a small
class with a ``run()`` method; the Flask layer discovers them through the
registry below and exposes them as ``POST /api/capabilities/<name>/run``.

Adding a capability is deliberately cheap: subclass :class:`Capability`,
implement ``run``, and decorate it with :func:`register`.
"""

from __future__ import annotations

import logging
import traceback
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable

from yoto.errors import YotoError

logger = logging.getLogger(__name__)


@dataclass
class CapabilityResult:
    """What a capability returns to its caller."""

    ok: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "message": self.message, "data": self.data}


@dataclass
class CapabilityInfo:
    """Metadata shown by ``GET /api/capabilities``."""

    name: str
    description: str
    parameters: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


class Capability(ABC):
    """Base class for everything the service can do."""

    #: URL-safe identifier, e.g. ``daily-story``.
    name: str = ""
    #: One-line summary shown in the API listing.
    description: str = ""
    #: Parameters accepted by ``run``, as ``{name, type, required, default}``.
    parameters: list[dict[str, Any]] = []

    @abstractmethod
    def run(self, **params: Any) -> CapabilityResult:
        """Execute the capability."""

    def info(self) -> CapabilityInfo:
        return CapabilityInfo(
            name=self.name,
            description=self.description,
            parameters=list(self.parameters),
        )


_REGISTRY: dict[str, Callable[[], Capability]] = {}

#: Shared objects the app hands to capabilities (the Yoto client, settings,
#: state).  A single Flask process serves one account, so a module-level
#: context is simpler than threading a container through every call.
_CONTEXT: dict[str, Any] = {}


def set_context(**values: Any) -> None:
    """Publish shared objects to the capability factories."""
    _CONTEXT.update(values)


def get_context() -> dict[str, Any]:
    """Return the shared capability context."""
    return dict(_CONTEXT)


def register(target: Any) -> Any:
    """Register a capability.

    Usable directly on a :class:`Capability` subclass::

        @register
        class MyThing(Capability):
            name = "my-thing"

    or on a factory function that returns one.  In both cases the decorated
    object is returned unchanged.
    """
    if isinstance(target, type) and issubclass(target, Capability):
        if not target.name:
            raise ValueError(f"{target!r} has no name")
        _REGISTRY[target.name] = target
        return target

    def decorator() -> Capability:
        cap = target()
        if not cap.name:
            raise ValueError(f"{target!r} has no name")
        _REGISTRY[cap.name] = target
        return cap

    return decorator


def get(name: str) -> Capability:
    """Instantiate a registered capability by name."""
    factory = _REGISTRY.get(name)
    if factory is None:
        raise KeyError(name)
    return factory()


def all_capabilities() -> list[Capability]:
    """Instantiate every registered capability."""
    return [factory() for factory in _REGISTRY.values()]


def names() -> list[str]:
    """Names of every registered capability."""
    return sorted(_REGISTRY)


def run_safely(name: str, *, include_traceback: bool = False, **params: Any) -> CapabilityResult:
    """Run a capability, turning any failure into a structured result.

    The detail of an unexpected failure stays on the server: the caller is
    told what happened in general terms, and the service log has the
    traceback.  The command line asks for the traceback, because whoever is
    running it is the operator.
    """
    try:
        cap = get(name)
    except KeyError:
        return CapabilityResult(
            ok=False,
            message=f"unknown capability: {name}",
            data={"available": names()},
        )

    try:
        return cap.run(**params)
    except YotoError as exc:
        data: dict[str, Any] = {}
        if include_traceback:
            data["traceback"] = traceback.format_exc(limit=3)
        return CapabilityResult(
            ok=False,
            message=f"{type(exc).__name__}: {exc}",
            data=data,
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("capability %s failed", name)
        data = {}
        if include_traceback:
            data["traceback"] = traceback.format_exc(limit=3)
        return CapabilityResult(
            ok=False,
            message=f"{type(exc).__name__}: {exc}",
            data=data,
        )
