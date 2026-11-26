"""Fence active scanner claims with renewable, expiry-only leases."""

from __future__ import annotations

from alembic import op

revision = "core_code_security_claim_renewal_20261010"
down_revision = "core_code_security_claim_recovery_20261010"
branch_labels = None
depends_on = None
migration_owner = "core-control-plane"
owned_tables = ("state_kv",)
rollback = {
    "strategy": "restore-same-worker-claim-recovery",
    "restores": "core_code_security_claim_recovery_20261010",
    "requires": "code-security-workers-stopped",
}


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fdai_code_security_claim(
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

        CREATE FUNCTION fdai_code_security_renew(
            p_key TEXT, p_claim TEXT, p_lease INTEGER
        ) RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, public AS $$
        DECLARE affected BIGINT;
        BEGIN
            IF NOT COALESCE(starts_with(p_key, 'operator-proposal:operations:'), FALSE)
                OR length(COALESCE(p_claim, '')) NOT BETWEEN 1 AND 64
                OR p_lease IS NULL OR p_lease NOT BETWEEN 60 AND 7200 THEN
                RAISE EXCEPTION 'code-security renewal parameters denied';
            END IF;
            UPDATE public.state_kv SET value = value || jsonb_build_object(
                'claim_expires_at', NOW() + make_interval(secs => p_lease)
            ), updated_at = NOW()
            WHERE key = p_key
                AND value ->> 'operation' IN
                    ('code_security.repository_change', 'code_security.scan_request')
                AND value ->> 'claim_id' = p_claim
                AND value ->> 'dispatch_status' = 'claimed';
            GET DIAGNOSTICS affected = ROW_COUNT;
            RETURN affected = 1;
        END $$;
        REVOKE ALL ON FUNCTION fdai_code_security_renew(TEXT, TEXT, INTEGER) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION fdai_code_security_renew(TEXT, TEXT, INTEGER)
            TO fdai_code_security_worker;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP FUNCTION fdai_code_security_renew(TEXT, TEXT, INTEGER);
        CREATE OR REPLACE FUNCTION fdai_code_security_claim(
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
                        (state.value ->> 'dispatch_status' = 'claimed' AND (
                         (state.value ->> 'claim_expires_at')::timestamptz <= NOW()
                         OR state.value ->> 'claim_worker_id' = p_worker
                        )))
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
        """
    )
