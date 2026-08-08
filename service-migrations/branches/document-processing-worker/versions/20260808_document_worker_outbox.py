"""Add the worker-owned lifecycle and deletion publication outbox."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "document_worker_outbox_20260808"
down_revision: str | Sequence[str] | None = "document_worker_base_20260808"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "document-processing-worker"
owned_tables = ("document_worker_claim", "document_worker_outbox")
rollback = {
    "strategy": "drop-worker-outbox",
    "restores": "document_worker_base_20260808",
}
_LIFECYCLE_SCHEMA_COLUMNS = (
    "document_upload_session.revision",
    "document_version.revision",
)
migration_prerequisites: dict[str, str | tuple[str, ...]] = {
    "revision": "ingestion_api_outbox_20260808",
    "columns": _LIFECYCLE_SCHEMA_COLUMNS,
}


def _require_lifecycle_schema() -> None:
    """Refuse worker migration when the API-owned revision fence is absent."""
    inspector = sa.inspect(op.get_bind())
    missing: list[str] = []
    for prerequisite in _LIFECYCLE_SCHEMA_COLUMNS:
        table, column = prerequisite.rsplit(".", maxsplit=1)
        available = {item["name"] for item in inspector.get_columns(table)}
        if column not in available:
            missing.append(prerequisite)
    if missing:
        revision = migration_prerequisites["revision"]
        raise RuntimeError(
            f"document-processing-worker migration requires {revision}; "
            f"missing columns: {', '.join(missing)}"
        )


def upgrade() -> None:
    _require_lifecycle_schema()
    op.drop_constraint(
        "document_worker_claim_stage_check",
        "document_worker_claim",
        type_="check",
    )
    op.create_check_constraint(
        "document_worker_claim_stage_check",
        "document_worker_claim",
        "stage IN ('received_replay', 'inspection', 'protection_replay', "
        "'safety_decision', 'indexing', 'deletion')",
    )
    op.create_table(
        "document_worker_outbox",
        sa.Column("event_id", sa.Uuid(), primary_key=True),
        sa.Column("idempotency_key", sa.Text(), nullable=False, unique=True),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("partition_key", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.execute(
        "REVOKE ALL PRIVILEGES ON TABLE document_worker_outbox "
        "FROM PUBLIC, fdai_ingestion_api, fdai_ingestion_cohost"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON TABLE document_worker_outbox TO fdai_ingestion_worker"
    )


def _require_no_unpublished_outbox() -> None:
    count = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM document_worker_outbox WHERE published_at IS NULL"))
        .scalar_one()
    )
    if int(count) != 0:
        raise RuntimeError(
            "document-processing-worker downgrade is blocked while unpublished outbox rows exist"
        )


def _require_no_inflight_deletion_claims() -> None:
    count = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT count(*) FROM document_worker_claim "
                "WHERE stage = 'deletion' AND status <> 'completed'"
            )
        )
        .scalar_one()
    )
    if int(count) != 0:
        raise RuntimeError(
            "document-processing-worker downgrade is blocked while in-flight deletion claims exist"
        )


def downgrade() -> None:
    _require_no_unpublished_outbox()
    _require_no_inflight_deletion_claims()
    op.execute(
        "DELETE FROM document_worker_claim WHERE stage = 'deletion' AND status = 'completed'"
    )
    op.execute("REVOKE ALL PRIVILEGES ON TABLE document_worker_outbox FROM fdai_ingestion_worker")
    op.drop_table("document_worker_outbox")
    op.drop_constraint(
        "document_worker_claim_stage_check",
        "document_worker_claim",
        type_="check",
    )
    op.create_check_constraint(
        "document_worker_claim_stage_check",
        "document_worker_claim",
        "stage IN ('received_replay', 'inspection', 'protection_replay', "
        "'safety_decision', 'indexing')",
    )
