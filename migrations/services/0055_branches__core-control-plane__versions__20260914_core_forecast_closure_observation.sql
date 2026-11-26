-- Migration Revision: core_forecast_closure_observation_20260914
-- Down Revision: core_human_access_execution_20260915
-- Owner: core-control-plane
-- Extracted SQL Blocks: 1

-- Statement 1
ALTER TABLE forecast_episode
            ADD COLUMN closure_observation JSONB,
            ADD CONSTRAINT forecast_closure_observation_object
                CHECK (
                    closure_observation IS NULL
                    OR (
                        state = 'closed'
                        AND jsonb_typeof(closure_observation) = 'object'
                    )
                );
