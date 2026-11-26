-- Migration Revision: core_question_campaign_20260819
-- Down Revision: core_incident_projection_20260819
-- Owner: core-control-plane
-- Extracted SQL Blocks: 11

-- Statement 1
CREATE TABLE IF NOT EXISTS question_campaign (
            campaign_id TEXT PRIMARY KEY CHECK (campaign_id ~ '^qs:[0-9a-f]{64}$'),
            source_revision TEXT NOT NULL CHECK (source_revision ~ '^[0-9a-f]{40}$'),
            ontology_release_digest TEXT NOT NULL
                CHECK (ontology_release_digest ~ '^sha256:[0-9a-f]{64}$'),
            question_universe_digest TEXT NOT NULL
                CHECK (question_universe_digest ~ '^sha256:[0-9a-f]{64}$'),
            started_at TIMESTAMPTZ NOT NULL,
            trigger_kind TEXT NOT NULL
                CHECK (trigger_kind IN ('manual', 'scheduled', 'release_certification')),
            identity JSONB NOT NULL,
            CHECK (jsonb_typeof(identity) = 'object')
        );

-- Statement 2
CREATE INDEX IF NOT EXISTS idx_question_campaign_source_started ON question_campaign(source_revision, started_at DESC);

-- Statement 3
CREATE INDEX IF NOT EXISTS idx_question_campaign_universe_started ON question_campaign(question_universe_digest, started_at DESC);

-- Statement 4
CREATE TABLE IF NOT EXISTS question_campaign_attempt (
            campaign_id TEXT NOT NULL REFERENCES question_campaign(campaign_id),
            case_id TEXT NOT NULL CHECK (char_length(case_id) BETWEEN 1 AND 256),
            attempt_number INTEGER NOT NULL CHECK (attempt_number BETWEEN 1 AND 10),
            terminal_disposition TEXT NULL CHECK (
                terminal_disposition IS NULL OR terminal_disposition IN (
                    'answered', 'clarification', 'held', 'unsupported',
                    'action_draft', 'cancelled'
                )
            ),
            terminal_reason TEXT NULL CHECK (
                terminal_reason IS NULL OR char_length(terminal_reason) BETWEEN 1 AND 128
            ),
            failure_kind TEXT NULL CHECK (
                failure_kind IS NULL OR char_length(failure_kind) BETWEEN 1 AND 128
            ),
            record JSONB NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (campaign_id, case_id, attempt_number),
            CHECK ((terminal_disposition IS NULL) <> (failure_kind IS NULL)),
            CHECK ((terminal_disposition IS NULL) = (terminal_reason IS NULL)),
            CHECK (jsonb_typeof(record) = 'object')
        );

-- Statement 5
CREATE INDEX IF NOT EXISTS idx_question_campaign_attempt_case ON question_campaign_attempt(campaign_id, case_id, attempt_number DESC);

-- Statement 6
CREATE TABLE IF NOT EXISTS question_campaign_completion (
            campaign_id TEXT PRIMARY KEY REFERENCES question_campaign(campaign_id),
            completed_at TIMESTAMPTZ NOT NULL,
            terminal_state TEXT NOT NULL
                CHECK (terminal_state IN ('completed', 'held', 'cancelled', 'failed')),
            terminal_reason TEXT NOT NULL
                CHECK (char_length(terminal_reason) BETWEEN 1 AND 128),
            evaluation_receipt_digest TEXT NOT NULL
                CHECK (evaluation_receipt_digest ~ '^sha256:[0-9a-f]{64}$'),
            selected_case_ids_digest TEXT NOT NULL
                CHECK (selected_case_ids_digest ~ '^sha256:[0-9a-f]{64}$'),
            record JSONB NOT NULL,
            CHECK (jsonb_typeof(record) = 'object')
        );

-- Statement 7
CREATE TABLE IF NOT EXISTS question_campaign_case_claim (
            campaign_id TEXT NOT NULL REFERENCES question_campaign(campaign_id),
            case_id TEXT NOT NULL CHECK (char_length(case_id) BETWEEN 1 AND 256),
            owner_id TEXT NOT NULL CHECK (char_length(owner_id) BETWEEN 1 AND 128),
            claimed_at TIMESTAMPTZ NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (campaign_id, case_id),
            CHECK (expires_at > claimed_at)
        );

-- Statement 8
GRANT SELECT, INSERT ON TABLE question_campaign TO fdai_core;

-- Statement 9
GRANT SELECT, INSERT ON TABLE question_campaign_attempt TO fdai_core;

-- Statement 10
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE question_campaign_case_claim TO fdai_core;

-- Statement 11
GRANT SELECT, INSERT ON TABLE question_campaign_completion TO fdai_core;
