"""Create the insert-only operational evidence proof store and its read-only source views.

Only the verifier role may insert proof records, nobody may update or delete them, and consumer
roles read them. The verifier reads Operator test-context commands, Mimir's revisioned history,
and its atomic audit rows through security-barrier views, so no caller-supplied function sees
the content of a row outside a view's filter. Built-in leakproof operators still evaluate every
underlying key, so planner estimates and EXPLAIN ANALYZE row counts can reveal whether a key
exists. The verifier holds no write role on any source it verifies and no explicit
temporary-object privilege.
Operator test-context command rows become insert-only for the Operator identity, and their
request fields and retained authentication receipt become immutable.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "core_operational_evidence_20260928"
down_revision: str | Sequence[str] | None = "core_rule_activation_receipts_20260922"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
migration_owner = "core-control-plane"
owned_tables = (
    "audit_log",
    "operational_evidence_admission",
    "operational_evidence_authentication",
    "operational_evidence_bundle",
    "operational_evidence_readback",
    "operational_evidence_rejection",
    "state_kv",
)
rollback = {
    "strategy": "drop-empty-operational-evidence-store-after-verifier-stops",
    "restores": "core_rule_activation_receipts_20260922",
    "requires": "verifier-stopped-and-no-retained-proof-records",
}


def upgrade() -> None:
    """Create roles, insert-only tables, immutability guards, and least-privilege views."""
    op.execute(
        """
        DO $role$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_roles WHERE rolname = 'fdai_operational_evidence_verifier'
            ) THEN
                CREATE ROLE fdai_operational_evidence_verifier
                    NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
                    NOINHERIT NOREPLICATION NOBYPASSRLS;
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_roles WHERE rolname = 'fdai_operational_evidence_reader'
            ) THEN
                CREATE ROLE fdai_operational_evidence_reader
                    NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
                    NOINHERIT NOREPLICATION NOBYPASSRLS;
            END IF;
        END
        $role$;
        ALTER ROLE fdai_operational_evidence_verifier
            NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
        ALTER ROLE fdai_operational_evidence_reader
            NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
        REVOKE pg_read_all_data, pg_write_all_data FROM fdai_operational_evidence_verifier;
        REVOKE pg_read_all_data, pg_write_all_data FROM fdai_operational_evidence_reader;
        GRANT USAGE ON SCHEMA public
            TO fdai_operational_evidence_verifier, fdai_operational_evidence_reader;

        CREATE TABLE operational_evidence_authentication (
            receipt_digest TEXT PRIMARY KEY CHECK (receipt_digest ~ '^sha256:[0-9a-f]{64}$'),
            receipt JSONB NOT NULL CHECK (jsonb_typeof(receipt) = 'object'),
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE TABLE operational_evidence_readback (
            receipt_digest TEXT PRIMARY KEY CHECK (receipt_digest ~ '^sha256:[0-9a-f]{64}$'),
            lookup_digest TEXT NOT NULL CHECK (lookup_digest ~ '^sha256:[0-9a-f]{64}$'),
            purpose_id TEXT NOT NULL CHECK (purpose_id ~ '^[a-z][a-z0-9_.-]{0,127}$'),
            pins_digest TEXT NOT NULL CHECK (pins_digest ~ '^sha256:[0-9a-f]{64}$'),
            receipt JSONB NOT NULL CHECK (jsonb_typeof(receipt) = 'object'),
            readback JSONB NOT NULL CHECK (jsonb_typeof(readback) = 'object'),
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE TABLE operational_evidence_bundle (
            bundle_digest TEXT PRIMARY KEY CHECK (bundle_digest ~ '^sha256:[0-9a-f]{64}$'),
            receipt_digest TEXT NOT NULL UNIQUE
                REFERENCES operational_evidence_readback (receipt_digest),
            bundle JSONB NOT NULL CHECK (jsonb_typeof(bundle) = 'object'),
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE TABLE operational_evidence_admission (
            record_key TEXT PRIMARY KEY
                CHECK (record_key ~ '^[0-9a-f]{64}/[0-9a-f]{64}/[0-9]{13}-[0-9a-f]{64}$'),
            pins_digest TEXT NOT NULL CHECK (pins_digest ~ '^sha256:[0-9a-f]{64}$'),
            lookup_digest TEXT NOT NULL CHECK (lookup_digest ~ '^sha256:[0-9a-f]{64}$'),
            purpose_id TEXT NOT NULL CHECK (purpose_id ~ '^[a-z][a-z0-9_.-]{0,127}$'),
            attempt_id TEXT NOT NULL UNIQUE CHECK (attempt_id ~ '^[0-9a-f]{32}$'),
            receipt_digest TEXT NOT NULL UNIQUE
                REFERENCES operational_evidence_readback (receipt_digest),
            record_digest TEXT NOT NULL UNIQUE CHECK (record_digest ~ '^sha256:[0-9a-f]{64}$'),
            record JSONB NOT NULL CHECK (jsonb_typeof(record) = 'object'),
            lineage JSONB NOT NULL CHECK (jsonb_typeof(lineage) = 'object'),
            verified_at TIMESTAMPTZ NOT NULL,
            valid_until TIMESTAMPTZ NOT NULL CHECK (valid_until > verified_at),
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX operational_evidence_admission_lookup
            ON operational_evidence_admission (lookup_digest, verified_at DESC);
        CREATE TABLE operational_evidence_rejection (
            record_key TEXT PRIMARY KEY
                CHECK (record_key ~ '^[0-9a-f]{64}/[0-9a-f]{64}/[0-9]{13}-[0-9a-f]{64}$'),
            pins_digest TEXT NOT NULL CHECK (pins_digest ~ '^sha256:[0-9a-f]{64}$'),
            lookup_digest TEXT NOT NULL CHECK (lookup_digest ~ '^sha256:[0-9a-f]{64}$'),
            purpose_id TEXT NOT NULL CHECK (purpose_id ~ '^[a-z][a-z0-9_.-]{0,127}$'),
            attempt_id TEXT NOT NULL UNIQUE CHECK (attempt_id ~ '^[0-9a-f]{32}$'),
            rejection_class TEXT NOT NULL CHECK (rejection_class IN (
                'conflicting', 'cross_scope', 'partial', 'replay_substituted',
                'revoked', 'stale', 'synthetic_live')),
            record_digest TEXT NOT NULL UNIQUE CHECK (record_digest ~ '^sha256:[0-9a-f]{64}$'),
            record JSONB NOT NULL CHECK (jsonb_typeof(record) = 'object'),
            recorded_at TIMESTAMPTZ NOT NULL,
            valid_until TIMESTAMPTZ NOT NULL
                CHECK (valid_until = recorded_at + INTERVAL '60 seconds')
        );
        CREATE INDEX operational_evidence_rejection_lookup
            ON operational_evidence_rejection (lookup_digest, recorded_at DESC);

        CREATE FUNCTION fdai_operational_evidence_writer()
        RETURNS TRIGGER LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $writer$
        BEGIN
            IF current_user <> 'fdai_operational_evidence_verifier' THEN
                RAISE EXCEPTION 'only the operational evidence verifier may write proof records';
            END IF;
            RETURN NEW;
        END;
        $writer$;
        CREATE FUNCTION fdai_operational_evidence_immutable()
        RETURNS TRIGGER LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $immutable$
        BEGIN
            RAISE EXCEPTION 'operational evidence proof records are immutable';
        END;
        $immutable$;
        REVOKE ALL ON FUNCTION fdai_operational_evidence_writer() FROM PUBLIC;
        REVOKE ALL ON FUNCTION fdai_operational_evidence_immutable() FROM PUBLIC;

        CREATE TRIGGER operational_evidence_authentication_writer
            BEFORE INSERT ON operational_evidence_authentication
            FOR EACH ROW EXECUTE FUNCTION fdai_operational_evidence_writer();
        CREATE TRIGGER operational_evidence_authentication_immutable
            BEFORE DELETE OR UPDATE ON operational_evidence_authentication
            FOR EACH ROW EXECUTE FUNCTION fdai_operational_evidence_immutable();
        CREATE TRIGGER operational_evidence_authentication_table_guard
            BEFORE TRUNCATE ON operational_evidence_authentication
            FOR EACH STATEMENT EXECUTE FUNCTION fdai_operational_evidence_immutable();
        CREATE TRIGGER operational_evidence_readback_writer
            BEFORE INSERT ON operational_evidence_readback
            FOR EACH ROW EXECUTE FUNCTION fdai_operational_evidence_writer();
        CREATE TRIGGER operational_evidence_readback_immutable
            BEFORE DELETE OR UPDATE ON operational_evidence_readback
            FOR EACH ROW EXECUTE FUNCTION fdai_operational_evidence_immutable();
        CREATE TRIGGER operational_evidence_readback_table_guard
            BEFORE TRUNCATE ON operational_evidence_readback
            FOR EACH STATEMENT EXECUTE FUNCTION fdai_operational_evidence_immutable();
        CREATE TRIGGER operational_evidence_bundle_writer
            BEFORE INSERT ON operational_evidence_bundle
            FOR EACH ROW EXECUTE FUNCTION fdai_operational_evidence_writer();
        CREATE TRIGGER operational_evidence_bundle_immutable
            BEFORE DELETE OR UPDATE ON operational_evidence_bundle
            FOR EACH ROW EXECUTE FUNCTION fdai_operational_evidence_immutable();
        CREATE TRIGGER operational_evidence_bundle_table_guard
            BEFORE TRUNCATE ON operational_evidence_bundle
            FOR EACH STATEMENT EXECUTE FUNCTION fdai_operational_evidence_immutable();
        CREATE TRIGGER operational_evidence_admission_writer
            BEFORE INSERT ON operational_evidence_admission
            FOR EACH ROW EXECUTE FUNCTION fdai_operational_evidence_writer();
        CREATE TRIGGER operational_evidence_admission_immutable
            BEFORE DELETE OR UPDATE ON operational_evidence_admission
            FOR EACH ROW EXECUTE FUNCTION fdai_operational_evidence_immutable();
        CREATE TRIGGER operational_evidence_admission_table_guard
            BEFORE TRUNCATE ON operational_evidence_admission
            FOR EACH STATEMENT EXECUTE FUNCTION fdai_operational_evidence_immutable();
        CREATE TRIGGER operational_evidence_rejection_writer
            BEFORE INSERT ON operational_evidence_rejection
            FOR EACH ROW EXECUTE FUNCTION fdai_operational_evidence_writer();
        CREATE TRIGGER operational_evidence_rejection_immutable
            BEFORE DELETE OR UPDATE ON operational_evidence_rejection
            FOR EACH ROW EXECUTE FUNCTION fdai_operational_evidence_immutable();
        CREATE TRIGGER operational_evidence_rejection_table_guard
            BEFORE TRUNCATE ON operational_evidence_rejection
            FOR EACH STATEMENT EXECUTE FUNCTION fdai_operational_evidence_immutable();

        REVOKE ALL ON TABLE
            operational_evidence_authentication, operational_evidence_readback,
            operational_evidence_bundle, operational_evidence_admission,
            operational_evidence_rejection
        FROM PUBLIC;
        GRANT SELECT, INSERT ON TABLE
            operational_evidence_authentication, operational_evidence_readback,
            operational_evidence_bundle, operational_evidence_admission,
            operational_evidence_rejection
        TO fdai_operational_evidence_verifier;
        GRANT SELECT ON TABLE
            operational_evidence_authentication, operational_evidence_readback,
            operational_evidence_bundle, operational_evidence_admission,
            operational_evidence_rejection
        TO fdai_operational_evidence_reader, fdai_core;

        CREATE FUNCTION fdai_guard_test_context_command_source()
        RETURNS TRIGGER LANGUAGE plpgsql
        SET search_path = public, pg_temp
        AS $guard$
        DECLARE
            request_field TEXT;
            command_operations TEXT[] := ARRAY[
                'test-context.propose', 'test-context.review', 'test-context.revoke'];
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF starts_with(NEW.key, 'operator-proposal:conversation:')
                   AND NEW.value ->> 'operation' = ANY (command_operations)
                   AND session_user <> 'fdai_operator'
                   AND current_setting('role', true) <> 'fdai_operator' THEN
                    RAISE EXCEPTION 'only Operator may record a test-context command';
                END IF;
                RETURN NEW;
            END IF;
            IF starts_with(OLD.key, 'operator-proposal:conversation:')
               AND OLD.value ->> 'operation' = ANY (command_operations) THEN
                IF TG_OP = 'DELETE' OR OLD.key <> NEW.key THEN
                    RAISE EXCEPTION 'test-context command source identity is immutable';
                END IF;
                FOREACH request_field IN ARRAY ARRAY[
                    'family', 'operation', 'principal_id', 'idempotency_key', 'payload',
                    'kind', 'proposal_id', 'request_digest', 'accepted_at',
                    'authentication_receipt'
                ] LOOP
                    IF OLD.value -> request_field IS DISTINCT FROM NEW.value -> request_field THEN
                        RAISE EXCEPTION 'test-context command source request is immutable';
                    END IF;
                END LOOP;
            ELSIF TG_OP <> 'DELETE' AND starts_with(NEW.key, 'operator-proposal:conversation:')
               AND NEW.value ->> 'operation' = ANY (command_operations) THEN
                RAISE EXCEPTION 'test-context command rows can only be inserted by Operator';
            END IF;
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END;
        $guard$;
        CREATE TRIGGER test_context_command_source_guard
            BEFORE INSERT OR DELETE OR UPDATE ON state_kv
            FOR EACH ROW EXECUTE FUNCTION fdai_guard_test_context_command_source();

        CREATE VIEW operational_evidence_test_context_command WITH (security_barrier) AS
            SELECT key,
                   jsonb_build_object(
                       'family', value -> 'family',
                       'operation', value -> 'operation',
                       'principal_id', value -> 'principal_id',
                       'idempotency_key', value -> 'idempotency_key',
                       'payload', value -> 'payload',
                       'kind', value -> 'kind',
                       'proposal_id', value -> 'proposal_id',
                       'request_digest', value -> 'request_digest',
                       'accepted_at', value -> 'accepted_at'
                   ) AS record,
                   value ->> 'dispatch_status' AS dispatch_status,
                   value -> 'authentication_receipt' AS authentication_receipt,
                   value -> 'payload' -> 'body' ->> 'access_scope_digest' AS access_scope_digest,
                   value -> 'payload' -> 'body' ->> 'target_ref' AS target_ref
              FROM public.state_kv
             WHERE starts_with(key, 'operator-proposal:conversation:')
               AND value ->> 'operation' IN (
                   'test-context.propose', 'test-context.review', 'test-context.revoke');
        CREATE VIEW operational_evidence_test_context_history WITH (security_barrier) AS
            SELECT key, value
              FROM public.state_kv
             WHERE starts_with(key, 'test-context-target:v1:');
        CREATE VIEW operational_evidence_test_context_audit WITH (security_barrier) AS
            SELECT seq, entry, previous_hash, entry_hash
              FROM public.audit_log
             WHERE action_kind = 'test_context.transition';
        REVOKE ALL ON TABLE
            operational_evidence_test_context_command,
            operational_evidence_test_context_history,
            operational_evidence_test_context_audit
        FROM PUBLIC;
        GRANT SELECT ON TABLE
            operational_evidence_test_context_command,
            operational_evidence_test_context_history,
            operational_evidence_test_context_audit
        TO fdai_operational_evidence_verifier;
        DO $temp$
        BEGIN
            EXECUTE format(
                'REVOKE TEMPORARY ON DATABASE %I FROM fdai_operational_evidence_verifier',
                current_database()
            );
        END
        $temp$;
        """
    )


def downgrade() -> None:
    """Refuse destructive rollback while any proof record is retained."""
    connection = op.get_bind()
    for table in (
        "operational_evidence_admission",
        "operational_evidence_rejection",
        "operational_evidence_bundle",
        "operational_evidence_readback",
        "operational_evidence_authentication",
    ):
        connection.execute(sa.text(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE"))
        if connection.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one():  # noqa: S608
            raise RuntimeError(
                "operational evidence rollback requires retained proof records to be preserved"
            )
    op.execute(
        """
        DROP VIEW operational_evidence_test_context_audit;
        DROP VIEW operational_evidence_test_context_history;
        DROP VIEW operational_evidence_test_context_command;
        DROP TRIGGER IF EXISTS test_context_command_source_guard ON state_kv;
        DROP FUNCTION fdai_guard_test_context_command_source();
        DROP TABLE operational_evidence_admission;
        DROP TABLE operational_evidence_rejection;
        DROP TABLE operational_evidence_bundle;
        DROP TABLE operational_evidence_readback;
        DROP TABLE operational_evidence_authentication;
        DROP FUNCTION fdai_operational_evidence_writer();
        DROP FUNCTION fdai_operational_evidence_immutable();
        REVOKE USAGE ON SCHEMA public
            FROM fdai_operational_evidence_verifier, fdai_operational_evidence_reader;
        DO $temp$
        BEGIN
            EXECUTE format(
                'REVOKE ALL ON DATABASE %I FROM fdai_operational_evidence_verifier',
                current_database()
            );
        END
        $temp$;
        DROP ROLE fdai_operational_evidence_verifier;
        DROP ROLE fdai_operational_evidence_reader;
        """
    )
