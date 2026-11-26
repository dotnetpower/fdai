-- Migration Revision: 20260717_0027
-- Down Revision: 20260717_0026
-- Owner: alembic
-- Extracted SQL Blocks: 2

-- Statement 1
CREATE TABLE model_health_transition (
            transition_id BIGSERIAL PRIMARY KEY,
            model_role TEXT NOT NULL,
            deployment TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('unhealthy', 'recovered', 'selected')),
            failure_kind TEXT CHECK (
                failure_kind IS NULL OR failure_kind IN (
                    'auth', 'rate_limit', 'overloaded', 'timeout', 'transport', 'unknown'
                )
            ),
            failure_count INTEGER NOT NULL CHECK (failure_count >= 0),
            cooldown_seconds INTEGER NOT NULL CHECK (cooldown_seconds >= 0),
            recorded_at TIMESTAMPTZ NOT NULL,
            reason TEXT NOT NULL DEFAULT ''
        );

-- Statement 2
CREATE INDEX idx_model_health_transition_role_deployment ON model_health_transition(model_role, deployment, transition_id DESC);
