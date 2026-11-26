-- Migration Revision: operator_runtime_role_20260808
-- Down Revision: operator_base_20260808
-- Owner: operator-service
-- Extracted SQL Blocks: 1

-- Statement 1
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
