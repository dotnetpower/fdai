"""Give the operational evidence verifier an exact lookup over Operator authentication receipts.

Core owns every verifier source function so that a Core rollback drops the function before the
verifier role it grants. The function is a fixed-parameter SECURITY DEFINER lookup with a pinned
search_path and no dynamic SQL; it returns at most two rows for one exact receipt digest so the
readback can detect a duplicate without probing any other receipt. The body is not validated at
creation, so Core can migrate before the Operator creates the receipt table; until then every call
fails and the verifier reports the receipt source unavailable.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_operator_receipt_source_20260930"
down_revision: str | Sequence[str] | None = "core_licensing_trial_20260929"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
migration_owner = "core-control-plane"
owned_tables: tuple[str, ...] = ()
rollback = {
    "strategy": "drop-operator-receipt-source-function",
    "restores": "core_licensing_trial_20260929",
    "requires": "verifier-stopped",
}


def upgrade() -> None:
    """Create the exact receipt lookup and grant EXECUTE only to the verifier role."""
    op.execute(
        """
        SET LOCAL check_function_bodies = off;
        CREATE FUNCTION fdai_operator_authentication_receipts_for_digest(p_receipt_digest TEXT)
        RETURNS TABLE (
            receipt_digest TEXT,
            request_id TEXT,
            principal_id TEXT,
            receipt JSONB,
            recorded_at TIMESTAMPTZ
        ) LANGUAGE SQL STABLE SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp AS $$
            SELECT source.receipt_digest, source.request_id, source.principal_id,
                   source.receipt, source.recorded_at
              FROM public.operator_authentication_receipt AS source
             WHERE p_receipt_digest ~ '^sha256:[0-9a-f]{64}$'
               AND source.receipt_digest = p_receipt_digest
             ORDER BY source.recorded_at DESC
             LIMIT 2
        $$;
        REVOKE ALL ON FUNCTION fdai_operator_authentication_receipts_for_digest(TEXT)
            FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION fdai_operator_authentication_receipts_for_digest(TEXT)
            TO fdai_operational_evidence_verifier;
        """
    )


def downgrade() -> None:
    """Revoke and drop the receipt lookup before the verifier role can be dropped."""
    op.execute(
        """
        REVOKE ALL ON FUNCTION fdai_operator_authentication_receipts_for_digest(TEXT)
            FROM fdai_operational_evidence_verifier;
        DROP FUNCTION fdai_operator_authentication_receipts_for_digest(TEXT);
        """
    )
