"""Create and constrain the isolated Executor PostgreSQL runtime role."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "executor_runtime_role_20260808"
down_revision: str | Sequence[str] | None = "executor_receipt_outbox_20260808"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "isolated-executor"
owned_tables = ("action_idempotency", "executor_receipt_outbox")
migration_prerequisites = {
    "service": "core-control-plane",
    "revision": "core_shared_data_ownership_20260808",
}
rollback = {
    "strategy": "revoke-executor-role-after-outbox-drain",
    "restores": "executor_receipt_outbox_20260808",
    "requires": "executor-runtime-stopped-and-receipt-outbox-drained",
}


def upgrade() -> None:
    op.execute(
        """
        DO $role$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fdai_executor') THEN
                CREATE ROLE fdai_executor
                    NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
                    NOINHERIT NOREPLICATION NOBYPASSRLS;
            END IF;
        END
        $role$;

        ALTER ROLE fdai_executor
            NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
            NOINHERIT NOREPLICATION NOBYPASSRLS;
        GRANT fdai_executor TO CURRENT_USER;
        GRANT USAGE ON SCHEMA public TO fdai_executor;

        REVOKE ALL PRIVILEGES ON TABLE state_kv, audit_log,
            action_idempotency, executor_receipt_outbox FROM PUBLIC, fdai_executor;
        REVOKE ALL PRIVILEGES ON SEQUENCE audit_log_seq_seq FROM PUBLIC, fdai_executor;

        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE state_kv TO fdai_executor;
        GRANT SELECT, INSERT ON TABLE audit_log TO fdai_executor;
        GRANT USAGE, SELECT ON SEQUENCE audit_log_seq_seq TO fdai_executor;
        GRANT SELECT, INSERT ON TABLE action_idempotency TO fdai_executor;
        GRANT SELECT, INSERT, UPDATE ON TABLE executor_receipt_outbox TO fdai_executor;

        CREATE OR REPLACE FUNCTION enforce_state_kv_namespace_owner()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        AS $state_owner$
        DECLARE
            source_key TEXT;
            target_key TEXT;
        BEGIN
            source_key := CASE WHEN TG_OP = 'INSERT' THEN NEW.key ELSE OLD.key END;
            target_key := CASE WHEN TG_OP = 'DELETE' THEN OLD.key ELSE NEW.key END;
            IF current_user = 'fdai_ingestion_api'
               AND NOT (
                   (
                       starts_with(source_key, 'stewardship_merge:')
                       OR starts_with(source_key, 'stewardship_repository_draft:')
                   )
                   AND (
                       starts_with(target_key, 'stewardship_merge:')
                       OR starts_with(target_key, 'stewardship_repository_draft:')
                   )
               ) THEN
                RAISE EXCEPTION
                    'fdai_ingestion_api does not own this state_kv namespace';
            ELSIF current_user = 'fdai_ingestion_worker'
                  AND NOT (
                      starts_with(source_key, 'handover_draft:')
                      AND starts_with(target_key, 'handover_draft:')
                  ) THEN
                RAISE EXCEPTION
                    'fdai_ingestion_worker does not own this state_kv namespace';
            ELSIF current_user = 'fdai_executor'
                  AND NOT (
                      (
                          starts_with(source_key, 'isolated-executor:')
                          OR starts_with(source_key, 'isolated_executor_')
                      )
                      AND (
                          starts_with(target_key, 'isolated-executor:')
                          OR starts_with(target_key, 'isolated_executor_')
                      )
                  ) THEN
                RAISE EXCEPTION
                    'fdai_executor does not own this state_kv namespace';
            ELSIF current_user = 'fdai_ingestion_cohost' THEN
                RAISE EXCEPTION
                    'fdai_ingestion_cohost has no state_kv write ownership';
            END IF;
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END;
        $state_owner$;
        """
    )


def _require_outbox_drained() -> None:
    count = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM executor_receipt_outbox WHERE published_at IS NULL"))
        .scalar_one()
    )
    if int(count) != 0:
        raise RuntimeError(
            "isolated-executor role downgrade is blocked while unpublished receipts exist"
        )


def downgrade() -> None:
    _require_outbox_drained()
    op.execute(
        """
        CREATE OR REPLACE FUNCTION enforce_state_kv_namespace_owner()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        AS $state_owner$
        DECLARE
            source_key TEXT;
            target_key TEXT;
        BEGIN
            source_key := CASE WHEN TG_OP = 'INSERT' THEN NEW.key ELSE OLD.key END;
            target_key := CASE WHEN TG_OP = 'DELETE' THEN OLD.key ELSE NEW.key END;
            IF current_user = 'fdai_ingestion_api'
               AND NOT (
                   (
                       starts_with(source_key, 'stewardship_merge:')
                       OR starts_with(source_key, 'stewardship_repository_draft:')
                   )
                   AND (
                       starts_with(target_key, 'stewardship_merge:')
                       OR starts_with(target_key, 'stewardship_repository_draft:')
                   )
               ) THEN
                RAISE EXCEPTION
                    'fdai_ingestion_api does not own this state_kv namespace';
            ELSIF current_user = 'fdai_ingestion_worker'
                  AND NOT (
                      starts_with(source_key, 'handover_draft:')
                      AND starts_with(target_key, 'handover_draft:')
                  ) THEN
                RAISE EXCEPTION
                    'fdai_ingestion_worker does not own this state_kv namespace';
            ELSIF current_user = 'fdai_ingestion_cohost' THEN
                RAISE EXCEPTION
                    'fdai_ingestion_cohost has no state_kv write ownership';
            END IF;
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END;
        $state_owner$;

        REVOKE ALL PRIVILEGES ON TABLE state_kv, audit_log,
            action_idempotency, executor_receipt_outbox FROM fdai_executor;
        REVOKE ALL PRIVILEGES ON SEQUENCE audit_log_seq_seq FROM fdai_executor;
        REVOKE USAGE ON SCHEMA public FROM fdai_executor;
        REVOKE fdai_executor FROM CURRENT_USER;
        DROP ROLE fdai_executor;
        """
    )
