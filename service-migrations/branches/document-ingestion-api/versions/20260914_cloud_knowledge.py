"""Add source-check checkpoints and immutable knowledge release admission records."""

from collections.abc import Sequence

from alembic import op

revision: str = "cloud_knowledge_20260914"
down_revision: str | Sequence[str] | None = "document_lifecycle_convergence_20260905"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "document-ingestion-api"
owned_tables = (
    "document_knowledge_source",
    "document_knowledge_check",
    "document_knowledge_release",
)
rollback = {
    "strategy": "stop-collector-and-remove-knowledge-metadata",
    "restores": "document_lifecycle_convergence_20260905",
    "requires": "cloud-knowledge-consumers-stopped",
}


def upgrade() -> None:
    """Create API-owned records without granting resource or document activation rights."""
    op.execute("""
        CREATE TABLE document_knowledge_source (
            registry_digest TEXT NOT NULL, source_id TEXT NOT NULL,
            revision BIGINT NOT NULL DEFAULT 0 CHECK (revision >= 0),
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            claim_id UUID, lease_until TIMESTAMPTZ,
            PRIMARY KEY (registry_digest, source_id)
        );
        CREATE TABLE document_knowledge_check (
            digest TEXT PRIMARY KEY, registry_digest TEXT NOT NULL, source_id TEXT NOT NULL,
            payload JSONB NOT NULL, recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
        );
        CREATE TABLE document_knowledge_release (
            collection_id TEXT NOT NULL, sequence BIGINT NOT NULL CHECK (sequence > 0),
            manifest_digest TEXT NOT NULL, upload_id UUID NOT NULL, payload JSONB NOT NULL,
            imported_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            PRIMARY KEY (collection_id, sequence), UNIQUE (manifest_digest)
        );
        REVOKE ALL ON document_knowledge_source, document_knowledge_check,
            document_knowledge_release FROM PUBLIC;
        DO $grant$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fdai_ingestion_api') THEN
                GRANT SELECT, INSERT, UPDATE ON document_knowledge_source TO fdai_ingestion_api;
                GRANT SELECT, INSERT ON document_knowledge_check, document_knowledge_release
                    TO fdai_ingestion_api;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fdai_core') THEN
                GRANT SELECT ON document_knowledge_source TO fdai_core;
            END IF;
        END $grant$;
    """)


def downgrade() -> None:
    """Remove only the stopped feature's metadata, never source documents or active indexes."""
    op.execute(
        "DROP TABLE document_knowledge_release, document_knowledge_check, document_knowledge_source"
    )
