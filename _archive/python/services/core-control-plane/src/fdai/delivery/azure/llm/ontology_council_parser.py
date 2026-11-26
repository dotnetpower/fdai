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
    CouncilTokenUsage,
    CouncilVote,
)

_VOTE_KEYS = frozenset(
    {
        "claim_id",
        "citation_digest",
        "disposition",
        "operation",
        "target_kind",
        "target_type",
        "target_identity",
        "authority",
        "properties",
        "semantics",
        "from_identity",
        "to_identity",
    }
)
_SEMANTIC_KEYS = frozenset(
    {"numbers", "units", "comparators", "negated", "effective_from", "effective_to"}
)


def parse_council_vote(
    content: str,
    identity: CouncilModelIdentity,
    *,
    usage: CouncilTokenUsage | None = None,
) -> CouncilVote:
    try:
        parsed = json.loads(content, parse_constant=_reject_json_constant)
        if not isinstance(parsed, dict):
            raise ValueError
        disposition = CouncilDisposition(_required_string(parsed, "disposition"))
        if set(parsed) != _VOTE_KEYS:
            raise ValueError
        claim_id = _required_string(parsed, "claim_id")
        citation_digest = _required_string(parsed, "citation_digest")
        if disposition is not CouncilDisposition.PROPOSE:
            if (
                any(
                    parsed[key] is not None
                    for key in (
                        "operation",
                        "target_kind",
                        "target_type",
                        "target_identity",
                        "authority",
                        "from_identity",
                        "to_identity",
                        "semantics",
                    )
                )
                or parsed["properties"] != []
            ):
                raise ValueError
            return CouncilVote(
                model_identity=identity,
                claim_id=claim_id,
                citation_digest=citation_digest,
                disposition=disposition,
                usage=usage or CouncilTokenUsage(),
            )
        target_kind = CouncilTargetKind(_required_string(parsed, "target_kind"))
        from_identity = _nullable_required_string(parsed, "from_identity")
        to_identity = _nullable_required_string(parsed, "to_identity")
        if target_kind is CouncilTargetKind.OBJECT:
            if from_identity is not None or to_identity is not None:
                raise ValueError
        elif from_identity is None or to_identity is None:
            raise ValueError
        return CouncilVote(
            model_identity=identity,
            claim_id=claim_id,
            citation_digest=citation_digest,
            disposition=disposition,
            operation=CouncilOperation(_required_string(parsed, "operation")),
            target_kind=target_kind,
            target_type=_required_string(parsed, "target_type"),
            target_identity=_required_string(parsed, "target_identity"),
            authority=_required_string(parsed, "authority"),
            properties=_parse_properties(parsed["properties"]),
            from_identity=from_identity,
            to_identity=to_identity,
            semantics=_parse_semantics(parsed["semantics"]),
            usage=usage or CouncilTokenUsage(),
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


def _nullable_required_string(value: Mapping[str, object], key: str) -> str | None:
    if value[key] is None:
        return None
    return _required_string(value, key)


def _reject_json_constant(_value: str) -> NoReturn:
    raise ValueError


__all__ = ["parse_council_vote"]
