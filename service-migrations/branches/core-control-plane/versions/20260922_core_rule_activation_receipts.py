"""Seal Operator Rule activation proposals at the Core-owned receipt boundary."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "core_rule_activation_receipts_20260922"
down_revision: str | Sequence[str] | None = "core_ontology_versions_20260921"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
migration_owner = "core-control-plane"
owned_tables = ("operator_rule_activation_receipt", "state_kv")
rollback = {
    "strategy": "drop-empty-rule-activation-receipts-after-writers-stop",
    "restores": "core_ontology_versions_20260921",
    "requires": "operator-grants-revoked-and-no-retained-receipts",
}


def upgrade() -> None:
    """Capture only new authenticated requests; never certify historical proposals."""
    op.execute(
        """
        CREATE TABLE operator_rule_activation_receipt (
            proposal_ref TEXT PRIMARY KEY
                CHECK (proposal_ref ~ '^operator-proposal:workflow:[0-9a-f]{64}$'),
            record JSONB NOT NULL CHECK (jsonb_typeof(record) = 'object'),
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        REVOKE ALL ON TABLE operator_rule_activation_receipt FROM PUBLIC;
        GRANT SELECT ON TABLE operator_rule_activation_receipt TO fdai_core;
        CREATE FUNCTION fdai_capture_rule_activation_receipt()
        RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $capture$
        BEGIN
            IF starts_with(NEW.key, 'operator-proposal:workflow:') AND NEW.value ->> 'operation' IN
                ('rule.activation-request', 'rule.activation-approve') THEN
                IF session_user <> 'fdai_operator'
                   AND current_setting('role', true) <> 'fdai_operator' THEN
                    RAISE EXCEPTION 'only Operator may record a Rule activation request';
                END IF;
                INSERT INTO public.operator_rule_activation_receipt(proposal_ref, record)
                VALUES (NEW.key, NEW.value);
            END IF;
            RETURN NEW;
        END;
        $capture$;
        REVOKE ALL ON FUNCTION fdai_capture_rule_activation_receipt() FROM PUBLIC;
        CREATE TRIGGER rule_activation_receipt_capture AFTER INSERT ON state_kv
            FOR EACH ROW EXECUTE FUNCTION fdai_capture_rule_activation_receipt();
        CREATE FUNCTION fdai_guard_rule_activation_proposal()
        RETURNS TRIGGER LANGUAGE plpgsql
        SET search_path = public, pg_temp
        AS $guard$
        DECLARE
            source_key TEXT;
            target_key TEXT;
            request_field TEXT;
        BEGIN
            source_key := CASE WHEN TG_OP = 'INSERT' THEN NEW.key ELSE OLD.key END;
            target_key := CASE WHEN TG_OP = 'DELETE' THEN OLD.key ELSE NEW.key END;
            IF TG_OP <> 'INSERT' AND starts_with(source_key, 'operator-proposal:workflow:')
               AND OLD.value ->> 'operation' IN
                   ('rule.activation-request', 'rule.activation-approve') THEN
                IF TG_OP = 'DELETE' OR source_key <> target_key THEN
                    RAISE EXCEPTION 'Rule activation source identity is immutable';
                END IF;
                FOREACH request_field IN ARRAY ARRAY[
                    'family', 'operation', 'principal_id', 'idempotency_key', 'payload',
                    'kind', 'mode', 'proposal_id', 'request_digest', 'accepted_at'
                ] LOOP
                    IF OLD.value -> request_field IS DISTINCT FROM NEW.value -> request_field THEN
                        RAISE EXCEPTION 'Rule activation source request is immutable';
                    END IF;
                END LOOP;
            END IF;
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END;
        $guard$;
        CREATE TRIGGER rule_activation_proposal_guard
            BEFORE INSERT OR DELETE OR UPDATE ON state_kv
            FOR EACH ROW EXECUTE FUNCTION fdai_guard_rule_activation_proposal();
        """
    )


def downgrade() -> None:
    """Refuse destructive rollback while accepted activation evidence remains."""
    connection = op.get_bind()
    connection.execute(
        sa.text("LOCK TABLE operator_rule_activation_receipt IN ACCESS EXCLUSIVE MODE")
    )
    count = connection.execute(
        sa.text("SELECT count(*) FROM operator_rule_activation_receipt")
    ).scalar_one()
    if count:
        raise RuntimeError(
            "Rule activation schema rollback requires retained receipts to be preserved"
        )
    op.execute(
        """
        DROP TRIGGER rule_activation_receipt_capture ON state_kv;
        DROP TRIGGER rule_activation_proposal_guard ON state_kv;
        DROP FUNCTION fdai_capture_rule_activation_receipt();
        DROP FUNCTION fdai_guard_rule_activation_proposal();
        DROP TABLE operator_rule_activation_receipt;
        """
    )
