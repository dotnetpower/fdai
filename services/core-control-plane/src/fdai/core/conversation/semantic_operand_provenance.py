"""Identity operand provenance checks for current-path model plans."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from fdai_service_contracts.ontology_query import OntologyQueryPlan, QueryNodeKind

_IDENTITY_PROPERTIES = frozenset({"id", "name", "display_name"})
# Every operator the plan verifier accepts that names one identity exactly.
_IDENTITY_OPERATORS = frozenset({"equals", "in", "equals_ignore_case"})
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

    texts = (utterance, *context)
    receipted = {receipt.identity for receipt in receipts}
    found = sorted(
        {operand for node in plan.nodes for operand in _node_operands(node.kind, node.arguments)}
    )
    return tuple(
        operand
        for operand in found
        if operand not in receipted and not any(_literally_present(operand, item) for item in texts)
    )


@dataclass(frozen=True, slots=True)
class ProvenanceScope:
    """Whether a plan's identity operands are checked, and the receipts that ground them."""

    enforced: bool
    receipts: tuple[IdentityBindingReceipt, ...] = ()
    utterance: str = ""
    context: tuple[str, ...] = ()


def provenance_scope(
    enforce_when: object, bound: object, utterance: str = "", context: Sequence[str] = ()
) -> ProvenanceScope:
    """Check operands under ``enforce_when``; a bound Console context grounds its own ids."""

    ids = getattr(bound, "resource_ids", None) or ()
    group = getattr(bound, "resource_group_id", None)
    identities = (*ids, *((group,) if isinstance(group, str) and group else ()))
    return ProvenanceScope(
        enforce_when is not None,
        tuple(
            IdentityBindingReceipt("bound_resource_context", "bound_resource_context", item)
            for item in identities
            if isinstance(item, str) and item
        ),
        utterance,
        tuple(context),
    )


def _literally_present(operand: str, text: str) -> bool:
    # Not meaning extraction: the operand must occur as written, bounded on both sides by
    # anything but an identifier character, so a Korean particle after a name still counts.
    if not operand.strip():
        return False
    pattern = rf"(?<![A-Za-z0-9_.\-]){re.escape(operand)}(?![A-Za-z0-9_\-]|\.[A-Za-z0-9])"
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


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
    elif kind is QueryNodeKind.RELATIONSHIP_TRAVERSAL:
        predicates = value.get("endpoint_predicates")
        for predicate in predicates if isinstance(predicates, list) else ():
            if isinstance(predicate, Mapping):
                found.extend(_predicate_operands(predicate))
    elif kind in {QueryNodeKind.METRIC_SERIES, QueryNodeKind.METRIC_SCOPE_SERIES}:
        found.extend(_identity_values(value.get("resource_id")))
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
    if property_name in _IDENTITY_PROPERTIES and operator in _IDENTITY_OPERATORS:
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


__all__ = [
    "IdentityBindingReceipt",
    "ProvenanceScope",
    "provenance_scope",
    "unproven_identity_operands",
]
