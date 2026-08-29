"""Contract checks for Operator-owned completion and conversation writes."""

from __future__ import annotations

import runpy
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_REVISION = (
    _REPO_ROOT / "service-migrations/branches/operator-service/versions/"
    "20260826_operator_read_investigation_completion.py"
)
_RETENTION_REVISION = (
    _REPO_ROOT / "service-migrations/branches/operator-service/versions/"
    "20260829_operator_completion_retention.py"
)


def test_completion_migration_grants_exact_conversation_writes() -> None:
    source = _REVISION.read_text(encoding="utf-8")
    migration = runpy.run_path(str(_REVISION))

    assert (
        'down_revision: str | Sequence[str] | None = "operator_index_maintenance_20260825"'
        in source
    )
    assert migration["owned_tables"] == (
        "operator_read_investigation_completion",
        "conversation_record",
        "conversation_turn",
    )
    assert migration["rollback"] == {
        "strategy": "stop-completion-consumer-and-drop-inbox",
        "restores": "operator_index_maintenance_20260825",
        "requires": "core-completion-publisher-stopped",
    }
    assert (
        "GRANT SELECT, INSERT ON TABLE\n"
        "            operator_read_investigation_completion\n"
        "        TO fdai_operator" in source
    )
    assert (
        "GRANT USAGE, SELECT ON SEQUENCE\n"
        "            operator_read_investigation_completion_sequence_seq\n"
        "        TO fdai_operator" in source
    )
    assert "GRANT SELECT, INSERT, UPDATE ON TABLE conversation_record TO fdai_operator" in source
    assert "GRANT SELECT, INSERT ON TABLE conversation_turn TO fdai_operator" in source
    assert "GRANT UPDATE ON TABLE conversation_turn" not in source
    assert "GRANT DELETE ON TABLE conversation_record" not in source
    assert "GRANT DELETE ON TABLE conversation_turn" not in source


def test_completion_migration_rollback_restores_read_only_conversation_access() -> None:
    source = _REVISION.read_text(encoding="utf-8")

    assert "REVOKE INSERT, UPDATE ON TABLE conversation_record FROM fdai_operator" in source
    assert "REVOKE INSERT ON TABLE conversation_turn FROM fdai_operator" in source
    assert (
        "REVOKE ALL PRIVILEGES ON SEQUENCE\n"
        "            operator_read_investigation_completion_sequence_seq\n"
        "        FROM fdai_operator" in source
    )
    assert (
        "REVOKE ALL PRIVILEGES ON TABLE\n"
        "            operator_read_investigation_completion\n"
        "        FROM fdai_operator" in source
    )


def test_completion_retention_grants_only_inbox_delete() -> None:
    source = _RETENTION_REVISION.read_text(encoding="utf-8")
    migration = runpy.run_path(str(_RETENTION_REVISION))

    assert (
        'down_revision: str | Sequence[str] | None = "operator_cost_governance_20260828"' in source
    )
    assert migration["owned_tables"] == ("operator_read_investigation_completion",)
    assert migration["rollback"] == {
        "strategy": "stop-completion-retention-and-revoke-delete",
        "restores": "operator_cost_governance_20260828",
        "requires": "operator-completion-retention-stopped",
    }
    assert (
        "GRANT DELETE ON TABLE operator_read_investigation_completion\n"
        "        TO fdai_operator" in source
    )
    assert "GRANT DELETE ON TABLE conversation_record" not in source
    assert "GRANT DELETE ON TABLE conversation_turn" not in source
    assert (
        "REVOKE DELETE ON TABLE operator_read_investigation_completion\n"
        "        FROM fdai_operator" in source
    )
