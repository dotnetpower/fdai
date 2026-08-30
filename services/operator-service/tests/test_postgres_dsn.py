"""Tests for direct Psycopg DSN normalization."""

from __future__ import annotations

import pytest
from fdai_operator_service.postgres_dsn import normalize_psycopg_dsn


def test_sqlalchemy_psycopg_dsn_is_normalized_for_direct_driver_use() -> None:
    assert normalize_psycopg_dsn("postgresql+psycopg://user@example.invalid/fdai") == (
        "postgresql://user@example.invalid/fdai"
    )
    assert normalize_psycopg_dsn("postgresql://user@example.invalid/fdai") == (
        "postgresql://user@example.invalid/fdai"
    )


def test_empty_postgres_target_is_rejected() -> None:
    with pytest.raises(ValueError, match="connection target"):
        normalize_psycopg_dsn("postgresql+psycopg://")
