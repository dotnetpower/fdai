"""Create and constrain the independent Operator PostgreSQL runtime role."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "operator_runtime_role_20260808"
down_revision: str | Sequence[str] | None = "operator_base_20260808"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "operator-service"
owned_tables: tuple[str, ...] = ()
rollback = {
    "strategy": "revoke-and-drop-operator-runtime-role",
    "restores": "operator_base_20260808",
    "requires": "operator-runtime-stopped",
}


def upgrade() -> None:
    op.execute(
        """
        DO $role$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fdai_operator') THEN
                CREATE ROLE fdai_operator
                    NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
                    NOINHERIT NOREPLICATION NOBYPASSRLS;
            END IF;
        END
        $role$;

        ALTER ROLE fdai_operator
            NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
            NOINHERIT NOREPLICATION NOBYPASSRLS;
        REVOKE pg_read_all_data, pg_write_all_data FROM fdai_operator;
        GRANT fdai_operator TO CURRENT_USER;
        REVOKE CREATE ON SCHEMA public FROM fdai_operator;
        GRANT USAGE ON SCHEMA public TO fdai_operator;

        REVOKE ALL PRIVILEGES ON TABLE audit_log, state_kv
            FROM PUBLIC, fdai_operator;
        GRANT SELECT ON TABLE audit_log TO fdai_operator;
        GRANT SELECT, INSERT, UPDATE ON TABLE state_kv TO fdai_operator;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        REVOKE ALL PRIVILEGES ON TABLE audit_log, state_kv FROM fdai_operator;
        REVOKE USAGE ON SCHEMA public FROM fdai_operator;
        REVOKE fdai_operator FROM CURRENT_USER;
        DROP ROLE fdai_operator;
        """
    )
