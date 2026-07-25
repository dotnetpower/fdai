"""Durable, no-drop approval grouping and bounded reminder planning."""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Final

from fdai.shared.providers.hil_channel import (
    HilApprovalRequest,
    HilChannel,
    HilChannelError,
)
from fdai.shared.providers.state_store import StateStore

_POLICY_SCHEMA: Final = "1.0.0"
_PARK_PREFIX: Final = "hil_park:"
_PLAN_PREFIX: Final = "hil_load_plan:"
_GROUP_PREFIX: Final = "hil_load_group:"
_REMINDER_ATTEMPT_PREFIX: Final = "hil_load_reminder_attempt:"
_TIME = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class ApprovalDispatchMode(StrEnum):
    SEND_NOW = "send_now"
    DEFERRED = "deferred"
    GROUPED = "grouped"


@dataclass(frozen=True, slots=True)
class ApprovalLoadPolicy:
    schema_version: str
    group_window_seconds: int
    max_pending_per_assignee: int
    reminder_offsets_seconds: tuple[int, ...]
    quiet_start_minute_utc: int
    quiet_end_minute_utc: int
    urgent_severities: frozenset[str]
    scan_limit: int
    worker_interval_seconds: int

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> ApprovalLoadPolicy:
        allowed = {
            "schema_version",
            "group_window_seconds",
            "max_pending_per_assignee",
            "reminder_offsets_seconds",
            "quiet_hours_utc",
            "urgent_severities",
            "scan_limit",
            "worker_interval_seconds",
        }
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(f"unknown approval load policy fields: {sorted(unknown)}")
        schema_version = _required_str(value, "schema_version")
        if schema_version != _POLICY_SCHEMA:
            raise ValueError(f"approval load policy schema MUST be {_POLICY_SCHEMA}")
        quiet = value.get("quiet_hours_utc")
        if not isinstance(quiet, Mapping):
            raise ValueError("quiet_hours_utc MUST be an object")
        offsets_raw = value.get("reminder_offsets_seconds")
        if not isinstance(offsets_raw, Sequence) or isinstance(offsets_raw, str | bytes):
            raise ValueError("reminder_offsets_seconds MUST be an array")
        offsets = tuple(_positive_int(item, "reminder offset") for item in offsets_raw)
        if len(offsets) > 4 or tuple(sorted(set(offsets))) != offsets:
            raise ValueError("reminder offsets MUST be unique, increasing, and contain at most 4")
        severities_raw = value.get("urgent_severities")
        if not isinstance(severities_raw, Sequence) or isinstance(severities_raw, str | bytes):
            raise ValueError("urgent_severities MUST be an array")
        severities = frozenset(str(item).strip().casefold() for item in severities_raw)
        if not severities or "critical" not in severities:
            raise ValueError("urgent_severities MUST include critical")
        return cls(
            schema_version=schema_version,
            group_window_seconds=_positive_int(
                value.get("group_window_seconds"), "group_window_seconds"
            ),
            max_pending_per_assignee=_positive_int(
                value.get("max_pending_per_assignee"), "max_pending_per_assignee"
            ),
            reminder_offsets_seconds=offsets,
            quiet_start_minute_utc=_time_minute(quiet.get("start"), "quiet start"),
            quiet_end_minute_utc=_time_minute(quiet.get("end"), "quiet end"),
            urgent_severities=severities,
            scan_limit=_positive_int(value.get("scan_limit"), "scan_limit"),
            worker_interval_seconds=_positive_int(
                value.get("worker_interval_seconds"), "worker_interval_seconds"
            ),
        )

    def in_quiet_hours(self, at: datetime) -> bool:
        minute = at.astimezone(UTC).hour * 60 + at.astimezone(UTC).minute
        start = self.quiet_start_minute_utc
        end = self.quiet_end_minute_utc
        if start == end:
            return False
        if start < end:
            return start <= minute < end
        return minute >= start or minute < end

    def next_quiet_end(self, at: datetime) -> datetime:
        current = at.astimezone(UTC)
        end_hour, end_minute = divmod(self.quiet_end_minute_utc, 60)
        candidate = current.replace(hour=end_hour, minute=end_minute, second=0, microsecond=0)
        if candidate <= current:
            candidate += timedelta(days=1)
        return candidate


