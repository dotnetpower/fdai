"""Store one installation-bound Trial record with compare-and-set observations.

The Trial window must survive restarts and upgrades without ever restarting, so it
lives in a single durable row rather than in process memory or a rendered config. Two
constraints carry that guarantee in the schema instead of in caller discipline:

- `singleton` is a fixed-value primary key, so one installation holds exactly one
  record and a concurrent writer cannot insert a second, fresher window.
- `revision` advances on every observation and is the compare-and-set token. A writer
  that lost a race updates zero rows and must re-read rather than overwrite.

`activated_at` is immutable by trigger. An upgrade, a restart, or a replica with a
stale read therefore cannot extend the window, which is the property the keyless Trial
depends on. Core reads and writes the row; no other role receives access.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_licensing_trial_20260929"
down_revision: str | Sequence[str] | None = "core_operational_evidence_source_functions_20260929"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
migration_owner = "core-control-plane"
owned_tables: tuple[str, ...] = ("licensing_trial",)
rollback = {
    "strategy": "drop-licensing-trial-singleton",
    "restores": "core_operational_evidence_source_functions_20260929",
    "requires": "core-stopped",
}


def upgrade() -> None:
    """Create the singleton Trial row, its immutability trigger, and Core's grants."""
    op.execute(
        """
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
        """
    )


def downgrade() -> None:
    """Drop the Trial row, its trigger, and the immutability function."""
    op.execute(
        """
        DROP TRIGGER licensing_trial_immutable_activation ON licensing_trial;
        DROP FUNCTION fdai_licensing_trial_immutable_activation();
        DROP TABLE licensing_trial;
        """
    )
