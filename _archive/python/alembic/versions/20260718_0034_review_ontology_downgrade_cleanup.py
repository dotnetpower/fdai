"""review ontology downgrade cleanup

Revision ID: 20260718_0034
Revises: 20260717_0033
Create Date: 2026-07-18 00:00:00+00:00

The review ontology seed predates runtime instance projection. A database that
contains projected ReviewCase/ReviewCheck resources cannot downgrade that seed
until dependent findings, links, and resources are removed. This append-only
corrective revision performs that cleanup before Alembic reaches the original
seed downgrade.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260718_0034"
down_revision: str | None = "20260717_0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REVIEW_OBJECT_TYPES = (
    "ReviewCase",
    "ReviewCheck",
    "EvidenceArtifact",
    "Principal",
    "Approval",
    "Decision",
)

_REVIEW_LINK_TYPES = (
    "runs_review",
    "scoped_to",
    "contains_check",
    "supported_by",
    "assigned_to",
    "has_approval",
    "granted_by",
    "resolved_by",
    "based_on",
    "produces_finding",
)


def upgrade() -> None:
    """No forward schema change; cleanup is needed only during downgrade."""


def downgrade() -> None:
    object_types = ", ".join(f"'{value}'" for value in _REVIEW_OBJECT_TYPES)
    link_types = ", ".join(f"'{value}'" for value in _REVIEW_LINK_TYPES)
    op.execute(
        "DELETE FROM ontology_finding WHERE resource_ref IN "
        f"(SELECT id FROM ontology_resource WHERE object_type IN ({object_types}));"
    )
    op.execute(
        "DELETE FROM ontology_link WHERE "
        f"link_type IN ({link_types}) OR "
        "from_id IN "
        f"(SELECT id FROM ontology_resource WHERE object_type IN ({object_types})) OR "
        "to_id IN "
        f"(SELECT id FROM ontology_resource WHERE object_type IN ({object_types}));"
    )
    op.execute(f"DELETE FROM ontology_resource WHERE object_type IN ({object_types});")
