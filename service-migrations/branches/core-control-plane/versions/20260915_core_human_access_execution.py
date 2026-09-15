"""Core-owned immutable human-access execution source and exact read function."""

from alembic import op

revision = "core_human_access_execution_20260915"
down_revision = "core_handover_semantics_20260914"
branch_labels = None
depends_on = None
migration_owner = "core-control-plane"
owned_tables = ("state_kv",)
rollback = {
    "strategy": "remove-unused-human-access-source",
    "restores": "core_handover_semantics_20260914",
    "requires": "no-retained-human-access-material",
}


def upgrade() -> None:
    """Expose only material-bound source rows; old reviewed material is never rewritten."""
    op.execute(
        """
        CREATE FUNCTION fdai_executor_human_access_source(action_id text, action_digest text)
        RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, public AS $$
            SELECT jsonb_build_object(
                'material', material.value,
                'current', current_sources.value,
                'case', assignment.value,
                'promotion', promotion.value,
                'kill_switch', (SELECT value FROM public.state_kv WHERE key = 'system:kill-switch'),
                'source_count', (SELECT count(*) FROM public.state_kv
                    WHERE starts_with(key, 'human_assignment:case:')),
                'inverse_original', inverse_original.value,
                'inverse_intent', inverse_intent.value,
                'inverse_result', inverse_result.value,
                'target_fence', fence.record,
                'recovery_demand', (SELECT COALESCE(jsonb_object_agg(
                    substring(demand.key from length('human_assignment:case:') + 1),
                    demand.value), '{}'::jsonb)
                    FROM public.state_kv demand
                    WHERE starts_with(demand.key, 'human_assignment:case:')
                        AND demand.key <> assignment.key
                        AND ((demand.value #>> '{intent,subject,provider}' = 'entra'
                            AND lower(demand.value #>> '{intent,subject,subject_id}') =
                                material.value->>'subject_id'
                            AND demand.value #>> '{intent,requested_role}' =
                                material.value->>'requested_role')
                          OR demand.key = 'human_assignment:case:' ||
                                (assignment.value #>> '{intent,revocation,case_id}')
                          OR demand.key IN (SELECT 'human_assignment:case:' || replacement_key
                            FROM jsonb_object_keys(COALESCE(
                                assignment.value #> '{intent,revocation,replacement_revisions}',
                                '{}'::jsonb)) replacement_key))),
                'related_cases', (SELECT jsonb_object_agg(related.key, related.value)
                    FROM public.state_kv related
                    WHERE related.key = 'human_assignment:case:' ||
                        (assignment.value #>> '{intent,revocation,case_id}')
                    OR related.key IN (SELECT 'human_assignment:case:' || replacement_key
                        FROM jsonb_object_keys(COALESCE(
                            assignment.value #> '{intent,revocation,replacement_revisions}',
                            '{}'::jsonb)) replacement_key)),
                'other_demand', EXISTS (SELECT 1 FROM public.state_kv demand
                    WHERE starts_with(demand.key, 'human_assignment:case:')
                        AND demand.key <> 'human_assignment:case:' ||
                            (assignment.value #>> '{intent,revocation,case_id}')
                        AND NOT (demand.value->'intent' ? 'revocation')
                        AND demand.value->>'state' IN ('active', 'iam_applying', 'degraded')
                        AND demand.value #>> '{intent,subject,provider}' = 'entra'
                        AND lower(demand.value #>> '{intent,subject,subject_id}') =
                            material.value->>'subject_id'
                        AND demand.value #>> '{intent,requested_role}' =
                            material.value->>'requested_role'),
                'parks', (SELECT jsonb_object_agg(slot, park.value)
                    FROM jsonb_array_elements_text(material.value->'approval_ids') slot
                    LEFT JOIN public.state_kv park ON park.key = 'hil_park:' || slot),
                'decisions', (SELECT jsonb_object_agg(slot, decision.value)
                    FROM jsonb_array_elements_text(material.value->'approval_ids') slot
                    LEFT JOIN public.state_kv decision
                        ON decision.key = 'operator-hil-decision:' || slot),
                'database_now', clock_timestamp()
            )
            FROM public.state_kv material
            LEFT JOIN public.state_kv current_sources ON
                current_sources.key = 'human_assignment:execution-current:' ||
                    (SELECT metadata.value #>> '{metadata,material_digest}'
                     FROM public.state_kv metadata
                     WHERE metadata.key = 'hil_park:' || (material.value->'approval_ids'->>0))
            LEFT JOIN public.state_kv assignment ON assignment.key = 'human_assignment:case:' ||
                ((material.value->>'action_json')::jsonb #>> '{params,case_id}')
            LEFT JOIN public.state_kv promotion ON promotion.key = 'action_promotion:' ||
                ((material.value->>'action_json')::jsonb ->> 'action_type')
            LEFT JOIN public.state_kv inverse_original ON inverse_original.key =
                'human_assignment:execution-material:' ||
                    (material.value #>> '{inverse,original_action_id}')
            LEFT JOIN public.state_kv inverse_intent ON inverse_intent.key =
                'isolated-executor:human-access:' || encode(sha256(convert_to(
                    '{"idempotency_key":' ||
                    to_json(material.value #>> '{inverse,original_idempotency_key}')::text ||
                    '}', 'UTF8')), 'hex') || ':' || 'intent'
            LEFT JOIN public.state_kv inverse_result ON inverse_result.key =
                replace(inverse_intent.key, ':' || 'intent', ':' || 'result')
            LEFT JOIN public.target_dispatch_fence fence ON fence.target_digest =
                'sha256:' || encode(sha256(convert_to('{"target_resource_ref":' ||
                    to_json((material.value->>'action_json')::jsonb
                        ->>'target_resource_ref')::text ||
                    '}', 'UTF8')), 'hex')
            WHERE action_id ~ '^[a-f0-9-]{36}$' AND action_digest ~ '^sha256:[a-f0-9]{64}$'
                AND material.key = 'human_assignment:execution-material:' || action_id
                AND (material.value->>'action_json')::jsonb->>'action_id' = action_id
                AND octet_length(material.value->>'action_json') <= 32768
                AND jsonb_array_length(material.value->'approval_ids') BETWEEN 1 AND 2
                AND action_digest = 'sha256:' || encode(
                    sha256(convert_to(material.value->>'action_json', 'UTF8')), 'hex')
        $$;
        REVOKE ALL ON FUNCTION fdai_executor_human_access_source(text, text) FROM PUBLIC;

        CREATE FUNCTION fdai_guard_human_access_material() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
        BEGIN
            IF starts_with(OLD.key, 'human_assignment:execution-material:') THEN
                IF TG_OP = 'DELETE' OR NEW IS DISTINCT FROM OLD THEN
                    RAISE EXCEPTION 'retained human access material is immutable';
                END IF;
            END IF;
            IF (starts_with(OLD.key, 'human_assignment:execution-closure:') OR
                starts_with(OLD.key, 'human_assignment:human-access-observation:'))
               AND (TG_OP = 'DELETE' OR NEW IS DISTINCT FROM OLD) THEN
                RAISE EXCEPTION
                    'retained human access release and observation evidence is immutable';
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER fdai_human_access_material_immutable BEFORE DELETE OR UPDATE
        ON state_kv FOR EACH ROW EXECUTE FUNCTION fdai_guard_human_access_material();

        CREATE FUNCTION fdai_guard_human_access_attempt() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
        DECLARE source_key text; target_key text;
        BEGIN
            source_key := CASE WHEN TG_OP='INSERT' THEN NEW.key ELSE OLD.key END;
            target_key := CASE WHEN TG_OP='DELETE' THEN OLD.key ELSE NEW.key END;
            IF starts_with(source_key, 'isolated-executor:human-access:') OR
               starts_with(target_key, 'isolated-executor:human-access:') THEN
                IF current_user <> 'fdai_executor' OR TG_OP <> 'INSERT' THEN
                    RAISE EXCEPTION 'only Executor may append immutable human access attempts';
                END IF;
            END IF;
            RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
        END $$;
        CREATE TRIGGER fdai_human_access_attempt_immutable BEFORE INSERT OR DELETE OR UPDATE
        ON state_kv FOR EACH ROW EXECUTE FUNCTION fdai_guard_human_access_attempt();
    """
    )


def downgrade() -> None:
    """Refuse to erase retained original execution history during rollback."""
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM state_kv
                       WHERE starts_with(key, 'human_assignment:execution-material:')) THEN
                RAISE EXCEPTION 'human access material remains; preserve history before rollback';
            END IF;
        END $$;
        DROP TRIGGER fdai_human_access_material_immutable ON state_kv;
        DROP FUNCTION fdai_guard_human_access_material();
        DROP TRIGGER fdai_human_access_attempt_immutable ON state_kv;
        DROP FUNCTION fdai_guard_human_access_attempt();
        DROP FUNCTION fdai_executor_human_access_source(text, text);
    """
    )
