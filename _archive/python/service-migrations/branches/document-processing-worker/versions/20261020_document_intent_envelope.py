"""Retain exact normalized intent envelopes behind a restricted Core read function."""

from collections.abc import Sequence

from alembic import op

revision: str = "document_intent_envelope_20261020"
down_revision: str | Sequence[str] | None = "cloud_knowledge_lexical_20260914"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
migration_owner = "document-processing-worker"
owned_tables = ("document_intent_envelope",)
rollback = {
    "strategy": "drop-empty-document-intent-envelope",
    "restores": "cloud_knowledge_lexical_20260914",
    "requires": "core-intent-consumer-stopped-and-no-retained-envelopes",
}


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE document_intent_envelope (
            document_id UUID NOT NULL,
            version_id UUID NOT NULL,
            envelope JSONB NOT NULL,
            envelope_digest TEXT NOT NULL CHECK(envelope_digest ~ '^sha256:[0-9a-f]{64}$'),
            source_sha256 TEXT NOT NULL CHECK(source_sha256 ~ '^[0-9a-f]{64}$'),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY(document_id, version_id)
        );
        REVOKE ALL ON document_intent_envelope FROM PUBLIC;
        GRANT SELECT, INSERT, DELETE ON document_intent_envelope TO fdai_ingestion_worker;
        CREATE FUNCTION fdai_document_intent_envelope(p_document UUID, p_version UUID)
        RETURNS JSONB LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path=pg_catalog,public AS $$
          SELECT envelope FROM public.document_intent_envelope
          WHERE document_id=p_document AND version_id=p_version
        $$;
        REVOKE ALL ON FUNCTION fdai_document_intent_envelope(UUID,UUID) FROM PUBLIC;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM document_intent_envelope) THEN
            RAISE EXCEPTION 'retained document intent envelopes prevent destructive downgrade';
          END IF;
        END $$;
        DROP FUNCTION fdai_document_intent_envelope(UUID,UUID);
        DROP TABLE document_intent_envelope;
        """
    )
