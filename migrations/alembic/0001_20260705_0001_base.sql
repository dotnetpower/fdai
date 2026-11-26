-- Migration Revision: 20260705_0001
-- Down Revision: none
-- Owner: alembic
-- Extracted SQL Blocks: 14

-- Statement 1
CREATE TABLE IF NOT EXISTS ontology_object_type (
            name        TEXT PRIMARY KEY,
            version     TEXT NOT NULL,
            key_field   TEXT NOT NULL,
            properties  JSONB NOT NULL,
            description TEXT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

-- Statement 2
CREATE TABLE IF NOT EXISTS ontology_link_type (
            name        TEXT PRIMARY KEY,
            version     TEXT NOT NULL,
            from_type   TEXT NOT NULL REFERENCES ontology_object_type(name),
            to_type     TEXT NOT NULL REFERENCES ontology_object_type(name),
            cardinality TEXT NOT NULL
                CHECK (cardinality IN ('one_to_one','one_to_many','many_to_one','many_to_many')),
            description TEXT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

-- Statement 3
CREATE TABLE IF NOT EXISTS ontology_resource (
            id          TEXT PRIMARY KEY,
            object_type TEXT NOT NULL REFERENCES ontology_object_type(name),
            properties  JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

-- Statement 4
CREATE INDEX idx_ontology_resource_object_type ON ontology_resource(object_type);

-- Statement 5
CREATE TABLE IF NOT EXISTS ontology_finding (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            rule_id      TEXT NOT NULL,
            resource_ref TEXT NOT NULL REFERENCES ontology_resource(id),
            severity     TEXT NOT NULL
                CHECK (severity IN ('critical','high','medium','low')),
            state        TEXT NOT NULL
                CHECK (state IN ('open','resolved','suppressed')),
            details      JSONB NOT NULL DEFAULT '{}'::jsonb,
            detected_at  TIMESTAMPTZ NOT NULL,
            resolved_at  TIMESTAMPTZ
        );

-- Statement 6
CREATE INDEX idx_ontology_finding_rule_id ON ontology_finding(rule_id);

-- Statement 7
CREATE INDEX idx_ontology_finding_resource_ref ON ontology_finding(resource_ref);

-- Statement 8
CREATE INDEX idx_ontology_finding_state ON ontology_finding(state);

-- Statement 9
CREATE TABLE IF NOT EXISTS ontology_link (
            id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            link_type  TEXT NOT NULL REFERENCES ontology_link_type(name),
            from_id    TEXT NOT NULL,
            to_id      TEXT NOT NULL,
            properties JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

-- Statement 10
CREATE INDEX idx_ontology_link_from ON ontology_link(from_id);

-- Statement 11
CREATE INDEX idx_ontology_link_to   ON ontology_link(to_id);

-- Statement 12
CREATE TABLE IF NOT EXISTS audit_log (
            seq            BIGSERIAL PRIMARY KEY,
            event_id       UUID NOT NULL,
            correlation_id TEXT,
            actor          TEXT NOT NULL,
            action_kind    TEXT NOT NULL,
            mode           TEXT NOT NULL CHECK (mode IN ('shadow','enforce')),
            entry          JSONB NOT NULL,
            previous_hash  TEXT NOT NULL,
            entry_hash     TEXT NOT NULL UNIQUE,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

-- Statement 13
CREATE INDEX idx_audit_log_event_id ON audit_log(event_id);

-- Statement 14
CREATE INDEX idx_audit_log_correlation_id ON audit_log(correlation_id) WHERE correlation_id IS NOT NULL;
