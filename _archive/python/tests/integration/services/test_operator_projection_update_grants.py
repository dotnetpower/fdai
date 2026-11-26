"""Contract checks for Operator-owned projection update privileges."""

from __future__ import annotations

import runpy
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_REVISION = (
    _REPO_ROOT / "service-migrations/branches/operator-service/versions/"
    "20260830_operator_projection_update_grants.py"
)


def test_projection_update_migration_grants_only_required_updates() -> None:
    source = _REVISION.read_text(encoding="utf-8")
    migration = runpy.run_path(str(_REVISION))

    assert migration["down_revision"] == "operator_background_task_projection_transport_20260829"
    assert migration["owned_tables"] == (
        "operator_read_investigation_completion",
        "operator_background_task_progress",
    )
    assert (
        "GRANT UPDATE (completion_id)\n"
        "        ON TABLE operator_read_investigation_completion TO fdai_operator" in source
    )
    assert (
        "GRANT UPDATE (task_id)\n"
        "        ON TABLE operator_background_task_progress TO fdai_operator" in source
    )
    assert "GRANT UPDATE ON TABLE" not in source
    assert "GRANT INSERT" not in source
    assert "GRANT DELETE" not in source


def test_projection_update_migration_revokes_only_added_updates() -> None:
    source = _REVISION.read_text(encoding="utf-8")

    assert (
        "REVOKE UPDATE (completion_id)\n"
        "        ON TABLE operator_read_investigation_completion FROM fdai_operator" in source
    )
    assert (
        "REVOKE UPDATE (task_id)\n"
        "        ON TABLE operator_background_task_progress FROM fdai_operator" in source
    )
