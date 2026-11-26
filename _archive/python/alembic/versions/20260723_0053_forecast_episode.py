"""durable forecast episode ledger and terminal outcome outbox

Revision ID: 20260723_0053
Revises: 20260722_0052
Create Date: 2026-07-23 14:30:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260723_0053"
down_revision: str | None = "20260722_0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE forecast_episode (
            episode_id UUID PRIMARY KEY,
            correlation_id TEXT NOT NULL CHECK (char_length(correlation_id) BETWEEN 1 AND 512),
            detector_id TEXT NOT NULL CHECK (char_length(detector_id) BETWEEN 1 AND 512),
            detector_version TEXT NOT NULL,
            scorer_version TEXT NOT NULL,
            access_scope_digest TEXT NOT NULL CHECK (
                access_scope_digest ~ '^[0-9a-f]{64}$'
            ),
            target_ref TEXT NOT NULL CHECK (char_length(target_ref) BETWEEN 1 AND 2048),
            target_digest TEXT NOT NULL CHECK (target_digest ~ '^[0-9a-f]{64}$'),
            metric TEXT NOT NULL CHECK (char_length(metric) BETWEEN 1 AND 512),
            feature_cutoff TIMESTAMPTZ NOT NULL,
            horizon_started_at TIMESTAMPTZ NOT NULL,
            horizon_ended_at TIMESTAMPTZ NOT NULL,
            telemetry_grace_seconds INTEGER NOT NULL CHECK (telemetry_grace_seconds >= 0),
            closure_due_at TIMESTAMPTZ NOT NULL,
            direction TEXT NOT NULL CHECK (direction IN ('rising', 'falling')),
            threshold DOUBLE PRECISION NOT NULL,
            evaluation_kind TEXT NOT NULL CHECK (
                evaluation_kind IN ('predicted_breach', 'predicted_no_breach', 'abstained')
            ),
            evidence_refs TEXT[] NOT NULL CHECK (
                cardinality(evidence_refs) > 0
                AND array_position(evidence_refs, '') IS NULL
            ),
            predicted_value DOUBLE PRECISION,
            interval_lower DOUBLE PRECISION,
            interval_upper DOUBLE PRECISION,
            abstain_reason TEXT,
            mode TEXT NOT NULL CHECK (mode IN ('shadow', 'enforce')),
            state TEXT NOT NULL CHECK (state IN ('open', 'closed')),
            revision INTEGER NOT NULL CHECK (revision >= 1),
            closure_leased_until TIMESTAMPTZ,
            closure_attempts INTEGER NOT NULL DEFAULT 0 CHECK (closure_attempts >= 0),
            closed_at TIMESTAMPTZ,
            closure_reason TEXT CHECK (
                closure_reason IS NULL OR closure_reason IN (
                    'scored', 'negative_no_breach', 'abstained_no_breach'
                )
            ),
            outcome_id UUID UNIQUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CHECK (feature_cutoff <= horizon_started_at),
            CHECK (horizon_started_at <= horizon_ended_at),
            CHECK (
                closure_due_at = horizon_ended_at
                    + make_interval(secs => telemetry_grace_seconds)
            ),
            CHECK (
                (evaluation_kind = 'predicted_breach'
                    AND predicted_value IS NOT NULL
                    AND interval_lower IS NOT NULL
                    AND interval_upper IS NOT NULL
                    AND abstain_reason IS NULL)
                OR (evaluation_kind = 'predicted_no_breach'
                    AND predicted_value IS NULL
                    AND interval_lower IS NULL
                    AND interval_upper IS NULL
                    AND abstain_reason IS NULL)
                OR (evaluation_kind = 'abstained'
                    AND predicted_value IS NULL
                    AND interval_lower IS NULL
                    AND interval_upper IS NULL
                    AND char_length(abstain_reason) > 0)
            ),
            CHECK (interval_lower IS NULL OR interval_lower <= interval_upper),
            CHECK (
                (state = 'open' AND closed_at IS NULL AND closure_reason IS NULL)
                OR (state = 'closed' AND closed_at IS NOT NULL AND closure_reason IS NOT NULL)
            )
        );

        CREATE INDEX ix_forecast_episode_due
            ON forecast_episode (closure_due_at, episode_id)
            WHERE state = 'open';
        CREATE INDEX ix_forecast_episode_scope_detector
            ON forecast_episode (
                access_scope_digest, detector_id, metric, horizon_ended_at DESC, episode_id
            );

        CREATE TABLE forecast_publication_outbox (
            publication_id UUID PRIMARY KEY,
            episode_id UUID NOT NULL REFERENCES forecast_episode(episode_id),
            topic TEXT NOT NULL CHECK (topic IN ('object.forecast', 'object.forecast-outcome')),
            payload JSONB NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
            available_at TIMESTAMPTZ NOT NULL,
            leased_until TIMESTAMPTZ,
            attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
            last_error TEXT,
            published_at TIMESTAMPTZ,
            dead_lettered_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (episode_id, topic),
            CHECK (published_at IS NULL OR leased_until IS NULL),
            CHECK (dead_lettered_at IS NULL OR leased_until IS NULL),
            CHECK (published_at IS NULL OR dead_lettered_at IS NULL)
        );
        CREATE INDEX ix_forecast_publication_outbox_pending
            ON forecast_publication_outbox (available_at, publication_id)
            WHERE published_at IS NULL AND dead_lettered_at IS NULL;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS forecast_publication_outbox;")
    op.execute("DROP TABLE IF EXISTS forecast_outcome_outbox;")
    op.execute("DROP TABLE IF EXISTS forecast_episode;")
