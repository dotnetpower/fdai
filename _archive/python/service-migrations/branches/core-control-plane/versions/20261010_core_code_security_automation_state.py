"""Allow the restricted scanner worker to retain revision and heartbeat state."""

# ruff: noqa: S608

from __future__ import annotations

from alembic import op

revision = "core_code_security_automation_20261010"
down_revision = "core_code_security_role_20261009"
branch_labels = None
depends_on = None
migration_owner = "core-control-plane"
owned_tables = ("state_kv",)
rollback = {
    "strategy": "restore-code-security-state-prefixes",
    "restores": "core_code_security_role_20261009",
    "requires": "code-security-workers-stopped",
}


def _replace_functions(*, automated: bool) -> None:
    categories = "repository|review|issues|schedule"
    prefixes = (
        "'runtime:code-security-repository:', 'runtime:code-security-review:', "
        "'runtime:code-security-issues:', 'runtime:code-security-schedule:'"
    )
    if automated:
        categories += "|revision|worker"
        prefixes += ", 'runtime:code-security-revision:', 'runtime:code-security-worker:'"
    statement = f"""
        CREATE OR REPLACE FUNCTION fdai_code_security_key_allowed(p_key TEXT) RETURNS BOOLEAN
        LANGUAGE SQL IMMUTABLE SET search_path = pg_catalog AS $$
            SELECT COALESCE(length(p_key) BETWEEN 1 AND 512 AND
                p_key ~ '^runtime:code-security-({categories}):.+$', FALSE)
        $$;

        CREATE OR REPLACE FUNCTION fdai_code_security_states(p_prefix TEXT, p_limit INTEGER)
        RETURNS TABLE(value JSONB) LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, public AS $$
        BEGIN
            IF p_prefix NOT IN ({prefixes})
                OR p_prefix IS NULL OR p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 1000 THEN
                RAISE EXCEPTION 'code-security state list scope denied' USING ERRCODE = '42501';
            END IF;
            RETURN QUERY SELECT state.value FROM public.state_kv AS state
                WHERE starts_with(state.key, p_prefix)
                ORDER BY state.updated_at DESC, state.key LIMIT p_limit;
        END $$;
        """
    op.execute(statement)


def upgrade() -> None:
    _replace_functions(automated=True)


def downgrade() -> None:
    _replace_functions(automated=False)
