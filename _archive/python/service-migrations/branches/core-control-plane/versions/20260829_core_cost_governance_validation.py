"""Persist exact-revision Cost Governance lifecycle and campaign evidence."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_cost_governance_validation_20260829"
down_revision: str | Sequence[str] | None = "core_cost_governance_decision_20260828"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = (
    "cost_governance_campaign_episode",
    "cost_governance_lifecycle_receipt",
    "cost_governance_validation_retention",
    "cost_governance_validation_retention_event",
)
rollback = {
    "strategy": "drop-cost-validation-evidence-after-campaign-readers-stop",
    "restores": "core_cost_governance_decision_20260828",
    "requires": "cost-governance-validation-readers-stopped",
}


def upgrade() -> None:
    """Create append-only W7 evidence and mutable CAS retention metadata."""

    op.execute(
        """
        CREATE TABLE cost_governance_lifecycle_receipt (
            receipt_id TEXT PRIMARY KEY CHECK (char_length(receipt_id) BETWEEN 1 AND 512),
            package_id TEXT NOT NULL REFERENCES vertical_package_activation(package_id),
            activation_revision BIGINT NOT NULL CHECK (activation_revision >= 1),
            operation TEXT NOT NULL
                CHECK (operation IN ('install', 'enable', 'disable', 'upgrade', 'rollback')),
            outcome TEXT NOT NULL CHECK (outcome IN ('succeeded', 'blocked', 'failed')),
            receipt_digest TEXT NOT NULL UNIQUE
                CHECK (receipt_digest ~ '^sha256:[0-9a-f]{64}$'),
            revision_pin_digest TEXT NOT NULL
                CHECK (revision_pin_digest ~ '^sha256:[0-9a-f]{64}$'),
            evidence_kind TEXT NOT NULL
                CHECK (evidence_kind IN ('live-authoritative', 'synthetic', 'fixture', 'unit')),
            payload JSONB NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
            evidence_refs JSONB NOT NULL CHECK (
                jsonb_typeof(evidence_refs) = 'array'
                AND jsonb_array_length(evidence_refs) BETWEEN 1 AND 64
            ),
            occurred_at TIMESTAMPTZ NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE
                CHECK (char_length(idempotency_key) BETWEEN 1 AND 512),
            UNIQUE (receipt_id, receipt_digest)
        );

        CREATE TABLE cost_governance_campaign_episode (
            campaign_id TEXT NOT NULL CHECK (char_length(campaign_id) BETWEEN 1 AND 512),
            episode_id TEXT NOT NULL CHECK (char_length(episode_id) BETWEEN 1 AND 512),
            revision BIGINT NOT NULL CHECK (revision >= 1),
            idempotency_key TEXT NOT NULL
                CHECK (char_length(idempotency_key) BETWEEN 1 AND 512),
            revision_pin_digest TEXT NOT NULL
                CHECK (revision_pin_digest ~ '^sha256:[0-9a-f]{64}$'),
            outcome TEXT NOT NULL CHECK (
                outcome IN (
                    'beneficial-action', 'no-op', 'deny', 'hold-unresolved',
                    'approval', 'execute', 'rollback'
                )
            ),
            evidence_kind TEXT NOT NULL
                CHECK (evidence_kind IN ('live-authoritative', 'synthetic', 'fixture', 'unit')),
            payload JSONB NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
            evidence_refs JSONB NOT NULL CHECK (
                jsonb_typeof(evidence_refs) = 'array'
                AND jsonb_array_length(evidence_refs) BETWEEN 1 AND 64
            ),
            observed_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (episode_id, revision),
            UNIQUE (episode_id, idempotency_key),
            UNIQUE (campaign_id, idempotency_key)
        );

        CREATE TABLE cost_governance_validation_retention (
            evidence_kind TEXT NOT NULL CHECK (
                evidence_kind IN ('lifecycle-receipt', 'campaign-episode')
            ),
            evidence_id TEXT NOT NULL CHECK (char_length(evidence_id) BETWEEN 1 AND 512),
            revision BIGINT NOT NULL CHECK (revision >= 1),
            retention_until TIMESTAMPTZ NOT NULL,
            purge_after TIMESTAMPTZ NOT NULL,
            legal_hold BOOLEAN NOT NULL DEFAULT FALSE,
            legal_hold_ref TEXT NULL,
            purged_at TIMESTAMPTZ NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (evidence_kind, evidence_id),
            CHECK (retention_until <= purge_after),
            CHECK (legal_hold = (legal_hold_ref IS NOT NULL)),
            CHECK (purged_at IS NULL OR (NOT legal_hold AND purged_at >= purge_after))
        );

        CREATE TABLE cost_governance_validation_retention_event (
            evidence_kind TEXT NOT NULL,
            evidence_id TEXT NOT NULL,
            revision BIGINT NOT NULL CHECK (revision >= 1),
            event_kind TEXT NOT NULL CHECK (
                event_kind IN ('created', 'hold-applied', 'hold-released', 'purged')
            ),
            legal_hold_ref TEXT NULL,
            recorded_at TIMESTAMPTZ NOT NULL,
            idempotency_key TEXT NOT NULL
                CHECK (char_length(idempotency_key) BETWEEN 1 AND 512),
            PRIMARY KEY (evidence_kind, evidence_id, revision),
            UNIQUE (evidence_kind, evidence_id, idempotency_key),
            FOREIGN KEY (evidence_kind, evidence_id)
                REFERENCES cost_governance_validation_retention(evidence_kind, evidence_id)
        );

        CREATE INDEX cost_governance_lifecycle_receipt_package_idx
            ON cost_governance_lifecycle_receipt
            (package_id, activation_revision DESC, occurred_at DESC);
        CREATE INDEX cost_governance_campaign_episode_campaign_idx
            ON cost_governance_campaign_episode
            (campaign_id, observed_at, episode_id, revision);
        CREATE INDEX cost_governance_validation_retention_purge_idx
            ON cost_governance_validation_retention
            (purge_after, evidence_kind, evidence_id)
            WHERE purged_at IS NULL AND NOT legal_hold;

        REVOKE ALL PRIVILEGES ON TABLE
            cost_governance_lifecycle_receipt,
            cost_governance_campaign_episode,
            cost_governance_validation_retention,
            cost_governance_validation_retention_event
        FROM PUBLIC, fdai_core;
        GRANT SELECT, INSERT ON TABLE
            cost_governance_lifecycle_receipt,
            cost_governance_campaign_episode,
            cost_governance_validation_retention_event
        TO fdai_core;
        GRANT SELECT, INSERT, UPDATE
            ON TABLE cost_governance_validation_retention TO fdai_core;
        """
    )


def downgrade() -> None:
    """Drop W7 local validation evidence after readers stop."""

    op.execute(
        """
        DROP TABLE cost_governance_validation_retention_event;
        DROP TABLE cost_governance_validation_retention;
        DROP TABLE cost_governance_campaign_episode;
        DROP TABLE cost_governance_lifecycle_receipt;
        """
    )