@dataclass(frozen=True, slots=True)
class ApprovalLoadPlan:
    approval_id: str
    policy_version: str
    mode: ApprovalDispatchMode
    group_id: str
    group_size: int
    pending_for_assignee: int
    overloaded: bool
    severity: str
    due_at: tuple[datetime, ...]

    def metadata(self) -> dict[str, str]:
        return {
            "approval_load_policy": self.policy_version,
            "approval_load_mode": self.mode.value,
            "approval_group_id": self.group_id,
            "approval_group_size": str(self.group_size),
            "approval_assignee_pending": str(self.pending_for_assignee),
            "approval_assignee_overloaded": str(self.overloaded).lower(),
        }


@dataclass(frozen=True, slots=True)
class ApprovalLoadSnapshot:
    total_plans: int
    by_mode: Mapping[str, int]
    overloaded_plans: int
    urgent_plans: int


class ApprovalLoadController:
    """Create durable delivery plans after the authoritative park exists."""

    def __init__(
        self,
        *,
        state_store: StateStore,
        policy: ApprovalLoadPolicy,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._state_store = state_store
        self.policy = policy
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    async def plan(self, parked: Mapping[str, Any], *, severity: str) -> ApprovalLoadPlan:
        now = self._clock()
        if now.tzinfo is None:
            raise RuntimeError("approval load clock MUST be timezone-aware")
        approval_id = _required_str(parked, "approval_id")
        assignee = str(parked.get("assignee_oid") or "role-scoped").strip().casefold()
        action_type = _required_str(parked, "action_type")
        expires_at = _expires_at(parked)
        normalized_severity = severity.strip().casefold()
        urgent = normalized_severity in self.policy.urgent_severities

        parks = await self._state_store.read_states(_PARK_PREFIX, limit=self.policy.scan_limit)
        pending_for_assignee = sum(
            1
            for item in parks
            if item.get("status") == "pending"
            and str(item.get("assignee_oid") or "role-scoped").strip().casefold() == assignee
        )
        overloaded = pending_for_assignee > self.policy.max_pending_per_assignee
        grouping_scope = "overload" if overloaded else action_type
        bucket = int(now.timestamp()) // self.policy.group_window_seconds
        group_material = f"{assignee}\0{grouping_scope}\0{bucket}"
        group_id = hashlib.sha256(group_material.encode()).hexdigest()
        if urgent:
            group_id = hashlib.sha256(f"urgent\0{approval_id}".encode()).hexdigest()
        group_key = f"{_GROUP_PREFIX}{group_id}"
        anchor_created = await self._state_store.write_state_with_audit_if_absent(
            group_key,
            {
                "approval_id": approval_id,
                "group_id": group_id,
                "assignee_oid": assignee,
                "action_type": action_type,
                "bucket": bucket,
                "created_at": now.isoformat(),
            },
            _audit(
                kind="hil.load.group_anchor",
                key=f"hil-load-group:{group_id}",
                approval_id=approval_id,
                at=now,
            ),
        )
        group_size = sum(
            1
            for item in parks
            if item.get("status") == "pending"
            and _same_group(item, assignee=assignee, action_type=action_type, overloaded=overloaded)
        )
        group_size = max(1, group_size)
        if urgent:
            mode = ApprovalDispatchMode.SEND_NOW
        elif not anchor_created:
            mode = ApprovalDispatchMode.GROUPED
        elif self.policy.in_quiet_hours(now):
            mode = ApprovalDispatchMode.DEFERRED
        else:
            mode = ApprovalDispatchMode.SEND_NOW

        if mode is ApprovalDispatchMode.GROUPED:
            due_at: tuple[datetime, ...] = ()
        else:
            base = self.policy.next_quiet_end(now) if mode is ApprovalDispatchMode.DEFERRED else now
            candidates = ((base,) if mode is ApprovalDispatchMode.DEFERRED else ()) + tuple(
                base + timedelta(seconds=offset) for offset in self.policy.reminder_offsets_seconds
            )
            due_at = tuple(item for item in candidates if item < expires_at)
        plan = ApprovalLoadPlan(
            approval_id=approval_id,
            policy_version=self.policy.schema_version,
            mode=mode,
            group_id=group_id,
            group_size=group_size,
            pending_for_assignee=pending_for_assignee,
            overloaded=overloaded,
            severity=normalized_severity,
            due_at=due_at,
        )
        await self._state_store.write_state(
            f"{_PLAN_PREFIX}{approval_id}",
            {
                "approval_id": approval_id,
                "policy_version": plan.policy_version,
                "mode": plan.mode.value,
                "group_id": plan.group_id,
                "group_size": plan.group_size,
                "pending_for_assignee": plan.pending_for_assignee,
                "overloaded": plan.overloaded,
                "severity": plan.severity,
                "due_at": [item.isoformat() for item in plan.due_at],
                "created_at": now.isoformat(),
            },
        )
        return plan

    async def snapshot(self) -> ApprovalLoadSnapshot:
        records = await self._state_store.read_states(_PLAN_PREFIX, limit=self.policy.scan_limit)
        modes = Counter(str(item.get("mode") or "unknown") for item in records)
        return ApprovalLoadSnapshot(
            total_plans=len(records),
            by_mode=dict(modes),
            overloaded_plans=sum(item.get("overloaded") is True for item in records),
            urgent_plans=sum(
                str(item.get("severity") or "").casefold() in self.policy.urgent_severities
                for item in records
            ),
        )


class ApprovalReminderDispatcher:
    """Attempt each planned reminder at most once without changing approval state."""

    def __init__(
        self,
        *,
        state_store: StateStore,
        channel: HilChannel,
        policy: ApprovalLoadPolicy,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._state_store = state_store
        self._channel = channel
        self._policy = policy
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    async def drain_due(self) -> int:
        now = self._clock()
        if now.tzinfo is None:
            raise RuntimeError("approval reminder clock MUST be timezone-aware")
        plans = await self._state_store.read_states(_PLAN_PREFIX, limit=self._policy.scan_limit)
        attempts = 0
        for plan in plans:
            approval_id = str(plan.get("approval_id") or "")
            if not approval_id:
                continue
            park = await self._state_store.read_state(f"{_PARK_PREFIX}{approval_id}")
            if park is None or park.get("status") != "pending" or _expires_at(park) <= now:
                continue
            due_raw = plan.get("due_at", ())
            if not isinstance(due_raw, Sequence) or isinstance(due_raw, str | bytes):
                continue
            for index, raw in enumerate(due_raw):
                due = _timestamp(raw, "approval reminder due_at")
                if due > now:
                    continue
                dispatch_id = f"{approval_id}:{index}"
                claimed = await self._state_store.write_state_with_audit_if_absent(
                    f"{_REMINDER_ATTEMPT_PREFIX}{dispatch_id}",
                    {"approval_id": approval_id, "index": index, "attempted_at": now.isoformat()},
                    _audit(
                        kind="hil.load.reminder_attempted",
                        key=f"hil-load-reminder:{dispatch_id}",
                        approval_id=approval_id,
                        at=now,
                    ),
                )
                if not claimed:
                    continue
                attempts += 1
                request = approval_request_from_park(
                    park,
                    metadata={
                        "approval_load_policy": str(plan.get("policy_version") or ""),
                        "approval_load_mode": "reminder",
                        "approval_group_id": str(plan.get("group_id") or ""),
                        "approval_group_size": str(plan.get("group_size") or 1),
                        "approval_reminder_index": str(index),
                        "approval_dispatch_id": dispatch_id,
                    },
                )
                try:
                    await self._channel.send(request)
                except HilChannelError:
                    await self._state_store.append_audit_entry(
                        _audit(
                            kind="hil.load.reminder_failed",
                            key=f"hil-load-reminder-failed:{dispatch_id}",
                            approval_id=approval_id,
                            at=now,
                        )
                    )
                else:
                    await self._state_store.append_audit_entry(
                        _audit(
                            kind="hil.load.reminder_sent",
                            key=f"hil-load-reminder-sent:{dispatch_id}",
                            approval_id=approval_id,
                            at=now,
                        )
                    )
        return attempts

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            await self.drain_due()
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._policy.worker_interval_seconds)
            except TimeoutError:
                continue


def approval_request_from_park(
    parked: Mapping[str, Any], *, metadata: Mapping[str, str] | None = None
) -> HilApprovalRequest:
    action = parked.get("action")
    if not isinstance(action, Mapping):
        raise ValueError("parked approval action MUST be an object")
    context = parked.get("approval_context")
    if not isinstance(context, Mapping):
        raise ValueError("parked approval context MUST be an object")
    citing_rules = action.get("citing_rules", ())
    reasons = context.get("reasons", ())
    return HilApprovalRequest(
        approval_id=_required_str(parked, "approval_id"),
        correlation_id=_required_str(parked, "correlation_id"),
        action_id=_required_str(action, "action_id"),
        action_type=_required_str(parked, "action_type"),
        rule_ids=tuple(str(item) for item in citing_rules),
        target_resource_ref=_required_str(action, "target_resource_ref"),
        blast_radius_summary=str(context.get("blast_radius_summary") or ""),
        reasons=tuple(str(item) for item in reasons),
        ttl_seconds=_positive_int(context.get("ttl_seconds"), "approval ttl_seconds"),
        metadata=dict(metadata or {}),
    )


def _same_group(
    item: Mapping[str, Any], *, assignee: str, action_type: str, overloaded: bool
) -> bool:
    item_assignee = str(item.get("assignee_oid") or "role-scoped").strip().casefold()
    if item_assignee != assignee:
        return False
    return overloaded or str(item.get("action_type") or "") == action_type


def _expires_at(parked: Mapping[str, Any]) -> datetime:
    context = parked.get("approval_context")
    if not isinstance(context, Mapping):
        raise ValueError("parked approval context MUST be an object")
    return _timestamp(context.get("expires_at"), "approval expires_at")


def _timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} MUST be an RFC 3339 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} MUST be an RFC 3339 string") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} MUST include a timezone")
    return parsed.astimezone(UTC)


def _time_minute(value: object, field: str) -> int:
    if not isinstance(value, str) or _TIME.fullmatch(value) is None:
        raise ValueError(f"{field} MUST use HH:MM UTC")
    hour, minute = value.split(":", 1)
    return int(hour) * 60 + int(minute)


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} MUST be a positive integer")
    return value


def _required_str(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ValueError(f"{key} MUST be a non-empty string")
    return item.strip()


def _audit(*, kind: str, key: str, approval_id: str, at: datetime) -> dict[str, Any]:
    return {
        "actor": "fdai.core.hil_resume.load_control",
        "action_kind": kind,
        "mode": "shadow",
        "idempotency_key": key,
        "approval_id": approval_id,
        "correlation_id": approval_id,
        "recorded_at": at.isoformat(),
    }


__all__ = [
    "ApprovalDispatchMode",
    "ApprovalLoadController",
    "ApprovalLoadPlan",
    "ApprovalLoadPolicy",
    "ApprovalLoadSnapshot",
    "ApprovalReminderDispatcher",
    "approval_request_from_park",
]
