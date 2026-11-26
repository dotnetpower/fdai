"""process ontology seed: Process ObjectType + targets / advances LinkTypes

Revision ID: 20260709_0001
Revises: 20260708_0008
Create Date: 2026-07-09

Promotes the process-automation ontology additions to first-class seeded
rows so a Process run and its runtime links can land without tripping the
FK references declared in the base migration
(``ontology_resource.object_type`` -> ``ontology_object_type.name`` and
``ontology_link.link_type`` -> ``ontology_link_type.name``).

Rows come from the design doc, not the runtime - the objective is
"deploy-time bootstrap that lets the first Process run land without FK
violations", not "authoritative catalog". Full definitions live in
``rule-catalog/vocabulary/object-types/Process.yaml`` and
``rule-catalog/vocabulary/link-types/{targets,advances}.yaml``; the
loaders under ``services/core-control-plane/src/fdai/rule_catalog/schema/`` remain the authoritative
runtime source. See ``docs/roadmap/decisioning/process-automation.md`` 3.

Both ``targets`` (Process -> Resource) and ``advances`` (Process ->
Finding) resolve to ObjectTypes seeded here or in the base ontology seed
(``Resource`` / ``Finding``), so the FK on
``ontology_link_type.from_type`` / ``.to_type`` holds.

The insert uses ``ON CONFLICT DO NOTHING`` so re-running the migration on
an already-seeded database is idempotent.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260709_0001"
down_revision: str | None = "20260708_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ---------------------------------------------------------------------------
# ObjectType seed
# ---------------------------------------------------------------------------
# ``{}::jsonb`` for `properties` because the full property map lives in the
# pydantic ontology model + the vocabulary YAML; this migration only
# creates the presence-required row.
_OBJECT_TYPES: tuple[tuple[str, str, str, str], ...] = (
    (
        "Process",
        "1.0.0",
        "id",
        "Runtime instance and state of one Workflow run over a target Resource.",
    ),
)


# ---------------------------------------------------------------------------
# LinkType seeds
# ---------------------------------------------------------------------------
# Columns match `ontology_link_type`:
#   name | version | from_type | to_type | cardinality | description
#
# Both endpoints resolve to a seeded ObjectType: `Process` (this
# migration) plus `Resource` / `Finding` (the base ontology seed).
_LINK_TYPES: tuple[tuple[str, str, str, str, str, str], ...] = (
    (
        "targets",
        "1.0.0",
        "Process",
        "Resource",
        "many_to_one",
        "The primary Resource a Process operates on.",
    ),
    (
        "advances",
        "1.0.0",
        "Process",
        "Finding",
        "many_to_many",
        "The ordered Findings a Process advanced through during its run.",
    ),
)


def upgrade() -> None:
    for name, version, key_field, description in _OBJECT_TYPES:
        op.execute(
            """
            INSERT INTO ontology_object_type
                (name, version, key_field, properties, description)
            VALUES (:name, :version, :key_field, '{}'::jsonb, :description)
            ON CONFLICT (name) DO NOTHING;
            """.replace(":name", f"'{name}'")
            .replace(":version", f"'{version}'")
            .replace(":key_field", f"'{key_field}'")
            .replace(":description", f"'{description}'")
        )

    for name, version, from_type, to_type, cardinality, description in _LINK_TYPES:
        op.execute(
            """
            INSERT INTO ontology_link_type
                (name, version, from_type, to_type, cardinality, description)
            VALUES (:name, :version, :from_type, :to_type, :cardinality, :description)
            ON CONFLICT (name) DO NOTHING;
            """.replace(":name", f"'{name}'")
            .replace(":version", f"'{version}'")
            .replace(":from_type", f"'{from_type}'")
            .replace(":to_type", f"'{to_type}'")
            .replace(":cardinality", f"'{cardinality}'")
            .replace(":description", f"'{description}'")
        )


def downgrade() -> None:
    # Remove only the seeded rows; leave user-authored additions intact by
    # bounding the delete to the exact names this migration wrote. Links
    # first so the ObjectType delete does not trip the link FK.
    seeded_link_names = ", ".join(f"'{r[0]}'" for r in _LINK_TYPES)
    seeded_object_names = ", ".join(f"'{r[0]}'" for r in _OBJECT_TYPES)
    op.execute(f"DELETE FROM ontology_link_type WHERE name IN ({seeded_link_names});")
    op.execute(
        "DELETE FROM ontology_object_type AS object_type "
        f"WHERE object_type.name IN ({seeded_object_names}) "
        "AND NOT EXISTS (SELECT 1 FROM ontology_link_type AS link_type "
        "WHERE link_type.from_type = object_type.name OR link_type.to_type = object_type.name);"
    )
