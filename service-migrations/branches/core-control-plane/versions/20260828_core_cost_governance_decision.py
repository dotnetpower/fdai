"""Persist Cost Governance decision, recovery, settlement, and retention lineage."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_cost_governance_decision_20260828"
down_revision: str | Sequence[str] | None = "core_cost_governance_runtime_20260828"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = (
    "cost_governance_episode",
    "cost_governance_recovery",
    "cost_governance_settlement",
    "cost_governance_effect_settlement",
    "cost_governance_evidence",
    "cost_governance_retention",
    "cost_governance_retention_event",
)
rollback = {
    "strategy": "drop-cost-decision-lineage-after-settlement-workers-stop",
    "restores": "core_cost_governance_runtime_20260828",
    "requires": "cost-governance-coordinator-and-settlement-stopped",
}


def upgrade() -> None:
    """Create append-only W4-W5 lineage and CAS retention metadata."""

    op.execute(
        """
        CREATE TABLE cost_governance_episode (
            episode_id TEXT NOT NULL CHECK (char_length(episode_id) BETWEEN 1 AND 256),
            revision BIGINT NOT NULL CHECK (revision >= 1),
            package_id TEXT NOT NULL
                REFERENCES vertical_package_activation(package_id),
            idempotency_key TEXT NOT NULL
                CHECK (char_length(idempotency_key) BETWEEN 1 AND 512),
            outcome TEXT NOT NULL CHECK (
                outcome IN ('no-op', 'deny', 'hold', 'approval', 'execute', 'rollback')
            ),
            reason TEXT NOT NULL CHECK (reason ~ '^[a-z0-9]+([._-][a-z0-9]+)*$'),
            decision_frame_digest TEXT NOT NULL
                CHECK (decision_frame_digest ~ '^sha256:[0-9a-f]{64}$'),
            terminal BOOLEAN NOT NULL,
            observation_mode BOOLEAN NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL,
            retention_until TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (episode_id, revision),
            UNIQUE (episode_id, idempotency_key),
            CHECK (recorded_at < retention_until),
            CHECK (NOT terminal OR outcome IN ('no-op', 'deny')),
            CHECK (NOT observation_mode OR outcome = 'hold')
        );

        CREATE TABLE cost_governance_recovery (
            episode_id TEXT NOT NULL,
            episode_revision BIGINT NOT NULL,
            attempt_index INTEGER NOT NULL CHECK (attempt_index BETWEEN 0 AND 6),
            step TEXT NOT NULL CHECK (
                step IN (
                    'reacquire-context', 'independent-source', 'remove-unsafe-options',
                    'reduce-scope', 'select-safe-option', 'bounded-hold',
                    'residual-approval'
                )
            ),
            status TEXT NOT NULL CHECK (
                status IN ('success', 'unavailable', 'timeout', 'conflict', 'exhausted')
            ),
            hypothesis_id TEXT NOT NULL
                CHECK (char_length(hypothesis_id) BETWEEN 1 AND 256),
            input_frame_digest TEXT NOT NULL
                CHECK (input_frame_digest ~ '^sha256:[0-9a-f]{64}$'),
            output_frame_digest TEXT NULL
                CHECK (
                    output_frame_digest IS NULL
                    OR output_frame_digest ~ '^sha256:[0-9a-f]{64}$'
                ),
            autonomy_ceiling TEXT NOT NULL
                CHECK (autonomy_ceiling IN ('observation', 'approval', 'execution-eligible')),
            attempted_at TIMESTAMPTZ NOT NULL,
            independent_source_authority TEXT NULL
                CHECK (
                    independent_source_authority IS NULL
                    OR char_length(independent_source_authority) BETWEEN 1 AND 256
                ),
            evidence_refs JSONB NOT NULL CHECK (
                jsonb_typeof(evidence_refs) = 'array'
                AND jsonb_array_length(evidence_refs) BETWEEN 1 AND 64
            ),
            PRIMARY KEY (episode_id, episode_revision, attempt_index),
            UNIQUE (episode_id, episode_revision, hypothesis_id),
            FOREIGN KEY (episode_id, episode_revision)
                REFERENCES cost_governance_episode(episode_id, revision),
            CHECK ((status = 'success') = (output_frame_digest IS NOT NULL)),
            CHECK (
                (independent_source_authority IS NOT NULL)
                = (step = 'independent-source' AND status = 'success')
            )
        );

        CREATE TABLE cost_governance_settlement (
            episode_id TEXT NOT NULL,
            episode_revision BIGINT NOT NULL,
            settlement_digest TEXT NOT NULL
                CHECK (settlement_digest ~ '^sha256:[0-9a-f]{64}$'),
            terminal BOOLEAN NOT NULL,
            realized_savings NUMERIC(28, 10) NOT NULL CHECK (realized_savings >= 0),
            rollback_request_id TEXT NULL,
            recovery_observed BOOLEAN NOT NULL,
            settled_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (episode_id, episode_revision),
            UNIQUE (settlement_digest),
            FOREIGN KEY (episode_id, episode_revision)
                REFERENCES cost_governance_episode(episode_id, revision),
            CHECK (rollback_request_id IS NULL OR realized_savings = 0),
            CHECK (NOT recovery_observed OR rollback_request_id IS NOT NULL)
        );

        CREATE TABLE cost_governance_effect_settlement (
            episode_id TEXT NOT NULL,
            episode_revision BIGINT NOT NULL,
            effect_id TEXT NOT NULL CHECK (char_length(effect_id) BETWEEN 1 AND 256),
            effect_kind TEXT NOT NULL
                CHECK (effect_kind IN ('cost', 'capacity', 'service', 'recovery')),
            status TEXT NOT NULL
                CHECK (status IN ('verified', 'failed', 'censored', 'unscorable')),
            reason TEXT NOT NULL CHECK (reason ~ '^[a-z0-9]+([._-][a-z0-9]+)*$'),
            terminal BOOLEAN NOT NULL,
            observation_digest TEXT NULL
                CHECK (
                    observation_digest IS NULL
                    OR observation_digest ~ '^sha256:[0-9a-f]{64}$'
                ),
            completeness_digest TEXT NULL
                CHECK (
                    completeness_digest IS NULL
                    OR completeness_digest ~ '^sha256:[0-9a-f]{64}$'
                ),
            settled_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (episode_id, episode_revision, effect_id),
            FOREIGN KEY (episode_id, episode_revision)
                REFERENCES cost_governance_settlement(episode_id, episode_revision),
            CHECK (
                status NOT IN ('verified', 'failed')
                OR (
                    observation_digest IS NOT NULL
                    AND completeness_digest IS NOT NULL
                    AND terminal
                )
            )
        );

        CREATE TABLE cost_governance_evidence (
            episode_id TEXT NOT NULL,
            episode_revision BIGINT NOT NULL,
            evidence_sequence INTEGER NOT NULL CHECK (evidence_sequence >= 0),
            evidence_ref TEXT NOT NULL CHECK (char_length(evidence_ref) BETWEEN 1 AND 512),
            evidence_digest TEXT NOT NULL
                CHECK (evidence_digest ~ '^sha256:[0-9a-f]{64}$'),
            source_authority TEXT NOT NULL
                CHECK (char_length(source_authority) BETWEEN 1 AND 256),
            recorded_at TIMESTAMPTZ NOT NULL,
            idempotency_key TEXT NOT NULL
                CHECK (char_length(idempotency_key) BETWEEN 1 AND 512),
            PRIMARY KEY (episode_id, episode_revision, evidence_sequence),
            UNIQUE (episode_id, episode_revision, evidence_digest),
            UNIQUE (episode_id, episode_revision, idempotency_key),
            FOREIGN KEY (episode_id, episode_revision)
                REFERENCES cost_governance_episode(episode_id, revision)
        );

        CREATE TABLE cost_governance_retention (
            episode_id TEXT PRIMARY KEY,
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

        CREATE TABLE cost_governance_retention_event (
            episode_id TEXT NOT NULL,
            revision BIGINT NOT NULL CHECK (revision >= 1),
            event_kind TEXT NOT NULL
                CHECK (event_kind IN ('created', 'hold-applied', 'hold-released', 'purged')),
            legal_hold_ref TEXT NULL,
            recorded_at TIMESTAMPTZ NOT NULL,
            idempotency_key TEXT NOT NULL
                CHECK (char_length(idempotency_key) BETWEEN 1 AND 512),
            PRIMARY KEY (episode_id, revision),
            UNIQUE (episode_id, idempotency_key),
            FOREIGN KEY (episode_id)
                REFERENCES cost_governance_retention(episode_id)
        );

        CREATE INDEX cost_governance_episode_retention_idx
            ON cost_governance_episode (retention_until, episode_id);
        CREATE INDEX cost_governance_retention_purge_idx
            ON cost_governance_retention (purge_after, episode_id)
            WHERE purged_at IS NULL AND NOT legal_hold;

        REVOKE ALL PRIVILEGES ON TABLE
            cost_governance_episode,
            cost_governance_recovery,
            cost_governance_settlement,
            cost_governance_effect_settlement,
            cost_governance_evidence,
            cost_governance_retention,
            cost_governance_retention_event
        FROM PUBLIC, fdai_core;
        GRANT SELECT, INSERT ON TABLE
            cost_governance_episode,
            cost_governance_recovery,
            cost_governance_settlement,
            cost_governance_effect_settlement,
            cost_governance_evidence,
            cost_governance_retention_event
        TO fdai_core;
        GRANT SELECT, INSERT, UPDATE
            ON TABLE cost_governance_retention TO fdai_core;
        """
    )


def downgrade() -> None:
    """Drop W4-W5 lineage only after all related workers stop."""

    op.execute(
        """
        DROP TABLE cost_governance_retention_event;
        DROP TABLE cost_governance_retention;
        DROP TABLE cost_governance_evidence;
        DROP TABLE cost_governance_effect_settlement;
        DROP TABLE cost_governance_settlement;
        DROP TABLE cost_governance_recovery;
        DROP TABLE cost_governance_episode;
        """
    )
