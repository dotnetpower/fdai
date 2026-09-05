"""Add durable provider protection reconciliation state."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "document_protection_reconciliation_20260905"
down_revision: str | Sequence[str] | None = "worker_knowledge_ownership_20260808"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "document-processing-worker"
owned_tables = ("document_protection_reconciliation",)
rollback = {
    "strategy": "drop-protection-reconciliation-after-active-and-cleanup-queues-drain",
    "restores": "worker_knowledge_ownership_20260808",
}


def upgrade() -> None:
    op.create_table(
        "document_protection_reconciliation",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("upload_id", sa.Uuid(), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("provider_ref", sa.Text(), nullable=False),
        sa.Column("policy_revision", sa.BigInteger(), nullable=False),
        sa.Column("protection_state", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column(
            "next_check_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("claim_owner", sa.Text(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revision", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason_code", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("document_id", "version_id"),
        sa.ForeignKeyConstraint(
            ["document_id", "version_id"],
            ["document_version.document_id", "document_version.version_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["upload_id"],
            ["document_upload_session.upload_id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'cleanup_pending', 'revoked')",
            name="ck_document_protection_reconciliation_status",
        ),
        sa.CheckConstraint(
            "char_length(source_sha256) = 64",
            name="ck_document_protection_reconciliation_digest",
        ),
        sa.CheckConstraint(
            "(claim_owner IS NULL) = (lease_expires_at IS NULL)",
            name="ck_document_protection_reconciliation_lease",
        ),
    )
    op.create_index(
        "ix_document_protection_reconciliation_due",
        "document_protection_reconciliation",
        ["status", "next_check_at", "document_id", "version_id"],
        postgresql_where=sa.text("status IN ('active', 'cleanup_pending')"),
    )
    op.execute(
        "REVOKE ALL PRIVILEGES ON TABLE document_protection_reconciliation "
        "FROM PUBLIC, fdai_ingestion_api, fdai_ingestion_cohost"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON TABLE document_protection_reconciliation "
        "TO fdai_ingestion_worker"
    )


def downgrade() -> None:
    count = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT count(*) FROM document_protection_reconciliation WHERE status <> 'revoked'"
            )
        )
        .scalar_one()
    )
    if int(count) != 0:
        raise RuntimeError(
            "document-processing-worker downgrade is blocked while protection "
            "reconciliation work remains"
        )
    op.execute(
        "REVOKE ALL PRIVILEGES ON TABLE document_protection_reconciliation "
        "FROM fdai_ingestion_worker"
    )
    op.drop_index(
        "ix_document_protection_reconciliation_due",
        table_name="document_protection_reconciliation",
    )
    op.drop_table("document_protection_reconciliation")
