"""Make the document worker the sole knowledge chunk writer."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "worker_knowledge_ownership_20260808"
down_revision: str | Sequence[str] | None = "document_worker_effects_20260808"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "document-processing-worker"
owned_tables = ("knowledge_chunk",)
rollback = {
    "strategy": "restore-legacy-grants-after-dependent-runtime-stop",
    "restores": "document_worker_effects_20260808",
    "requires": "api-outbox-worker-knowledge-heads-shared-database-drained-and-explicit-stop-ack",
    "risk": "restores-api-delete-and-cohost-write-for-monolith-recovery-only",
}

_DEPENDENT_RUNTIME_GUARD = sa.text(
    """
    SELECT
        current_setting('fdai.dependent_runtimes_stopped', true) = 'on'
        AND (
            SELECT version_num
            FROM alembic_version_document_ingestion_api
        ) = 'ingestion_api_outbox_20260808'
        AND (
            SELECT version_num
            FROM alembic_version_document_processing_worker
        ) = 'worker_knowledge_ownership_20260808'
        AND NOT EXISTS (
            SELECT 1
            FROM pg_stat_activity
            WHERE datname = current_database()
            AND pid <> pg_backend_pid()
        )
    """
)


def _require_dependent_runtimes_stopped() -> None:
    """Refuse legacy grant restoration without explicit stopped-runtime proof."""
    safe_to_restore = op.get_bind().execute(_DEPENDENT_RUNTIME_GUARD).scalar_one()
    if safe_to_restore is not True:
        raise RuntimeError(
            "worker knowledge downgrade requires stopped ingestion runtimes at the "
            "API outbox and worker knowledge heads with "
            "fdai.dependent_runtimes_stopped=on"
        )


def upgrade() -> None:
    op.execute(
        "REVOKE ALL PRIVILEGES ON TABLE knowledge_chunk "
        "FROM fdai_ingestion_api, fdai_ingestion_worker, fdai_ingestion_cohost"
    )
    op.execute("GRANT SELECT ON TABLE knowledge_chunk TO fdai_ingestion_api")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE knowledge_chunk TO fdai_ingestion_worker"
    )
    op.execute("GRANT SELECT ON TABLE knowledge_chunk TO fdai_ingestion_cohost")


def downgrade() -> None:
    _require_dependent_runtimes_stopped()
    op.execute(
        "REVOKE ALL PRIVILEGES ON TABLE knowledge_chunk "
        "FROM fdai_ingestion_api, fdai_ingestion_worker, fdai_ingestion_cohost"
    )
    op.execute("GRANT SELECT, DELETE ON TABLE knowledge_chunk TO fdai_ingestion_api")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE knowledge_chunk "
        "TO fdai_ingestion_worker, fdai_ingestion_cohost"
    )
