"""Restart-safe, content-free handover knowledge event production."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from fdai_service_contracts.handover_knowledge import (
    KNOWLEDGE_SOURCE_EVENT,
    HandoverKnowledgeNotice,
    notice_for_source,
)
from fdai_service_contracts.handover_observation import (
    HandoverGoalObservation,
    handover_observation_fields,
)

from fdai.core.human_assignment.goals import GoalEvidence, HandoverGoalState
from fdai.core.stewardship.names import AGENT_NAME_SET
from fdai.shared.contracts.models import Event, Mode
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.handover_goals import HandoverGoalProjectionReader
from fdai.shared.providers.state_store import StateStore

_KNOWN_PREFIX = "handover_knowledge_source:"
_GOAL_PREFIXES = ("handover_goal:goal:", "operator-handover-goal:", _KNOWN_PREFIX)
_RECEIPT_PREFIX = "handover_knowledge_lifecycle:"
_FAILURE_PREFIX = "handover_knowledge_lifecycle_failure:"
_NAMESPACE = uuid.NAMESPACE_URL
_LOGGER = logging.getLogger("fdai.handover.knowledge_lifecycle")
_GAP_STATES = frozenset(
    {
        HandoverGoalState.NOT_STARTED,
        HandoverGoalState.IN_PROGRESS,
        HandoverGoalState.BLOCKED,
    }
)
_CANDIDATE_STATES = frozenset(
    {
        HandoverGoalState.READY_FOR_REVIEW,
        HandoverGoalState.ACCEPTED,
    }
)


@dataclass(frozen=True, slots=True)
class _LifecycleGoal:
    goal_id: str
    assignment_case_id: str | None
    agent_name: str
    scope_ref: str
    prompt_ref: str
    priority: int
    state: HandoverGoalState
    revision: int
    evidence: tuple[GoalEvidence, ...]


@dataclass(slots=True)
class HandoverKnowledgeLifecycleWorker:
    """Schedule source rechecks; only the actual agents issue admission and candidate decisions."""

    store: StateStore
    bus: EventBus
    topic: str
    interval_seconds: float = 60.0
    batch_limit: int = 100
    operator_goals: HandoverGoalProjectionReader | None = None
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    _offsets: dict[str, int] = field(default_factory=dict, init=False, repr=False)
    _next_prefix: int = field(default=0, init=False, repr=False)
    _scan_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        if not 0 < self.interval_seconds <= 3600:
            raise ValueError("handover knowledge interval MUST be in (0, 3600]")
        if not 1 <= self.batch_limit <= 1000:
            raise ValueError("handover knowledge batch limit MUST be between 1 and 1000")
        if not self.topic.strip():
            raise ValueError("handover knowledge event topic MUST be non-empty")

    async def run_once(self) -> int:
        """Bound scanned rows, alternate source priority, and retain a failed page for retry."""
        async with self._scan_lock:
            return await self._scan()

    async def _scan(self) -> int:
        processed, scanned = 0, 0
        for index in range(len(_GOAL_PREFIXES)):
            prefix = _GOAL_PREFIXES[(self._next_prefix + index) % len(_GOAL_PREFIXES)]
            if prefix == "operator-handover-goal:" and self.operator_goals is None:
                continue
            offset = self._offsets.get(prefix, 0)
            if prefix == "operator-handover-goal:":
                if self.operator_goals is None:
                    raise RuntimeError("Operator goal projection is unavailable")
                goals, total = await self.operator_goals.read_page(
                    limit=self.batch_limit - scanned, offset=offset
                )
            else:
                goals, total = await self.store.read_state_page(
                    prefix, limit=self.batch_limit - scanned, offset=offset
                )
            for raw in goals:
                processed += int(await self._process(raw, prefix=prefix))
                scanned += 1
            next_offset = offset + len(goals)
            self._offsets[prefix] = next_offset if goals and next_offset < total else 0
            if scanned >= self.batch_limit:
                break
        self._next_prefix = (self._next_prefix + 1) % len(_GOAL_PREFIXES)
        return processed

    async def _process(self, raw: Mapping[str, Any], *, prefix: str) -> bool:
        try:
            if prefix == _KNOWN_PREFIX:
                previous = HandoverKnowledgeNotice.model_validate(raw.get("notice"))
                notice = previous.model_copy(
                    update={"check_epoch": int(self.clock().timestamp()) // 300}
                )
            else:
                _parse_goal(raw)
                notice = notice_for_source(
                    raw,
                    source="operator" if prefix == "operator-handover-goal:" else "core",
                    at=self.clock(),
                )
        except (KeyError, TypeError, ValueError):
            failure_id = uuid.uuid5(_NAMESPACE, repr(sorted(raw.items())))
            return await self.store.write_state_with_audit_if_absent(
                f"{_FAILURE_PREFIX}{failure_id}",
                {"failure_kind": "invalid_goal_record"},
                {
                    "actor": "handover-knowledge-scheduler",
                    "action_kind": "handover.knowledge_goal_rejected",
                    "failure_kind": "invalid_goal_record",
                    "recorded_at": datetime.now(UTC).isoformat(),
                },
            )
        receipt_key = f"{_RECEIPT_PREFIX}{notice.notice_id}"
        if await self.store.read_state(receipt_key) is not None:
            return False
        event_id = uuid.uuid5(_NAMESPACE, notice.notice_id)
        timestamp = self.clock()
        event = Event(
            schema_version="1.0.0",
            event_id=event_id,
            idempotency_key=f"handover-knowledge-{event_id}",
            correlation_id=notice.source_id,
            source="handover-knowledge-scheduler",
            event_type=KNOWLEDGE_SOURCE_EVENT,
            resource_ref=f"handover-source:{notice.source_id}",
            payload={"notice": notice.model_dump(mode="json")},
            detected_at=timestamp,
            ingested_at=timestamp,
            mode=Mode.SHADOW,
        )
        # Retain identity before dispatch so deletion/restart cannot orphan a previously seen goal.
        await self._track_source(notice)
        await self.bus.publish(
            self.topic, key=notice.source_id, payload=event.model_dump(mode="json")
        )
        recorded_at = self.clock().isoformat()
        return await self.store.write_state_with_audit_if_absent(
            receipt_key,
            {
                "source_id": notice.source_id,
                "goal_revision": notice.goal_revision,
                "action": "source_check",
                "event_ids": [str(event.event_id)],
                "recorded_at": recorded_at,
            },
            {
                "actor": "handover-knowledge-scheduler",
                "action_kind": "handover.knowledge_source_check_published",
                "source_id": notice.source_id,
                "goal_revision": notice.goal_revision,
                "event_count": 1,
                "recorded_at": recorded_at,
            },
        )

    async def _track_source(self, notice: HandoverKnowledgeNotice) -> None:
        """Retain the latest identity with CAS; deletion never regresses to its first revision."""
        key = f"{_KNOWN_PREFIX}{notice.source_id}"
        for _attempt in range(4):
            current = await self.store.read_state(key)
            revision = 0
            if current is not None:
                stored_revision = current.get("revision")
                if type(stored_revision) is not int or stored_revision < 1:
                    raise ValueError("handover tracked source revision is malformed")
                revision = stored_revision
                previous = HandoverKnowledgeNotice.model_validate(current.get("notice"))
                if previous.goal_revision >= notice.goal_revision:
                    return
            value = {"revision": revision + 1, "notice": notice.model_dump(mode="json")}
            audit = {
                "actor": "handover-knowledge-scheduler",
                "action_kind": "handover.source.tracked",
                "source_id": notice.source_id,
                "recorded_at": self.clock().isoformat(),
            }
            if current is None:
                changed = await self.store.write_state_with_audit_if_absent(key, value, audit)
            else:
                changed = await self.store.compare_and_set_state_with_audit(
                    key, value, expected_revision=revision, audit_entry=audit
                )
            if changed:
                return
        raise RuntimeError("handover tracked source changed concurrently")

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                processed = await self.run_once()
                _LOGGER.info(
                    "handover_knowledge_lifecycle_reconciled",
                    extra={"processed": processed},
                )
            except Exception as exc:  # noqa: BLE001 - durable receipts preserve replay safety
                _LOGGER.error(
                    "handover_knowledge_lifecycle_failed",
                    extra={"error_type": type(exc).__name__},
                )
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.interval_seconds)
            except TimeoutError:
                continue


def _parse_goal(raw: Mapping[str, Any]) -> _LifecycleGoal:
    observation = HandoverGoalObservation.model_validate(handover_observation_fields(raw))
    raw = observation.model_dump(mode="json")
    if observation.agent_name not in AGENT_NAME_SET:
        raise ValueError("handover observation names an unknown agent")
    evidence = raw.get("evidence", [])
    if not isinstance(evidence, list):
        raise ValueError("handover goal evidence MUST be an array")
    assignment_case_id = raw.get("assignment_case_id")
    if assignment_case_id is not None and not isinstance(assignment_case_id, str):
        raise ValueError("handover goal assignment_case_id MUST be a string")
    return _LifecycleGoal(
        goal_id=_required_string(raw, "goal_id"),
        assignment_case_id=assignment_case_id,
        agent_name=_required_string(raw, "agent_name"),
        scope_ref=_required_string(raw, "scope_ref"),
        prompt_ref=_required_string(raw, "prompt_ref"),
        priority=_positive_integer(raw, "priority"),
        state=HandoverGoalState(_required_string(raw, "state")),
        revision=_positive_integer(raw, "revision"),
        evidence=tuple(
            GoalEvidence(
                evidence_ref=_required_string(item, "evidence_ref"),
                digest=_required_string(item, "digest"),
                kind=_required_string(item, "kind"),
            )
            for item in evidence
            if isinstance(item, Mapping)
        ),
    )


def _required_string(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ValueError(f"handover goal {key} MUST be a non-empty string")
    return item


def _positive_integer(value: Mapping[str, Any], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool) or item < 1:
        raise ValueError(f"handover goal {key} MUST be a positive integer")
    return item


__all__ = ["HandoverKnowledgeLifecycleWorker"]
