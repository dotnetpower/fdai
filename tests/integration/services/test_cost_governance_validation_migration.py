from __future__ import annotations

import json
import runpy
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[3]
_MIGRATION = (
    _ROOT
    / "service-migrations/branches/core-control-plane/versions"
    / "20260829_core_cost_governance_validation.py"
)
_STORE = (
    _ROOT
    / "services/core-control-plane/src/fdai/delivery/persistence"
    / "postgres_cost_governance_validation.py"
)


def _sql(name: str) -> tuple[dict[str, object], str]:
    module = runpy.run_path(str(_MIGRATION))
    statements: list[str] = []
    module[name].__globals__["op"] = SimpleNamespace(execute=statements.append)
    module[name]()
    return module, "\n".join(statements)


def test_w7_validation_tables_are_core_owned_and_evidence_is_append_only() -> None:
    module, sql = _sql("upgrade")
    expected = {
        "cost_governance_lifecycle_receipt",
        "cost_governance_campaign_episode",
        "cost_governance_validation_retention",
        "cost_governance_validation_retention_event",
    }
    ownership = json.loads(
        (_ROOT / "service-migrations/ownership.json").read_text(encoding="utf-8")
    )

    assert module["migration_owner"] == "core-control-plane"
    assert set(module["owned_tables"]) == expected
    assert expected <= set(ownership["table_migrations"]["core-control-plane"])
    assert expected <= set(ownership["whole_table_writers"]["core-control-plane"])
    normalized = " ".join(sql.split())
    assert "GRANT SELECT, INSERT ON TABLE" in normalized
    assert (
        "GRANT SELECT, INSERT, UPDATE ON TABLE cost_governance_validation_retention TO fdai_core"
    ) in normalized
    assert "GRANT DELETE" not in sql
    assert "ON DELETE CASCADE" not in sql


def test_receipts_and_campaigns_pin_revision_provenance_and_idempotency() -> None:
    _, sql = _sql("upgrade")

    assert "activation_revision BIGINT NOT NULL" in sql
    assert "revision_pin_digest TEXT NOT NULL" in sql
    assert "receipt_digest TEXT NOT NULL UNIQUE" in sql
    assert "idempotency_key TEXT NOT NULL UNIQUE" in sql
    assert "UNIQUE (episode_id, idempotency_key)" in sql
    assert "UNIQUE (campaign_id, idempotency_key)" in sql
    assert "'install', 'enable', 'disable', 'upgrade', 'rollback'" in sql
    assert "'live-authoritative', 'synthetic', 'fixture', 'unit'" in sql
    assert "'beneficial-action', 'no-op', 'deny', 'hold-unresolved'" in sql
    assert "jsonb_array_length(evidence_refs) BETWEEN 1 AND 64" in sql


def test_validation_retention_is_revisioned_held_and_bounded() -> None:
    _, sql = _sql("upgrade")
    source = _STORE.read_text(encoding="utf-8")

    assert "legal_hold BOOLEAN NOT NULL DEFAULT FALSE" in sql
    assert "legal_hold = (legal_hold_ref IS NOT NULL)" in sql
    assert "purged_at IS NULL OR (NOT legal_hold AND purged_at >= purge_after)" in sql
    assert "WHERE purge_after <= %s" in source
    assert "AND NOT legal_hold" in source
    assert "LIMIT %s" in source
    assert "FOR UPDATE SKIP LOCKED" in source
    assert "revision = revision + 1" in source
    assert "expected_revision" in source


def test_store_verifies_receipt_digest_and_campaign_cas() -> None:
    source = _STORE.read_text(encoding="utf-8")

    assert "receipt.verify_digest(expected_receipt_digest)" in source
    assert "persisted lifecycle receipt failed digest verification" in source
    assert "episode.revision != expected_revision + 1" in source
    assert "actual != expected_revision" in source
    assert source.count("ON CONFLICT DO NOTHING") >= 2
    assert "revision_pin_digest = %s" in source


def test_w7_migration_has_explicit_reverse_path() -> None:
    _, downgrade = _sql("downgrade")

    assert "DROP TABLE cost_governance_validation_retention_event" in downgrade
    assert "DROP TABLE cost_governance_validation_retention" in downgrade
    assert "DROP TABLE cost_governance_campaign_episode" in downgrade
    assert "DROP TABLE cost_governance_lifecycle_receipt" in downgrade
