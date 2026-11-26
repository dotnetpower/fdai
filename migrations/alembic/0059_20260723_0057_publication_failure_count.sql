-- Migration Revision: 20260723_0057
-- Down Revision: 20260723_0056
-- Owner: alembic
-- Extracted SQL Blocks: 1

-- Statement 1
ALTER TABLE forecast_publication_outbox
            ADD COLUMN IF NOT EXISTS claim_count INTEGER NOT NULL DEFAULT 0
                CHECK (claim_count >= 0),
            ADD COLUMN IF NOT EXISTS publish_fail_count INTEGER NOT NULL DEFAULT 0
                CHECK (publish_fail_count >= 0);
        UPDATE forecast_publication_outbox
           SET claim_count = GREATEST(claim_count, attempts);
