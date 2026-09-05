"""Grant the Operator runtime read-only inventory invalidation watermark access."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "operator_inventory_invalidation_read_20260906"
down_revision: str | Sequence[str] | None = "operator_handover_document_read_20260905"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "operator-service"
owned_tables: tuple[str, ...] = ()
rollback = {
    "strategy": "revoke-operator-inventory-invalidation-read",
    "restores": "operator_handover_document_read_20260905",
    "requires": "operator-inventory-invalidation-stream-stopped",
}


def upgrade() -> None:
    """Expose only the durable journal watermark to the Operator invalidation stream.

    The Operator SSE invalidation signal never reads resource identities,
    provider references, properties, or principals from the Core-owned
    inventory observation journal; it only needs SELECT to compute a
    bounded watermark page, so no other privilege is granted.
    """
    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE inventory_observation_journal
            FROM PUBLIC, fdai_operator;
        GRANT SELECT ON TABLE inventory_observation_journal TO fdai_operator;
        """
    )


def downgrade() -> None:
    """Remove inventory journal access from the Operator role."""
    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE inventory_observation_journal FROM fdai_operator
        """
    )
