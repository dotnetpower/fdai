"""persist exact ontology declaration releases

Revision ID: 20260801_0067
Revises: 20260731_0066
Create Date: 2026-08-01 00:00:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260801_0067"
down_revision: str | None = "20260731_0066"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Historical rows predate release digests. Keep them NULL rather than
    # assigning the migration-time release and fabricating replay provenance.
    op.execute(
        "ALTER TABLE ontology_resource ADD COLUMN type_version TEXT, ADD COLUMN catalog_digest TEXT"
    )
    op.execute(
        "ALTER TABLE ontology_link ADD COLUMN type_version TEXT, ADD COLUMN catalog_digest TEXT"
    )
    op.execute(
        "ALTER TABLE ontology_resource ADD CONSTRAINT ontology_resource_type_version_format "
        "CHECK (type_version IS NULL OR type_version ~ '^[0-9]+\\.[0-9]+\\.[0-9]+$'), "
        "ADD CONSTRAINT ontology_resource_catalog_digest_format "
        "CHECK (catalog_digest IS NULL OR catalog_digest ~ '^sha256:[a-f0-9]{64}$')"
    )
    op.execute(
        "ALTER TABLE ontology_link ADD CONSTRAINT ontology_link_type_version_format "
        "CHECK (type_version IS NULL OR type_version ~ '^[0-9]+\\.[0-9]+\\.[0-9]+$'), "
        "ADD CONSTRAINT ontology_link_catalog_digest_format "
        "CHECK (catalog_digest IS NULL OR catalog_digest ~ '^sha256:[a-f0-9]{64}$')"
    )
    op.execute(
        "ALTER TABLE ontology_resource ADD CONSTRAINT ontology_resource_type_ref_pair "
        "CHECK ((type_version IS NULL) = (catalog_digest IS NULL))"
    )
    op.execute(
        "ALTER TABLE ontology_link ADD CONSTRAINT ontology_link_type_ref_pair "
        "CHECK ((type_version IS NULL) = (catalog_digest IS NULL))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE ontology_link DROP COLUMN catalog_digest, DROP COLUMN type_version")
    op.execute("ALTER TABLE ontology_resource DROP COLUMN catalog_digest, DROP COLUMN type_version")
