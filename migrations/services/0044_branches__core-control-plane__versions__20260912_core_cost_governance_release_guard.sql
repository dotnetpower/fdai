-- Migration Revision: core_cost_governance_release_guard_20260912
-- Down Revision: core_cost_governance_w7_lifecycle_20260912
-- Owner: core-control-plane
-- Extracted SQL Blocks: 1

-- Statement 1
DO $repair$
        DECLARE
            function_identity REGPROCEDURE := (
                'public.fdai_register_cost_governance_release('
                'text,text,text,text,text,text,text,text,text,text,'
                'text,text,bigint,text,jsonb)'
            )::REGPROCEDURE;
            function_definition TEXT;
            broken_expression TEXT := (
                'receipt.payload -> ''revision_pin'' - ''activation_revision'''
            );
            fixed_expression TEXT := (
                '(receipt.payload -> ''revision_pin'') - ''activation_revision'''
            );
            occurrence_count INTEGER;
        BEGIN
            SELECT pg_get_functiondef(function_identity)
              INTO function_definition;
            occurrence_count := (
                length(function_definition)
                - length(replace(function_definition, broken_expression, ''))
            ) / length(broken_expression);
            IF occurrence_count <> 1 OR position(fixed_expression IN function_definition) > 0 THEN
                RAISE EXCEPTION 'Cost Governance release guard repair source mismatch';
            END IF;
            EXECUTE replace(function_definition, broken_expression, fixed_expression);
        END;
        $repair$;
