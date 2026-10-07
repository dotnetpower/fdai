"""Select reviewed LinkType query sides for one admitted relation.

A relation sense selects LinkTypes only through their reviewed ``semantic_traits``,
and the subject position selects the stored query side. Stored direction is
never rewritten, and a LinkType without a reviewed trait is reported instead of
being guessed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from fdai_service_contracts.ontology_query import OntologyQueryPlan, QueryNodeKind

from .semantic_reasoning_form import (
    RelationReach,
    RelationScope,
    RelationSense,
    SubjectPosition,
)

TRANSITIVE_MAX_DEPTH = 5

# Reviewed closed mapping from a relation sense to one LinkType semantic trait.
# ``composition`` has no reviewed trait yet, so it selects nothing.
RECIPROCAL_TRAIT = "reciprocal"
SENSE_TRAITS: Mapping[RelationSense, str | None] = {
    RelationSense.CONTAINMENT: "containment",
    RelationSense.ATTACHMENT: "attachment",
    RelationSense.DEPENDENCY: "dependency",
    RelationSense.CONNECTIVITY: "connectivity",
    RelationSense.TRAFFIC: "traffic",
    RelationSense.CLASSIFICATION: "classification",
    RelationSense.COMPOSITION: None,
    RelationSense.OWNERSHIP: "ownership",
    RelationSense.AUTHORIZATION: "authorization",
    RelationSense.EVIDENCE: "evidence",
}

Direction = Literal["outgoing", "incoming"]


@dataclass(frozen=True, slots=True, order=True)
class RelationSide:
    """One stored LinkType side read from an anchor of ``anchor_type``."""

    link_type: str
    direction: Direction
    anchor_type: str
    endpoint_type: str
    role: str | None
    max_depth: int


@dataclass(frozen=True, slots=True)
class RelationSelection:
    """Every applicable side plus the LinkTypes excluded for lack of a trait."""

    sides: tuple[RelationSide, ...]
    unmapped_link_types: tuple[str, ...]
    intransitive_link_types: tuple[str, ...]


def link_descriptors(descriptors: tuple[dict[str, Any], ...]) -> tuple[Mapping[str, Any], ...]:
    """Return manifest LinkType descriptors in stable name order."""

    return tuple(
        sorted(
            (item for item in descriptors if item.get("kind") == "link"),
            key=lambda item: str(item.get("name")),
        )
    )


def select_relation_sides(
    descriptors: tuple[dict[str, Any], ...],
    *,
    anchor_type: str,
    sense: RelationSense | None,
    scope: RelationScope,
    position: SubjectPosition,
    reach: RelationReach,
) -> RelationSelection:
    """Return exact query sides for one relation atom of an anchor type.

    ``one_sense`` requires the trait mapped from ``sense``. ``all_kinds`` reads
    every LinkType side of the anchor type, mapped or not, so no relationship
    kind is silently omitted. ``transitive`` reach keeps only LinkTypes declared
    transitive between one endpoint type and reports the others.
    """

    if scope is RelationScope.ONE_SENSE and sense is None:
        raise ValueError("a one-sense relation requires a sense")
    trait = SENSE_TRAITS[sense] if scope is RelationScope.ONE_SENSE and sense else None
    sides: list[RelationSide] = []
    unmapped: list[str] = []
    intransitive: list[str] = []
    for descriptor in link_descriptors(descriptors):
        name = descriptor.get("name")
        from_type = descriptor.get("from_type")
        to_type = descriptor.get("to_type")
        if not (isinstance(name, str) and isinstance(from_type, str) and isinstance(to_type, str)):
            continue
        if anchor_type not in {from_type, to_type}:
            continue
        traits = _traits(descriptor)
        if scope is RelationScope.ONE_SENSE:
            if not traits:
                unmapped.append(name)
                continue
            if trait is None or trait not in traits:
                continue
        transitive = descriptor.get("is_transitive") is True and from_type == to_type
        if reach is RelationReach.TRANSITIVE and not transitive:
            intransitive.append(name)
            continue
        depth = TRANSITIVE_MAX_DEPTH if reach is RelationReach.TRANSITIVE else 1
        forward_role = _role(descriptor.get("forward_role"))
        reverse_role = _role(descriptor.get("reverse_role"))
        # A reciprocal LinkType, such as peering, has no direction, so a stated direction
        # never narrows it to one stored side.
        side = SubjectPosition.EITHER if RECIPROCAL_TRAIT in traits else position
        if side in {SubjectPosition.SOURCE, SubjectPosition.EITHER} and from_type == anchor_type:
            sides.append(RelationSide(name, "outgoing", anchor_type, to_type, forward_role, depth))
        if side in {SubjectPosition.TARGET, SubjectPosition.EITHER} and to_type == anchor_type:
            sides.append(
                RelationSide(name, "incoming", anchor_type, from_type, reverse_role, depth)
            )
    return RelationSelection(
        sides=tuple(sorted(set(sides))),
        unmapped_link_types=tuple(sorted(set(unmapped))),
        intransitive_link_types=tuple(sorted(set(intransitive))),
    )


def traversal_roots(plans: Sequence[OntologyQueryPlan]) -> set[str]:
    """Return the exact anchor identity each relationship traversal starts from."""

    roots: set[str] = set()
    for plan in plans:
        by_id = {node.node_id: node for node in plan.nodes}
        for node in plan.nodes:
            if node.kind is not QueryNodeKind.RELATIONSHIP_TRAVERSAL:
                continue
            source = by_id.get(node.depends_on[0]) if node.depends_on else None
            definition = (
                (source.arguments.get("definition") or {})
                if source is not None and source.kind is QueryNodeKind.OBJECT_SET
                else {}
            )
            identities = [
                item.get("equals")
                for item in definition.get("predicates") or ()
                if item.get("property") == "id" and item.get("operator") == "equals"
            ]
            roots.add(str(identities[0]) if len(identities) == 1 else "<unbound>")
    return roots


def _traits(descriptor: Mapping[str, Any]) -> frozenset[str]:
    raw = descriptor.get("semantic_traits")
    if not isinstance(raw, (list, tuple)):
        return frozenset()
    return frozenset(item for item in raw if isinstance(item, str))


def _role(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def containment_scope_sides(
    descriptors: Sequence[Mapping[str, Any]], *, depth: int
) -> set[tuple[str, str, Any]]:
    """Return every transitive Resource containment side a scope reads, at ``depth``."""

    trait = SENSE_TRAITS[RelationSense.CONTAINMENT]
    return {
        (str(item.get("name")), "outgoing", depth)
        for item in descriptors
        if item.get("kind") == "link"
        and trait in set(item.get("semantic_traits") or ())
        and item.get("is_transitive") is True
        and item.get("from_type") == item.get("to_type") == "Resource"
    }


__all__ = [
    "RECIPROCAL_TRAIT",
    "SENSE_TRAITS",
    "TRANSITIVE_MAX_DEPTH",
    "containment_scope_sides",
    "RelationSelection",
    "RelationSide",
    "link_descriptors",
    "select_relation_sides",
    "traversal_roots",
]
