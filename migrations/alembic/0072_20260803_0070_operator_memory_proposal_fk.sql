-- Migration Revision: 20260803_0070
-- Down Revision: 20260801_0069
-- Owner: alembic
-- Extracted SQL Blocks: 1

-- Statement 1
ALTER TABLE operator_memory_proposal
            ADD CONSTRAINT fk_operator_memory_proposal_materialized_entry
            FOREIGN KEY (materialized_entry_id)
            REFERENCES operator_memory(id)
            ON DELETE RESTRICT
            NOT VALID;
        ALTER TABLE operator_memory_proposal
            VALIDATE CONSTRAINT fk_operator_memory_proposal_materialized_entry;
