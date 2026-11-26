"""Response-shape validation for Azure semantic planning calls."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from fdai.core.conversation.semantic_planning_models import SemanticFrameProposal
from fdai.delivery.catalog_search.ontology_candidate_proposal import OntologyCandidateProposal

_MAX_RESPONSE_BYTES = 65_536
_ProposalT = TypeVar("_ProposalT", bound=BaseModel)


class SemanticPlanningResponseValidationError(ValueError):
    """Redacted response-shape failure with a machine-readable stage."""

    def __init__(self, stage: str) -> None:
        self.stage = stage
        super().__init__("semantic planning response failed validation")


def validated_content(  # noqa: UP047 - pinned mypy does not parse PEP 695 functions
    response: httpx.Response,
    proposal_type: type[_ProposalT],
) -> tuple[dict[str, Any], str, Mapping[str, Any] | None]:
    envelope = response.json()
    choices = envelope.get("choices") if isinstance(envelope, Mapping) else None
    if not isinstance(choices, list) or not choices:
        raise SemanticPlanningResponseValidationError("no_choice")
    if proposal_type is OntologyCandidateProposal and (
        len(choices) != 1
        or not isinstance(choices[0], Mapping)
        or choices[0].get("finish_reason") != "stop"
    ):
        raise SemanticPlanningResponseValidationError("candidate_choice")
    message = choices[0].get("message") if isinstance(choices[0], Mapping) else None
    content = message.get("content") if isinstance(message, Mapping) else None
    if not isinstance(content, str) or not content or len(content.encode()) > _MAX_RESPONSE_BYTES:
        raise SemanticPlanningResponseValidationError("content")
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        raise SemanticPlanningResponseValidationError("json") from None
    if proposal_type is OntologyCandidateProposal:
        payload = normalize_candidate_proposal_payload(payload)
    if proposal_type is SemanticFrameProposal and isinstance(payload, dict):
        payload = _normalize_frame_tokens(payload)
    proposal = proposal_type.model_validate(payload)
    usage = envelope.get("usage") if isinstance(envelope.get("usage"), Mapping) else None
    return proposal.model_dump(mode="json"), content, usage


def normalize_candidate_proposal_payload(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    clauses = payload.get("clauses")
    if not isinstance(clauses, list):
        return payload
    normalized_clauses: list[Any] = []
    quotes: list[str] = []
    for clause in clauses:
        if not isinstance(clause, dict):
            normalized_clauses.append(clause)
            continue
        normalized = dict(clause)
        quote = normalized.pop("quote", None)
        object_ids = normalized.get("object_ids")
        if isinstance(object_ids, list):
            normalized["object_ids"] = list(dict.fromkeys(object_ids))
        nested = normalized.get("nested_predicates")
        if isinstance(nested, list):
            normalized["nested_predicates"] = [
                {name: value for name, value in item.items() if value is not None}
                if isinstance(item, dict)
                else item
                for item in nested
            ]
        normalized_clauses.append(normalized)
        if isinstance(quote, str):
            quotes.append(quote)
    output = dict(payload)
    output["clauses"] = normalized_clauses
    output["clause_quotes"] = quotes
    return output


async def provider_error_code(response: httpx.Response) -> str | None:
    try:
        if response.is_stream_consumed:
            raw = response.content
        else:
            chunks: list[bytes] = []
            total = 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > 8192:
                    await response.aclose()
                    return None
                chunks.append(chunk)
            raw = b"".join(chunks)
        payload = json.loads(raw)
    except (httpx.HTTPError, ValueError):
        return None
    if not isinstance(payload, Mapping):
        return None
    error = payload.get("error")
    if not isinstance(error, Mapping):
        return None
    code = error.get("code")
    return code[:128] if isinstance(code, str) and code else None


def _normalize_frame_tokens(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    normalized.setdefault("confidence", 0.0)
    evidence_requirements = normalized.get("evidence_requirements")
    if isinstance(evidence_requirements, list):
        normalized["evidence_requirements"] = [
            _machine_token(item) if isinstance(item, str) else item
            for item in evidence_requirements
        ]
    return normalized


def _machine_token(value: str) -> str:
    return re.sub(r"[^a-z0-9_.-]+", "_", value.strip().casefold()).strip("_")


__all__ = [
    "SemanticPlanningResponseValidationError",
    "normalize_candidate_proposal_payload",
    "provider_error_code",
    "validated_content",
]
