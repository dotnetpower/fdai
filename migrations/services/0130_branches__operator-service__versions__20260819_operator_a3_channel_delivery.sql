-- Migration Revision: operator_a3_channel_delivery_20260819
-- Down Revision: operator_inventory_active_read_20260819
-- Owner: operator-service
-- Extracted SQL Blocks: 1

-- Statement 1
CREATE TABLE conversation_channel_message_claim (
            idempotency_key TEXT PRIMARY KEY CHECK (char_length(idempotency_key) = 64),
            state TEXT NOT NULL CHECK (state IN ('processing', 'completed')),
            claimed_at TIMESTAMPTZ NOT NULL,
            lease_expires_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            CHECK (
                (state = 'processing' AND lease_expires_at IS NOT NULL AND completed_at IS NULL)
                OR (state = 'completed' AND lease_expires_at IS NULL AND completed_at IS NOT NULL)
            ),
            CHECK (lease_expires_at IS NULL OR claimed_at < lease_expires_at),
            CHECK (completed_at IS NULL OR claimed_at <= completed_at)
        );
        CREATE INDEX conversation_channel_message_claim_lease_idx
            ON conversation_channel_message_claim (lease_expires_at, idempotency_key)
            WHERE state = 'processing';

        REVOKE ALL PRIVILEGES ON TABLE
            conversation_channel_message_claim,
            principal_conversation_binding,
            conversation_outbound_delivery,
            conversation_outbound_delivery_attempt,
            conversation_outbound_delivery_acknowledgement,
            conversation_adapter_breaker
        FROM PUBLIC, fdai_operator;

        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE
            conversation_channel_message_claim,
            principal_conversation_binding,
            conversation_outbound_delivery,
            conversation_outbound_delivery_attempt,
            conversation_outbound_delivery_acknowledgement,
            conversation_adapter_breaker
        TO fdai_operator;
