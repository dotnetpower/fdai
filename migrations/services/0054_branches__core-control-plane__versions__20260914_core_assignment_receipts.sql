-- Migration Revision: core_assignment_receipts_20260914
-- Down Revision: core_cost_governance_review_20260913
-- Owner: core-control-plane
-- Extracted SQL Blocks: 1

-- Statement 1
CREATE TABLE operator_assignment_receipt (
            proposal_ref TEXT PRIMARY KEY
                CHECK (proposal_ref ~ '^operator-proposal:iam:[0-9a-f]{64}$'),
            record JSONB NOT NULL CHECK (jsonb_typeof(record) = 'object'),
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        REVOKE ALL ON TABLE operator_assignment_receipt FROM PUBLIC;
        GRANT SELECT ON TABLE operator_assignment_receipt TO fdai_core;
        CREATE FUNCTION fdai_capture_assignment_receipt()
        RETURNS TRIGGER LANGUAGE plpgsql
        SET search_path = public, pg_temp
        AS $capture$
        BEGIN
            IF starts_with(NEW.key, 'operator-proposal:iam:') AND NEW.value ->> 'operation' IN
                ('assignments.create', 'assignments.submit', 'assignments.review') THEN
                IF current_user <> 'fdai_operator' THEN
                    RAISE EXCEPTION 'only Operator may record an assignment request';
                END IF;
                INSERT INTO public.operator_assignment_receipt(proposal_ref, record)
                VALUES (NEW.key, NEW.value);
            END IF;
            RETURN NEW;
        END;
        $capture$;
        CREATE TRIGGER assignment_receipt_capture AFTER INSERT ON state_kv
            FOR EACH ROW EXECUTE FUNCTION fdai_capture_assignment_receipt();
        CREATE FUNCTION fdai_guard_assignment_state()
        RETURNS TRIGGER LANGUAGE plpgsql
        SET search_path = public, pg_temp
        AS $guard$
        DECLARE
            source_key TEXT;
            target_key TEXT;
            request_field TEXT;
        BEGIN
            source_key := CASE WHEN TG_OP = 'INSERT' THEN NEW.key ELSE OLD.key END;
            target_key := CASE WHEN TG_OP = 'DELETE' THEN OLD.key ELSE NEW.key END;
            IF (starts_with(source_key, 'operator-handover-goal:') OR
                starts_with(target_key, 'operator-handover-goal:'))
               AND current_user <> 'fdai_operator' THEN
                RAISE EXCEPTION 'only Operator may write its handover goals';
            END IF;
            IF (starts_with(source_key, 'human_assignment:') OR
                starts_with(target_key, 'human_assignment:')) AND current_user <> 'fdai_core' THEN
                RAISE EXCEPTION 'only Core may write assignment state';
            END IF;
            IF TG_OP <> 'INSERT' AND starts_with(source_key, 'operator-proposal:iam:')
               AND OLD.value ->> 'operation' IN
                   ('assignments.create', 'assignments.submit', 'assignments.review') THEN
                IF TG_OP = 'DELETE' OR source_key <> target_key THEN
                    RAISE EXCEPTION 'assignment source identity is immutable';
                END IF;
                FOREACH request_field IN ARRAY ARRAY[
                    'family', 'operation', 'principal_id', 'idempotency_key', 'payload',
                    'kind', 'mode', 'proposal_id', 'request_digest', 'accepted_at'
                ] LOOP
                    IF OLD.value -> request_field IS DISTINCT FROM NEW.value -> request_field THEN
                        RAISE EXCEPTION 'assignment source request is immutable';
                    END IF;
                END LOOP;
            END IF;
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END;
        $guard$;
        CREATE TRIGGER assignment_state_guard BEFORE INSERT OR DELETE OR UPDATE ON state_kv
            FOR EACH ROW EXECUTE FUNCTION fdai_guard_assignment_state();
