-- Migration Revision: operator_authentication_receipts_20260929
-- Down Revision: operator_workflow_authoring_20260929
-- Owner: operator-service
-- Extracted SQL Blocks: 1

-- Statement 1
CREATE TABLE operator_authentication_receipt (
            receipt_digest TEXT NOT NULL CHECK (receipt_digest ~ '^sha256:[0-9a-f]{64}$'),
            request_id TEXT NOT NULL CHECK (char_length(request_id) BETWEEN 1 AND 256),
            principal_id TEXT NOT NULL CHECK (char_length(principal_id) BETWEEN 1 AND 256),
            receipt JSONB NOT NULL CHECK (jsonb_typeof(receipt) = 'object'),
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (receipt_digest, request_id)
        );

        CREATE FUNCTION fdai_operator_authentication_receipt_writer()
        RETURNS TRIGGER LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $writer$
        BEGIN
            IF current_user <> 'fdai_operator' THEN
                RAISE EXCEPTION 'only the Operator runtime may retain authentication receipts';
            END IF;
            RETURN NEW;
        END;
        $writer$;
        CREATE FUNCTION fdai_operator_authentication_receipt_immutable()
        RETURNS TRIGGER LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $immutable$
        BEGIN
            RAISE EXCEPTION 'Operator authentication receipts are immutable';
        END;
        $immutable$;
        REVOKE ALL ON FUNCTION fdai_operator_authentication_receipt_writer() FROM PUBLIC;
        REVOKE ALL ON FUNCTION fdai_operator_authentication_receipt_immutable() FROM PUBLIC;
        CREATE TRIGGER operator_authentication_receipt_writer
            BEFORE INSERT ON operator_authentication_receipt
            FOR EACH ROW EXECUTE FUNCTION fdai_operator_authentication_receipt_writer();
        CREATE TRIGGER operator_auth_receipt_update_immutable
            BEFORE UPDATE ON operator_authentication_receipt
            FOR EACH ROW EXECUTE FUNCTION fdai_operator_authentication_receipt_immutable();
        CREATE TRIGGER operator_auth_receipt_delete_immutable
            BEFORE DELETE ON operator_authentication_receipt
            FOR EACH ROW EXECUTE FUNCTION fdai_operator_authentication_receipt_immutable();

        REVOKE ALL PRIVILEGES ON TABLE operator_authentication_receipt FROM PUBLIC, fdai_operator;
        GRANT INSERT ON TABLE operator_authentication_receipt TO fdai_operator;
