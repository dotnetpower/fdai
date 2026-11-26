"""PostgreSQL evidence feed for automation blueprint suggestions."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

import psycopg
from psycopg.rows import dict_row

from fdai.core.scheduler.blueprints.models import (
    AutomationBlueprintEvidence,
    BlueprintEvidenceSource,
    BlueprintOutcome,
)
from fdai.core.scheduler.models import ScheduledRunIsolationProfile


@dataclass(frozen=True, slots=True)
class PostgresAutomationBlueprintEvidenceFeedConfig:
    dsn: str
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10

    def __post_init__(self) -> None:
        if not self.dsn.strip():
            raise ValueError("automation blueprint evidence feed dsn MUST be non-empty")
        if self.statement_timeout_ms < 1 or self.connect_timeout_s < 1:
            raise ValueError("automation blueprint evidence feed timeouts MUST be positive")


class PostgresAutomationBlueprintEvidenceFeed:
    """Read completed operator-turn evidence from the durable semantic result projection."""

    def __init__(self, config: PostgresAutomationBlueprintEvidenceFeedConfig) -> None:
        self._config = config

    async def completed_turns(self) -> Sequence[AutomationBlueprintEvidence]:
        rows = await self._fetch_all(
            """
            SELECT result.value AS result_value
              FROM state_kv AS result
              JOIN state_kv AS request
                ON request.value ->> 'request_id' = result.value ->> 'request_id'
             WHERE result.value ->> 'kind' = 'operator.semantic_result'
               AND request.value ->> 'kind' = 'operator.semantic_turn'
               AND result.value -> 'data' -> 'semantic_result' ->> 'disposition' = 'answered'
               AND result.value -> 'data' -> 'payload' ? 'automation_blueprint_evidence'
             ORDER BY result.value ->> 'recorded_at', result.key
             LIMIT 500
            """
        )
        return tuple(
            evidence
            for row in rows
            for evidence in _evidence_from_result(row.get("result_value"))
            if evidence.source is BlueprintEvidenceSource.OPERATOR_TURN
        )

    async def scheduler_history(self) -> Sequence[AutomationBlueprintEvidence]:
        rows = await self._fetch_all(
            """
            SELECT value
              FROM state_kv
             WHERE value ->> 'kind' = 'automation_blueprint.scheduler_history'
               AND value ? 'automation_blueprint_evidence'
             ORDER BY value ->> 'recorded_at', key
             LIMIT 500
            """
        )
        return tuple(
            evidence
            for row in rows
            for evidence in _evidence_from_record(row.get("value"))
            if evidence.source is BlueprintEvidenceSource.SCHEDULED_RUN
        )

    async def _fetch_all(self, query: str) -> list[dict[str, Any]]:
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        ) as connection:
            await connection.execute(
                "SELECT set_config('statement_timeout', %s, true)",
                (str(self._config.statement_timeout_ms),),
            )
            cursor = await connection.execute(query)
            return list(await cursor.fetchall())


def _evidence_from_result(value: object) -> tuple[AutomationBlueprintEvidence, ...]:
    record = _json_mapping(value, label="semantic result")
    data = _json_mapping(record.get("data"), label="semantic result data")
    payload = _json_mapping(data.get("payload"), label="semantic result payload")
    evidence = payload.get("automation_blueprint_evidence")
    if isinstance(evidence, list):
        return tuple(_parse_evidence(item) for item in evidence)
    return (_parse_evidence(evidence),)


def _evidence_from_record(value: object) -> tuple[AutomationBlueprintEvidence, ...]:
    record = _json_mapping(value, label="scheduler history")
    return (_parse_evidence(record.get("automation_blueprint_evidence")),)


def _parse_evidence(value: object) -> AutomationBlueprintEvidence:
    data = _json_mapping(value, label="automation blueprint evidence")
    source = BlueprintEvidenceSource(str(data.get("source")))
    outcome = BlueprintOutcome(str(data.get("outcome")))
    occurred_at = _aware_timestamp(data.get("occurred_at"))
    tools = data.get("required_tools", ())
    if not isinstance(tools, list | tuple):
        raise ValueError("automation blueprint evidence required_tools MUST be an array")
    profile_data = _json_mapping(data.get("isolation_profile", {}), label="isolation profile")
    return AutomationBlueprintEvidence(
        evidence_id=str(data["evidence_id"]),
        principal_id=str(data["principal_id"]),
        normalized_task_intent=str(data["normalized_task_intent"]),
        schedule_class=str(data["schedule_class"]),
        schedule_expression=str(data["schedule_expression"]),
        event_type=str(data["event_type"]),
        resource_scope=str(data["resource_scope"]),
        delivery_intent=str(data["delivery_intent"]),
        required_tools=tuple(str(tool) for tool in tools),
        isolation_profile=_isolation_profile(profile_data),
        outcome=outcome,
        source=source,
        occurred_at=occurred_at,
        estimated_cost_microusd=_int_value(data.get("estimated_cost_microusd", 0)),
        unresolved_failure=bool(data.get("unresolved_failure", False)),
    )


def _isolation_profile(data: Mapping[str, object]) -> ScheduledRunIsolationProfile:
    allowed = data.get("allowed_tool_ids", ())
    if not isinstance(allowed, list | tuple | set | frozenset):
        raise ValueError("isolation_profile allowed_tool_ids MUST be an array")
    return ScheduledRunIsolationProfile(
        profile_id=str(data.get("profile_id", "default-deny")),
        max_session_seconds=_int_value(data.get("max_session_seconds", 300)),
        max_context_chars=_int_value(data.get("max_context_chars", 16_000)),
        max_tool_calls=_int_value(data.get("max_tool_calls", 0)),
        allowed_tool_ids=frozenset(str(tool) for tool in allowed),
        command_sandbox_profile_id=(
            str(data["command_sandbox_profile_id"])
            if data.get("command_sandbox_profile_id") is not None
            else None
        ),
    )


def _json_mapping(value: object, *, label: str) -> Mapping[str, object]:
    decoded = json.loads(value) if isinstance(value, str) else value
    if not isinstance(decoded, Mapping):
        raise ValueError(f"{label} MUST be a JSON object")
    return cast(Mapping[str, object], decoded)


def _int_value(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int | str):
        raise ValueError("automation blueprint evidence integer field is malformed")
    return int(value)


def _aware_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("automation blueprint evidence occurred_at MUST be a timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("automation blueprint evidence occurred_at MUST include timezone")
    return parsed


__all__ = [
    "PostgresAutomationBlueprintEvidenceFeed",
    "PostgresAutomationBlueprintEvidenceFeedConfig",
]
