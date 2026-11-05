"""Tests for F06.3 ARB and operational readiness local qualification rehearsal (#2205)."""

from __future__ import annotations

import os

import pytest
from scripts.governance.qualify_f063_dev_installation import (
    qualify_f063_dev_installation,
    qualify_f063_postgres,
)
from scripts.governance.rehearse_f063_arb_operational_readiness import (
    rehearse_f063_arb_operational_readiness,
    rehearse_f063_postgres,
    require_validation_postgres_dsn,
)


def test_f063_validation_postgres_dsn_guard_fails_closed() -> None:
    with pytest.raises(ValueError, match="port 5433"):
        require_validation_postgres_dsn("postgresql://localhost/fdai")
    with pytest.raises(ValueError, match="port 5433"):
        require_validation_postgres_dsn("postgresql://127.0.0.1:5432/fdai")
    with pytest.raises(ValueError, match="port 5433"):
        require_validation_postgres_dsn("postgresql://127.0.0.1:5433/fdai?port=5432")
    with pytest.raises(ValueError, match="hostaddr"):
        require_validation_postgres_dsn("postgresql://127.0.0.1:5433/fdai?hostaddr=192.0.2.1")
    assert (
        require_validation_postgres_dsn("postgresql+psycopg://127.0.0.1:5433/fdai")
        == "postgresql://127.0.0.1:5433/fdai"
    )


@pytest.mark.asyncio
async def test_rehearse_f063_arb_operational_readiness_in_memory() -> None:
    result = await rehearse_f063_arb_operational_readiness()

    assert result["execution_authority"] is False
    assert result["rehearsal_only"] is True
    assert result["venue"] == "in-memory-rehearsal"
    assert all(result["local_rehearsal_invariants"].values())
    assert result["rehearsal_receipt_digest"].startswith("sha256:")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_rehearse_f063_arb_operational_readiness_postgres_parity() -> None:
    dsn = os.environ.get("FDAI_DATABASE_URL", "").strip()
    if not dsn:
        pytest.skip("FDAI_DATABASE_URL is unset")
    in_memory = await rehearse_f063_arb_operational_readiness()
    postgres = await rehearse_f063_postgres(dsn)

    assert postgres["venue"] == "isolated-validation-postgres-5433"
    assert postgres["execution_authority"] is False
    assert postgres["rehearsal_only"] is True
    assert postgres["decision_receipt_digest"] == in_memory["decision_receipt_digest"]
    assert postgres["arb2_trace_digest"] == in_memory["arb2_trace_digest"]
    assert postgres["arb4_conformant_closure_digest"] == in_memory["arb4_conformant_closure_digest"]
    assert postgres["arb4_recovery_closure_digest"] == in_memory["arb4_recovery_closure_digest"]


@pytest.mark.asyncio
async def test_qualify_f063_dev_installation_in_memory() -> None:
    result = await qualify_f063_dev_installation()

    assert result["execution_authority"] is False
    assert result["not_production_qualification"] is True
    assert result["qualification_profile"] == "single-operator-development"
    assert len(result["criteria_verified"]) == 15
    assert all(result["criteria_verified"].values())
    assert result["qualification_receipt_digest"].startswith("sha256:")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_qualify_f063_dev_installation_postgres_parity() -> None:
    dsn = os.environ.get("FDAI_DATABASE_URL", "").strip()
    if not dsn:
        pytest.skip("FDAI_DATABASE_URL is unset")
    in_memory = await qualify_f063_dev_installation()
    postgres = await qualify_f063_postgres(dsn)

    assert postgres["venue"] == "isolated-validation-postgres-5433"
    assert postgres["execution_authority"] is False
    assert postgres["not_production_qualification"] is True
    assert all(postgres["criteria_verified"].values())
    assert postgres["decision_receipt_digest"] == in_memory["decision_receipt_digest"]
    assert postgres["workflow_parity_digest"] == in_memory["workflow_parity_digest"]
    assert postgres["frozen_cohort_digest"] == in_memory["frozen_cohort_digest"]
    assert postgres["promotion_receipt_digest"] == in_memory["promotion_receipt_digest"]
