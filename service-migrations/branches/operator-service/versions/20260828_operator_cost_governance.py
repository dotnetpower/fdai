"""Create server-owned Cost Governance access policy and read grants."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "operator_cost_governance_20260828"
down_revision: str | Sequence[str] | None = "operator_console_evidence_reads_20260827"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "operator-service"
owned_tables = ("cost_access_grant", "cost_disclosure_ceiling")
rollback = {
    "strategy": "drop-cost-access-after-operator-stopped",
    "restores": "operator_console_evidence_reads_20260827",
    "requires": "operator-cost-governance-routes-stopped",
}


def upgrade() -> None:
    """Create revisioned per-user grants and a deployment disclosure ceiling."""

    op.execute(
        """
        CREATE TABLE cost_access_grant (
            grant_id TEXT NOT NULL CHECK (char_length(grant_id) BETWEEN 1 AND 256),
            principal_id TEXT NOT NULL CHECK (char_length(principal_id) BETWEEN 1 AND 256),
            revision BIGINT NOT NULL CHECK (revision >= 0),
            purpose TEXT NOT NULL CHECK (char_length(purpose) BETWEEN 1 AND 128),
            scopes JSONB NOT NULL CHECK (jsonb_typeof(scopes) = 'array'),
            disclosure JSONB NOT NULL CHECK (jsonb_typeof(disclosure) = 'object'),
            effective_at TIMESTAMPTZ NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            source_authority TEXT NOT NULL
                CHECK (char_length(source_authority) BETWEEN 1 AND 256),
            PRIMARY KEY (grant_id, revision),
            CHECK (effective_at < expires_at)
        );
        CREATE INDEX cost_access_grant_principal_idx
            ON cost_access_grant (principal_id, purpose, revision DESC);

        CREATE TABLE cost_disclosure_ceiling (
            singleton BOOLEAN NOT NULL DEFAULT TRUE CHECK (singleton),
            revision BIGINT NOT NULL CHECK (revision >= 0),
            disclosure JSONB NOT NULL CHECK (jsonb_typeof(disclosure) = 'object'),
            effective_at TIMESTAMPTZ NOT NULL,
            source_authority TEXT NOT NULL
                CHECK (char_length(source_authority) BETWEEN 1 AND 256),
            PRIMARY KEY (singleton, revision)
        );

        REVOKE ALL PRIVILEGES ON TABLE
            cost_access_grant,
            cost_disclosure_ceiling,
            vertical_package_activation,
            cost_observation
        FROM PUBLIC, fdai_operator;
        GRANT SELECT ON TABLE
            cost_access_grant,
            cost_disclosure_ceiling,
            vertical_package_activation,
            cost_observation
        TO fdai_operator;
        """
    )


def downgrade() -> None:
    """Remove package access policy without deleting retained Core cost evidence."""

    op.execute(
        """
        REVOKE SELECT ON TABLE vertical_package_activation, cost_observation
            FROM fdai_operator;
        DROP TABLE cost_disclosure_ceiling;
        DROP TABLE cost_access_grant;
        """
    )
