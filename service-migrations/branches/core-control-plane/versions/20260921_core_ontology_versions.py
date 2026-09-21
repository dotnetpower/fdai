"""Install inactive versioned graph storage; activation is a separate operation."""

from __future__ import annotations

from alembic import op

revision = "core_ontology_versions_20260921"
down_revision = "core_hil_park_queue_index_20260921"
branch_labels = None
depends_on = None
migration_owner = "core-control-plane"
owned_tables = (
    "ontology_resource",
    "ontology_link",
    "ontology_graph_version",
    "ontology_graph_control",
    "ontology_resource_version",
    "ontology_link_version",
)
rollback = {
    "strategy": "remove-inactive-ontology-version-storage",
    "restores": "core_hil_park_queue_index_20260921",
    "requires": "materialized legacy graph and no active version",
}


def upgrade() -> None:
    op.execute("""
CREATE TABLE ontology_graph_version (
    version_id TEXT PRIMARY KEY,
    content_digest TEXT,
    object_count BIGINT,
    link_count BIGINT,
    sealed BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (NOT sealed OR (content_digest ~ '^sha256:[0-9a-f]{64}$'
        AND object_count >= 0 AND link_count >= 0
        AND content_digest IS NOT NULL AND object_count IS NOT NULL AND link_count IS NOT NULL))
);
CREATE TABLE ontology_graph_control (
    singleton BOOLEAN PRIMARY KEY CHECK (singleton),
    epoch BIGINT NOT NULL CHECK (epoch >= 0),
    active_version TEXT REFERENCES ontology_graph_version(version_id)
);
INSERT INTO ontology_graph_control VALUES (TRUE, 0, NULL);
CREATE TABLE ontology_resource_version (
    snapshot_version TEXT NOT NULL REFERENCES ontology_graph_version(version_id),
    LIKE ontology_resource INCLUDING DEFAULTS INCLUDING CONSTRAINTS,
    PRIMARY KEY (snapshot_version, id)
);
CREATE INDEX ontology_resource_version_type ON ontology_resource_version
    (snapshot_version, object_type, id);
CREATE TABLE ontology_link_version (
    snapshot_version TEXT NOT NULL REFERENCES ontology_graph_version(version_id),
    LIKE ontology_link INCLUDING DEFAULTS INCLUDING CONSTRAINTS,
    UNIQUE (snapshot_version, from_id, link_type, to_id),
    FOREIGN KEY (snapshot_version, from_id)
        REFERENCES ontology_resource_version(snapshot_version, id),
    FOREIGN KEY (snapshot_version, to_id)
        REFERENCES ontology_resource_version(snapshot_version, id)
);
CREATE INDEX ontology_link_version_target ON ontology_link_version
    (snapshot_version, to_id, link_type);
CREATE FUNCTION enforce_ontology_version_content() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE frozen BOOLEAN;
BEGIN
    IF TG_OP='DELETE'
       AND current_setting('fdai.ontology_version_gc',true)=OLD.snapshot_version
       AND NOT EXISTS (SELECT 1 FROM ontology_graph_control
                       WHERE active_version=OLD.snapshot_version) THEN
        RETURN OLD;
    END IF;
    IF TG_OP = 'UPDATE' AND NEW.snapshot_version IS DISTINCT FROM OLD.snapshot_version THEN
        RAISE EXCEPTION 'ontology version identity is immutable' USING ERRCODE='55000';
    END IF;
    SELECT sealed INTO frozen FROM ontology_graph_version
    WHERE version_id=CASE WHEN TG_OP='DELETE' THEN OLD.snapshot_version
                         ELSE NEW.snapshot_version END FOR SHARE;
    IF frozen IS DISTINCT FROM FALSE THEN
        RAISE EXCEPTION 'ontology version content is sealed or unavailable' USING ERRCODE='55000';
    END IF;
    IF TG_OP='DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER ontology_resource_version_content BEFORE INSERT OR DELETE OR UPDATE
ON ontology_resource_version FOR EACH ROW EXECUTE FUNCTION enforce_ontology_version_content();
CREATE TRIGGER ontology_link_version_content BEFORE INSERT OR DELETE OR UPDATE
ON ontology_link_version FOR EACH ROW EXECUTE FUNCTION enforce_ontology_version_content();
CREATE FUNCTION reject_ontology_version_truncate() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'ontology version truncation is forbidden' USING ERRCODE='55000';
END;
$$;
CREATE TRIGGER ontology_resource_version_no_truncation BEFORE TRUNCATE ON ontology_resource_version
FOR EACH STATEMENT EXECUTE FUNCTION reject_ontology_version_truncate();
CREATE TRIGGER ontology_link_version_no_truncation BEFORE TRUNCATE ON ontology_link_version
FOR EACH STATEMENT EXECUTE FUNCTION reject_ontology_version_truncate();
CREATE FUNCTION enforce_ontology_version_seal() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP='DELETE'
       AND current_setting('fdai.ontology_version_gc',true)=OLD.version_id
    AND NOT EXISTS (SELECT 1 FROM ontology_graph_control
              WHERE active_version=OLD.version_id) THEN
        RETURN OLD;
    END IF;
    IF OLD.sealed THEN
        RAISE EXCEPTION 'ontology version seal is immutable' USING ERRCODE='55000';
    END IF;
    IF TG_OP='DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER ontology_graph_version_seal BEFORE DELETE OR UPDATE ON ontology_graph_version
FOR EACH ROW EXECUTE FUNCTION enforce_ontology_version_seal();
CREATE FUNCTION enforce_ontology_legacy_version() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM ontology_graph_control WHERE active_version IS NOT NULL)
       AND current_setting('fdai.ontology_materialization',true) IS DISTINCT FROM 'on' THEN
        RAISE EXCEPTION 'legacy ontology writes are fenced after activation' USING ERRCODE='55000';
    END IF;
    RETURN NULL;
END;
$$;
CREATE TRIGGER ontology_resource_version_fence BEFORE INSERT OR DELETE OR TRUNCATE
ON ontology_resource FOR EACH STATEMENT EXECUTE FUNCTION enforce_ontology_legacy_version();
CREATE TRIGGER ontology_resource_version_update_fence BEFORE UPDATE
ON ontology_resource FOR EACH STATEMENT EXECUTE FUNCTION enforce_ontology_legacy_version();
CREATE TRIGGER ontology_link_version_fence BEFORE INSERT OR DELETE OR TRUNCATE
ON ontology_link FOR EACH STATEMENT EXECUTE FUNCTION enforce_ontology_legacy_version();
CREATE TRIGGER ontology_link_version_update_fence BEFORE UPDATE
ON ontology_link FOR EACH STATEMENT EXECUTE FUNCTION enforce_ontology_legacy_version();
CREATE FUNCTION enforce_ontology_graph_control() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP<>'UPDATE' THEN
        RAISE EXCEPTION 'ontology graph control cannot be removed or replaced'
            USING ERRCODE='55000';
    END IF;
    IF NEW.epoch<>OLD.epoch + (CASE WHEN NEW.active_version IS DISTINCT FROM OLD.active_version
                                   THEN 1 ELSE 0 END)
       OR current_setting('fdai.ontology_writer_protocol',true) IS DISTINCT FROM '2'
       OR (NEW.active_version IS NULL
           AND current_setting('fdai.ontology_materialization',true) IS DISTINCT FROM 'on')
       OR (NEW.active_version IS NOT NULL AND NOT EXISTS (
           SELECT 1 FROM ontology_graph_version WHERE version_id=NEW.active_version AND sealed
       )) THEN
        RAISE EXCEPTION 'ontology graph control transition is invalid' USING ERRCODE='55000';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER ontology_graph_control_guard BEFORE INSERT OR DELETE OR UPDATE
ON ontology_graph_control FOR EACH ROW EXECUTE FUNCTION enforce_ontology_graph_control();
CREATE TRIGGER ontology_graph_control_no_truncation BEFORE TRUNCATE ON ontology_graph_control
FOR EACH STATEMENT EXECUTE FUNCTION reject_ontology_version_truncate();
REVOKE ALL ON ontology_graph_control, ontology_graph_version,
    ontology_resource_version, ontology_link_version FROM PUBLIC;
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='fdai_core') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON ontology_graph_control, ontology_graph_version,
            ontology_resource_version, ontology_link_version TO fdai_core;
    END IF;
END $$;
    """)


def downgrade() -> None:
    op.execute("""
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM ontology_graph_control WHERE active_version IS NOT NULL) THEN
        RAISE EXCEPTION 'materialize the active ontology graph before downgrade'
            USING ERRCODE='55000';
    END IF;
END $$;
DROP TRIGGER ontology_resource_version_fence ON ontology_resource;
DROP TRIGGER ontology_resource_version_update_fence ON ontology_resource;
DROP TRIGGER ontology_link_version_fence ON ontology_link;
DROP TRIGGER ontology_link_version_update_fence ON ontology_link;
DROP TABLE ontology_link_version;
DROP TABLE ontology_resource_version;
DROP TABLE ontology_graph_control;
DROP TABLE ontology_graph_version;
DROP FUNCTION enforce_ontology_version_content();
DROP FUNCTION enforce_ontology_version_seal();
DROP FUNCTION reject_ontology_version_truncate();
DROP FUNCTION enforce_ontology_legacy_version();
DROP FUNCTION enforce_ontology_graph_control();
    """)
