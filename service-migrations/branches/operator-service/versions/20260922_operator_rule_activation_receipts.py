"""Grant Operator append/read access to Core-owned Rule activation receipts."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "operator_rule_activation_receipts_20260922"
down_revision: str | Sequence[str] | None = "operator_chaos_report_read_20260921"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
migration_owner = "operator-service"
owned_tables: tuple[str, ...] = ()
migration_prerequisites = {
    "service": "core-control-plane",
    "revision": "core_rule_activation_receipts_20260922",
}
rollback = {
    "strategy": "revoke-rule-activation-receipt-grants-after-producers-stop",
    "restores": "operator_chaos_report_read_20260921",
    "requires": "rule-activation-consumers-and-producers-stopped",
}


def upgrade() -> None:
    """Keep Operator access on the source table and outside trusted receipts."""
    op.execute("REVOKE ALL ON TABLE operator_rule_activation_receipt FROM fdai_operator")


def downgrade() -> None:
    op.execute("REVOKE ALL ON TABLE operator_rule_activation_receipt FROM fdai_operator")
