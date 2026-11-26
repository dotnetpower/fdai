-- Temporal-Ontology Causal Inference, Azure Telemetry Series & Preventive Gap Schema
-- Enforces bitemporal as-of integrity, anti-pollution constraints, and finite evidence bounds.

CREATE TABLE IF NOT EXISTS ontology_topology_bitemporal (
    id BIGSERIAL PRIMARY KEY,
    subscription_id TEXT NOT NULL CHECK (char_length(subscription_id) BETWEEN 1 AND 128),
    source_ref TEXT NOT NULL CHECK (char_length(source_ref) BETWEEN 1 AND 512),
    relation_type TEXT NOT NULL CHECK (relation_type ~ '^[a-z0-9_:-]{1,64}$'),
    target_ref TEXT NOT NULL CHECK (char_length(target_ref) BETWEEN 1 AND 512),
    weight DOUBLE PRECISION NOT NULL CHECK (weight >= -10.0 AND weight <= 10.0),
    unless_inhibitors JSONB NOT NULL DEFAULT '[]'::jsonb,
    graph_generation BIGINT NOT NULL DEFAULT 1 CHECK (graph_generation >= 1),
    valid_from TIMESTAMPTZ NOT NULL,
    valid_to TIMESTAMPTZ NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (valid_to IS NULL OR valid_to > valid_from)
);

CREATE INDEX IF NOT EXISTS idx_ontology_topology_bitemp_asof
    ON ontology_topology_bitemporal (subscription_id, recorded_at, valid_from, valid_to);

CREATE TABLE IF NOT EXISTS azure_telemetry_series (
    id BIGSERIAL PRIMARY KEY,
    subscription_id TEXT NOT NULL CHECK (char_length(subscription_id) BETWEEN 1 AND 128),
    resource_id TEXT NOT NULL CHECK (char_length(resource_id) BETWEEN 1 AND 512),
    resource_type TEXT NOT NULL CHECK (char_length(resource_type) BETWEEN 1 AND 256),
    metric_or_change_concept TEXT NOT NULL CHECK (metric_or_change_concept ~ '^[A-Za-z0-9_.:-]{1,128}$'),
    valid_at TIMESTAMPTZ NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    value DOUBLE PRECISION NOT NULL CHECK (value = value),
    status_tag TEXT NOT NULL DEFAULT 'ok' CHECK (char_length(status_tag) <= 64),
    change_digest TEXT NULL CHECK (change_digest IS NULL OR char_length(change_digest) <= 128)
);

CREATE INDEX IF NOT EXISTS idx_azure_telemetry_resource_concept_time
    ON azure_telemetry_series (resource_id, metric_or_change_concept, valid_at DESC, ingested_at DESC);

CREATE TABLE IF NOT EXISTS causal_edge_evidence (
    id BIGSERIAL PRIMARY KEY,
    subscription_id TEXT NOT NULL CHECK (char_length(subscription_id) BETWEEN 1 AND 128),
    cause_concept TEXT NOT NULL CHECK (cause_concept ~ '^[A-Za-z0-9_.:-]{1,128}$'),
    relation_type TEXT NOT NULL CHECK (relation_type ~ '^[A-Za-z0-9_.:-]{1,64}$'),
    effect_concept TEXT NOT NULL CHECK (effect_concept ~ '^[A-Za-z0-9_.:-]{1,128}$'),
    evidence_grade TEXT NOT NULL CHECK (
        evidence_grade IN (
            'insufficient_evidence',
            'association_only',
            'confounded',
            'temporal_granger_supported',
            'quasi_experimental',
            'interventional_verified'
        )
    ),
    optimal_lag_seconds BIGINT NOT NULL DEFAULT 0 CHECK (optimal_lag_seconds >= 0),
    granger_r2_gain DOUBLE PRECISION NOT NULL DEFAULT 0.0 CHECK (granger_r2_gain >= 0.0 AND granger_r2_gain <= 1.0),
    confounder_controlled BOOLEAN NOT NULL DEFAULT FALSE,
    counterfactual_verified BOOLEAN NOT NULL DEFAULT FALSE,
    evidence_cutoff TIMESTAMPTZ NOT NULL,
    graph_digest TEXT NOT NULL CHECK (char_length(graph_digest) BETWEEN 1 AND 128),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (subscription_id, cause_concept, relation_type, effect_concept)
);

CREATE TABLE IF NOT EXISTS preventive_guard_gaps (
    id BIGSERIAL PRIMARY KEY,
    subscription_id TEXT NOT NULL CHECK (char_length(subscription_id) BETWEEN 1 AND 128),
    resource_id TEXT NOT NULL CHECK (char_length(resource_id) BETWEEN 1 AND 512),
    resource_type TEXT NOT NULL CHECK (char_length(resource_type) BETWEEN 1 AND 256),
    failure_class TEXT NOT NULL CHECK (failure_class ~ '^[a-z0-9_]{1,64}$'),
    missing_guard TEXT NOT NULL CHECK (missing_guard ~ '^[a-z0-9_]{1,128}$'),
    reason TEXT NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ NULL,
    UNIQUE (subscription_id, resource_id, failure_class, missing_guard)
);
