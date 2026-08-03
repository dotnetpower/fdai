"""Strict, content-free parsing for ontology council model votes."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import NoReturn

from fdai.shared.providers.ontology_council import (
    CouncilDisposition,
    CouncilModelIdentity,
    CouncilOperation,
    CouncilProperty,
    CouncilScalar,
    CouncilSemanticFields,
    CouncilTargetKind,
    CouncilVote,
)

_BASE_KEYS = frozenset({"claim_id", "citation_digest", "disposition"})
_PROPOSAL_KEYS = frozenset(
    {
        "operation",
        "target_kind",
        "target_type",
        "target_identity",
        "authority",
        "properties",
        "semantics",
    }
)
_LINK_KEYS = frozenset({"from_identity", "to_identity"})
_SEMANTIC_KEYS = frozenset(
    {"numbers", "units", "comparators", "negated", "effective_from", "effective_to"}
)


def parse_council_vote(content: str, identity: CouncilModelIdentity) -> CouncilVote:
    try:
        parsed = json.loads(content, parse_constant=_reject_json_constant)
        if not isinstance(parsed, dict):
            raise ValueError
        disposition = CouncilDisposition(_required_string(parsed, "disposition"))
        allowed = _BASE_KEYS
        if disposition is CouncilDisposition.PROPOSE:
            allowed |= _PROPOSAL_KEYS
            if parsed.get("target_kind") == CouncilTargetKind.LINK.value:
                allowed |= _LINK_KEYS
        if set(parsed) != allowed:
            raise ValueError
        claim_id = _required_string(parsed, "claim_id")
        citation_digest = _required_string(parsed, "citation_digest")
        if disposition is not CouncilDisposition.PROPOSE:
            return CouncilVote(
                model_identity=identity,
                claim_id=claim_id,
                citation_digest=citation_digest,
                disposition=disposition,
            )
        return CouncilVote(
            model_identity=identity,
            claim_id=claim_id,
            citation_digest=citation_digest,
            disposition=disposition,
            operation=CouncilOperation(_required_string(parsed, "operation")),
            target_kind=CouncilTargetKind(_required_string(parsed, "target_kind")),
            target_type=_required_string(parsed, "target_type"),
            target_identity=_required_string(parsed, "target_identity"),
            authority=_required_string(parsed, "authority"),
            properties=_parse_properties(parsed["properties"]),
            from_identity=_optional_required_string(parsed, "from_identity"),
            to_identity=_optional_required_string(parsed, "to_identity"),
            semantics=_parse_semantics(parsed["semantics"]),
        )
    except (KeyError, TypeError, ValueError):
        raise ValueError("ontology council vote schema is invalid") from None


def _parse_properties(value: object) -> tuple[CouncilProperty, ...]:
    if not isinstance(value, list) or len(value) > 64:
        raise ValueError
    result: list[CouncilProperty] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {"name", "value"}:
            raise ValueError
        scalar = _parse_scalar(item["value"])
        result.append(CouncilProperty(name=_required_string(item, "name"), value=scalar))
    names = [item.name for item in result]
    if names != sorted(names) or len(names) != len(set(names)):
        raise ValueError
    return tuple(result)


def _parse_scalar(value: object) -> CouncilScalar:
    if value is None:
        return None
    if isinstance(value, str):
        if len(value) > 4096:
            raise ValueError
        return value
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if abs(value) > 10**18:
            raise ValueError
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError
        return value
    raise ValueError


def _parse_semantics(value: object) -> CouncilSemanticFields:
    if not isinstance(value, dict) or set(value) != _SEMANTIC_KEYS:
        raise ValueError
    negated = value["negated"]
    if type(negated) is not bool:
        raise ValueError
    return CouncilSemanticFields(
        numbers=_string_tuple(value["numbers"]),
        units=_string_tuple(value["units"]),
        comparators=_string_tuple(value["comparators"]),
        negated=negated,
        effective_from=_nullable_string(value["effective_from"]),
        effective_to=_nullable_string(value["effective_to"]),
    )


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > 64:
        raise ValueError
    if any(type(item) is not str or not item or len(item) > 64 for item in value):
        raise ValueError
    if value != sorted(value) or len(value) != len(set(value)):
        raise ValueError
    return tuple(value)


def _nullable_string(value: object) -> str | None:
    if value is None:
        return None
    if type(value) is not str or not value or len(value) > 64:
        raise ValueError
    return value


def _required_string(value: Mapping[str, object], key: str) -> str:
    result = value[key]
    if type(result) is not str or not result:
        raise ValueError
    return result


def _optional_required_string(value: Mapping[str, object], key: str) -> str | None:
    if key not in value:
        return None
    return _required_string(value, key)


def _reject_json_constant(_value: str) -> NoReturn:
    raise ValueError


__all__ = ["parse_council_vote"]
