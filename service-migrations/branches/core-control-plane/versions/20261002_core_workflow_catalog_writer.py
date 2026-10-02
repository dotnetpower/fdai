"""Restore Core's reviewed upstream workflow catalog writer privileges."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_workflow_catalog_writer_20261002"
down_revision: str | Sequence[str] | None = "core_operational_evidence_forecast_sources_20261002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
migration_owner = "core-control-plane"
owned_tables: tuple[str, ...] = ()
rollback = {
    "strategy": "revoke-core-workflow-catalog-writer",
    "restores": "core_operational_evidence_forecast_sources_20261002",
    "requires": "core-runtime-stopped",
}


def upgrade() -> None:
    """Allow Core catalog upserts without changing Operator authoring restrictions."""
    op.execute("GRANT SELECT, INSERT, UPDATE ON TABLE workflow_definition TO fdai_core;")


def downgrade() -> None:
    """Remove only the privileges introduced by this migration."""
    op.execute("REVOKE SELECT, INSERT, UPDATE ON TABLE workflow_definition FROM fdai_core;")
