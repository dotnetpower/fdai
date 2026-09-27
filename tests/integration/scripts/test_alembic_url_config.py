"""Regression for URL-encoded PostgreSQL credentials in Alembic configuration."""

from __future__ import annotations

from configparser import ConfigParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ENV_SOURCE = ROOT / "alembic" / "env.py"


def test_alembic_source_escapes_configparser_percent_tokens() -> None:
    source = ENV_SOURCE.read_text(encoding="utf-8")

    assert 'config.set_main_option("sqlalchemy.url", _url.replace("%", "%%"))' in source


def test_percent_encoded_password_round_trips_through_configparser() -> None:
    url = "******example:5432/fdai?sslmode=require"
    config = ConfigParser()
    config.add_section("alembic")

    config.set("alembic", "sqlalchemy.url", url.replace("%", "%%"))

    assert config.get("alembic", "sqlalchemy.url") == url
