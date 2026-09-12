"""Create append-only independent effect observation retention."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_effect_observation_20260913"
down_revision: str | Sequence[str] | None = "core_cost_governance_w7_lifecycle_20260912"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = ("independent_effect_observation",)
rollback = {
    "strategy": "drop-independent-effect-observation",
    "restores": "core_cost_governance_w7_lifecycle_20260912",
    "requires": "effect-observation-writers-stopped",
}


def upgrade() -> None:
    """Retain one immutable receipt per dispatch and sequence position.

    The grant is deliberately limited to SELECT and INSERT, so independent
    effect evidence stays append-only: a contradicting later observation is
    a new row rather than an edit of the row it contradicts.
    """

    op.execute(
        """
        CREATE TABLE independent_effect_observation (
            evidence_identity_digest TEXT NOT NULL
                CHECK (evidence_identity_digest ~ '^sha256:[0-9a-f]{64}$'),
            sequence INTEGER NOT NULL CHECK (sequence > 0),
            observation_id TEXT NOT NULL CHECK (length(observation_id) BETWEEN 1 AND 512),
            receipt_digest TEXT NOT NULL
                CHECK (receipt_digest ~ '^sha256:[0-9a-f]{64}$'),
            prior_receipt_digest TEXT
                CHECK (
                    prior_receipt_digest IS NULL
                    OR prior_receipt_digest ~ '^sha256:[0-9a-f]{64}$'
                ),
            safeguard_bundle_digest TEXT NOT NULL
                CHECK (safeguard_bundle_digest ~ '^sha256:[0-9a-f]{64}$'),
            outcome TEXT NOT NULL CHECK (
                outcome IN (
                    'verified',
                    'failed',
                    'missing',
                    'stale',
                    'conflicting',
                    'censored',
                    'unavailable'
                )
            ),
            disposition TEXT NOT NULL CHECK (
                disposition IN ('effect_verified', 'recovery_required', 'unknown_hold')
            ),
            effect_verified BOOLEAN NOT NULL,
            observer_instance_id TEXT NOT NULL
                CHECK (length(observer_instance_id) BETWEEN 1 AND 512),
            executor_instance_id TEXT NOT NULL
                CHECK (length(executor_instance_id) BETWEEN 1 AND 512),
            source_instance_id TEXT NOT NULL
                CHECK (length(source_instance_id) BETWEEN 1 AND 512),
            receipt JSONB NOT NULL CHECK (jsonb_typeof(receipt) = 'object'),
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            PRIMARY KEY (evidence_identity_digest, sequence),
            CONSTRAINT independent_effect_observation_verified_agrees
                CHECK (effect_verified = (outcome = 'verified')),
            CONSTRAINT independent_effect_observation_disposition_agrees
                CHECK (
                    disposition = CASE
                        WHEN outcome = 'verified' THEN 'effect_verified'
                        WHEN outcome = 'failed' THEN 'recovery_required'
                        ELSE 'unknown_hold'
                    END
                ),
            CONSTRAINT independent_effect_observation_identities_distinct
                CHECK (
                    lower(observer_instance_id) <> lower(executor_instance_id)
                    AND lower(observer_instance_id) <> lower(source_instance_id)
                    AND lower(executor_instance_id) <> lower(source_instance_id)
                ),
            CONSTRAINT independent_effect_observation_chain_start
                CHECK ((sequence = 1) = (prior_receipt_digest IS NULL))
        );

        CREATE UNIQUE INDEX independent_effect_observation_receipt_unique
            ON independent_effect_observation (receipt_digest);

        REVOKE ALL PRIVILEGES ON TABLE independent_effect_observation
        FROM PUBLIC, fdai_core;
        GRANT SELECT, INSERT ON TABLE independent_effect_observation TO fdai_core;
        """
    )


def downgrade() -> None:
    """Drop observation evidence only after every observer writer stops."""

    op.execute("DROP TABLE independent_effect_observation")
