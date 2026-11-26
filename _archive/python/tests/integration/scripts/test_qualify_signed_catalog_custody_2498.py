"""Tests for signed catalog role custody and operational paths qualification (#2498)."""

from __future__ import annotations

import os

import pytest
from scripts.deployment.local.qualify_signed_catalog_custody_2498 import (
    qualify_signed_catalog_custody,
    qualify_signed_catalog_custody_postgres,
    require_validation_postgres_dsn,
)


def test_2498_validation_postgres_dsn_guard_fails_closed() -> None:
    with pytest.raises(ValueError, match="port 5433"):
        require_validation_postgres_dsn("postgresql://127.0.0.1:5432/fdai")
    with pytest.raises(ValueError, match="loopback"):
        require_validation_postgres_dsn("postgresql://db.example.com:5433/fdai")
    assert (
        require_validation_postgres_dsn("postgresql+psycopg://127.0.0.1:5433/fdai")
        == "postgresql://127.0.0.1:5433/fdai"
    )


def test_qualify_signed_catalog_custody_sqlite() -> None:
    receipt = qualify_signed_catalog_custody()

    assert receipt["execution_authority"] is False
    assert all(receipt["criteria_verified"].values())
    assert receipt["custody_receipt"]["root_private_keys_entered_hub"] is False
    assert receipt["custody_receipt"]["snapshot_exportable"] is False
    assert receipt["custody_receipt"]["timestamp_exportable"] is False
    assert receipt["rebinding_audit_actions"] == ["source.bound", "source.rebound"]
    assert receipt["refusal_and_rotation"]["expired_timestamp_recall_rolloff_only"] is True
    assert receipt["refusal_and_rotation"]["root_rotation_review_required"] is True
    assert receipt["refusal_and_rotation"]["persisted_root_version"] == 2
    assert (
        receipt["refusal_and_rotation"]["aks_freshness"]["mode_when_timestamp_expired"] == "shadow"
    )
    assert receipt["enrollment"]["approved_status"] == "enrolled"
    assert receipt["qualification_digest"].startswith("sha256:")


@pytest.mark.integration
def test_qualify_signed_catalog_custody_postgres_parity() -> None:
    dsn = os.environ.get("FDAI_DATABASE_URL", "").strip()
    if not dsn:
        pytest.skip("FDAI_DATABASE_URL is unset")
    sqlite_receipt = qualify_signed_catalog_custody()
    pg_receipt = qualify_signed_catalog_custody_postgres(dsn)

    assert pg_receipt["venue"] == "isolated-validation-postgres-5433"
    assert all(pg_receipt["criteria_verified"].values())
    assert pg_receipt["rebinding_audit_actions"] == sqlite_receipt["rebinding_audit_actions"]
    assert pg_receipt["refusal_and_rotation"] == sqlite_receipt["refusal_and_rotation"]
    assert pg_receipt["enrollment"] == sqlite_receipt["enrollment"]
