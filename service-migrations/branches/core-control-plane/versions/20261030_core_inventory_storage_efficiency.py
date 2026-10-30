"""Share immutable inventory membership without a generation replay chain."""

from __future__ import annotations

from alembic import op

revision = "core_inventory_storage_efficiency_20261030"
down_revision = "core_cache_storage_efficiency_20261030"
branch_labels = None
depends_on = None

migration_owner = "core-control-plane"
owned_tables = (
    "inventory_observation_snapshot_generation",
    "inventory_observation_snapshot_member",
    "inventory_observation_snapshot_member_legacy",
    "inventory_observation_snapshot_page",
    "inventory_observation_snapshot_set",
    "inventory_observation_snapshot_binding",
    "inventory_snapshot_resource",
    "inventory_snapshot_link",
    "inventory_snapshot_resource_row",
    "inventory_snapshot_link_row",
    "inventory_snapshot_properties",
)
rollback = {
    "strategy": "materialize-shared-membership-before-restoring-legacy-schema",
    "restores": "core_cache_storage_efficiency_20261030",
    "requires": "snapshot-membership-writers-and-readers-stopped",
}


def upgrade() -> None:
    op.execute(
        """
        SET LOCAL statement_timeout = '15s';
        SET LOCAL lock_timeout = '2s';
        LOCK TABLE inventory_snapshot_resource, inventory_snapshot_link,
            inventory_observation_snapshot_member IN ACCESS EXCLUSIVE MODE;
        DO $preflight$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_catalog.pg_depend dependency
                JOIN pg_catalog.pg_rewrite rewrite
                    ON dependency.classid='pg_catalog.pg_rewrite'::regclass
                    AND rewrite.oid=dependency.objid
                JOIN pg_catalog.pg_class dependent ON dependent.oid=rewrite.ev_class
                WHERE dependency.refclassid='pg_catalog.pg_class'::regclass
                AND dependency.refobjid=ANY(ARRAY[
                    'inventory_snapshot_resource'::regclass,
                    'inventory_snapshot_link'::regclass,
                    'inventory_observation_snapshot_member'::regclass
                ]) AND dependent.relkind IN ('v', 'm')
            ) THEN
                RAISE EXCEPTION
                    'inventory storage efficiency migration has unsupported view dependency';
            END IF;
        END;
        $preflight$;
        """
    )
    op.execute(
        """
        CREATE TABLE inventory_snapshot_properties (
            digest TEXT PRIMARY KEY,
            body TEXT NOT NULL CHECK (
                octet_length(body) <= 1048576 AND jsonb_typeof(body::jsonb)='object'
                AND digest='sha256:' || encode(sha256(convert_to(body, 'UTF8')), 'hex')
            )
        );
        REVOKE ALL ON inventory_snapshot_properties FROM PUBLIC;
        GRANT SELECT, INSERT, DELETE ON inventory_snapshot_properties TO fdai_core;
        CREATE TRIGGER inventory_snapshot_properties_no_update
            BEFORE UPDATE ON inventory_snapshot_properties FOR EACH ROW
            EXECUTE FUNCTION fdai_reject_inventory_snapshot_membership_mutation();
        ALTER TABLE inventory_snapshot_resource RENAME TO inventory_snapshot_resource_row;
        ALTER TABLE inventory_snapshot_resource_row
            ALTER COLUMN props DROP NOT NULL,
            ADD COLUMN props_digest TEXT REFERENCES inventory_snapshot_properties(digest),
            ADD COLUMN props_freshness JSONB NOT NULL DEFAULT '{}',
            ADD CONSTRAINT inventory_snapshot_resource_row_body_binding CHECK (
                (props IS NOT NULL AND props_digest IS NULL AND props_freshness='{}')
                OR (props IS NULL AND props_digest IS NOT NULL
                    AND jsonb_typeof(props_freshness)='object')
            );
        CREATE INDEX inventory_snapshot_resource_row_props_digest_idx
            ON inventory_snapshot_resource_row(props_digest) WHERE props_digest IS NOT NULL;
        CREATE VIEW inventory_snapshot_resource AS
            SELECT stored.snapshot_id, stored.resource_id, stored.resource_type,
                CASE WHEN stored.props_digest IS NULL THEN stored.props
                    ELSE content.body::jsonb || stored.props_freshness END AS props,
                stored.provider_ref, stored.last_seen
            FROM inventory_snapshot_resource_row stored
            LEFT JOIN inventory_snapshot_properties content ON content.digest=stored.props_digest;
        ALTER VIEW inventory_snapshot_resource ALTER COLUMN props SET DEFAULT '{}'::jsonb;
        CREATE FUNCTION fdai_inventory_snapshot_resource_compat()
        RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER AS $$
        BEGIN
            IF TG_OP='INSERT' THEN
                INSERT INTO inventory_snapshot_resource_row
                    (snapshot_id,resource_id,resource_type,props,provider_ref,last_seen)
                VALUES (NEW.snapshot_id,NEW.resource_id,NEW.resource_type,NEW.props,
                    NEW.provider_ref,NEW.last_seen);
            ELSIF TG_OP='UPDATE' THEN
                UPDATE inventory_snapshot_resource_row
                SET snapshot_id=NEW.snapshot_id, resource_id=NEW.resource_id,
                    resource_type=NEW.resource_type, props=NEW.props,
                    provider_ref=NEW.provider_ref, last_seen=NEW.last_seen,
                    props_digest=NULL, props_freshness='{}'
                WHERE snapshot_id=OLD.snapshot_id AND resource_id=OLD.resource_id;
            ELSE
                DELETE FROM inventory_snapshot_resource_row
                WHERE snapshot_id=OLD.snapshot_id AND resource_id=OLD.resource_id;
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$;
        REVOKE ALL ON FUNCTION fdai_inventory_snapshot_resource_compat() FROM PUBLIC;
        CREATE TRIGGER inventory_snapshot_resource_compat_insert INSTEAD OF INSERT
            ON inventory_snapshot_resource FOR EACH ROW
            EXECUTE FUNCTION fdai_inventory_snapshot_resource_compat();
        CREATE TRIGGER inventory_snapshot_resource_compat_update INSTEAD OF UPDATE
            ON inventory_snapshot_resource FOR EACH ROW
            EXECUTE FUNCTION fdai_inventory_snapshot_resource_compat();
        CREATE TRIGGER inventory_snapshot_resource_compat_delete INSTEAD OF DELETE
            ON inventory_snapshot_resource FOR EACH ROW
            EXECUTE FUNCTION fdai_inventory_snapshot_resource_compat();
        REVOKE ALL ON inventory_snapshot_resource FROM PUBLIC;
        DO $$
        DECLARE permission RECORD;
        BEGIN
            FOR permission IN
                SELECT grantee, privilege_type, is_grantable
                FROM information_schema.role_table_grants
                WHERE table_schema=current_schema()
                    AND table_name='inventory_snapshot_resource_row'
                    AND privilege_type IN ('SELECT', 'INSERT', 'UPDATE', 'DELETE')
            LOOP
                EXECUTE format('GRANT %s ON %I TO %I%s',
                    permission.privilege_type, 'inventory_snapshot_resource', permission.grantee,
                    CASE WHEN permission.is_grantable='YES'
                        THEN ' WITH GRANT OPTION' ELSE '' END);
            END LOOP;
        END;
        $$;
        """
    )
    op.execute(
        """
        ALTER TABLE inventory_snapshot_link RENAME TO inventory_snapshot_link_row;
        ALTER TABLE inventory_snapshot_link_row
            ALTER COLUMN props DROP NOT NULL,
            ADD COLUMN props_digest TEXT REFERENCES inventory_snapshot_properties(digest),
            ADD COLUMN props_freshness JSONB NOT NULL DEFAULT '{}',
            ADD CONSTRAINT inventory_snapshot_link_row_body_binding CHECK (
                (props IS NOT NULL AND props_digest IS NULL AND props_freshness='{}')
                OR (props IS NULL AND props_digest IS NOT NULL
                    AND jsonb_typeof(props_freshness)='object')
            );
        CREATE INDEX inventory_snapshot_link_row_props_digest_idx
            ON inventory_snapshot_link_row(props_digest) WHERE props_digest IS NOT NULL;
        CREATE VIEW inventory_snapshot_link AS
            SELECT stored.snapshot_id, stored.from_id, stored.from_type, stored.link_type,
                stored.to_id, stored.to_type,
                CASE WHEN stored.props_digest IS NULL THEN stored.props
                    ELSE content.body::jsonb || stored.props_freshness END AS props
            FROM inventory_snapshot_link_row stored
            LEFT JOIN inventory_snapshot_properties content ON content.digest=stored.props_digest;
        ALTER VIEW inventory_snapshot_link ALTER COLUMN props SET DEFAULT '{}'::jsonb;
        CREATE FUNCTION fdai_inventory_snapshot_link_compat()
        RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER AS $$
        BEGIN
            IF TG_OP='INSERT' THEN
                INSERT INTO inventory_snapshot_link_row
                    (snapshot_id,from_id,from_type,link_type,to_id,to_type,props)
                VALUES (NEW.snapshot_id,NEW.from_id,NEW.from_type,NEW.link_type,
                    NEW.to_id,NEW.to_type,NEW.props);
            ELSIF TG_OP='UPDATE' THEN
                UPDATE inventory_snapshot_link_row
                SET snapshot_id=NEW.snapshot_id, from_id=NEW.from_id, from_type=NEW.from_type,
                    link_type=NEW.link_type, to_id=NEW.to_id, to_type=NEW.to_type, props=NEW.props,
                    props_digest=NULL, props_freshness='{}'
                WHERE snapshot_id=OLD.snapshot_id AND from_id=OLD.from_id
                    AND link_type=OLD.link_type AND to_id=OLD.to_id;
            ELSE
                DELETE FROM inventory_snapshot_link_row
                WHERE snapshot_id=OLD.snapshot_id AND from_id=OLD.from_id
                    AND link_type=OLD.link_type AND to_id=OLD.to_id;
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$;
        REVOKE ALL ON FUNCTION fdai_inventory_snapshot_link_compat() FROM PUBLIC;
        CREATE TRIGGER inventory_snapshot_link_compat_insert INSTEAD OF INSERT
            ON inventory_snapshot_link FOR EACH ROW
            EXECUTE FUNCTION fdai_inventory_snapshot_link_compat();
        CREATE TRIGGER inventory_snapshot_link_compat_update INSTEAD OF UPDATE
            ON inventory_snapshot_link FOR EACH ROW
            EXECUTE FUNCTION fdai_inventory_snapshot_link_compat();
        CREATE TRIGGER inventory_snapshot_link_compat_delete INSTEAD OF DELETE
            ON inventory_snapshot_link FOR EACH ROW
            EXECUTE FUNCTION fdai_inventory_snapshot_link_compat();
        REVOKE ALL ON inventory_snapshot_link FROM PUBLIC;
        DO $$
        DECLARE permission RECORD;
        BEGIN
            FOR permission IN
                SELECT grantee, privilege_type, is_grantable
                FROM information_schema.role_table_grants
                WHERE table_schema=current_schema() AND table_name='inventory_snapshot_link_row'
                    AND privilege_type IN ('SELECT', 'INSERT', 'UPDATE', 'DELETE')
            LOOP
                EXECUTE format('GRANT %s ON %I TO %I%s',
                    permission.privilege_type, 'inventory_snapshot_link', permission.grantee,
                    CASE WHEN permission.is_grantable='YES'
                        THEN ' WITH GRANT OPTION' ELSE '' END);
            END LOOP;
        END;
        $$;
        """
    )
    op.execute(
        """
        ALTER TABLE inventory_observation_snapshot_generation
            ADD COLUMN storage_schema_version INTEGER NOT NULL DEFAULT 1
                CHECK (storage_schema_version IN (1, 2));
        ALTER TABLE inventory_observation_snapshot_member
            RENAME TO inventory_observation_snapshot_member_legacy;
        CREATE TABLE inventory_observation_snapshot_page (
            digest TEXT PRIMARY KEY,
            body TEXT NOT NULL CHECK (
                octet_length(body) <= 4194304
                AND jsonb_typeof(body::jsonb) = 'array'
                AND digest = 'sha256:' ||
                    encode(sha256(convert_to(body, 'UTF8')), 'hex')
            )
        );
        CREATE TABLE inventory_observation_snapshot_set (
            digest TEXT PRIMARY KEY,
            body TEXT NOT NULL CHECK (
                octet_length(body) <= 16777216
                AND jsonb_typeof(body::jsonb) = 'object'
                AND body::jsonb ?& ARRAY['count', 'pages']
                AND jsonb_typeof(body::jsonb->'count') = 'number'
                AND jsonb_typeof(body::jsonb->'pages') = 'array'
                AND (body::jsonb->>'count')::integer BETWEEN 0 AND 250000
                AND digest = 'sha256:' ||
                    encode(sha256(convert_to(body, 'UTF8')), 'hex')
            )
        );
        CREATE TABLE inventory_observation_snapshot_binding (
            generation_id TEXT PRIMARY KEY
                REFERENCES inventory_observation_snapshot_generation(generation_id),
            set_digest TEXT NOT NULL REFERENCES inventory_observation_snapshot_set(digest),
            bindings JSONB NOT NULL CHECK (
                jsonb_typeof(bindings) = 'object'
                AND bindings ? 'generation_id'
                AND bindings->>'generation_id' = generation_id
                AND bindings->>'observed_at' IS NOT NULL
                AND bindings->>'recorded_at' IS NOT NULL
            )
        );
        CREATE FUNCTION fdai_inventory_shared_snapshot_members(
            requested_generation TEXT,
            requested_kind TEXT DEFAULT NULL,
            requested_subject TEXT DEFAULT NULL
        )
        RETURNS SETOF JSONB LANGUAGE plpgsql STABLE SECURITY INVOKER AS $$
        DECLARE
            root JSONB;
            clocks JSONB;
            descriptor JSONB;
            page JSONB;
            members JSONB;
            template JSONB;
            substitution JSONB;
            member JSONB;
            total INTEGER := 0;
            subject_key TEXT;
            member_index INTEGER;
        BEGIN
            IF requested_kind IS NOT NULL AND requested_subject IS NOT NULL THEN
                subject_key := encode(sha256(convert_to(
                    '[' || to_jsonb(requested_kind)::text || ',' ||
                    to_jsonb(requested_subject)::text || ']', 'UTF8'
                )), 'hex');
            ELSIF requested_kind IS NOT NULL OR requested_subject IS NOT NULL THEN
                RAISE EXCEPTION 'inventory snapshot membership subject is incomplete';
            END IF;
            SELECT s.body::jsonb, b.bindings INTO root, clocks
            FROM inventory_observation_snapshot_binding b
            JOIN inventory_observation_snapshot_set s ON s.digest=b.set_digest
            WHERE b.generation_id=requested_generation;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'inventory snapshot membership binding is unavailable';
            END IF;
            FOR descriptor IN SELECT jsonb_array_elements(root->'pages') LOOP
                IF subject_key IS NOT NULL
                    AND NOT starts_with(subject_key, descriptor->>0) THEN
                    CONTINUE;
                END IF;
                SELECT body::jsonb INTO members FROM inventory_observation_snapshot_page
                WHERE digest=descriptor->>1;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'inventory snapshot membership page is unavailable';
                END IF;
                SELECT body::jsonb INTO page FROM inventory_observation_snapshot_page
                WHERE digest=descriptor->>2;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'inventory snapshot membership page is unavailable';
                END IF;
                IF jsonb_array_length(members) <> jsonb_array_length(page) THEN
                    RAISE EXCEPTION 'inventory snapshot membership evidence count changed';
                END IF;
                member_index := 0;
                FOR template IN SELECT jsonb_array_elements(page) LOOP
                    member := members->member_index || (template->'body');
                    member_index := member_index + 1;
                    FOR substitution IN
                        SELECT jsonb_array_elements(template->'substitutions')
                    LOOP
                        IF NOT clocks ? (substitution->>'binding') THEN
                            RAISE EXCEPTION 'inventory snapshot membership clock is unavailable';
                        END IF;
                        member := jsonb_set(
                            member,
                            ARRAY(SELECT jsonb_array_elements_text(substitution->'path')),
                            clocks->(substitution->>'binding'),
                            false
                        );
                    END LOOP;
                    total := total + 1;
                    IF total > 250000 THEN
                        RAISE EXCEPTION 'inventory snapshot membership exceeds its bound';
                    END IF;
                    IF subject_key IS NULL OR (
                        member->>'subject_kind'=requested_kind
                        AND member->>'subject_ref'=requested_subject
                    ) THEN
                        RETURN NEXT member;
                    END IF;
                END LOOP;
            END LOOP;
            IF subject_key IS NULL AND total <> (root->>'count')::integer THEN
                RAISE EXCEPTION 'inventory snapshot membership count changed';
            END IF;
        END;
        $$;
        CREATE VIEW inventory_observation_snapshot_member AS
            SELECT * FROM inventory_observation_snapshot_member_legacy
            UNION ALL
            SELECT generation.generation_id,
                member->>'subject_kind', member->>'subject_ref', member->>'subject_type',
                member->>'semantic_digest', member->>'provider_ref', member->>'scope_ref',
                (member->>'observed_at')::timestamptz, member->'freshness_properties',
                member->>'from_id', member->>'from_type', member->>'link_type',
                member->>'to_id', member->>'to_type'
            FROM inventory_observation_snapshot_generation generation
            CROSS JOIN LATERAL fdai_inventory_shared_snapshot_members(
                generation.generation_id
            ) member
            WHERE generation.storage_schema_version=2;
        REVOKE ALL ON inventory_observation_snapshot_page,
            inventory_observation_snapshot_set, inventory_observation_snapshot_binding,
            inventory_observation_snapshot_member FROM PUBLIC;
        REVOKE ALL ON FUNCTION fdai_inventory_shared_snapshot_members(TEXT, TEXT, TEXT)
            FROM PUBLIC;
        GRANT SELECT, INSERT ON inventory_observation_snapshot_page,
            inventory_observation_snapshot_set, inventory_observation_snapshot_binding
            TO fdai_core;
        GRANT SELECT ON inventory_observation_snapshot_member TO fdai_core;
        REVOKE INSERT ON inventory_observation_snapshot_member_legacy FROM fdai_core;
        GRANT EXECUTE ON FUNCTION fdai_inventory_shared_snapshot_members(TEXT, TEXT, TEXT)
            TO fdai_core;
        """
    )
    op.execute(
        """
        CREATE TRIGGER inventory_observation_snapshot_page_no_update
            BEFORE UPDATE ON inventory_observation_snapshot_page FOR EACH ROW
            EXECUTE FUNCTION fdai_reject_inventory_snapshot_membership_mutation();
        CREATE TRIGGER inventory_observation_snapshot_page_no_delete
            BEFORE DELETE ON inventory_observation_snapshot_page FOR EACH ROW
            EXECUTE FUNCTION fdai_reject_inventory_snapshot_membership_mutation();
        CREATE TRIGGER inventory_observation_snapshot_set_no_update
            BEFORE UPDATE ON inventory_observation_snapshot_set FOR EACH ROW
            EXECUTE FUNCTION fdai_reject_inventory_snapshot_membership_mutation();
        CREATE TRIGGER inventory_observation_snapshot_set_no_delete
            BEFORE DELETE ON inventory_observation_snapshot_set FOR EACH ROW
            EXECUTE FUNCTION fdai_reject_inventory_snapshot_membership_mutation();
        CREATE TRIGGER inventory_observation_snapshot_binding_no_update
            BEFORE UPDATE ON inventory_observation_snapshot_binding FOR EACH ROW
            EXECUTE FUNCTION fdai_reject_inventory_snapshot_membership_mutation();
        CREATE TRIGGER inventory_observation_snapshot_binding_no_delete
            BEFORE DELETE ON inventory_observation_snapshot_binding FOR EACH ROW
            EXECUTE FUNCTION fdai_reject_inventory_snapshot_membership_mutation();
        DO $pin_functions$
        BEGIN
            EXECUTE format(
                'ALTER FUNCTION %I.fdai_inventory_shared_snapshot_members(TEXT,TEXT,TEXT) '
                'SET search_path = pg_catalog, %I, pg_temp', current_schema(), current_schema());
            EXECUTE format(
                'ALTER FUNCTION %I.fdai_inventory_snapshot_resource_compat() '
                'SET search_path = pg_catalog, %I, pg_temp', current_schema(), current_schema());
            EXECUTE format(
                'ALTER FUNCTION %I.fdai_inventory_snapshot_link_compat() '
                'SET search_path = pg_catalog, %I, pg_temp', current_schema(), current_schema());
        END;
        $pin_functions$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        SET LOCAL statement_timeout = '15s';
        SET LOCAL lock_timeout = '2s';
        INSERT INTO inventory_observation_snapshot_member_legacy
        SELECT member.* FROM inventory_observation_snapshot_member member
        JOIN inventory_observation_snapshot_generation generation
            ON generation.generation_id=member.generation_id
        WHERE generation.storage_schema_version=2;
        DROP VIEW inventory_observation_snapshot_member;
        DROP FUNCTION fdai_inventory_shared_snapshot_members(TEXT, TEXT, TEXT);
        DROP TABLE inventory_observation_snapshot_binding;
        DROP TABLE inventory_observation_snapshot_set;
        DROP TABLE inventory_observation_snapshot_page;
        ALTER TABLE inventory_observation_snapshot_generation
            DROP COLUMN storage_schema_version;
        ALTER TABLE inventory_observation_snapshot_member_legacy
            RENAME TO inventory_observation_snapshot_member;
        GRANT SELECT, INSERT ON inventory_observation_snapshot_member TO fdai_core;
        """
    )
    op.execute(
        """
        UPDATE inventory_snapshot_resource_row stored
        SET props=content.body::jsonb || stored.props_freshness,
            props_digest=NULL, props_freshness='{}'
        FROM inventory_snapshot_properties content WHERE content.digest=stored.props_digest;
        DROP VIEW inventory_snapshot_resource;
        DROP FUNCTION fdai_inventory_snapshot_resource_compat();
        ALTER TABLE inventory_snapshot_resource_row
            DROP CONSTRAINT inventory_snapshot_resource_row_body_binding,
            DROP COLUMN props_digest, DROP COLUMN props_freshness,
            ALTER COLUMN props SET NOT NULL;
        ALTER TABLE inventory_snapshot_resource_row RENAME TO inventory_snapshot_resource;
        UPDATE inventory_snapshot_link_row stored
        SET props=content.body::jsonb || stored.props_freshness,
            props_digest=NULL, props_freshness='{}'
        FROM inventory_snapshot_properties content WHERE content.digest=stored.props_digest;
        DROP VIEW inventory_snapshot_link;
        DROP FUNCTION fdai_inventory_snapshot_link_compat();
        ALTER TABLE inventory_snapshot_link_row
            DROP CONSTRAINT inventory_snapshot_link_row_body_binding,
            DROP COLUMN props_digest, DROP COLUMN props_freshness,
            ALTER COLUMN props SET NOT NULL;
        ALTER TABLE inventory_snapshot_link_row RENAME TO inventory_snapshot_link;
        DROP TABLE inventory_snapshot_properties;
        """
    )
