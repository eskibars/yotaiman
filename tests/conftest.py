"""Shared fixtures for the test suite.

The service asks for a token before it does anything, so the client here
has already presented one.  A test that is about the perimeter itself
builds its own client and stays unauthenticated.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from yoto_daily.app import create_app  # noqa: E402
from yoto_daily.config import Settings  # noqa: E402


@pytest.fixture
def settings(tmp_path):
    """Settings that keep the test off the real state directory."""
    return Settings(state_dir=tmp_path / "state")


@pytest.fixture
def app(settings):
    """The service, built on a scratch state directory."""
    application = create_app(settings)
    application.config["TESTING"] = True
    return application


@pytest.fixture
def token(app):
    """The token this service expects."""
    return str(app.config["YOTO_TOKEN"])


@pytest.fixture
def client(app):
    """A test client that has already presented the API token."""
    test_client = app.test_client()
    test_client.environ_base["HTTP_AUTHORIZATION"] = (
        f"Bearer {app.config['YOTO_TOKEN']}"
    )
    return test_client


@pytest.fixture
def anon_client(app):
    """A test client that has presented nothing."""
    return app.test_client()
