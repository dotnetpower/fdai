"""durable conversation binding and outbound delivery ledger

Revision ID: 20260720_0047
Revises: 20260720_0046
Create Date: 2026-07-20 23:45:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260720_0047"
down_revision: str | None = "20260720_0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE principal_conversation_binding (
            binding_id TEXT PRIMARY KEY,
            principal_id TEXT NOT NULL,
            scope_ref TEXT NOT NULL,
            conversation_id TEXT NOT NULL,
            channel_kind TEXT NOT NULL CHECK (channel_kind IN ('web', 'slack', 'teams')),
            channel_id TEXT NOT NULL,
            sender_id TEXT NOT NULL,
            thread_id TEXT,
            verification_ref TEXT NOT NULL,
            verified_at TIMESTAMPTZ NOT NULL,
            created_by TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            resumed_from_binding_id TEXT REFERENCES principal_conversation_binding(binding_id),
            state TEXT NOT NULL CHECK (state IN ('active', 'revoked')),
            revoked_by TEXT,
            revoked_at TIMESTAMPTZ,
            CHECK (
                (state = 'active' AND revoked_by IS NULL AND revoked_at IS NULL)
                OR (state = 'revoked' AND revoked_by IS NOT NULL AND revoked_at IS NOT NULL)
            )
        );
        CREATE INDEX principal_conversation_binding_principal_idx
            ON principal_conversation_binding (principal_id, created_at DESC);
        CREATE UNIQUE INDEX principal_conversation_binding_active_endpoint_idx
            ON principal_conversation_binding (
                principal_id, scope_ref, channel_kind, channel_id, sender_id,
                COALESCE(thread_id, '')
            ) WHERE state = 'active';

        CREATE TABLE conversation_outbound_delivery (
            delivery_id TEXT PRIMARY KEY,
            idempotency_key TEXT NOT NULL UNIQUE,
            principal_id TEXT NOT NULL,
            scope_ref TEXT NOT NULL,
            conversation_id TEXT NOT NULL,
            binding_id TEXT REFERENCES principal_conversation_binding(binding_id),
            channel_kind TEXT NOT NULL CHECK (channel_kind IN ('web', 'slack', 'teams')),
            response JSONB NOT NULL CHECK (jsonb_typeof(response) = 'object'),
            response_digest TEXT NOT NULL CHECK (char_length(response_digest) = 64),
            state TEXT NOT NULL CHECK (
                state IN ('pending', 'sending', 'delivered', 'ambiguous', 'failed', 'abandoned')
            ),
            created_at TIMESTAMPTZ NOT NULL,
            due_at TIMESTAMPTZ NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            retention_until TIMESTAMPTZ NOT NULL,
            attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count BETWEEN 0 AND 8),
            lease_owner TEXT,
            lease_expires_at TIMESTAMPTZ,
            last_error_code TEXT CHECK (char_length(last_error_code) <= 512),
            duplicate_risk BOOLEAN NOT NULL DEFAULT FALSE,
            terminal_at TIMESTAMPTZ,
            CHECK (created_at <= due_at AND due_at < expires_at AND expires_at <= retention_until),
            CHECK (
                (state = 'sending' AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)
                OR (state <> 'sending' AND lease_owner IS NULL AND lease_expires_at IS NULL)
            ),
            CHECK (
                (state IN ('delivered', 'ambiguous', 'abandoned') AND terminal_at IS NOT NULL)
                OR (state NOT IN ('delivered', 'ambiguous', 'abandoned') AND terminal_at IS NULL)
            ),
            CHECK (state <> 'ambiguous' OR duplicate_risk)
        );
        CREATE INDEX conversation_outbound_delivery_due_idx
            ON conversation_outbound_delivery (due_at, delivery_id)
            WHERE state IN ('pending', 'failed');
        CREATE INDEX conversation_outbound_delivery_retention_idx
            ON conversation_outbound_delivery (retention_until, delivery_id);
        CREATE INDEX conversation_outbound_delivery_duplicate_risk_idx
            ON conversation_outbound_delivery (terminal_at DESC, delivery_id)
            WHERE duplicate_risk;
        CREATE INDEX conversation_outbound_delivery_latency_idx
            ON conversation_outbound_delivery (terminal_at DESC, created_at)
            WHERE state = 'delivered';

        CREATE TABLE conversation_outbound_delivery_attempt (
            attempt_id TEXT PRIMARY KEY,
            delivery_id TEXT NOT NULL REFERENCES conversation_outbound_delivery(delivery_id)
                ON DELETE CASCADE,
            sequence INTEGER NOT NULL CHECK (sequence BETWEEN 1 AND 8),
            worker_id TEXT NOT NULL,
            started_at TIMESTAMPTZ NOT NULL,
            completed_at TIMESTAMPTZ,
            outcome TEXT CHECK (
                outcome IN ('delivered', 'ambiguous', 'failed', 'abandoned')
            ),
            error_code TEXT CHECK (char_length(error_code) <= 512),
            UNIQUE (delivery_id, sequence),
            CHECK ((completed_at IS NULL) = (outcome IS NULL))
        );
        CREATE INDEX conversation_outbound_delivery_attempt_delivery_idx
            ON conversation_outbound_delivery_attempt (delivery_id, sequence DESC);

        CREATE TABLE conversation_outbound_delivery_acknowledgement (
            delivery_id TEXT PRIMARY KEY REFERENCES conversation_outbound_delivery(delivery_id)
                ON DELETE CASCADE,
            attempt_id TEXT NOT NULL UNIQUE
                REFERENCES conversation_outbound_delivery_attempt(attempt_id) ON DELETE CASCADE,
            provider_message_id TEXT NOT NULL,
            acknowledged_at TIMESTAMPTZ NOT NULL,
            degraded_to_text BOOLEAN NOT NULL DEFAULT FALSE
        );

        CREATE TABLE conversation_adapter_breaker (
            adapter_id TEXT PRIMARY KEY,
            channel_kind TEXT NOT NULL CHECK (channel_kind IN ('web', 'slack', 'teams')),
            mode TEXT NOT NULL CHECK (mode IN ('closed', 'open', 'paused')),
            failure_timestamps JSONB NOT NULL CHECK (jsonb_typeof(failure_timestamps) = 'array'),
            revision INTEGER NOT NULL CHECK (revision >= 0),
            updated_at TIMESTAMPTZ NOT NULL,
            updated_by TEXT NOT NULL,
            reason TEXT NOT NULL CHECK (char_length(reason) BETWEEN 1 AND 512)
        );
        CREATE INDEX conversation_adapter_breaker_mode_idx
            ON conversation_adapter_breaker (mode, updated_at DESC);

        CREATE FUNCTION reject_terminal_conversation_delivery_update()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.state IN ('delivered', 'ambiguous', 'abandoned') THEN
                RAISE EXCEPTION 'terminal conversation delivery is immutable';
            END IF;
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER conversation_outbound_delivery_terminal_guard
            BEFORE UPDATE ON conversation_outbound_delivery
            FOR EACH ROW EXECUTE FUNCTION reject_terminal_conversation_delivery_update();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER conversation_outbound_delivery_terminal_guard
            ON conversation_outbound_delivery;
        DROP FUNCTION reject_terminal_conversation_delivery_update();
        DROP TABLE conversation_adapter_breaker;
        DROP TABLE conversation_outbound_delivery_acknowledgement;
        DROP TABLE conversation_outbound_delivery_attempt;
        DROP TABLE conversation_outbound_delivery;
        DROP TABLE principal_conversation_binding;
        """
    )
