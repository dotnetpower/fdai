"""Grant Core runtime access to the adopted ontology release registry."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_ontology_release_access_20260813"
down_revision: str | Sequence[str] | None = "core_inventory_routes_links_20260810"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = ("ontology_release",)
rollback = {
    "strategy": "revoke-ontology-release-runtime-access",
    "restores": "core_inventory_routes_links_20260810",
    "requires": "core-runtime-stopped",
}


def upgrade() -> None:
    """Allow Core to persist and read immutable ontology release manifests."""
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE ontology_release TO fdai_core")


def downgrade() -> None:
    """Remove Core runtime access to the ontology release registry."""
    op.execute("REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLE ontology_release FROM fdai_core")
