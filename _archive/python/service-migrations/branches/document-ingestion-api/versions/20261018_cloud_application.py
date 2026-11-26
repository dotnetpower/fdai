"""Persist independently reviewed content authority and exact single-request nonces."""

from collections.abc import Sequence

from alembic import op

revision: str = "cloud_application_20261018"
down_revision: str | Sequence[str] | None = "cloud_knowledge_20260914"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
migration_owner = "document-ingestion-api"
owned_tables = (
    "document_knowledge_policy",
    "document_knowledge_application",
    "document_knowledge_policy_audit",
)
created_tables = owned_tables
rollback = {
    "strategy": "stop-policy-application-and-remove-authority",
    "restores": "cloud_knowledge_20260914",
    "requires": "cloud-knowledge-consumers-stopped",
}


def upgrade() -> None:
    op.execute("""
        CREATE TABLE document_knowledge_policy (
            digest TEXT PRIMARY KEY, policy_id TEXT NOT NULL, revision BIGINT NOT NULL,
            payload JSONB NOT NULL, UNIQUE (policy_id, revision)
        );
        CREATE TABLE document_knowledge_application (
            upload_id UUID PRIMARY KEY, nonce UUID NOT NULL UNIQUE,
            policy_digest TEXT NOT NULL REFERENCES document_knowledge_policy(digest),
            payload JSONB NOT NULL
        );
        CREATE TABLE document_knowledge_policy_audit (
            event_id BIGSERIAL PRIMARY KEY, policy_digest TEXT NOT NULL,
            actor_id TEXT NOT NULL, action TEXT NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
        );
        REVOKE ALL ON document_knowledge_policy, document_knowledge_application,
            document_knowledge_policy_audit FROM PUBLIC;
        DO $grant$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fdai_ingestion_api') THEN
                GRANT SELECT, INSERT, UPDATE ON document_knowledge_policy TO fdai_ingestion_api;
                GRANT SELECT, INSERT ON document_knowledge_application,
                    document_knowledge_policy_audit TO fdai_ingestion_api;
                GRANT USAGE ON SEQUENCE document_knowledge_policy_audit_event_id_seq
                    TO fdai_ingestion_api;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fdai_core') THEN
                GRANT SELECT ON document_knowledge_policy, document_knowledge_application
                    TO fdai_core;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fdai_ingestion_worker') THEN
                GRANT SELECT ON document_knowledge_policy, document_knowledge_application
                    TO fdai_ingestion_worker;
            END IF;
        END $grant$;
    """)


def downgrade() -> None:
    op.execute(
        "DROP TABLE document_knowledge_application, document_knowledge_policy_audit, "
        "document_knowledge_policy"
    )
