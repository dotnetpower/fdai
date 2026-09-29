"""Retain content-free Operator authentication receipts for semantic read authorization."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "operator_authentication_receipts_20260929"
down_revision: str | Sequence[str] | None = "operator_workflow_definition_read_20260929"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "operator-service"
owned_tables: tuple[str, ...] = ("operator_authentication_receipt",)
rollback = {
    "strategy": "drop-empty-operator-authentication-receipts-after-operator-and-verifier-stop",
    "restores": "operator_workflow_definition_read_20260929",
    "requires": "operator-runtime-and-operational-evidence-verifier-stopped",
}


def upgrade() -> None:
    """Create an insert-only receipt table and exact verifier source function."""
    op.execute(
        """
        CREATE TABLE operator_authentication_receipt (
            receipt_digest TEXT PRIMARY KEY CHECK (receipt_digest ~ '^sha256:[0-9a-f]{64}$'),
            request_id TEXT NOT NULL CHECK (char_length(request_id) BETWEEN 1 AND 256),
            principal_id TEXT NOT NULL CHECK (char_length(principal_id) BETWEEN 1 AND 256),
            receipt JSONB NOT NULL CHECK (jsonb_typeof(receipt) = 'object'),
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX operator_authentication_receipt_request_idx
            ON operator_authentication_receipt (request_id, recorded_at DESC);

        CREATE FUNCTION fdai_operator_authentication_receipt_writer()
        RETURNS TRIGGER LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $writer$
        BEGIN
            IF current_user <> 'fdai_operator' THEN
                RAISE EXCEPTION 'only the Operator runtime may retain authentication receipts';
            END IF;
            RETURN NEW;
        END;
        $writer$;
        CREATE FUNCTION fdai_operator_authentication_receipt_immutable()
        RETURNS TRIGGER LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $immutable$
        BEGIN
            RAISE EXCEPTION 'Operator authentication receipts are immutable';
        END;
        $immutable$;
        REVOKE ALL ON FUNCTION fdai_operator_authentication_receipt_writer() FROM PUBLIC;
        REVOKE ALL ON FUNCTION fdai_operator_authentication_receipt_immutable() FROM PUBLIC;
        CREATE TRIGGER operator_authentication_receipt_writer
            BEFORE INSERT ON operator_authentication_receipt
            FOR EACH ROW EXECUTE FUNCTION fdai_operator_authentication_receipt_writer();
        CREATE TRIGGER operator_auth_receipt_update_immutable
            BEFORE UPDATE ON operator_authentication_receipt
            FOR EACH ROW EXECUTE FUNCTION fdai_operator_authentication_receipt_immutable();
        CREATE TRIGGER operator_auth_receipt_delete_immutable
            BEFORE DELETE ON operator_authentication_receipt
            FOR EACH ROW EXECUTE FUNCTION fdai_operator_authentication_receipt_immutable();

        REVOKE ALL PRIVILEGES ON TABLE operator_authentication_receipt FROM PUBLIC, fdai_operator;
        GRANT INSERT ON TABLE operator_authentication_receipt TO fdai_operator;

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
    """Drop the exact source function and the empty receipt table."""
    op.execute(
        """
        LOCK TABLE operator_authentication_receipt IN ACCESS EXCLUSIVE MODE;
        DO $guard$
        BEGIN
            IF EXISTS (SELECT 1 FROM operator_authentication_receipt LIMIT 1) THEN
                RAISE EXCEPTION 'operator authentication receipt downgrade requires an empty table';
            END IF;
        END
        $guard$;
        REVOKE ALL ON FUNCTION fdai_operator_authentication_receipts_for_digest(TEXT)
            FROM fdai_operational_evidence_verifier;
        DROP FUNCTION fdai_operator_authentication_receipts_for_digest(TEXT);
        DROP TRIGGER operator_auth_receipt_delete_immutable ON operator_authentication_receipt;
        DROP TRIGGER operator_auth_receipt_update_immutable ON operator_authentication_receipt;
        DROP TRIGGER operator_authentication_receipt_writer ON operator_authentication_receipt;
        """
    )
    op.execute(
        """
        DROP FUNCTION fdai_operator_authentication_receipt_immutable();
        DROP FUNCTION fdai_operator_authentication_receipt_writer();
        REVOKE ALL PRIVILEGES ON TABLE operator_authentication_receipt FROM fdai_operator;
        DROP TABLE operator_authentication_receipt;
        """
    )
