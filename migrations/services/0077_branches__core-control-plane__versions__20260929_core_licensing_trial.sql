-- Migration Revision: core_licensing_trial_20260929
-- Down Revision: core_operational_evidence_source_functions_20260929
-- Owner: core-control-plane
-- Extracted SQL Blocks: 1

-- Statement 1
CREATE TABLE licensing_trial (
            singleton BOOLEAN PRIMARY KEY DEFAULT TRUE,
            installation_binding TEXT NOT NULL,
            deployment_binding TEXT NOT NULL,
            activated_at TIMESTAMPTZ NOT NULL,
            last_observed_at TIMESTAMPTZ NOT NULL,
            revision BIGINT NOT NULL,
            clock_blocked BOOLEAN NOT NULL,
            CONSTRAINT licensing_trial_is_singleton CHECK (singleton),
            CONSTRAINT licensing_trial_installation_digest
                CHECK (installation_binding ~ '^[0-9a-f]{64}$'),
            CONSTRAINT licensing_trial_deployment_digest
                CHECK (deployment_binding ~ '^[0-9a-f]{64}$'),
            CONSTRAINT licensing_trial_revision_positive CHECK (revision >= 1),
            CONSTRAINT licensing_trial_observation_not_before_activation
                CHECK (last_observed_at >= activated_at)
        );

        CREATE FUNCTION fdai_licensing_trial_immutable_activation()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $$
        BEGIN
            IF NEW.activated_at <> OLD.activated_at
                OR NEW.installation_binding <> OLD.installation_binding
                OR NEW.deployment_binding <> OLD.deployment_binding
            THEN
                RAISE EXCEPTION 'Trial activation and bindings are immutable';
            END IF;
            IF NEW.revision <= OLD.revision THEN
                RAISE EXCEPTION 'Trial revision must advance';
            END IF;
            IF OLD.clock_blocked AND NOT NEW.clock_blocked THEN
                RAISE EXCEPTION 'Trial clock denial is sticky';
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE TRIGGER licensing_trial_immutable_activation
            BEFORE UPDATE ON licensing_trial
            FOR EACH ROW
            EXECUTE FUNCTION fdai_licensing_trial_immutable_activation();

        REVOKE ALL ON TABLE licensing_trial FROM PUBLIC;
        GRANT SELECT, INSERT, UPDATE ON TABLE licensing_trial TO fdai_core;
