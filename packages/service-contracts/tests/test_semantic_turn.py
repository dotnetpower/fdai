"""Semantic-turn wire-contract integrity tests."""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import pytest
from fdai_service_contracts import (
    GoalTaskReceipt,
    RuleSearchProjection,
    RuleSearchReceipt,
    query_content_digest,
    rule_search_query_digest,
)
from pydantic import ValidationError


def _projection_payload() -> dict[str, Any]:
    query_digest = rule_search_query_digest(
        {
            "query": "find retry rules",
            "operation": "discover",
            "corpus": "active",
            "limit": 7,
        }
    )
    retrieval_receipt = RuleSearchReceipt.model_validate(
        {
            "schema_version": "1.0.0",
            "query_digest": query_digest,
            "operation": "discover",
            "corpus": "active",
            "catalog_digest": f"sha256:{'c' * 64}",
            "semantic_state": "available",
            "generation_digest": f"sha256:{'d' * 64}",
            "results": [],
            "execution_authority": False,
        }
    )
    invocation_receipt = GoalTaskReceipt.model_validate(
        {
            "task_id": "query:rules",
            "goal_id": "rules",
            "intent": "function",
            "capability": "query.function",
            "evidence_mode": "operational",
            "status": "completed",
            "duration_ms": 5,
            "evidence_refs": ["catalog:rule.one"],
            "started_at": "2026-08-11T00:00:00Z",
            "completed_at": "2026-08-11T00:00:00Z",
        }
    )
    invocation_payload = invocation_receipt.model_dump(mode="json")
    return {
        "query_digest": query_digest,
        "retrieval_receipt_digest": retrieval_receipt.digest,
        "function_invocation_receipt_digest": query_content_digest(invocation_payload),
        "candidates": [],
        "retrieval_receipt": retrieval_receipt.model_dump(mode="json"),
        "function_invocation_receipt": invocation_payload,
        "authority": "candidate_only",
        "execution_authority": False,
    }


def test_rule_search_projection_accepts_exact_function_invocation_receipt() -> None:
    projection = RuleSearchProjection.model_validate(_projection_payload())

    assert projection.function_invocation_receipt.task_id == "query:rules"
    assert projection.execution_authority is False


@pytest.mark.parametrize(
    "tamper",
    (
        lambda payload: payload.__setitem__(
            "function_invocation_receipt_digest", f"sha256:{'0' * 64}"
        ),
        lambda payload: payload["function_invocation_receipt"].__setitem__("duration_ms", 6),
    ),
    ids=("digest", "content"),
)
def test_rule_search_projection_rejects_function_receipt_digest_tampering(
    tamper: Callable[[dict[str, Any]], None],
) -> None:
    payload = copy.deepcopy(_projection_payload())
    tamper(payload)

    with pytest.raises(ValidationError, match="digest MUST match canonical"):
        RuleSearchProjection.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("status", "failed"),
        ("task_id", "query:other"),
        ("intent", "relationship"),
        ("capability", "query.relationship"),
    ),
)
def test_rule_search_projection_rejects_non_function_invocation_receipts(
    field: str,
    value: str,
) -> None:
    payload = copy.deepcopy(_projection_payload())
    invocation_receipt = payload["function_invocation_receipt"]
    invocation_receipt[field] = value
    payload["function_invocation_receipt_digest"] = query_content_digest(invocation_receipt)

    with pytest.raises(ValidationError, match="completed query function"):
        RuleSearchProjection.model_validate(payload)
