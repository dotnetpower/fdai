"""Strict wire mapping for consent-filtered post-turn review inputs."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from fdai.core.learning.models import PostTurnReviewInput, ToolReceiptEvidence
from fdai.core.operator_memory import ScopeKind


def review_input_to_mapping(review_input: PostTurnReviewInput) -> dict[str, object]:
    return {
        "review_id": review_input.review_id,
        "principal_scope": review_input.principal_scope,
        "operator_turn_id": review_input.operator_turn_id,
        "assistant_turn_id": review_input.assistant_turn_id,
        "completed_at": review_input.completed_at.isoformat(),
        "operator_body": review_input.operator_body,
        "assistant_body": review_input.assistant_body,
        "tool_receipts": [
            {
                "tool_name": receipt.tool_name,
                "status": receipt.status,
                "evidence_ref": receipt.evidence_ref,
            }
            for receipt in review_input.tool_receipts
        ],
        "validation_outcomes": list(review_input.validation_outcomes),
        "explicit_corrections": list(review_input.explicit_corrections),
        "evidence_refs": list(review_input.evidence_refs),
        "memory_scope_kind": (
            review_input.memory_scope_kind.value
            if review_input.memory_scope_kind is not None
            else None
        ),
        "memory_scope_ref": review_input.memory_scope_ref,
        "failure_recovered": review_input.failure_recovered,
        "procedure_fingerprint": review_input.procedure_fingerprint,
        "repeated_procedure_count": review_input.repeated_procedure_count,
    }


def review_input_from_mapping(value: Mapping[str, object]) -> PostTurnReviewInput:
    tool_receipts_raw = value.get("tool_receipts", [])
    if not isinstance(tool_receipts_raw, list):
        raise ValueError("post-turn tool_receipts MUST be a list")
    receipts: list[ToolReceiptEvidence] = []
    for raw in tool_receipts_raw:
        if not isinstance(raw, Mapping):
            raise ValueError("post-turn tool receipt MUST be an object")
        receipts.append(
            ToolReceiptEvidence(
                tool_name=_required_string(raw, "tool_name"),
                status=_required_string(raw, "status"),
                evidence_ref=_required_string(raw, "evidence_ref"),
            )
        )
    completed_raw = _required_string(value, "completed_at")
    try:
        completed_at = datetime.fromisoformat(completed_raw)
    except ValueError as exc:
        raise ValueError("post-turn completed_at MUST be ISO 8601") from exc
    scope_kind_raw = value.get("memory_scope_kind")
    return PostTurnReviewInput(
        review_id=_required_string(value, "review_id"),
        principal_scope=_required_string(value, "principal_scope"),
        operator_turn_id=_required_string(value, "operator_turn_id"),
        assistant_turn_id=_required_string(value, "assistant_turn_id"),
        completed_at=completed_at,
        operator_body=_optional_string(value, "operator_body"),
        assistant_body=_optional_string(value, "assistant_body"),
        tool_receipts=tuple(receipts),
        validation_outcomes=_string_tuple(value, "validation_outcomes"),
        explicit_corrections=_string_tuple(value, "explicit_corrections"),
        evidence_refs=_string_tuple(value, "evidence_refs"),
        memory_scope_kind=(ScopeKind(scope_kind_raw) if isinstance(scope_kind_raw, str) else None),
        memory_scope_ref=_optional_string(value, "memory_scope_ref"),
        failure_recovered=value.get("failure_recovered") is True,
        procedure_fingerprint=_optional_string(value, "procedure_fingerprint"),
        repeated_procedure_count=_non_negative_int(value, "repeated_procedure_count"),
    )


def _required_string(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"post-turn {key} MUST be a non-empty string")
    return item


def _optional_string(value: Mapping[str, object], key: str) -> str | None:
    item = value.get(key)
    if item is None:
        return None
    if not isinstance(item, str):
        raise ValueError(f"post-turn {key} MUST be a string or null")
    return item


def _string_tuple(value: Mapping[str, object], key: str) -> tuple[str, ...]:
    item = value.get(key, [])
    if not isinstance(item, list) or not all(isinstance(entry, str) for entry in item):
        raise ValueError(f"post-turn {key} MUST be a string list")
    return tuple(item)


def _non_negative_int(value: Mapping[str, object], key: str) -> int:
    item = value.get(key, 0)
    if not isinstance(item, int) or isinstance(item, bool) or item < 0:
        raise ValueError(f"post-turn {key} MUST be a non-negative integer")
    return item


__all__ = ["review_input_from_mapping", "review_input_to_mapping"]
