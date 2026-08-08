"""Add restart-safe worker external-effect reconciliation state."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "document_worker_effects_20260808"
down_revision: str | Sequence[str] | None = "document_worker_outbox_20260808"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "document-processing-worker"
owned_tables = ("document_worker_effect",)
rollback = {
    "strategy": "drop-worker-effect-journal-after-pending-effects-drain",
    "restores": "document_worker_outbox_20260808",
}


def upgrade() -> None:
    op.create_table(
        "document_worker_effect",
        sa.Column("effect_id", sa.Uuid(), primary_key=True),
        sa.Column("upload_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("effect_kind", sa.Text(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["upload_id"],
            ["document_upload_session.upload_id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("upload_id", "effect_kind", name="uq_document_worker_effect_kind"),
        sa.CheckConstraint(
            "effect_kind IN ('source_promotion', 'ephemeral_source_cleanup')",
            name="ck_document_worker_effect_kind",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'completed')",
            name="ck_document_worker_effect_status",
        ),
        sa.CheckConstraint(
            "(status = 'pending' AND completed_at IS NULL) "
            "OR (status = 'completed' AND completed_at IS NOT NULL)",
            name="ck_document_worker_effect_completion",
        ),
    )
    op.create_index(
        "ix_document_worker_effect_pending",
        "document_worker_effect",
        ["next_attempt_at", "created_at", "effect_id"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.execute(
        "REVOKE ALL PRIVILEGES ON TABLE document_worker_effect "
        "FROM PUBLIC, fdai_ingestion_api, fdai_ingestion_cohost"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON TABLE document_worker_effect TO fdai_ingestion_worker"
    )


def _require_no_pending_effects() -> None:
    count = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM document_worker_effect WHERE status = 'pending'"))
        .scalar_one()
    )
    if int(count) != 0:
        raise RuntimeError(
            "document-processing-worker downgrade is blocked while pending effects exist"
        )


def downgrade() -> None:
    _require_no_pending_effects()
    op.execute("REVOKE ALL PRIVILEGES ON TABLE document_worker_effect FROM fdai_ingestion_worker")
    op.drop_index("ix_document_worker_effect_pending", table_name="document_worker_effect")
    op.drop_table("document_worker_effect")
