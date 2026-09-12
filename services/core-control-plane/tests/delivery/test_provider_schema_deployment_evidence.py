"""Deployment evidence checks for one provider-schema Job execution."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fdai.delivery.provider_schema import ProviderSchemaError
from fdai.delivery.provider_schema_deployment_evidence import (
    collect_provider_schema_deployment_evidence,
)
from fdai.delivery.provider_schema_ledger import ProviderSchemaLedger
from fdai.delivery.provider_schema_state_ledger import StateStoreProviderSchemaLedger
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_NOW = datetime(2026, 9, 12, 4, 0, tzinfo=UTC)
_SOURCE_COMMIT = "a" * 40
_RUNTIME_REVISION = "b" * 40
_PLAN_ID = "plan-123-1"
_DRIFT_DIGEST = "c" * 64
_CORRELATION_ID = f"provider-schema:azure:{_DRIFT_DIGEST}"


class _AuditReader:
    def __init__(self, rows: tuple[dict[str, object], ...]) -> None:
        self.rows = rows
        self.calls = 0

    async def list_incident_evidence(
        self,
        *,
        correlation_id: str,
        limit: int,
    ) -> tuple[tuple[dict[str, object], ...], bool]:
        assert correlation_id == _CORRELATION_ID
        assert limit == 50
        self.calls += 1
        return self.rows, False


def _receipt(*, review_required: bool = True) -> dict[str, object]:
    return {
        "provider": "azure",
        "disposition": "breaking" if review_required else "unchanged",
        "reason": "schema_breaking" if review_required else "schema_unchanged",
        "checked_at": _NOW.isoformat(),
        "source_name": "azure-bicep-primary",
        "source_kind": "primary",
        "source_revision": "d" * 40,
        "fallback_used": False,
        "baseline_digest": "sha256:" + "e" * 64,
        "observed_digest": "sha256:" + "f" * 64,
        "drift_digest": _DRIFT_DIGEST if review_required else None,
        "type_count": 3000,
        "modeled_count": 62,
        "stale": False,
        "review_required": review_required,
        "review_package_digest": "sha256:" + "1" * 64 if review_required else None,
        "review_dispatched": review_required,
        "review_handoff_reason": None,
        "grants_authority": False,
    }


def _audit_row() -> dict[str, object]:
    payload = {
        "producer_principal": "Forseti",
        "correlation_id": _CORRELATION_ID,
        "idempotency_key": f"provider-schema-drift:{_DRIFT_DIGEST}",
        "resource_id": "provider-schema://azure",
        "action_type": "",
        "risk_verdict": "hil",
        "reason": "no_rule_match",
    }
    return {
        "seq": 7,
        "mode": "shadow",
        "entry": {
            "principal": "Forseti",
            "topic": "object.verdict",
            "correlation_id": _CORRELATION_ID,
            "entry_hash": "2" * 64,
            "payload": payload,
        },
    }


async def _persist_receipt(tmp_path: Path, receipt: dict[str, object]) -> InMemoryStateStore:
    ledger_root = tmp_path / "source"
    ledger_root.mkdir()
    ProviderSchemaLedger(ledger_root).record_run("azure", receipt)
    store = InMemoryStateStore()
    await StateStoreProviderSchemaLedger(store).persist(ledger_root)
    return store


async def test_collects_exact_generation_and_agent_audit(tmp_path: Path) -> None:
    store = await _persist_receipt(tmp_path, _receipt())

    evidence = await collect_provider_schema_deployment_evidence(
        store=store,
        audit_reader=_AuditReader((_audit_row(),)),
        ledger_root=tmp_path / "readback",
        application_source_commit=_SOURCE_COMMIT,
        runtime_image_revision=_RUNTIME_REVISION,
        plan_id=_PLAN_ID,
        execution_name="provider-schema-abc123",
        execution_status="Succeeded",
        started_at=_NOW - timedelta(seconds=1),
    )

    assert evidence["provider_source_revision"] == "d" * 40
    assert (
        evidence["job_execution_ref_digest"]
        == hashlib.sha256(b"provider-schema-abc123").hexdigest()
    )
    assert evidence["baseline_digest"] == "sha256:" + "e" * 64
    assert evidence["drift_digest"] == _DRIFT_DIGEST
    assert evidence["review_package_digest"] == "sha256:" + "1" * 64
    assert str(evidence["durable_generation_digest"]).startswith("sha256:")
    assert evidence["durable_generation_revision"] == 1
    assert evidence["heimdall_review_dispatched"] is True
    assert evidence["review_evidence_status"] == "verified"
    assert evidence["forseti_risk_verdict"] == "hil"
    assert evidence["forseti_reason"] == "no_rule_match"
    assert evidence["saga_audit_entry_hash"] == "2" * 64
    assert evidence["grants_authority"] is False


async def test_unchanged_run_records_agent_review_as_not_applicable(tmp_path: Path) -> None:
    store = await _persist_receipt(tmp_path, _receipt(review_required=False))

    evidence = await collect_provider_schema_deployment_evidence(
        store=store,
        audit_reader=_AuditReader(()),
        ledger_root=tmp_path / "readback",
        application_source_commit=_SOURCE_COMMIT,
        runtime_image_revision=_RUNTIME_REVISION,
        plan_id=_PLAN_ID,
        execution_name="provider-schema-abc123",
        execution_status="Succeeded",
        started_at=_NOW - timedelta(seconds=1),
    )

    assert evidence["review_evidence_status"] == "not_applicable"
    assert evidence["correlation_id"] is None
    assert evidence["saga_audit_entry_hash"] is None


async def test_rejects_inconsistent_no_review_receipt(tmp_path: Path) -> None:
    receipt = _receipt(review_required=False)
    receipt["review_dispatched"] = True
    store = await _persist_receipt(tmp_path, receipt)

    with pytest.raises(ProviderSchemaError, match="no-review receipt is inconsistent"):
        await collect_provider_schema_deployment_evidence(
            store=store,
            audit_reader=_AuditReader(()),
            ledger_root=tmp_path / "readback",
            application_source_commit=_SOURCE_COMMIT,
            runtime_image_revision=_RUNTIME_REVISION,
            plan_id=_PLAN_ID,
            execution_name="provider-schema-abc123",
            execution_status="Succeeded",
            started_at=_NOW - timedelta(seconds=1),
        )


async def test_compatible_run_retains_drift_without_agent_review(tmp_path: Path) -> None:
    receipt = _receipt(review_required=False)
    receipt.update({"disposition": "compatible", "reason": "schema_compatible"})
    receipt["drift_digest"] = _DRIFT_DIGEST
    store = await _persist_receipt(tmp_path, receipt)

    evidence = await collect_provider_schema_deployment_evidence(
        store=store,
        audit_reader=_AuditReader(()),
        ledger_root=tmp_path / "readback",
        application_source_commit=_SOURCE_COMMIT,
        runtime_image_revision=_RUNTIME_REVISION,
        plan_id=_PLAN_ID,
        execution_name="provider-schema-abc123",
        execution_status="Succeeded",
        started_at=_NOW - timedelta(seconds=1),
    )

    assert evidence["drift_digest"] == _DRIFT_DIGEST
    assert evidence["review_evidence_status"] == "not_applicable"


async def test_rejects_receipt_older_than_job_execution(tmp_path: Path) -> None:
    store = await _persist_receipt(tmp_path, _receipt())

    with pytest.raises(ProviderSchemaError, match="predates Job execution"):
        await collect_provider_schema_deployment_evidence(
            store=store,
            audit_reader=_AuditReader((_audit_row(),)),
            ledger_root=tmp_path / "readback",
            application_source_commit=_SOURCE_COMMIT,
            runtime_image_revision=_RUNTIME_REVISION,
            plan_id=_PLAN_ID,
            execution_name="provider-schema-abc123",
            execution_status="Succeeded",
            started_at=_NOW + timedelta(seconds=1),
        )


async def test_rejects_missing_forseti_and_saga_evidence(tmp_path: Path) -> None:
    store = await _persist_receipt(tmp_path, _receipt())
    waits: list[float] = []

    async def record_wait(seconds: float) -> None:
        waits.append(seconds)

    with pytest.raises(ProviderSchemaError, match="Forseti verdict and Saga audit"):
        await collect_provider_schema_deployment_evidence(
            store=store,
            audit_reader=_AuditReader(()),
            ledger_root=tmp_path / "readback",
            application_source_commit=_SOURCE_COMMIT,
            runtime_image_revision=_RUNTIME_REVISION,
            plan_id=_PLAN_ID,
            execution_name="provider-schema-abc123",
            execution_status="Succeeded",
            started_at=_NOW - timedelta(seconds=1),
            audit_attempts=2,
            audit_interval_seconds=0.25,
            sleep=record_wait,
        )

    assert waits == [0.25]
