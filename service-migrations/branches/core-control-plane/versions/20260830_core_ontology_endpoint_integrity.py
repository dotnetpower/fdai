"""Enforce ontology link endpoint integrity."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_ontology_endpoint_integrity_20260830"
down_revision: str | Sequence[str] | None = "core_catalog_lifecycle_20260829"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = ("ontology_link", "ontology_resource")
rollback = {
    "strategy": "drop-ontology-endpoint-foreign-keys",
    "restores": "core_catalog_lifecycle_20260829",
    "requires": "core-runtime-stopped",
}


def upgrade() -> None:
    """Reject existing or future dangling ontology links."""

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                  FROM ontology_link AS link
                  LEFT JOIN ontology_resource AS source
                    ON source.id = link.from_id
                  LEFT JOIN ontology_resource AS target
                    ON target.id = link.to_id
                 WHERE source.id IS NULL OR target.id IS NULL
            ) THEN
                RAISE EXCEPTION
                    'cannot enforce ontology endpoint integrity while dangling links exist';
            END IF;
        END
        $$;

        ALTER TABLE ontology_link
            ADD CONSTRAINT ontology_link_from_resource_fk
            FOREIGN KEY (from_id) REFERENCES ontology_resource(id)
            ON DELETE CASCADE NOT VALID;
        ALTER TABLE ontology_link
            ADD CONSTRAINT ontology_link_to_resource_fk
            FOREIGN KEY (to_id) REFERENCES ontology_resource(id)
            ON DELETE CASCADE NOT VALID;
        ALTER TABLE ontology_link
            VALIDATE CONSTRAINT ontology_link_from_resource_fk;
        ALTER TABLE ontology_link
            VALIDATE CONSTRAINT ontology_link_to_resource_fk;
        """
    )


def downgrade() -> None:
    """Remove endpoint foreign keys without changing ontology records."""

    op.execute(
        """
        ALTER TABLE ontology_link
            DROP CONSTRAINT IF EXISTS ontology_link_to_resource_fk;
        ALTER TABLE ontology_link
            DROP CONSTRAINT IF EXISTS ontology_link_from_resource_fk;
        """
    )
