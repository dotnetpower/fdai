"""Retain an original full grant and its acceptance audit without touching Trial state."""

from alembic import op

revision = "core_accepted_entitlement_20261021"
down_revision = "core_canary_sequence_index_20261021"
branch_labels = None
depends_on = None
migration_owner = "core-control-plane"
owned_tables = ("licensing_accepted_entitlement", "licensing_entitlement_acceptance_audit")
rollback = {
    "strategy": "retain-accepted-entitlement-until-explicit-empty-rollback",
    "restores": "core_canary_sequence_index_20261021",
    "requires": "core-stopped-and-no-retained-entitlements",
}


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE licensing_accepted_entitlement (
            installation_binding TEXT NOT NULL CHECK (installation_binding ~ '^[0-9a-f]{64}$'),
            deployment_binding TEXT NOT NULL CHECK (deployment_binding ~ '^[0-9a-f]{64}$'),
            token_value TEXT NOT NULL CHECK (octet_length(token_value) BETWEEN 1 AND 8192),
            token_digest TEXT NOT NULL CHECK (token_digest ~ '^[0-9a-f]{64}$'),
            acceptance_id TEXT NOT NULL UNIQUE CHECK (acceptance_id ~ '^[0-9a-f]{64}$'),
            accepted_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (installation_binding, deployment_binding),
            UNIQUE (installation_binding, deployment_binding, acceptance_id, token_digest)
        );
        CREATE TABLE licensing_entitlement_acceptance_audit (
            acceptance_id TEXT PRIMARY KEY,
            installation_binding TEXT NOT NULL,
            deployment_binding TEXT NOT NULL,
            token_digest TEXT NOT NULL,
            accepted_at TIMESTAMPTZ NOT NULL,
            actor TEXT NOT NULL CHECK (actor = 'fdai.licensing-owner.import'),
            FOREIGN KEY (installation_binding, deployment_binding, acceptance_id, token_digest)
                REFERENCES licensing_accepted_entitlement
                (installation_binding, deployment_binding, acceptance_id, token_digest)
        );
        REVOKE ALL ON TABLE licensing_accepted_entitlement FROM PUBLIC;
        REVOKE ALL ON TABLE licensing_entitlement_acceptance_audit FROM PUBLIC;
        GRANT SELECT, INSERT ON TABLE licensing_accepted_entitlement TO fdai_core;
        GRANT SELECT, INSERT ON TABLE licensing_entitlement_acceptance_audit TO fdai_core;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM licensing_accepted_entitlement)
               OR EXISTS (SELECT 1 FROM licensing_entitlement_acceptance_audit) THEN
                RAISE EXCEPTION 'retained entitlement acceptance blocks schema rollback';
            END IF;
        END;
        $$;
        DROP TABLE licensing_entitlement_acceptance_audit;
        DROP TABLE licensing_accepted_entitlement;
        """
    )
