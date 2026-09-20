"""Install an initially permissive ontology writer compatibility barrier."""

from __future__ import annotations

from alembic import op

revision = "core_ontology_writer_fence_20260920"
down_revision = "core_inventory_coverage_indexes_20260919"
branch_labels = None
depends_on = None
migration_owner = "core-control-plane"
owned_tables = ("state_kv", "ontology_resource", "ontology_link")
rollback = {
    "strategy": "remove-permissive-ontology-writer-barrier",
    "restores": "core_inventory_coverage_indexes_20260919",
    "requires": "legacy graph restored and minimum writer version returned to 1",
}


def upgrade() -> None:
    op.execute("""
INSERT INTO state_kv (key,value) VALUES
(
    'ontology:writer-protocol',
    jsonb_build_object('schema_version', '1.0.0', 'minimum_writer_version', 1)
)
ON CONFLICT (key) DO NOTHING;
CREATE FUNCTION enforce_ontology_writer_protocol() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE barrier jsonb;
BEGIN
    SELECT value INTO barrier FROM state_kv
    WHERE key='ontology:writer-protocol' FOR SHARE;
    IF barrier IS NULL
       OR barrier->>'schema_version' IS DISTINCT FROM '1.0.0'
       OR barrier->>'minimum_writer_version' IS NULL
       OR barrier->>'minimum_writer_version' NOT IN ('1','2')
       OR jsonb_typeof(barrier->'minimum_writer_version') <> 'number'
       OR barrier - 'schema_version' - 'minimum_writer_version' <> '{}'::jsonb THEN
        RAISE EXCEPTION 'ontology writer barrier is unavailable' USING ERRCODE='55000';
    END IF;
    IF barrier->>'minimum_writer_version' = '2'
       AND current_setting('fdai.ontology_writer_protocol', true) IS DISTINCT FROM '2' THEN
        RAISE EXCEPTION 'ontology writer protocol is fenced' USING ERRCODE='55000';
    END IF;
    RETURN NULL;
END;
$$;
CREATE TRIGGER ontology_resource_writer_protocol
BEFORE INSERT OR DELETE OR TRUNCATE ON ontology_resource
FOR EACH STATEMENT EXECUTE FUNCTION enforce_ontology_writer_protocol();
CREATE TRIGGER ontology_resource_writer_update_protocol
BEFORE UPDATE ON ontology_resource
FOR EACH STATEMENT EXECUTE FUNCTION enforce_ontology_writer_protocol();
CREATE TRIGGER ontology_link_writer_protocol
BEFORE INSERT OR DELETE OR TRUNCATE ON ontology_link
FOR EACH STATEMENT EXECUTE FUNCTION enforce_ontology_writer_protocol();
CREATE TRIGGER ontology_link_writer_update_protocol
BEFORE UPDATE ON ontology_link
FOR EACH STATEMENT EXECUTE FUNCTION enforce_ontology_writer_protocol();
    """)


def downgrade() -> None:
    op.execute("""
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM state_kv WHERE key='ontology:writer-protocol'
        AND value=jsonb_build_object(
            'schema_version', '1.0.0', 'minimum_writer_version', 1
        )
    ) THEN
        RAISE EXCEPTION 'restore the legacy graph and permissive barrier before downgrade'
            USING ERRCODE='55000';
    END IF;
END $$;
DROP TRIGGER ontology_resource_writer_protocol ON ontology_resource;
DROP TRIGGER ontology_resource_writer_update_protocol ON ontology_resource;
DROP TRIGGER ontology_link_writer_protocol ON ontology_link;
DROP TRIGGER ontology_link_writer_update_protocol ON ontology_link;
DROP FUNCTION enforce_ontology_writer_protocol();
DELETE FROM state_kv WHERE key='ontology:writer-protocol';
    """)
