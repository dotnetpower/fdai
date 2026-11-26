-- Migration Revision: operator_cost_disclosure_audit_20260912
-- Down Revision: operator_skill_proposal_evidence_20260912
-- Owner: operator-service
-- Extracted SQL Blocks: 1

-- Statement 1
CREATE TABLE IF NOT EXISTS cost_disclosure_audit (
            decision_id TEXT PRIMARY KEY
                CHECK (decision_id ~ '^sha256:[0-9a-f]{64}$'),
            principal_digest TEXT NOT NULL
                CHECK (principal_digest ~ '^sha256:[0-9a-f]{64}$'),
            scope_digest TEXT NOT NULL
                CHECK (scope_digest ~ '^sha256:[0-9a-f]{64}$'),
            surface TEXT NOT NULL
                CHECK (surface ~ '^[a-z][a-z0-9-]{0,63}$'),
            grant_revision BIGINT NOT NULL CHECK (grant_revision >= 0),
            ceiling_revision BIGINT NOT NULL CHECK (ceiling_revision >= 0),
            activation_revision BIGINT NOT NULL CHECK (activation_revision >= 0),
            disclosure_digest TEXT NOT NULL
                CHECK (disclosure_digest ~ '^sha256:[0-9a-f]{64}$'),
            record_count INTEGER NOT NULL CHECK (record_count >= 0),
            suppressed_count INTEGER NOT NULL CHECK (
                suppressed_count >= 0 AND suppressed_count <= record_count
            ),
            authorized BOOLEAN NOT NULL CHECK (authorized),
            occurred_at TIMESTAMPTZ NOT NULL
        );
        CREATE TABLE IF NOT EXISTS cost_disclosure_audit_retention (
            decision_id TEXT PRIMARY KEY
                REFERENCES cost_disclosure_audit(decision_id),
            revision BIGINT NOT NULL CHECK (revision >= 1),
            retention_until TIMESTAMPTZ NOT NULL,
            purge_after TIMESTAMPTZ NOT NULL,
            legal_hold BOOLEAN NOT NULL DEFAULT FALSE,
            legal_hold_ref TEXT NULL,
            purged_at TIMESTAMPTZ NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            CHECK (retention_until <= purge_after),
            CHECK (legal_hold = (legal_hold_ref IS NOT NULL)),
            CHECK (purged_at IS NULL OR (NOT legal_hold AND purged_at >= purge_after))
        );
        CREATE TABLE IF NOT EXISTS cost_disclosure_audit_retention_event (
            decision_id TEXT NOT NULL
                REFERENCES cost_disclosure_audit(decision_id),
            revision BIGINT NOT NULL CHECK (revision >= 1),
            event_kind TEXT NOT NULL CHECK (
                event_kind IN ('created', 'hold-applied', 'hold-released', 'purged')
            ),
            legal_hold_ref TEXT NULL,
            recorded_at TIMESTAMPTZ NOT NULL,
            idempotency_key TEXT NOT NULL
                CHECK (char_length(idempotency_key) BETWEEN 1 AND 512),
            PRIMARY KEY (decision_id, revision),
            UNIQUE (decision_id, idempotency_key)
        );
        CREATE INDEX IF NOT EXISTS cost_disclosure_audit_time_idx
            ON cost_disclosure_audit (occurred_at, decision_id);
        CREATE INDEX IF NOT EXISTS cost_disclosure_audit_retention_purge_idx
            ON cost_disclosure_audit_retention (purge_after, decision_id)
            WHERE purged_at IS NULL AND NOT legal_hold;
        REVOKE ALL PRIVILEGES ON TABLE
            cost_disclosure_audit,
            cost_disclosure_audit_retention,
            cost_disclosure_audit_retention_event
        FROM PUBLIC;
        GRANT SELECT, INSERT ON TABLE cost_disclosure_audit TO fdai_operator;
        GRANT SELECT, INSERT, UPDATE
            ON TABLE cost_disclosure_audit_retention TO fdai_operator;
        GRANT SELECT, INSERT
            ON TABLE cost_disclosure_audit_retention_event TO fdai_operator;
        REVOKE EXECUTE ON FUNCTION fdai_set_cost_governance_enabled_legacy(
            TEXT, TEXT, BOOLEAN, BIGINT, TEXT
        ) FROM fdai_operator;
        GRANT EXECUTE ON FUNCTION fdai_set_cost_governance_enabled(
            TEXT, TEXT, BOOLEAN, BIGINT, TEXT
        ) TO fdai_operator;
