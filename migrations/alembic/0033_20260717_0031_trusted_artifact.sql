-- Migration Revision: 20260717_0031
-- Down Revision: 20260717_0030
-- Owner: alembic
-- Extracted SQL Blocks: 1

-- Statement 1
CREATE TABLE trusted_artifact (
            artifact_kind TEXT NOT NULL CHECK (artifact_kind IN ('extension', 'skill')),
            artifact_id TEXT NOT NULL CHECK (artifact_id ~ '^[a-z][a-z0-9.-]{2,127}$'),
            version TEXT NOT NULL CHECK (
                version ~ ('^(0|[1-9][0-9]*)[.]' ||
                           '(0|[1-9][0-9]*)[.](0|[1-9][0-9]*)$')
            ),
            source TEXT NOT NULL CHECK (length(source) BETWEEN 1 AND 512),
            content_sha256 TEXT NOT NULL CHECK (content_sha256 ~ '^[a-f0-9]{64}$'),
            artifact BYTEA NOT NULL CHECK (octet_length(artifact) BETWEEN 1 AND 33554432),
            signature BYTEA NOT NULL CHECK (octet_length(signature) = 64),
            state TEXT NOT NULL CHECK (state IN ('disabled', 'enabled')),
            revision BIGINT NOT NULL CHECK (revision > 0),
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL CHECK (updated_at >= created_at),
            PRIMARY KEY (artifact_kind, artifact_id)
        );
        CREATE INDEX trusted_artifact_kind_state_idx
            ON trusted_artifact (artifact_kind, state, artifact_id);
