"""Identity operand provenance checks for current-path model plans."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from fdai_service_contracts.ontology_query import OntologyQueryPlan, QueryNodeKind

_IDENTITY_PROPERTIES = frozenset({"id", "name", "display_name"})
_IDENTITY_KEYS = frozenset(
    {
        "object_ids",
        "root_ids",
        "resource_id",
        "target_resource_id",
        "incident_id",
        "row_ids",
    }
)


@dataclass(frozen=True, slots=True)
class IdentityBindingReceipt:
    """One accepted source for an identity literal in a current-path plan."""

    source: str
    lookup: str
    identity: str
    span: tuple[int, int] | None = None


def unproven_identity_operands(
    plan: OntologyQueryPlan,
    *,
    utterance: str,
    context: Sequence[str] = (),
    receipts: Sequence[IdentityBindingReceipt] = (),
) -> tuple[str, ...]:
    """Return identity literals that are not grounded in text, context, handle, or receipt."""

    allowed = set(_identity_spans(utterance))
    for item in context:
        allowed.update(_identity_spans(item))
    allowed.update(receipt.identity for receipt in receipts)
    found = sorted(
        {operand for node in plan.nodes for operand in _node_operands(node.kind, node.arguments)}
    )
    return tuple(operand for operand in found if operand not in allowed)


def _identity_spans(text: str) -> tuple[str, ...]:
    # This is not meaning extraction: it only accepts exact literal presence for a plan operand.
    return tuple(
        token.strip(".,;:!?()[]{}\"'") for token in text.split() if token.strip(".,;:!?()[]{}\"'")
    )


def _node_operands(kind: QueryNodeKind, value: Mapping[str, object]) -> tuple[str, ...]:
    found: list[str] = []
    if kind is QueryNodeKind.OBJECT_SET:
        definition = value.get("definition")
        if isinstance(definition, Mapping):
            for key in ("object_ids", "root_ids"):
                found.extend(_identity_values(definition.get(key)))
            for predicate in definition.get("predicates", ()):
                if isinstance(predicate, Mapping):
                    found.extend(_predicate_operands(predicate))
    elif kind is QueryNodeKind.FUNCTION:
        arguments = value.get("arguments")
        if isinstance(arguments, Mapping):
            for key, child in arguments.items():
                if key in _IDENTITY_KEYS:
                    found.extend(_identity_values(child))
    return tuple(found)


def _predicate_operands(value: Mapping[str, object]) -> tuple[str, ...]:
    property_name = value.get("property")
    operator = value.get("operator")
    found: list[str] = []
    if property_name in _IDENTITY_PROPERTIES and operator in {"equals", "in"}:
        equals = value.get("equals")
        if isinstance(equals, str):
            found.append(equals)
        values = value.get("values")
        if isinstance(values, list):
            found.extend(item for item in values if isinstance(item, str))
    return tuple(found)


def _identity_values(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        return tuple(item for item in value if isinstance(item, str))
    return ()


__all__ = ["IdentityBindingReceipt", "unproven_identity_operands"]
