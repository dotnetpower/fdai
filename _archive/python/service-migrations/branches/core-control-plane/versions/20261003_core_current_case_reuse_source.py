"""Expose retained current-case reuse rows to the verifier role."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_current_case_reuse_source_20261003"
down_revision: str | Sequence[str] | None = "core_operational_evidence_action_history_20261003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
migration_owner = "core-control-plane"
owned_tables: tuple[str, ...] = ()
rollback = {
    "strategy": "drop-current-case-reuse-source-function",
    "restores": "core_operational_evidence_action_history_20261003",
    "requires": "verifier-stopped",
}


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION fdai_current_case_reuse_source(p_key TEXT)
        RETURNS JSONB LANGUAGE SQL STABLE SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp AS $$
            SELECT state.value
              FROM public.state_kv AS state
             WHERE starts_with(p_key, 'current-case-reuse:v1:')
               AND state.key = p_key
        $$;
        REVOKE ALL ON FUNCTION fdai_current_case_reuse_source(TEXT) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION fdai_current_case_reuse_source(TEXT)
        TO fdai_operational_evidence_verifier;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        REVOKE ALL ON FUNCTION fdai_current_case_reuse_source(TEXT)
        FROM fdai_operational_evidence_verifier;
        DROP FUNCTION fdai_current_case_reuse_source(TEXT);
        """
    )
