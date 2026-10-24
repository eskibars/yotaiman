"""Yoto Daily -- a local service that keeps a Yoto card fresh.

The package is split into three layers:

``yoto``            the SDK: auth, cards, media upload
``yoto_daily``      the service: config, state, capabilities
``yoto_daily.app``  the Flask application on top
"""

from __future__ import annotations

from .config import Settings

__version__ = "0.1.0"

__all__ = ["Settings", "create_app", "__version__"]


def create_app(settings: Settings | None = None):
    """Convenience re-export of :func:`yoto_daily.app.create_app`."""
    from .app import create_app as _create_app

    return _create_app(settings)
