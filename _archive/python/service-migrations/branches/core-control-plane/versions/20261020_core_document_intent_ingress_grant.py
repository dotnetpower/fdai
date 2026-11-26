"""Grant Core one exact worker-owned envelope read after both service prerequisites exist."""

from alembic import op

revision = "core_document_intent_ingress_20261020"
down_revision = "core_document_intent_20261019"
branch_labels = None
depends_on = None
migration_owner = "core-control-plane"
owned_tables: tuple[str, ...] = ()
rollback = {
    "strategy": "revoke-core-document-intent-envelope-read",
    "restores": "core_document_intent_20261019",
    "requires": "core-document-intent-consumer-stopped",
}


def upgrade() -> None:
    op.execute("GRANT EXECUTE ON FUNCTION fdai_document_intent_envelope(UUID,UUID) TO fdai_core")


def downgrade() -> None:
    op.execute("REVOKE EXECUTE ON FUNCTION fdai_document_intent_envelope(UUID,UUID) FROM fdai_core")
