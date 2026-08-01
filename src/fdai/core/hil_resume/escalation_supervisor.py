"""Durable approval non-response escalation over authoritative HIL parks."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol

from fdai.core.hil_resume.load_control import approval_request_from_park
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.hil_channel import HilChannel, HilChannelError
from fdai.shared.providers.state_store import StateStore

_PARK_PREFIX = "hil_park:"


class EscalationDuty(StrEnum):
    PRIMARY = "primary"
    BACKUP = "backup"
    ESCALATION = "escalation"
    MAINTAINER = "maintainer"


class EscalationStatus(StrEnum):
    PENDING_DELIVERY = "pending_delivery"
    AWAITING_DECISION = "awaiting_decision"
    EXHAUSTED = "exhausted"
    DECIDED = "decided"


@dataclass(frozen=True, slots=True)
class EscalationRung:
    subject_ref: str
    duty: EscalationDuty
    minimum_role: str = "Approver"

    def __post_init__(self) -> None:
        if not self.subject_ref.strip() or len(self.subject_ref) > 256:
            raise ValueError("escalation subject_ref MUST be non-empty and bounded")
        if not self.minimum_role.strip() or len(self.minimum_role) > 64:
            raise ValueError("escalation minimum_role MUST be non-empty and bounded")


@dataclass(frozen=True, slots=True)
class EscalationPolicy:
    decision_timeout_seconds: int = 300
    overall_timeout_seconds: int = 1800
    delivery_retry_seconds: int = 60
    mode: Mode = Mode.SHADOW
    scan_limit: int = 500
    worker_interval_seconds: int = 30

    def __post_init__(self) -> None:
        for name in (
            "decision_timeout_seconds",
            "overall_timeout_seconds",
            "delivery_retry_seconds",
            "scan_limit",
            "worker_interval_seconds",
        ):
            if not 1 <= getattr(self, name) <= 86_400:
                raise ValueError(f"{name} MUST be in [1, 86400]")


class RungEligibility(Protocol):
    async def is_eligible(self, *, subject_ref: str, minimum_role: str) -> bool: ...


class _AllowAllEligibility:
    async def is_eligible(self, *, subject_ref: str, minimum_role: str) -> bool:
        return True


@dataclass(frozen=True, slots=True)
class EscalationTickResult:
    scanned: int = 0
    delivered: int = 0
    advanced: int = 0
    exhausted: int = 0
    delivery_failed: int = 0
    observed: int = 0


class HumanNonResponseSupervisor:
    """Advance delivered-but-unanswered HIL parks without execution authority."""

    def __init__(
        self,
        *,
        state_store: StateStore,
        channel: HilChannel,
        policy: EscalationPolicy | None = None,
        eligibility: RungEligibility | None = None,
        clock: Callable[[], datetime] | None = None,
        actor: str = "fdai.core.hil_resume.escalation_supervisor",
    ) -> None:
        self._state_store = state_store
        self._channel = channel
        self.policy = policy or EscalationPolicy()
        self._eligibility = eligibility or _AllowAllEligibility()
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._actor = actor

    def attach(
        self,
        parked: Mapping[str, Any],
        *,
        rungs: Sequence[EscalationRung],
        now: datetime,
    ) -> dict[str, Any]:
        """Snapshot one bounded ladder into a not-yet-persisted HIL park."""
        timestamp = _aware(now)
        submitter = str(parked.get("submitter_oid") or "").strip().casefold()
        unique: list[EscalationRung] = []
        seen: set[str] = set()
        for rung in rungs:
            normalized = rung.subject_ref.strip().casefold()
            if normalized == submitter or normalized in seen:
                continue
            seen.add(normalized)
            unique.append(rung)
        if not unique:
            raise ValueError("escalation ladder requires a non-requester rung")
        if len(unique) > 8:
            raise ValueError("escalation ladder exceeds the eight-rung limit")
        context = parked.get("approval_context")
        if not isinstance(context, Mapping):
            raise ValueError("parked approval_context MUST be an object")
        park_deadline = _timestamp(context.get("expires_at"), "approval expires_at")
        overall_deadline = min(
            park_deadline,
            timestamp + timedelta(seconds=self.policy.overall_timeout_seconds),
        )
        updated = dict(parked)
        updated["revision"] = _revision(parked)
        updated["assignee_oid"] = unique[0].subject_ref
        updated["escalation"] = {
            "status": EscalationStatus.PENDING_DELIVERY.value,
            "current_rung": 0,
            "rungs": [
                {
                    "subject_ref": rung.subject_ref,
                    "duty": rung.duty.value,
                    "minimum_role": rung.minimum_role,
                }
                for rung in unique
            ],
            "attempted_subjects": [],
            "action_hash": _action_hash(parked),
            "request_fingerprint": str(parked.get("request_fingerprint") or ""),
            "overall_deadline": overall_deadline.isoformat(),
            "next_delivery_at": timestamp.isoformat(),
            "delivery_attempts": 0,
            "delivered_at": None,
            "decision_deadline": None,
        }
        return updated

    async def mark_delivered(self, approval_id: str, at: datetime | None = None) -> bool:
        now = _aware(at or self._clock())
        parked = await self._state_store.read_state(f"{_PARK_PREFIX}{approval_id}")
        if parked is None or parked.get("status") != "pending":
            return False
        escalation = _escalation(parked)
        if escalation.get("status") != EscalationStatus.PENDING_DELIVERY.value:
            return False
        overall = _timestamp(escalation.get("overall_deadline"), "overall_deadline")
        updated_escalation = dict(escalation)
        updated_escalation.update(
            {
                "status": EscalationStatus.AWAITING_DECISION.value,
                "delivered_at": now.isoformat(),
                "decision_deadline": min(
                    overall,
                    now + timedelta(seconds=self.policy.decision_timeout_seconds),
                ).isoformat(),
            }
        )
        return await self._cas(
            parked,
            escalation=updated_escalation,
            action_kind="hil.escalation.delivered",
            now=now,
        )

    async def tick(self, *, at: datetime | None = None) -> EscalationTickResult:
        now = _aware(at or self._clock())
        parks = await self._state_store.read_states(_PARK_PREFIX, limit=self.policy.scan_limit)
        delivered = advanced = exhausted = delivery_failed = observed = 0
        for parked in parks:
            if parked.get("status") != "pending" or not isinstance(
                parked.get("escalation"), Mapping
            ):
                continue
            escalation = _escalation(parked)
            if not _integrity_matches(parked, escalation):
                exhausted += int(await self._exhaust(parked, now=now, reason="integrity_failed"))
                continue
            overall_due = now >= _timestamp(escalation.get("overall_deadline"), "overall_deadline")
            status = EscalationStatus(str(escalation.get("status")))
            if self.policy.mode is Mode.SHADOW and status is EscalationStatus.PENDING_DELIVERY:
                continue
            decision_due = (
                status is EscalationStatus.AWAITING_DECISION
                and _timestamp(escalation.get("decision_deadline"), "decision_deadline") <= now
            )
            if self.policy.mode is Mode.SHADOW and (overall_due or decision_due):
                observed += int(
                    await self._observe_due(
                        parked,
                        now=now,
                        reason="overall_deadline" if overall_due else "human_non_response",
                    )
                )
                continue
            if self.policy.mode is Mode.SHADOW:
                continue
            if overall_due:
                exhausted += int(await self._exhaust(parked, now=now, reason="overall_deadline"))
                continue
            if status is EscalationStatus.AWAITING_DECISION:
                deadline = _timestamp(escalation.get("decision_deadline"), "decision_deadline")
                if deadline > now:
                    continue
                if await self._advance(parked, now=now, reason="human_non_response"):
                    advanced += 1
                else:
                    exhausted += int(
                        await self._exhaust(parked, now=now, reason="ladder_exhausted")
                    )
                continue
            if status is not EscalationStatus.PENDING_DELIVERY:
                continue
            next_delivery = _timestamp(escalation.get("next_delivery_at"), "next_delivery_at")
            if next_delivery > now:
                continue
            result = await self._dispatch(parked, now=now)
            delivered += int(result == "delivered")
            advanced += int(result == "advanced")
            exhausted += int(result == "exhausted")
            delivery_failed += int(result == "delivery_failed")
        return EscalationTickResult(
            scanned=len(parks),
            delivered=delivered,
            advanced=advanced,
            exhausted=exhausted,
            delivery_failed=delivery_failed,
            observed=observed,
        )

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            await self.tick()
            try:
                await asyncio.wait_for(
                    stop.wait(),
                    timeout=self.policy.worker_interval_seconds,
                )
            except TimeoutError:
                continue

    async def _observe_due(
        self,
        parked: Mapping[str, Any],
        *,
        now: datetime,
        reason: str,
    ) -> bool:
        escalation = dict(_escalation(parked))
        if escalation.get("shadow_observed_at") is not None:
            return False
        escalation["shadow_observed_at"] = now.isoformat()
        escalation["shadow_reason"] = reason
        escalation["shadow_next_rung"] = int(escalation.get("current_rung") or 0) + 1
        return await self._cas(
            parked,
            escalation=escalation,
            action_kind="hil.escalation.shadow_due",
            reason=reason,
            now=now,
        )

    async def _dispatch(self, parked: Mapping[str, Any], *, now: datetime) -> str:
        escalation = _escalation(parked)
        rung = _current_rung(escalation)
        if not await self._eligibility.is_eligible(
            subject_ref=str(rung["subject_ref"]),
            minimum_role=str(rung["minimum_role"]),
        ):
            if await self._advance(parked, now=now, reason="rung_ineligible"):
                return "advanced"
            await self._exhaust(parked, now=now, reason="no_eligible_rung")
            return "exhausted"
        claimed = await self._claim_delivery(parked, now=now)
        if claimed is None:
            return ""
        claimed_escalation = _escalation(claimed)
        request = approval_request_from_park(
            claimed,
            metadata={
                "assignee_oid": str(rung["subject_ref"]),
                "escalation_duty": str(rung["duty"]),
            },
        )
        try:
            await self._channel.send(request)
        except HilChannelError:
            await self._cas(
                claimed,
                escalation=claimed_escalation,
                action_kind="hil.escalation.delivery_failed",
                now=now,
            )
            return "delivery_failed"
        delivered = await self.mark_delivered(str(claimed["approval_id"]), at=now)
        return "delivered" if delivered else ""

    async def _claim_delivery(
        self,
        parked: Mapping[str, Any],
        *,
        now: datetime,
    ) -> Mapping[str, Any] | None:
        escalation = dict(_escalation(parked))
        escalation["delivery_attempts"] = int(escalation.get("delivery_attempts") or 0) + 1
        escalation["next_delivery_at"] = (
            now + timedelta(seconds=self.policy.delivery_retry_seconds)
        ).isoformat()
        revision = _revision(parked)
        claimed = dict(parked)
        claimed["escalation"] = escalation
        claimed["revision"] = revision + 1
        approval_id = str(parked["approval_id"])
        accepted = await self._state_store.compare_and_set_state_with_audit(
            f"{_PARK_PREFIX}{approval_id}",
            claimed,
            expected_revision=revision,
            audit_entry={
                "actor": self._actor,
                "action_kind": "hil.escalation.delivery_claimed",
                "mode": self.policy.mode.value,
                "idempotency_key": (
                    f"{parked.get('idempotency_key')}:hil.escalation.delivery_claimed:{revision}"
                ),
                "approval_id": approval_id,
                "correlation_id": str(parked.get("correlation_id") or approval_id),
                "action_hash": escalation.get("action_hash"),
                "recorded_at": now.isoformat(),
            },
        )
        return claimed if accepted else None

    async def _advance(self, parked: Mapping[str, Any], *, now: datetime, reason: str) -> bool:
        escalation = _escalation(parked)
        current = int(escalation.get("current_rung") or 0)
        rungs = _rungs(escalation)
        if current + 1 >= len(rungs):
            return False
        attempted = list(escalation.get("attempted_subjects") or [])
        attempted.append(str(rungs[current]["subject_ref"]))
        next_rung = rungs[current + 1]
        updated_escalation = dict(escalation)
        updated_escalation.update(
            {
                "status": EscalationStatus.PENDING_DELIVERY.value,
                "current_rung": current + 1,
                "attempted_subjects": attempted,
                "next_delivery_at": now.isoformat(),
                "delivery_attempts": 0,
                "delivered_at": None,
                "decision_deadline": None,
            }
        )
        return await self._cas(
            parked,
            escalation=updated_escalation,
            assignee_oid=str(next_rung["subject_ref"]),
            action_kind="hil.escalated",
            reason=reason,
            now=now,
        )

    async def _exhaust(self, parked: Mapping[str, Any], *, now: datetime, reason: str) -> bool:
        escalation = dict(_escalation(parked))
        escalation["status"] = EscalationStatus.EXHAUSTED.value
        escalation["exhausted_reason"] = reason
        return await self._cas(
            parked,
            escalation=escalation,
            status="resolved",
            decision="timeout",
            approver_oid="system:approval-escalation",
            resolved_at=now.isoformat(),
            action_kind="hil.escalation.exhausted",
            reason=reason,
            now=now,
        )

    async def _cas(
        self,
        parked: Mapping[str, Any],
        *,
        escalation: Mapping[str, Any],
        action_kind: str,
        now: datetime,
        reason: str | None = None,
        **fields: object,
    ) -> bool:
        revision = _revision(parked)
        updated = dict(parked)
        updated.update(fields)
        updated["escalation"] = dict(escalation)
        updated["revision"] = revision + 1
        approval_id = str(parked["approval_id"])
        return await self._state_store.compare_and_set_state_with_audit(
            f"{_PARK_PREFIX}{approval_id}",
            updated,
            expected_revision=revision,
            audit_entry={
                "actor": self._actor,
                "action_kind": action_kind,
                "mode": self.policy.mode.value,
                "idempotency_key": f"{parked.get('idempotency_key')}:{action_kind}:{revision}",
                "approval_id": approval_id,
                "correlation_id": str(parked.get("correlation_id") or approval_id),
                "action_hash": escalation.get("action_hash"),
                "reason": reason,
                "terminal_noop": action_kind == "hil.escalation.exhausted",
                "recorded_at": now.isoformat(),
            },
        )


def _revision(parked: Mapping[str, Any]) -> int:
    value = parked.get("revision", 0)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("parked approval revision MUST be a non-negative integer")
    return int(value)


def _escalation(parked: Mapping[str, Any]) -> Mapping[str, Any]:
    value = parked.get("escalation")
    if not isinstance(value, Mapping):
        raise ValueError("parked escalation state MUST be an object")
    return value


def _rungs(escalation: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    value = escalation.get("rungs")
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, Mapping) for item in value)
    ):
        raise ValueError("parked escalation rungs MUST be a non-empty array")
    return tuple(value)


def _current_rung(escalation: Mapping[str, Any]) -> Mapping[str, Any]:
    rungs = _rungs(escalation)
    current = escalation.get("current_rung")
    if isinstance(current, bool) or not isinstance(current, int) or not 0 <= current < len(rungs):
        raise ValueError("parked escalation current_rung is invalid")
    return rungs[current]


def _action_hash(parked: Mapping[str, Any]) -> str:
    action = parked.get("action")
    if not isinstance(action, Mapping):
        raise ValueError("parked action MUST be an object")
    canonical = json.dumps(action, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _integrity_matches(parked: Mapping[str, Any], escalation: Mapping[str, Any]) -> bool:
    return escalation.get("action_hash") == _action_hash(parked) and escalation.get(
        "request_fingerprint"
    ) == parked.get("request_fingerprint")


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("escalation timestamp MUST be timezone-aware")
    return value.astimezone(UTC)


def _timestamp(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{name} MUST be an ISO timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return _aware(parsed)


__all__ = [
    "EscalationDuty",
    "EscalationPolicy",
    "EscalationRung",
    "EscalationStatus",
    "EscalationTickResult",
    "HumanNonResponseSupervisor",
    "RungEligibility",
]
