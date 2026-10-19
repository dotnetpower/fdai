"""Private exact-diff intent provenance; source metadata remains ingestion-API owned."""

from alembic import op

revision = "core_document_intent_20261019"
down_revision = "core_canary_age_index_20261019"
branch_labels = None
depends_on = None
migration_owner = "core-control-plane"
owned_tables = (
    "document_intent_projection",
    "document_intent_transition",
    "document_intent_resource",
)
rollback = {
    "strategy": "drop-empty-document-intent-state",
    "restores": "core_canary_age_index_20261019",
    "requires": "consumers-stopped-and-no-retained-intent-projections",
}


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE document_intent_projection (
            digest TEXT PRIMARY KEY,
            diff JSONB NOT NULL,
            envelope JSONB NOT NULL,
            document_id UUID NOT NULL,
            version_id UUID NOT NULL,
            target_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'candidate',
            before_image JSONB,
            applied_revision BIGINT,
            approval_key TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX document_intent_active_target
            ON document_intent_projection(target_id) WHERE status IN ('applied','restored');
        CREATE TABLE document_intent_transition (
            digest TEXT NOT NULL REFERENCES document_intent_projection(digest),
            phase TEXT NOT NULL,
            correlation_id TEXT NOT NULL,
            receipt JSONB NOT NULL,
            published_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY(digest,phase,correlation_id)
        );
        CREATE TABLE document_intent_resource (
            id TEXT PRIMARY KEY,
            object_type TEXT NOT NULL CHECK(object_type='BusinessService'),
            properties JSONB NOT NULL,
            revision BIGINT NOT NULL CHECK(revision>0),
            type_version TEXT NOT NULL,
            catalog_digest TEXT NOT NULL
        );
        REVOKE ALL ON document_intent_projection, document_intent_transition,
            document_intent_resource FROM PUBLIC;
        GRANT SELECT,INSERT,UPDATE,DELETE ON document_intent_resource TO fdai_core;
        GRANT SELECT, INSERT, UPDATE ON document_intent_projection TO fdai_core;
        GRANT SELECT, INSERT, UPDATE ON document_intent_transition TO fdai_core;
        CREATE FUNCTION fdai_guard_document_intent() RETURNS TRIGGER
        LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
        BEGIN
            IF TG_TABLE_NAME='document_intent_projection' THEN
                IF OLD.digest IS DISTINCT FROM NEW.digest
                   OR OLD.diff IS DISTINCT FROM NEW.diff
                   OR OLD.envelope IS DISTINCT FROM NEW.envelope
                   OR OLD.document_id IS DISTINCT FROM NEW.document_id
                   OR OLD.version_id IS DISTINCT FROM NEW.version_id
                   OR OLD.target_id IS DISTINCT FROM NEW.target_id
                   OR OLD.created_at IS DISTINCT FROM NEW.created_at THEN
                    RAISE EXCEPTION 'document intent source and diff are immutable';
                END IF;
            ELSE
                IF OLD.digest IS DISTINCT FROM NEW.digest OR OLD.phase IS DISTINCT FROM NEW.phase
                   OR OLD.correlation_id IS DISTINCT FROM NEW.correlation_id
                   OR OLD.receipt IS DISTINCT FROM NEW.receipt
                   OR OLD.created_at IS DISTINCT FROM NEW.created_at THEN
                    RAISE EXCEPTION 'document intent transition is immutable';
                END IF;
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER document_intent_diff_guard BEFORE UPDATE ON document_intent_projection
            FOR EACH ROW EXECUTE FUNCTION fdai_guard_document_intent();
        CREATE TRIGGER document_intent_transition_guard BEFORE UPDATE ON document_intent_transition
            FOR EACH ROW EXECUTE FUNCTION fdai_guard_document_intent();
        CREATE FUNCTION fdai_document_intent_source(p_document UUID, p_version UUID)
        RETURNS JSONB LANGUAGE plpgsql VOLATILE SECURITY DEFINER
        SET search_path=pg_catalog,public AS $$
        DECLARE result JSONB;
        BEGIN
            SELECT payload || jsonb_build_object(
                '_row_revision', revision, '_row_state', state, '_row_active', active
            ) INTO result FROM public.document_version
            WHERE document_id=p_document AND version_id=p_version FOR SHARE;
            RETURN result;
        END $$;
        REVOKE ALL ON FUNCTION fdai_document_intent_source(UUID,UUID) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION fdai_document_intent_source(UUID,UUID) TO fdai_core;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM document_intent_projection) THEN
            RAISE EXCEPTION 'retained document intent prevents destructive downgrade';
          END IF;
        END $$;
        DROP FUNCTION fdai_document_intent_source(UUID,UUID);
        DROP TABLE document_intent_resource;
        DROP TABLE document_intent_transition;
        DROP TABLE document_intent_projection;
        DROP FUNCTION fdai_guard_document_intent();
        """
    )
