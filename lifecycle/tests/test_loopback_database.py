"""The PostgreSQL test fixtures drop every Hub table, so only a loopback database is accepted."""

from __future__ import annotations

import pytest

ENV = "FDAI_DATABASE_URL"


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "[::1]"])
def test_loopback_database_is_accepted(
    host: str, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> None:
    monkeypatch.setenv(ENV, f"postgresql://fdai@{host}:5432/fdai")

    url = request.getfixturevalue("loopback_postgres_url")

    assert url == f"postgresql+psycopg://fdai@{host}:5432/fdai"


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://fdai@db.example.com:5432/fdai",
        "postgresql://fdai@localhost.example.com:5432/fdai",
        "postgresql://fdai@10.0.0.5:5432/fdai",
        "postgresql+psycopg://fdai@db.example.com:5432/fdai",
        "postgresql:///fdai?host=/var/run/postgresql",
    ],
)
def test_other_database_is_refused_before_any_connection(
    url: str, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> None:
    monkeypatch.setenv(ENV, url)

    with pytest.raises(pytest.UsageError, match="must name a loopback host"):
        request.getfixturevalue("loopback_postgres_url")
