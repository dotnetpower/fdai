"""Contract checks for the Operator's SELECT-only workflow definition read grant."""

from __future__ import annotations

import runpy
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_REVISION = (
    _REPO_ROOT / "service-migrations/branches/operator-service/versions/"
    "20260929_operator_workflow_definition_read.py"
)


def test_workflow_definition_read_grant_is_select_only_and_revocable() -> None:
    source = _REVISION.read_text(encoding="utf-8")
    migration = runpy.run_path(str(_REVISION))
    upgrade = source[source.index("def upgrade") : source.index("def downgrade")]
    downgrade = source[source.index("def downgrade") :]

    assert migration["revision"] == "operator_workflow_definition_read_20260929"
    assert migration["down_revision"] == "operator_rule_activation_receipts_20260922"
    assert migration["migration_owner"] == "operator-service"
    assert migration["owned_tables"] == ("workflow_binding", "workflow_definition")
    assert migration["rollback"]["restores"] == migration["down_revision"]
    assert "GRANT SELECT ON TABLE workflow_definition, workflow_binding TO fdai_operator" in upgrade
    assert "FROM PUBLIC, fdai_operator" in upgrade
    assert upgrade.count("GRANT ") == 1
    assert "GRANT" not in downgrade
    assert "REVOKE ALL PRIVILEGES ON TABLE workflow_definition, workflow_binding" in downgrade
