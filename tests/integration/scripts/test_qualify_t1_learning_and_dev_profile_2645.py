"""Tests for T1 learning loop, T1/T2 shadow canary, and dev-profile qualification (#2645)."""

from __future__ import annotations

import os

import pytest
from scripts.governance.qualify_t1_learning_and_dev_profile_2645 import (
    qualify_t1_learning_and_dev_profile_in_memory,
    qualify_t1_learning_postgres,
    require_validation_postgres_dsn,
)


def test_2645_validation_postgres_dsn_guard_fails_closed() -> None:
    with pytest.raises(ValueError, match="port 5433"):
        require_validation_postgres_dsn("postgresql://127.0.0.1:5432/fdai")
    with pytest.raises(ValueError, match="loopback"):
        require_validation_postgres_dsn("postgresql://remote.example.com:5433/fdai")
    assert (
        require_validation_postgres_dsn("postgresql+psycopg://127.0.0.1:5433/fdai")
        == "postgresql://127.0.0.1:5433/fdai"
    )


@pytest.mark.asyncio
async def test_qualify_t1_learning_and_dev_profile_in_memory() -> None:
    receipt = await qualify_t1_learning_and_dev_profile_in_memory()

    assert receipt["execution_authority"] is False
    assert receipt["not_production_qualification"] is True
    assert all(receipt["criteria_verified"].values())
    assert receipt["t1_learning_metrics"]["initial_shadow_outcome"] == "abstain"
    assert receipt["t1_learning_metrics"]["promoted_outcome"] == "reused"
    assert receipt["t1_learning_metrics"]["promoted_reuse_count"] == 22
    assert receipt["shadow_canary_metrics"]["t1_reuse_model_calls"] == 0
    assert receipt["shadow_canary_metrics"]["t2_consultation_model_calls"] == 3
    assert receipt["shadow_canary_metrics"]["retries_on_429"] == 0
    assert receipt["qualification_digest"].startswith("sha256:")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_qualify_t1_learning_and_dev_profile_postgres_parity() -> None:
    dsn = os.environ.get("FDAI_DATABASE_URL", "").strip()
    if not dsn:
        pytest.skip("FDAI_DATABASE_URL is unset")
    pg_receipt = await qualify_t1_learning_postgres(dsn)

    assert pg_receipt["venue"] == "isolated-validation-postgres-5433"
    assert pg_receipt["execution_authority"] is False
    assert all(pg_receipt["criteria_verified"].values())
    assert pg_receipt["qualification_digest"].startswith("sha256:")
