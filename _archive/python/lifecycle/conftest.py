"""Fixtures shared by the lifecycle Hub, agent, and loop tests."""

from __future__ import annotations

import ipaddress
import os

import pytest
from sqlalchemy import make_url

DATABASE_URL_ENV = "FDAI_DATABASE_URL"


def _is_loopback(host: str | None) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host or "").is_loopback
    except ValueError:
        return False


@pytest.fixture
def loopback_postgres_url() -> str:
    """The psycopg URL of the loopback test database, or a skip when none is configured.

    Tests that use it drop every Hub table, so a database on any other host is refused.
    """

    url = os.environ.get(DATABASE_URL_ENV)
    if not url:
        pytest.skip(f"{DATABASE_URL_ENV} is not set")
    url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    if not _is_loopback(make_url(url).host):
        raise pytest.UsageError(f"{DATABASE_URL_ENV} must name a loopback host")
    return url
