-- Migration Revision: core_background_task_progress_order_20260829
-- Down Revision: core_standing_authority_lifecycle_20260829
-- Owner: core-control-plane
-- Extracted SQL Blocks: 1

-- Statement 1
REVOKE ALL PRIVILEGES ON TABLE background_task_projection_outbox
            FROM PUBLIC, fdai_core;
        GRANT SELECT, INSERT, UPDATE ON TABLE background_task_projection_outbox TO fdai_core;

        REVOKE ALL PRIVILEGES ON SEQUENCE background_task_progress_append_order_seq
            FROM PUBLIC, fdai_core;
        GRANT USAGE, SELECT ON SEQUENCE background_task_progress_append_order_seq TO fdai_core;

        REVOKE ALL PRIVILEGES ON SEQUENCE
            background_task_projection_outbox_outbox_sequence_seq
        FROM PUBLIC, fdai_core;
        GRANT USAGE, SELECT ON SEQUENCE
            background_task_projection_outbox_outbox_sequence_seq
        TO fdai_core;
