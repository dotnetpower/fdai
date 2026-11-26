"""Contract checks for bounded Operator workflow authoring grants."""

from __future__ import annotations

import runpy
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_REVISION = (
    _REPO_ROOT / "service-migrations/branches/operator-service/versions/"
    "20260929_operator_workflow_authoring.py"
)


def test_workflow_authoring_grant_is_bounded_and_audited() -> None:
    source = _REVISION.read_text(encoding="utf-8")
    migration = runpy.run_path(str(_REVISION))
    upgrade = source[source.index("def upgrade") : source.index("def downgrade")]
    downgrade = source[source.index("def downgrade") :]

    assert migration["revision"] == "operator_workflow_authoring_20260929"
    assert migration["down_revision"] == "operator_workflow_definition_read_20260929"
    assert migration["migration_owner"] == "operator-service"
    assert "operator_workflow_authoring_audit" in migration["owned_tables"]
    assert "CREATE TABLE operator_workflow_authoring_audit" in upgrade
    assert "UNIQUE (principal_id, operation, idempotency_key)" in upgrade
    assert "GRANT SELECT, INSERT ON TABLE workflow_definition TO fdai_operator" in upgrade
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE workflow_binding" in upgrade
    assert "GRANT SELECT, INSERT ON TABLE operator_workflow_authoring_audit" in upgrade
    assert "DROP TABLE operator_workflow_authoring_audit" in downgrade
    assert "GRANT SELECT ON TABLE workflow_definition, workflow_binding" in downgrade
