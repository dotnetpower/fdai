-- Migration Revision: operator_automation_blueprint_intent_20261019
-- Down Revision: operator_entitlement_state_read_20261001
-- Owner: operator-service
-- Extracted SQL Blocks: 1

-- Statement 1
ALTER TABLE automation_blueprint_candidate
            ADD COLUMN schedule_timezone TEXT NOT NULL DEFAULT 'UTC',
            ADD COLUMN event_payload_json TEXT NOT NULL DEFAULT '{}',
            ADD CONSTRAINT automation_blueprint_schedule_timezone_nonempty
                CHECK (char_length(schedule_timezone) BETWEEN 1 AND 255),
            ADD CONSTRAINT automation_blueprint_event_payload_bounded
                CHECK (
                    char_length(event_payload_json) <= 16384
                    AND jsonb_typeof(event_payload_json::jsonb) = 'object'
                );
