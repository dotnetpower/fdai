"""align current ontology relationship direction

Revision ID: 20260808_0078
Revises: 20260806_0077
Create Date: 2026-08-08 00:00:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260808_0078"
down_revision: str | None = "20260806_0077"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The ontology instance tables are a rebuildable current-state read model.
    # Remove only links whose stored endpoints prove the old semantic direction.
    # Unrelated projections and exact release pins remain intact.
    op.execute(
        """
        DELETE FROM ontology_link AS link
        USING ontology_resource AS child, ontology_resource AS parent
        WHERE link.link_type = 'contains'
          AND link.from_id = child.id
          AND link.to_id = parent.id
          AND child.object_type = 'Resource'
          AND parent.object_type = 'Resource'
          AND child.properties ->> 'parent_id' = parent.id;

        DELETE FROM ontology_link AS link
        USING ontology_resource AS source
        WHERE link.link_type = 'attached_to'
          AND link.from_id = source.id
          AND source.object_type = 'Resource'
          AND source.properties ->> 'type' = 'compute.vm';

        UPDATE ontology_link_type
        SET version = '2.0.0',
            cardinality = 'one_to_many',
            description = 'Ownership / scope containment from parent to child; '
                || 'recursive traversal walks descendants.'
        WHERE name = 'contains';
        """
    )


def downgrade() -> None:
    # Deleted observed links cannot be reconstructed by a schema downgrade. The
    # prior runtime rebuilds them from its authoritative inventory source.
    op.execute(
        """
        UPDATE ontology_link_type
        SET version = '1.0.0',
            cardinality = 'many_to_one',
            description = 'Ownership / scope containment; '
                || 'recursive traversal walks the whole chain.'
        WHERE name = 'contains';
        """
    )
