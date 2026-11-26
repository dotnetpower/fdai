"""review ontology: governed review ObjectTypes and LinkTypes

Revision ID: 20260713_0013
Revises: 20260713_0012
Create Date: 2026-07-13 00:00:02

The YAML vocabulary remains authoritative for full properties and flags. This
migration creates the metadata rows required by runtime instance foreign keys.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260713_0013"
down_revision: str | None = "20260713_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OBJECT_TYPES: tuple[tuple[str, str], ...] = (
    ("ReviewCase", "Current aggregate state of one governed review."),
    ("ReviewCheck", "One bounded requirement evaluated during a review."),
    ("EvidenceArtifact", "Immutable metadata for externally held evidence."),
    ("Principal", "Stable reference to a user, group, service, or agent principal."),
    ("Approval", "Action-bound approval request and current decision state."),
    ("Decision", "Recorded outcome of a governed review decision point."),
)

_LINK_TYPES: tuple[tuple[str, str, str, str, str], ...] = (
    ("runs_review", "Process", "ReviewCase", "one_to_one", "Review run aggregate."),
    ("scoped_to", "ReviewCase", "Resource", "many_to_one", "Reviewed scope."),
    ("contains_check", "ReviewCase", "ReviewCheck", "one_to_many", "Review check."),
    ("supported_by", "ReviewCheck", "EvidenceArtifact", "many_to_many", "Evidence."),
    ("assigned_to", "ReviewCheck", "Principal", "many_to_one", "Accountable principal."),
    ("has_approval", "ReviewCase", "Approval", "one_to_many", "Approval request."),
    ("granted_by", "Approval", "Principal", "many_to_one", "Approving principal."),
    ("resolved_by", "ReviewCase", "Decision", "one_to_many", "Review decision."),
    ("based_on", "Decision", "EvidenceArtifact", "many_to_many", "Decision evidence."),
    ("produces_finding", "ReviewCheck", "Finding", "one_to_many", "Failed check finding."),
)


def upgrade() -> None:
    for name, description in _OBJECT_TYPES:
        op.execute(
            "INSERT INTO ontology_object_type "
            "(name, version, key_field, properties, description) "
            f"VALUES ('{name}', '1.0.0', 'id', '{{}}'::jsonb, "
            f"'{description.replace(chr(39), chr(39) * 2)}') "
            "ON CONFLICT (name) DO NOTHING;"
        )
    for name, from_type, to_type, cardinality, description in _LINK_TYPES:
        op.execute(
            "INSERT INTO ontology_link_type "
            "(name, version, from_type, to_type, cardinality, description) "
            f"VALUES ('{name}', '1.0.0', '{from_type}', '{to_type}', "
            f"'{cardinality}', '{description.replace(chr(39), chr(39) * 2)}') "
            "ON CONFLICT (name) DO NOTHING;"
        )


def downgrade() -> None:
    link_names = ", ".join(f"'{item[0]}'" for item in _LINK_TYPES)
    object_names = ", ".join(f"'{item[0]}'" for item in _OBJECT_TYPES)
    op.execute(f"DELETE FROM ontology_link_type WHERE name IN ({link_names});")
    op.execute(
        "DELETE FROM ontology_object_type AS object_type "
        f"WHERE object_type.name IN ({object_names}) "
        "AND NOT EXISTS (SELECT 1 FROM ontology_link_type AS link_type "
        "WHERE link_type.from_type = object_type.name OR link_type.to_type = object_type.name);"
    )
