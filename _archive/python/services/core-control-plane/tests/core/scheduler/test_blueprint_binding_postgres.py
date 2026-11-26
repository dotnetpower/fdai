"""PostgreSQL integration for automation-blueprint suggestion binding."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from fdai.core.scheduler.blueprints.models import AutomationBlueprintState
from fdai.delivery.automation_blueprint_binding import build_postgres_automation_blueprint_binding

_NOW = datetime(2026, 9, 29, 13, 0, tzinfo=UTC)

pytestmark = pytest.mark.skipif(
    not os.environ.get("FDAI_DATABASE_URL"), reason="FDAI_DATABASE_URL is unset"
)


def _evidence(run_id: str, index: int, *, source: str = "operator_turn") -> dict[str, object]:
    return {
        "evidence_id": f"turn-{run_id}-{index}",
        "principal_id": "operator-1",
        "normalized_task_intent": "check inventory drift",
        "schedule_class": "daily",
        "schedule_expression": "0 3 * * *",
        "event_type": "object.drift-check-requested",
        "resource_scope": f"scope://subscription/example/resource-group/{run_id}",
        "delivery_intent": "audit-only",
        "required_tools": ["query_inventory"],
        "isolation_profile": {"profile_id": "default-deny", "max_tool_calls": 0},
        "outcome": "succeeded",
        "source": source,
        "occurred_at": (_NOW + timedelta(minutes=index)).isoformat(),
        "estimated_cost_microusd": 0,
    }


def _semantic_request(request_id: str, index: int) -> dict[str, object]:
    return {
        "kind": "operator.semantic_turn",
        "request_id": request_id,
        "principal_id": "operator-1",
        "idempotency_key": f"idem-{request_id}",
        "accepted_at": (_NOW + timedelta(minutes=index)).isoformat(),
        "envelope": {"semantic_turn": {"session_id": "sess-1", "turn_id": request_id}},
    }


def _semantic_result(request_id: str, index: int, run_id: str) -> dict[str, object]:
    return {
        "kind": "operator.semantic_result",
        "request_id": request_id,
        "projection_id": f"projection-{request_id}",
        "recorded_at": (_NOW + timedelta(minutes=index, seconds=30)).isoformat(),
        "data": {
            "semantic_result": {
                "disposition": "answered",
                "session_id": "sess-1",
                "turn_id": request_id,
                "turn_sequence": index,
            },
            "payload": {"automation_blueprint_evidence": _evidence(run_id, index)},
        },
    }


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:24]


async def test_postgres_binding_turns_three_completed_operator_turns_into_one_candidate() -> None:
    dsn = os.environ["FDAI_DATABASE_URL"]
    run_id = uuid4().hex[:8]
    records: dict[str, object] = {}
    for index in range(3):
        request_id = f"blueprint-{run_id}-{index}"
        records[f"semantic-turn:{run_id}:{index}"] = _semantic_request(request_id, index)
        records[f"semantic-result:{run_id}:{index}"] = _semantic_result(request_id, index, run_id)
    review_request_id = f"blueprint-{run_id}-review"
    records[f"semantic-turn:{run_id}:review"] = _semantic_request(review_request_id, 4)
    records[f"semantic-result:{run_id}:review"] = {
        **_semantic_result(review_request_id, 4, run_id),
        "data": {
            "semantic_result": {
                "disposition": "answered",
                "session_id": "sess-1",
                "turn_id": review_request_id,
                "turn_sequence": 4,
            },
            "payload": {
                "automation_blueprint_evidence": _evidence(
                    run_id,
                    4,
                    source="blueprint_review",
                )
            },
        },
    }
    async with await psycopg.AsyncConnection.connect(dsn) as connection:
        for key, value in records.items():
            await connection.execute(
                "INSERT INTO state_kv (key, value) VALUES (%s, %s::jsonb) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                (f"test:{key}:{_digest(value)}", json.dumps(value, sort_keys=True)),
            )

    binding = build_postgres_automation_blueprint_binding(dsn=dsn)
    summary = await binding.run_once(now=_NOW + timedelta(days=1))
    candidates = [
        candidate
        for candidate in await binding.review._store.list_all()  # type: ignore[attr-defined]
        if candidate.resource_scope.endswith(run_id)
    ]

    assert summary["proposed"] >= 1
    assert len(candidates) == 1
    assert candidates[0].state is AutomationBlueprintState.DRAFT
    assert candidates[0].enabled is False
    assert candidates[0].shadow_only is True
    assert len(candidates[0].evidence_fingerprints) == 3
