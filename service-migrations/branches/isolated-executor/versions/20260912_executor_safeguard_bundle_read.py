"""Grant isolated Executor read-only access to finalized safeguard bundles."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "executor_safeguard_bundle_read_20260912"
down_revision: str | Sequence[str] | None = "executor_outbox_pending_index_20260911"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "isolated-executor"
owned_tables: tuple[str, ...] = ()
migration_prerequisites = {
    "service": "core-control-plane",
    "revision": "core_safeguard_dispatch_evidence_20260911",
}
rollback = {
    "strategy": "revoke-executor-safeguard-bundle-read",
    "restores": "executor_outbox_pending_index_20260911",
    "requires": "isolated-executor-effect-consumer-stopped",
}


def upgrade() -> None:
    """Index bundle identity and grant only SELECT to the Executor role."""

    op.execute(
        """
        CREATE INDEX ix_safeguard_dispatch_bundle_digest
        ON safeguard_dispatch_evidence ((record #>> '{bundle,bundle_digest}'));

        REVOKE ALL PRIVILEGES ON TABLE safeguard_dispatch_evidence
        FROM PUBLIC, fdai_executor;
        GRANT SELECT ON TABLE safeguard_dispatch_evidence TO fdai_executor;
        """
    )


def downgrade() -> None:
    """Remove the read grant and lookup index after the consumer stops."""

    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE safeguard_dispatch_evidence
        FROM fdai_executor;
        DROP INDEX ix_safeguard_dispatch_bundle_digest;
        """
    )
