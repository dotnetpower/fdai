"""ontology seed: initial ObjectType + LinkType rows

Revision ID: 20260705_0003
Revises: 20260705_0002
Create Date: 2026-07-05 00:00:02

Seeds the ontology metadata tables so downstream inserts into
``ontology_resource`` / ``ontology_link`` do not trip the FK references
declared in the base migration.

Rows here come from the design docs, not the runtime - the objective is
"deploy-time bootstrap that lets the first Inventory batch land without
FK violations", not "authoritative catalog":

- ``ontology_object_type`` - the four ontology entities documented in
  [`docs/roadmap/architecture/llm-strategy.md` § Ontology Foundation]:
  ``Resource``, ``Rule``, ``Signal``, ``Finding``.
- ``ontology_link_type`` - the P1-scoped LinkTypes whose ``from_type`` and
  ``to_type`` both resolve to one of the seeded ObjectTypes:
  ``contains`` / ``attached_to`` / ``depends_on`` (Resource↔Resource),
  ``resource_of`` (Signal→Resource), and ``precedes`` / ``follows``
  (Finding temporal). ``peered_with`` / ``routes_to`` are P3+ and are
  omitted so an adapter emitting them today opens a governance PR.
  The **Rule-dispatch links** (``applies_to`` → ResourceType,
  ``triggered_by`` → SignalType, ``evaluates`` → Property,
  ``remediates`` → ActionType) and ``overrides`` (Override → Rule)
  reference ObjectTypes that are NOT yet first-class rows - see
  [`docs/roadmap/architecture/llm-strategy.md` § Fork Extension] - so a schema-level
  seed for them belongs in the follow-up that promotes
  ``ResourceType`` / ``SignalType`` / ``ActionType`` / ``Override`` to
  ontology types. Seeding those links today would violate the FK on
  ``ontology_link_type.from_type`` / ``.to_type``.

The insert uses ``ON CONFLICT DO NOTHING`` so re-running the migration on
an already-seeded database is idempotent (matches the ``full_snapshot``
contract in
[`docs/roadmap/architecture/csp-neutrality.md` § 5]).

Full JSON definitions live in
``services/core-control-plane/src/fdai/shared/contracts/ontology/*.json``; the loaders under
``services/core-control-plane/src/fdai/rule_catalog/schema/`` remain the authoritative
runtime source. This migration only *bootstraps* the tables.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260705_0003"
down_revision: str | None = "20260705_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ---------------------------------------------------------------------------
# ObjectType seeds
# ---------------------------------------------------------------------------
# Each row uses ``{}::jsonb`` for `properties` because a full property map
# lives in the pydantic ontology models; the runtime seeds it. This
# migration only creates the presence-required rows.
_OBJECT_TYPES: tuple[tuple[str, str, str, str], ...] = (
    (
        "Resource",
        "1.0.0",
        "resource_id",
        "A cloud resource under governance; populated by the Inventory adapter.",
    ),
    (
        "Rule",
        "1.0.0",
        "id",
        "A deterministic control with an intent (applies_to, evaluates, remediates).",
    ),
    (
        "Signal",
        "1.0.0",
        "signal_id",
        "A typed observation (Activity Log line, drift diff, cost anomaly, canary result).",
    ),
    (
        "Finding",
        "1.0.0",
        "finding_id",
        "A rule match on a resource at a point in time; audited.",
    ),
)


# ---------------------------------------------------------------------------
# LinkType seeds (P1 scope)
# ---------------------------------------------------------------------------
# Columns match `ontology_link_type`:
#   name | version | from_type | to_type | cardinality | description
#
# Only LinkTypes whose from_type and to_type reference an already-seeded
# ObjectType are safe to insert here - the base migration declares FKs to
# `ontology_object_type.name`. Rule-dispatch links (`applies_to` →
# ResourceType, `triggered_by` → SignalType, `evaluates` → Property,
# `remediates` → ActionType) plus `overrides` (Override → Rule) are
# deferred until those ObjectTypes are promoted in a follow-up migration.
_LINK_TYPES: tuple[tuple[str, str, str, str, str, str], ...] = (
    (
        "contains",
        "1.0.0",
        "Resource",
        "Resource",
        "many_to_one",
        "Ownership / scope containment: subscription→resource-group→resource, "
        "VNet→subnet, cluster→node-pool. Recursive.",
    ),
    (
        "attached_to",
        "1.0.0",
        "Resource",
        "Resource",
        "many_to_one",
        "Lifetime-bound attachment: NIC→VM, disk→VM, private-endpoint→target.",
    ),
    (
        "depends_on",
        "1.0.0",
        "Resource",
        "Resource",
        "many_to_many",
        "Logical reference required for correct operation: ContainerApp→Key-Vault, "
        "managed-identity→app. Broken edges degrade the dependent.",
    ),
    (
        "resource_of",
        "1.0.0",
        "Signal",
        "Resource",
        "many_to_one",
        "Which resource a signal is about.",
    ),
    (
        "precedes",
        "1.0.0",
        "Finding",
        "Finding",
        "many_to_many",
        "Temporal ordering of correlated findings on one incident.",
    ),
    (
        "follows",
        "1.0.0",
        "Finding",
        "Finding",
        "many_to_many",
        "Reverse of `precedes`; kept explicit for query symmetry.",
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
    # bounding the delete to the exact names this migration wrote.
    seeded_link_names = ", ".join(f"'{r[0]}'" for r in _LINK_TYPES)
    seeded_object_names = ", ".join(f"'{r[0]}'" for r in _OBJECT_TYPES)
    op.execute(f"DELETE FROM ontology_link_type WHERE name IN ({seeded_link_names});")
    op.execute(
        "DELETE FROM ontology_object_type AS object_type "
        f"WHERE object_type.name IN ({seeded_object_names}) "
        "AND NOT EXISTS (SELECT 1 FROM ontology_link_type AS link_type "
        "WHERE link_type.from_type = object_type.name OR link_type.to_type = object_type.name);"
    )
