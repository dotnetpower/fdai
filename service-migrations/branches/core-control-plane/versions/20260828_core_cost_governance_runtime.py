"""Persist Cost Governance activation, immutable facts, and collection cursors."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_cost_governance_runtime_20260828"
down_revision: str | Sequence[str] | None = "core_kubernetes_merge_20260827"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = (
    "vertical_package_activation",
    "cost_observation",
    "cost_collection_cursor",
)
rollback = {
    "strategy": "drop-cost-runtime-after-package-jobs-stop",
    "restores": "core_kubernetes_merge_20260827",
    "requires": "cost-governance-collector-and-analyzer-stopped",
}


def upgrade() -> None:
    """Create disabled-first activation and append-only cost evidence."""

    op.execute(
        """
        CREATE TABLE vertical_package_activation (
            package_id TEXT PRIMARY KEY CHECK (char_length(package_id) BETWEEN 1 AND 128),
            vertical_id TEXT NOT NULL CHECK (char_length(vertical_id) BETWEEN 1 AND 128),
            available BOOLEAN NOT NULL,
            enabled BOOLEAN NOT NULL DEFAULT FALSE,
            previously_enabled BOOLEAN NOT NULL DEFAULT FALSE,
            availability_reasons JSONB NOT NULL CHECK (
                jsonb_typeof(availability_reasons) = 'array'
                AND jsonb_array_length(availability_reasons) <= 32
            ),
            package_version TEXT NOT NULL
                CHECK (char_length(package_version) BETWEEN 1 AND 64),
            image_digest TEXT NOT NULL CHECK (image_digest ~ '^sha256:[0-9a-f]{64}$'),
            asset_manifest_digest TEXT NOT NULL
                CHECK (asset_manifest_digest ~ '^sha256:[0-9a-f]{64}$'),
            semantic_profile_digest TEXT NOT NULL
                CHECK (semantic_profile_digest ~ '^sha256:[0-9a-f]{64}$'),
            revision BIGINT NOT NULL DEFAULT 0 CHECK (revision >= 0),
            effective_at TIMESTAMPTZ NOT NULL,
            ontology_release_id TEXT NOT NULL
                CHECK (char_length(ontology_release_id) BETWEEN 1 AND 256),
            ontology_release_digest TEXT NOT NULL
                CHECK (ontology_release_digest ~ '^sha256:[0-9a-f]{64}$'),
            source_authority TEXT NOT NULL
                CHECK (char_length(source_authority) BETWEEN 1 AND 256),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (NOT enabled OR available),
            CHECK (
                (available AND jsonb_array_length(availability_reasons) = 0)
                OR (NOT available AND jsonb_array_length(availability_reasons) > 0)
            )
        );

        CREATE TABLE cost_collection_cursor (
            package_id TEXT NOT NULL
                REFERENCES vertical_package_activation(package_id),
            scope_id TEXT NOT NULL CHECK (char_length(scope_id) BETWEEN 1 AND 1024),
            revision BIGINT NOT NULL DEFAULT 0 CHECK (revision >= 0),
            analysis_revision BIGINT NOT NULL DEFAULT 0 CHECK (analysis_revision >= 0),
            resume_token TEXT NULL CHECK (
                resume_token IS NULL OR char_length(resume_token) BETWEEN 1 AND 4096
            ),
            coverage_through_at TIMESTAMPTZ NOT NULL,
            retention_floor_at TIMESTAMPTZ NOT NULL,
            last_published_at TIMESTAMPTZ NULL,
            last_published_observation_id TEXT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (package_id, scope_id),
            CHECK (retention_floor_at <= coverage_through_at),
            CHECK (
                (last_published_at IS NULL) =
                (last_published_observation_id IS NULL)
            )
        );

        CREATE TABLE cost_observation (
            observation_id TEXT PRIMARY KEY
                CHECK (observation_id ~ '^costobs:[0-9a-f]{64}$'),
            package_id TEXT NOT NULL,
            scope_id TEXT NOT NULL,
            service_id TEXT NOT NULL CHECK (char_length(service_id) BETWEEN 1 AND 256),
            amount NUMERIC(28, 10) NOT NULL CHECK (amount >= 0),
            currency TEXT NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
            event_start_at TIMESTAMPTZ NOT NULL,
            event_end_at TIMESTAMPTZ NOT NULL,
            observed_at TIMESTAMPTZ NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL,
            source_authority TEXT NOT NULL
                CHECK (char_length(source_authority) BETWEEN 1 AND 256),
            source_uri TEXT NOT NULL CHECK (char_length(source_uri) BETWEEN 1 AND 2048),
            completeness NUMERIC(5, 4) NOT NULL
                CHECK (completeness >= 0 AND completeness <= 1),
            ontology_release_id TEXT NOT NULL
                CHECK (char_length(ontology_release_id) BETWEEN 1 AND 256),
            ontology_release_digest TEXT NOT NULL
                CHECK (ontology_release_digest ~ '^sha256:[0-9a-f]{64}$'),
            evidence_digest TEXT NOT NULL
                CHECK (evidence_digest ~ '^sha256:[0-9a-f]{64}$'),
            retention_until TIMESTAMPTZ NOT NULL,
            FOREIGN KEY (package_id, scope_id)
                REFERENCES cost_collection_cursor(package_id, scope_id),
            CHECK (event_start_at < event_end_at),
            CHECK (event_end_at <= observed_at),
            CHECK (observed_at <= recorded_at),
            CHECK (recorded_at < retention_until)
        );
        CREATE INDEX cost_observation_scope_time_idx
            ON cost_observation (package_id, scope_id, observed_at, observation_id);
        CREATE INDEX cost_observation_retention_idx
            ON cost_observation (retention_until);

        REVOKE ALL PRIVILEGES ON TABLE
            vertical_package_activation,
            cost_collection_cursor,
            cost_observation
        FROM PUBLIC, fdai_core;
        GRANT SELECT, INSERT, UPDATE
            ON TABLE vertical_package_activation, cost_collection_cursor TO fdai_core;
        GRANT SELECT, INSERT
            ON TABLE cost_observation TO fdai_core;
        """
    )


def downgrade() -> None:
    """Drop package runtime state only after all cost jobs stop."""

    op.execute(
        """
        DROP TABLE cost_observation;
        DROP TABLE cost_collection_cursor;
        DROP TABLE vertical_package_activation;
        """
    )
