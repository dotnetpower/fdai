"""Represent genuinely lexical-only documents without fabricated embedding vectors."""

from collections.abc import Sequence

from alembic import op

revision: str = "cloud_knowledge_lexical_20260914"
down_revision: str | Sequence[str] | None = "document_protection_reconciliation_20260905"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
migration_owner = "document-processing-worker"
owned_tables = ("knowledge_chunk", "document_worker_effect")
rollback = {
    "strategy": "block-until-lexical-cloud-documents-retired",
    "restores": "document_protection_reconciliation_20260905",
}


def upgrade() -> None:
    op.execute("ALTER TABLE knowledge_chunk ALTER COLUMN embedding DROP NOT NULL")
    op.execute("ALTER TABLE document_worker_effect DROP CONSTRAINT ck_document_worker_effect_kind")
    op.execute(
        "ALTER TABLE document_worker_effect ADD CONSTRAINT ck_document_worker_effect_kind "
        "CHECK (effect_kind IN ('source_promotion', 'ephemeral_source_cleanup', "
        "'deletion_cleanup', 'knowledge_activation'))"
    )


def downgrade() -> None:
    # PostgreSQL deliberately rejects rollback while any lexical-only rows remain.
    op.execute("ALTER TABLE knowledge_chunk ALTER COLUMN embedding SET NOT NULL")
    # Existing activation evidence must be retained or explicitly retired before downgrade.
    op.execute("ALTER TABLE document_worker_effect DROP CONSTRAINT ck_document_worker_effect_kind")
    op.execute(
        "ALTER TABLE document_worker_effect ADD CONSTRAINT ck_document_worker_effect_kind "
        "CHECK (effect_kind IN ('source_promotion', 'ephemeral_source_cleanup', "
        "'deletion_cleanup'))"
    )
