"""Persist Cost Analytics receipts and explicit observation-mode case projections."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_cost_governance_live_20260917"
down_revision: str | Sequence[str] | None = (
    "core_assignment_receipts_20260914",
    "core_inventory_progress_20260916",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = (
    "cost_observation_current",
    "cost_governance_analytics_run_receipt",
    "cost_governance_case_projection",
    "cost_governance_settlement",
)
rollback = {
    "strategy": "drop-cost-live-projection-after-producer-and-operator-stop",
    "restores": "core_assignment_receipts_20260914+core_inventory_progress_20260916",
    "requires": "cost-analytics-and-operator-runtime-stopped",
}


def upgrade() -> None:
    """Create additive, authority-free evidence and projection records."""

    op.execute(
        """
        CREATE TABLE cost_observation_current (
            package_id TEXT NOT NULL,
            scope_id TEXT NOT NULL,
            service_id TEXT NOT NULL,
            currency TEXT NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
            event_day DATE NOT NULL,
            observation_id TEXT NOT NULL UNIQUE
                REFERENCES cost_observation(observation_id),
            recorded_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (package_id, scope_id, service_id, currency, event_day)
        );
        INSERT INTO cost_observation_current (
            package_id, scope_id, service_id, currency, event_day,
            observation_id, recorded_at
        )
        SELECT DISTINCT ON (
                   package_id, scope_id, service_id, currency,
                   (event_start_at AT TIME ZONE 'UTC')::DATE
               )
               package_id, scope_id, service_id, currency,
               (event_start_at AT TIME ZONE 'UTC')::DATE,
               observation_id, recorded_at
          FROM cost_observation
         ORDER BY package_id, scope_id, service_id, currency,
                  (event_start_at AT TIME ZONE 'UTC')::DATE,
                  recorded_at DESC, observation_id DESC;

        CREATE TABLE cost_governance_analytics_run_receipt (
            run_id TEXT PRIMARY KEY CHECK (run_id ~ '^costrun:[0-9a-f]{64}$'),
            receipt_digest TEXT NOT NULL UNIQUE
                CHECK (receipt_digest ~ '^sha256:[0-9a-f]{64}$'),
            package_id TEXT NOT NULL CHECK (package_id = 'cost-governance'),
            scope_id TEXT NOT NULL CHECK (char_length(scope_id) BETWEEN 1 AND 1024),
            scope_digest TEXT NOT NULL CHECK (scope_digest ~ '^sha256:[0-9a-f]{64}$'),
            venue TEXT NOT NULL CHECK (venue IN ('local', 'deployed')),
            window_start_at TIMESTAMPTZ NOT NULL,
            window_end_at TIMESTAMPTZ NOT NULL,
            started_at TIMESTAMPTZ NOT NULL,
            finished_at TIMESTAMPTZ NOT NULL,
            status TEXT NOT NULL CHECK (
                status IN ('complete', 'partial', 'failed', 'disabled')
            ),
            sources JSONB NOT NULL CHECK (
                jsonb_typeof(sources) = 'array' AND jsonb_array_length(sources) <= 8
            ),
            observation_count INTEGER NOT NULL CHECK (observation_count >= 0),
            trend_point_count INTEGER NOT NULL CHECK (trend_point_count >= 0),
            budget_count INTEGER NOT NULL CHECK (budget_count >= 0),
            recommendation_count INTEGER NOT NULL CHECK (recommendation_count >= 0),
            utilization_count INTEGER NOT NULL CHECK (utilization_count >= 0),
            limitations JSONB NOT NULL CHECK (
                jsonb_typeof(limitations) = 'array'
                AND jsonb_array_length(limitations) <= 32
            ),
            failure_reason TEXT NULL CHECK (
                failure_reason IS NULL
                OR failure_reason ~ '^[a-z0-9]+([._-][a-z0-9]+)*$'
            ),
            snapshot_id TEXT NULL
                REFERENCES cost_governance_analytics_snapshot(snapshot_id),
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CHECK (window_start_at < window_end_at),
            CHECK (started_at <= finished_at),
            CHECK ((status = 'failed') = (failure_reason IS NOT NULL)),
            CHECK (
                snapshot_id IS NULL OR status IN ('complete', 'partial')
            ),
            CHECK (
                replace(run_id, 'costrun:', '') =
                replace(receipt_digest, 'sha256:', '')
            )
        );
        CREATE INDEX cost_governance_analytics_run_scope_idx
            ON cost_governance_analytics_run_receipt(scope_id, finished_at DESC);

        CREATE TABLE cost_governance_case_projection (
            episode_id TEXT NOT NULL,
            episode_revision BIGINT NOT NULL CHECK (episode_revision >= 1),
            scope_id TEXT NOT NULL CHECK (char_length(scope_id) BETWEEN 1 AND 1024),
            evidence_cutoff TIMESTAMPTZ NOT NULL,
            decision_frame_digest TEXT NOT NULL
                CHECK (decision_frame_digest ~ '^sha256:[0-9a-f]{64}$'),
            target_refs JSONB NOT NULL CHECK (
                jsonb_typeof(target_refs) = 'array'
                AND jsonb_array_length(target_refs) BETWEEN 1 AND 256
            ),
            options JSONB NOT NULL CHECK (
                jsonb_typeof(options) = 'array'
                AND jsonb_array_length(options) BETWEEN 1 AND 256
            ),
            selected_option_id TEXT NULL
                CHECK (
                    selected_option_id IS NULL
                    OR char_length(selected_option_id) BETWEEN 1 AND 256
                ),
            verdict TEXT NOT NULL CHECK (verdict = 'hold'),
            reason TEXT NOT NULL CHECK (
                reason ~ '^[a-z0-9]+([._-][a-z0-9]+)*$'
            ),
            source_authority TEXT NOT NULL
                CHECK (char_length(source_authority) BETWEEN 1 AND 256),
            recorded_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (episode_id, episode_revision),
            FOREIGN KEY (episode_id, episode_revision)
                REFERENCES cost_governance_episode(episode_id, revision),
            CHECK (evidence_cutoff <= recorded_at)
        );
        CREATE INDEX cost_governance_case_projection_scope_idx
            ON cost_governance_case_projection(scope_id, recorded_at DESC);

        ALTER TABLE cost_governance_settlement
            ADD COLUMN currency TEXT NULL
                CHECK (currency IS NULL OR currency ~ '^[A-Z]{3}$'),
            ADD COLUMN action_ref TEXT NULL
                CHECK (action_ref IS NULL OR char_length(action_ref) BETWEEN 1 AND 512),
            ADD COLUMN action_revision BIGINT NULL
                CHECK (action_revision IS NULL OR action_revision >= 1),
            ADD CONSTRAINT ck_cost_governance_settlement_action_revision
                CHECK ((action_ref IS NULL) = (action_revision IS NULL));

        REVOKE ALL PRIVILEGES ON TABLE
            cost_observation_current,
            cost_governance_analytics_run_receipt,
            cost_governance_case_projection
        FROM PUBLIC, fdai_core;
        GRANT SELECT, INSERT, UPDATE ON TABLE
            cost_observation_current
        TO fdai_core;
        GRANT SELECT, INSERT ON TABLE
            cost_governance_analytics_run_receipt,
            cost_governance_case_projection
        TO fdai_core;
        """
    )


def downgrade() -> None:
    """Drop additive read evidence after its producer and consumer stop."""

    op.execute(
        """
        ALTER TABLE cost_governance_settlement
            DROP CONSTRAINT ck_cost_governance_settlement_action_revision,
            DROP COLUMN action_revision,
            DROP COLUMN action_ref,
            DROP COLUMN currency;
        DROP TABLE cost_governance_case_projection;
        DROP TABLE cost_governance_analytics_run_receipt;
        DROP TABLE cost_observation_current;
        """
    )
