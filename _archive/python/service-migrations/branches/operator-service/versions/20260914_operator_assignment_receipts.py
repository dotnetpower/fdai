"""Grant only insert/read access to the Core-owned immutable assignment receipt table."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "operator_assignment_receipts_20260914"
down_revision: str | Sequence[str] | None = "operator_conversation_document_refs_20260914"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
migration_owner = "operator-service"
owned_tables: tuple[str, ...] = ()
migration_prerequisites = {
    "service": "core-control-plane",
    "revision": "core_assignment_receipts_20260914",
}
rollback = {
    "strategy": "revoke-assignment-receipt-grants-after-producers-stop",
    "restores": "operator_conversation_document_refs_20260914",
    "requires": "assignment-consumers-and-producers-stopped",
}


def upgrade() -> None:
    """Operator may append authenticated requests but never edit their retained evidence."""
    op.execute("GRANT SELECT, INSERT ON TABLE operator_assignment_receipt TO fdai_operator")


def downgrade() -> None:
    """Revoke the grant without deleting any Core-owned request evidence."""
    op.execute("REVOKE SELECT, INSERT ON TABLE operator_assignment_receipt FROM fdai_operator")
