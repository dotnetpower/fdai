"""Grant the scan worker fixed-parameter capabilities, never direct shared-table access."""

from __future__ import annotations

from alembic import op

revision = "core_code_security_role_20261009"
down_revision = "core_current_case_reuse_source_20261003"
branch_labels = None
depends_on = None
migration_owner = "core-control-plane"
owned_tables = ("state_kv", "audit_log")
rollback = {
    "strategy": "drop-code-security-worker-capabilities",
    "restores": "core_current_case_reuse_source_20261003",
    "requires": "code-security-workers-stopped",
}


def upgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fdai_code_security_worker') THEN
                CREATE ROLE fdai_code_security_worker NOLOGIN NOSUPERUSER NOCREATEDB
                    NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
            END IF;
        END $$;
        ALTER ROLE fdai_code_security_worker NOLOGIN NOSUPERUSER NOCREATEDB
            NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
        REVOKE pg_read_all_data, pg_write_all_data FROM fdai_code_security_worker;
        REVOKE ALL ON TABLE public.state_kv, public.audit_log FROM fdai_code_security_worker;
        REVOKE CREATE ON SCHEMA public FROM fdai_code_security_worker;
        GRANT USAGE ON SCHEMA public TO fdai_code_security_worker;
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_auth_members
                WHERE member = 'fdai_code_security_worker'::regrole
            ) OR has_table_privilege('fdai_code_security_worker', 'public.state_kv', 'SELECT')
                OR has_table_privilege('fdai_code_security_worker', 'public.state_kv', 'INSERT')
                OR has_table_privilege('fdai_code_security_worker', 'public.state_kv', 'UPDATE')
                OR has_table_privilege('fdai_code_security_worker', 'public.state_kv', 'DELETE')
                OR has_table_privilege('fdai_code_security_worker', 'public.audit_log', 'SELECT')
                OR has_table_privilege('fdai_code_security_worker', 'public.audit_log', 'INSERT')
                OR has_table_privilege('fdai_code_security_worker', 'public.audit_log', 'UPDATE')
                OR has_table_privilege('fdai_code_security_worker', 'public.audit_log', 'DELETE')
            THEN
                RAISE EXCEPTION 'code-security role has unexpected inherited or public grants';
            END IF;
        END $$;

        CREATE FUNCTION fdai_code_security_key_allowed(p_key TEXT) RETURNS BOOLEAN
        LANGUAGE SQL IMMUTABLE SET search_path = pg_catalog AS $$
            SELECT COALESCE(length(p_key) BETWEEN 1 AND 512 AND
                p_key ~ '^runtime:code-security-(repository|review|issues|schedule):.+$', FALSE)
        $$;
        REVOKE ALL ON FUNCTION fdai_code_security_key_allowed(TEXT) FROM PUBLIC;

        CREATE FUNCTION fdai_code_security_state_read(p_key TEXT) RETURNS JSONB
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
        BEGIN
            IF NOT public.fdai_code_security_key_allowed(p_key) THEN
                RAISE EXCEPTION 'code-security state scope denied' USING ERRCODE = '42501';
            END IF;
            RETURN (SELECT value FROM public.state_kv WHERE key = p_key);
        END $$;

        CREATE FUNCTION fdai_code_security_states(p_prefix TEXT, p_limit INTEGER)
        RETURNS TABLE(value JSONB) LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, public AS $$
        BEGIN
            IF p_prefix NOT IN (
                'runtime:code-security-repository:', 'runtime:code-security-review:',
                'runtime:code-security-issues:', 'runtime:code-security-schedule:'
            ) OR p_prefix IS NULL OR p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 1000 THEN
                RAISE EXCEPTION 'code-security state list scope denied' USING ERRCODE = '42501';
            END IF;
            RETURN QUERY SELECT state.value FROM public.state_kv AS state
                WHERE starts_with(state.key, p_prefix)
                ORDER BY state.updated_at DESC, state.key LIMIT p_limit;
        END $$;

        CREATE FUNCTION fdai_code_security_state_write(
            p_key TEXT, p_value JSONB, p_operation TEXT, p_revision BIGINT
        ) RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, public AS $$
        DECLARE affected BIGINT;
        BEGIN
            IF NOT public.fdai_code_security_key_allowed(p_key)
                OR jsonb_typeof(p_value) IS DISTINCT FROM 'object'
                OR octet_length(p_value::text) > 1000000
                OR p_operation IS NULL OR p_operation NOT IN ('insert', 'upsert', 'cas') THEN
                RAISE EXCEPTION 'code-security state write denied' USING ERRCODE = '42501';
            END IF;
            IF p_operation <> 'insert' AND (
                starts_with(p_key, 'runtime:code-security-review:') OR
                starts_with(p_key, 'runtime:code-security-issues:')
            ) THEN
                RAISE EXCEPTION 'code-security review evidence is immutable'
                    USING ERRCODE = '42501';
            END IF;
            IF p_operation = 'insert' THEN
                INSERT INTO public.state_kv(key, value) VALUES (p_key, p_value)
                    ON CONFLICT (key) DO NOTHING;
            ELSIF p_operation = 'upsert' THEN
                INSERT INTO public.state_kv(key, value) VALUES (p_key, p_value)
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW();
            ELSE
                IF p_revision IS NULL OR p_revision < 0 THEN
                    RAISE EXCEPTION 'invalid code-security expected revision';
                END IF;
                UPDATE public.state_kv SET value = p_value, updated_at = NOW()
                    WHERE key = p_key AND COALESCE(value ->> 'revision', '0') = p_revision::text;
            END IF;
            GET DIAGNOSTICS affected = ROW_COUNT;
            RETURN affected = 1;
        END $$;

        CREATE FUNCTION fdai_code_security_audit_head() RETURNS TEXT
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
        BEGIN
            PERFORM pg_advisory_xact_lock(4461889768303105);
            RETURN COALESCE((SELECT entry_hash FROM public.audit_log ORDER BY seq DESC LIMIT 1),
                repeat('0', 64));
        END $$;

        CREATE FUNCTION fdai_code_security_audit_append(
            p_canonical TEXT, p_previous TEXT, p_hash TEXT, p_event UUID
        ) RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, public AS $$
        DECLARE payload JSONB; current_hash TEXT;
        BEGIN
            IF octet_length(p_canonical) > 8192 THEN
                RAISE EXCEPTION 'code-security audit size denied' USING ERRCODE = '42501';
            END IF;
            payload := p_canonical::jsonb;
            IF jsonb_typeof(payload) IS DISTINCT FROM 'object' OR
                payload ->> 'kind' IS DISTINCT FROM 'code_security_repository_changed' OR
                payload ->> 'producer_principal' IS DISTINCT FROM 'Heimdall' OR
                payload -> 'execution_authority' IS DISTINCT FROM 'false'::jsonb OR
                payload ->> 'change' NOT IN ('registered', 'enabled', 'disabled',
                    'knowledge_connected', 'knowledge_disconnected') OR
                payload ->> 'change' IS NULL OR
                COALESCE(payload ->> 'repository_alias', '')
                    !~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$' OR
                length(COALESCE(payload ->> 'actor', '')) NOT BETWEEN 1 AND 256 OR
                EXISTS (SELECT 1 FROM jsonb_object_keys(payload) AS fields(name) WHERE name NOT IN
                    ('kind', 'producer_principal', 'change', 'repository_alias', 'provider',
                     'enabled', 'registration_revision', 'actor', 'execution_authority')) THEN
                RAISE EXCEPTION 'code-security audit scope denied' USING ERRCODE = '42501';
            END IF;
            current_hash := public.fdai_code_security_audit_head();
            IF current_hash IS DISTINCT FROM p_previous OR
                encode(sha256(convert_to(p_previous || p_canonical, 'UTF8')), 'hex')
                    IS DISTINCT FROM p_hash THEN
                RAISE EXCEPTION 'code-security audit chain mismatch';
            END IF;
            INSERT INTO public.audit_log
                (event_id, correlation_id, actor, action_kind, mode, entry,
                 previous_hash, entry_hash)
            VALUES (p_event, NULL, payload ->> 'actor', payload ->> 'kind', 'shadow',
                    payload, p_previous, p_hash);
        END $$;

        CREATE FUNCTION fdai_code_security_claim(
            p_claim TEXT, p_worker TEXT, p_lease INTEGER
        ) RETURNS TABLE(key TEXT, value JSONB) LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, public AS $$
        BEGIN
            IF length(COALESCE(p_claim, '')) NOT BETWEEN 1 AND 64
                OR length(COALESCE(p_worker, '')) NOT BETWEEN 1 AND 128
                OR p_lease IS NULL OR p_lease NOT BETWEEN 60 AND 7200 THEN
                RAISE EXCEPTION 'code-security claim parameters denied';
            END IF;
            RETURN QUERY
            WITH candidate AS (
                SELECT state.key FROM public.state_kv AS state
                WHERE starts_with(state.key, 'operator-proposal:operations:')
                    AND state.value ->> 'family' = 'operations'
                    AND state.value ->> 'operation' IN
                        ('code_security.repository_change', 'code_security.scan_request')
                    AND (state.value ->> 'dispatch_status' = 'pending' OR
                        (state.value ->> 'dispatch_status' = 'claimed' AND
                         (state.value ->> 'claim_expires_at')::timestamptz <= NOW()))
                ORDER BY state.value ->> 'accepted_at', state.key
                FOR UPDATE SKIP LOCKED LIMIT 1
            )
            UPDATE public.state_kv AS proposal SET value = proposal.value || jsonb_build_object(
                'dispatch_status', 'claimed', 'claim_id', p_claim, 'claim_worker_id', p_worker,
                'claim_expires_at', NOW() + make_interval(secs => p_lease),
                'attempt', COALESCE((proposal.value ->> 'attempt')::integer, 0) + 1
            ), updated_at = NOW() FROM candidate WHERE proposal.key = candidate.key
            RETURNING proposal.key, proposal.value;
        END $$;

        CREATE FUNCTION fdai_code_security_close(p_key TEXT, p_claim TEXT, p_update JSONB)
        RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, public AS $$
        DECLARE affected BIGINT;
        BEGIN
            IF NOT COALESCE(starts_with(p_key, 'operator-proposal:operations:'), FALSE)
                OR jsonb_typeof(p_update) IS DISTINCT FROM 'object'
                OR octet_length(p_update::text) > 16384
                OR p_update ->> 'dispatch_status' IS NULL
                OR p_update ->> 'dispatch_status' NOT IN ('published', 'rejected')
                OR EXISTS (SELECT 1 FROM jsonb_object_keys(p_update) AS fields(name)
                    WHERE name NOT IN ('dispatch_status', 'request_result', 'rejection_reason',
                                       'closed_at')) THEN
                RAISE EXCEPTION 'code-security close scope denied' USING ERRCODE = '42501';
            END IF;
            UPDATE public.state_kv SET value = value || p_update, updated_at = NOW()
            WHERE key = p_key AND value ->> 'family' = 'operations'
                AND value ->> 'operation' IN
                    ('code_security.repository_change', 'code_security.scan_request')
                AND value ->> 'claim_id' = p_claim
                AND value ->> 'dispatch_status' = 'claimed';
            GET DIAGNOSTICS affected = ROW_COUNT;
            RETURN affected = 1;
        END $$;

        REVOKE ALL ON FUNCTION fdai_code_security_state_read(TEXT),
            fdai_code_security_states(TEXT, INTEGER),
            fdai_code_security_state_write(TEXT, JSONB, TEXT, BIGINT),
            fdai_code_security_audit_head(),
            fdai_code_security_audit_append(TEXT, TEXT, TEXT, UUID),
            fdai_code_security_claim(TEXT, TEXT, INTEGER),
            fdai_code_security_close(TEXT, TEXT, JSONB) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION fdai_code_security_state_read(TEXT),
            fdai_code_security_states(TEXT, INTEGER),
            fdai_code_security_state_write(TEXT, JSONB, TEXT, BIGINT),
            fdai_code_security_audit_head(),
            fdai_code_security_audit_append(TEXT, TEXT, TEXT, UUID),
            fdai_code_security_claim(TEXT, TEXT, INTEGER),
            fdai_code_security_close(TEXT, TEXT, JSONB) TO fdai_code_security_worker;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP FUNCTION fdai_code_security_close(TEXT, TEXT, JSONB);
        DROP FUNCTION fdai_code_security_claim(TEXT, TEXT, INTEGER);
        DROP FUNCTION fdai_code_security_audit_append(TEXT, TEXT, TEXT, UUID);
        DROP FUNCTION fdai_code_security_audit_head();
        DROP FUNCTION fdai_code_security_state_write(TEXT, JSONB, TEXT, BIGINT);
        DROP FUNCTION fdai_code_security_states(TEXT, INTEGER);
        DROP FUNCTION fdai_code_security_state_read(TEXT);
        DROP FUNCTION fdai_code_security_key_allowed(TEXT);
        """
    )
