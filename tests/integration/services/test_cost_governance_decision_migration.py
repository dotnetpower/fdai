from __future__ import annotations

import json
import runpy
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[3]
_MIGRATION = (
    _ROOT
    / "service-migrations/branches/core-control-plane/versions"
    / "20260828_core_cost_governance_decision.py"
)
_STORE = (
    _ROOT
    / "services/core-control-plane/src/fdai/delivery/persistence"
    / "postgres_cost_governance_decision.py"
)


def _sql() -> tuple[dict[str, object], str]:
    module = runpy.run_path(str(_MIGRATION))
    statements: list[str] = []
    module["upgrade"].__globals__["op"] = SimpleNamespace(execute=statements.append)
    module["upgrade"]()
    return module, "\n".join(statements)


def test_w4_w5_lineage_tables_are_core_owned_and_append_only() -> None:
    module, sql = _sql()
    expected = {
        "cost_governance_episode",
        "cost_governance_recovery",
        "cost_governance_settlement",
        "cost_governance_effect_settlement",
        "cost_governance_evidence",
        "cost_governance_retention",
        "cost_governance_retention_event",
    }

    assert module["migration_owner"] == "core-control-plane"
    assert set(module["owned_tables"]) == expected
    ownership = json.loads(
        (_ROOT / "service-migrations/ownership.json").read_text(encoding="utf-8")
    )
    assert expected <= set(ownership["table_migrations"]["core-control-plane"])
    assert expected <= set(ownership["whole_table_writers"]["core-control-plane"])
    assert "GRANT SELECT, INSERT ON TABLE" in " ".join(sql.split())
    assert "GRANT SELECT, INSERT, UPDATE ON TABLE cost_governance_retention" in " ".join(
        sql.split()
    )
    assert "GRANT DELETE" not in sql
    assert "ON DELETE CASCADE" not in sql


def test_episode_recovery_and_settlement_invariants_are_persisted() -> None:
    _, sql = _sql()

    assert "UNIQUE (episode_id, idempotency_key)" in sql
    assert "PRIMARY KEY (episode_id, revision)" in sql
    assert "attempt_index INTEGER NOT NULL CHECK (attempt_index BETWEEN 0 AND 6)" in sql
    assert "'reacquire-context', 'independent-source', 'remove-unsafe-options'" in sql
    assert "'verified', 'failed', 'censored', 'unscorable'" in sql
    assert "(step = 'independent-source' AND status = 'success')" in sql
    assert "observation_digest IS NOT NULL" in sql
    assert "completeness_digest IS NOT NULL" in sql
    assert "rollback_request_id IS NULL OR realized_savings = 0" in sql
    assert "UNIQUE (episode_id, episode_revision, idempotency_key)" in sql


def test_retention_is_revisioned_legal_hold_safe_and_bounded() -> None:
    _, sql = _sql()
    source = _STORE.read_text(encoding="utf-8")

    assert "legal_hold BOOLEAN NOT NULL DEFAULT FALSE" in sql
    assert "purged_at IS NULL OR (NOT legal_hold AND purged_at >= purge_after)" in sql
    assert "WHERE purge_after <= %s" in source
    assert "AND NOT legal_hold" in source
    assert "LIMIT %s" in source
    assert "FOR UPDATE SKIP LOCKED" in source
    assert "if not 1 <= limit <= 500" in source
    assert "vertical_package_activation" not in source


def test_store_uses_cas_and_idempotent_append_for_restart_replay() -> None:
    source = _STORE.read_text(encoding="utf-8")

    assert "record.revision != expected_revision + 1" in source
    assert "actual_revision != expected_revision" in source
    assert source.count("ON CONFLICT DO NOTHING") >= 5
    assert "revision != record.episode_revision" in source
    assert "INSERT INTO cost_governance_evidence" in source
    assert "episode record revision MUST follow expected revision" in source
    assert "recovery attempt index MUST match the fixed step order" in source
    assert "if attempt_index != last_index + 1" in source
    assert "SELECT MAX(attempt_index) AS attempt_index" in source
    assert "LIMIT 1\n                     FOR UPDATE" in source
