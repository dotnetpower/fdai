"""Tests for F07 Cost Governance single-operator dev qualification (#2206)."""

from __future__ import annotations

import os

import pytest
from scripts.governance.qualify_f07_cost_governance_2206 import (
    qualify_f07_cost_governance,
    qualify_f07_postgres,
    require_validation_postgres_dsn,
)


def test_2206_validation_postgres_dsn_guard_fails_closed() -> None:
    with pytest.raises(ValueError, match="port 5433"):
        require_validation_postgres_dsn("postgresql://127.0.0.1:5432/fdai")
    with pytest.raises(ValueError, match="loopback"):
        require_validation_postgres_dsn("postgresql://remote.example.com:5433/fdai")
    assert (
        require_validation_postgres_dsn("postgresql+psycopg://127.0.0.1:5433/fdai")
        == "postgresql://127.0.0.1:5433/fdai"
    )


@pytest.mark.asyncio
async def test_qualify_f07_cost_governance_in_memory() -> None:
    receipt = await qualify_f07_cost_governance()

    assert receipt["execution_authority"] is False
    assert receipt["not_production_qualification"] is True
    assert receipt["qualification_profile"] == "single-operator-development"
    assert len(receipt["criteria_verified"]) == 14
    assert all(receipt["criteria_verified"].values())
    assert receipt["forecast_calibration"]["matched_samples"] == 6
    assert receipt["settlement_summary"]["run_rate_realized_savings_usd"] == "20"
    assert receipt["settlement_summary"]["invoice_allocated_realized_savings_usd"] == "20"
    assert receipt["settlement_summary"]["failed_savings_usd"] == "0"
    assert receipt["settlement_summary"]["rolled_back_savings_usd"] == "0"
    assert receipt["settlement_summary"]["censored_savings_usd"] == "0"
    assert receipt["settlement_summary"]["unscorable_savings_usd"] == "0"
    assert len(receipt["w7_campaign_and_reviews"]["promotion_reviews"]) == 6
    assert receipt["qualification_receipt_digest"].startswith("sha256:")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_qualify_f07_cost_governance_postgres_parity() -> None:
    dsn = os.environ.get("FDAI_DATABASE_URL", "").strip()
    if not dsn:
        pytest.skip("FDAI_DATABASE_URL is unset")
    in_memory = await qualify_f07_cost_governance()
    postgres = await qualify_f07_postgres(dsn)

    assert postgres["venue"] == "isolated-validation-postgres-5433"
    assert postgres["execution_authority"] is False
    assert postgres["not_production_qualification"] is True
    assert all(postgres["criteria_verified"].values())
    assert postgres["forecast_calibration"] == in_memory["forecast_calibration"]
    assert postgres["settlement_summary"] == in_memory["settlement_summary"]
    assert postgres["w7_campaign_and_reviews"] == in_memory["w7_campaign_and_reviews"]
