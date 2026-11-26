-- Migration Revision: operator_cost_governance_20260828
-- Down Revision: operator_console_evidence_reads_20260827
-- Owner: operator-service
-- Extracted SQL Blocks: 1

-- Statement 1
CREATE TABLE IF NOT EXISTS cost_access_grant (
            grant_id TEXT NOT NULL CHECK (char_length(grant_id) BETWEEN 1 AND 256),
            principal_id TEXT NOT NULL CHECK (char_length(principal_id) BETWEEN 1 AND 256),
            revision BIGINT NOT NULL CHECK (revision >= 0),
            purpose TEXT NOT NULL CHECK (char_length(purpose) BETWEEN 1 AND 128),
            scopes JSONB NOT NULL CHECK (jsonb_typeof(scopes) = 'array'),
            disclosure JSONB NOT NULL CHECK (jsonb_typeof(disclosure) = 'object'),
            effective_at TIMESTAMPTZ NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            source_authority TEXT NOT NULL
                CHECK (char_length(source_authority) BETWEEN 1 AND 256),
            PRIMARY KEY (grant_id, revision),
            CHECK (effective_at < expires_at)
        );
        CREATE INDEX IF NOT EXISTS cost_access_grant_principal_idx
            ON cost_access_grant (principal_id, purpose, revision DESC);

        CREATE TABLE IF NOT EXISTS cost_disclosure_ceiling (
            singleton BOOLEAN NOT NULL DEFAULT TRUE CHECK (singleton),
            revision BIGINT NOT NULL CHECK (revision >= 0),
            disclosure JSONB NOT NULL CHECK (jsonb_typeof(disclosure) = 'object'),
            effective_at TIMESTAMPTZ NOT NULL,
            source_authority TEXT NOT NULL
                CHECK (char_length(source_authority) BETWEEN 1 AND 256),
            PRIMARY KEY (singleton, revision)
        );

        REVOKE ALL PRIVILEGES ON TABLE
            cost_access_grant,
            cost_disclosure_ceiling,
            vertical_package_activation,
            cost_observation
        FROM PUBLIC, fdai_operator;
        GRANT SELECT ON TABLE
            cost_access_grant,
            cost_disclosure_ceiling,
            vertical_package_activation,
            cost_observation
        TO fdai_operator;
