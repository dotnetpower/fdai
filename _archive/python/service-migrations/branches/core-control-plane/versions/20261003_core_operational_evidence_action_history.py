"""Expose bounded action-audit readback for forecast history.

The verifier receives no direct SELECT on audit_log or state_kv. The function returns the hash
anchors for every Thor action-save audit row in the requested window and only returns ActionRun
payload fields when the run belongs to the exact target. That lets the verifier prove sequence and
hash continuity without receiving unrelated target payloads.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_operational_evidence_action_history_20261003"
down_revision: str | Sequence[str] | None = "core_workflow_catalog_writer_20261002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
migration_owner = "core-control-plane"
owned_tables: tuple[str, ...] = ()
rollback = {
    "strategy": "drop-forecast-action-history-source-function",
    "restores": "core_workflow_catalog_writer_20261002",
    "requires": "verifier-stopped",
}


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION fdai_forecast_action_history_audit(
            p_target_ref TEXT,
            p_start_at TIMESTAMPTZ,
            p_end_at TIMESTAMPTZ,
            p_limit INTEGER
        ) RETURNS TABLE (
            seq BIGINT,
            recorded_at TIMESTAMPTZ,
            entry JSONB,
            previous_hash TEXT,
            entry_hash TEXT,
            state_value JSONB
        ) LANGUAGE SQL STABLE SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp AS $$
            SELECT audit.seq::BIGINT,
                   audit.created_at AS recorded_at,
                   CASE WHEN run.value ->> 'resource_id' = p_target_ref
                        THEN audit.entry ELSE NULL::JSONB END AS entry,
                   audit.previous_hash::TEXT,
                   audit.entry_hash::TEXT,
                   CASE WHEN run.value ->> 'resource_id' = p_target_ref
                        THEN run.value ELSE NULL::JSONB END AS state_value
              FROM public.audit_log AS audit
              LEFT JOIN public.state_kv AS run
                ON run.key = 'thor:run|' || (audit.entry ->> 'correlation_id')
             WHERE char_length(p_target_ref) BETWEEN 1 AND 512
               AND p_start_at IS NOT NULL
               AND p_end_at IS NOT NULL
               AND p_start_at <= p_end_at
               AND p_limit BETWEEN 1 AND 512
               AND audit.action_kind = 'thor.action-run-save'
               AND audit.created_at >= p_start_at
               AND audit.created_at <= p_end_at
             ORDER BY audit.seq
             LIMIT p_limit
        $$;
        REVOKE ALL ON FUNCTION fdai_forecast_action_history_audit(
            TEXT, TIMESTAMPTZ, TIMESTAMPTZ, INTEGER
        ) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION fdai_forecast_action_history_audit(
            TEXT, TIMESTAMPTZ, TIMESTAMPTZ, INTEGER
        ) TO fdai_operational_evidence_verifier;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        REVOKE ALL ON FUNCTION fdai_forecast_action_history_audit(
            TEXT, TIMESTAMPTZ, TIMESTAMPTZ, INTEGER
        ) FROM fdai_operational_evidence_verifier;
        DROP FUNCTION fdai_forecast_action_history_audit(TEXT, TIMESTAMPTZ, TIMESTAMPTZ, INTEGER);
        """
    )
