# mypy: disable-error-code="attr-defined,arg-type,no-any-return,misc,has-type"
"""Recurring chaos schedule mixin for Loki."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from fdai.agents._framework.loki_runtime_records import ChaosProposal, _parse_time
from fdai.agents._framework.loki_scheduling import DueChaosWindow, due_window, window_key
from fdai.agents._framework.specialist_ingress import CHAOS_ACTION_TYPES
from fdai.agents._framework.topics import stable_idempotency_key

_HELD_PREFIX = "pantheon/loki/held-proposals/"
_SCHEDULED_PREFIX = "pantheon/loki/scheduled-chaos/"
_MAX_HELD_PROPOSALS = 256


class LokiScheduleRuntimeMixin:
    """Claim, recover, and compact scheduled chaos windows."""

    async def maintenance_tick(self) -> None:
        await super().maintenance_tick()
        cutoff = self._now() - self._reservation_ttl
        async with self._reservation_lock:
            if self._reservation_journal is not None:
                expired = await self._reservation_journal.expire_stale(cutoff=cutoff.isoformat())
                if expired.targets:
                    self._in_flight_targets = set(expired.occupied)
                    self.record_behavior("chaos_reservation:expired", len(expired.targets))
            expired_experiments = [
                experiment_id
                for experiment_id, reservation in self._reservations.items()
                if reservation.reserved_at <= cutoff
                and experiment_id not in self._publishing_experiments
            ]
            if not expired_experiments:
                pass
            else:
                expired_targets: list[str] = []
                for experiment_id in expired_experiments:
                    reservation = self._reservations.pop(experiment_id)
                    expired_targets.extend(reservation.targets)
                self._release_targets(tuple(expired_targets))
                self.record_behavior("chaos_reservation:expired", len(expired_targets))
        await self._hold_stale_claimed_schedule_windows()
        await self._run_recurring_schedule()
        await self._compact_scheduled_windows()

    async def _compact_scheduled_windows(self) -> None:
        if self._state_store is None:
            return
        deleted = await self._state_store.delete_states_beyond(
            _SCHEDULED_PREFIX,
            retain_newest=_MAX_HELD_PROPOSALS,
        )
        if deleted:
            self.record_behavior("chaos_scheduler:scheduled_windows_compacted", deleted)

    async def _hold_stale_claimed_schedule_windows(self) -> None:
        state_store = self._state_store
        if state_store is None:
            return
        for record in await state_store.read_states(_SCHEDULED_PREFIX, limit=_MAX_HELD_PROPOSALS):
            if record.get("state") != "claimed":
                continue
            due = _due_window_from_record(record)
            claimed_at = _parse_time_or_none(record.get("claimed_at"))
            if due is None or claimed_at is None:
                key = _scheduled_record_key(record)
                if key is None:
                    self.record_behavior("chaos_scheduler:claimed_window_unrecoverable")
                    continue
                await state_store.write_state(
                    key,
                    {
                        "schema_version": "1.0.0",
                        "revision": int(record.get("revision") or 1) + 1,
                        "state": "held",
                        "reason": "claimed_window_unrecoverable",
                        "schedule_id": str(record.get("schedule_id") or ""),
                        "window_start": str(record.get("window_start") or ""),
                        "experiment_id": str(record.get("experiment_id") or ""),
                    },
                )
                self.record_behavior("chaos_scheduler:claimed_window_unrecoverable")
                continue
            if self._now() - claimed_at <= self._reservation_ttl:
                continue
            await state_store.write_state(
                f"{_SCHEDULED_PREFIX}{window_key(due)}",
                {
                    "schema_version": "1.0.0",
                    "revision": int(record.get("revision") or 1) + 1,
                    "state": "held",
                    "reason": "claimed_window_expired",
                    "schedule_id": due.schedule_id,
                    "window_start": due.window_start.isoformat(),
                    "experiment_id": due.experiment_id,
                    "claimed_at": claimed_at.isoformat(),
                },
            )
            await self._record_scheduler_hold("claimed_window_expired", due=due)

    async def _run_recurring_schedule(self) -> None:
        schedule = self._recurring_schedule
        if schedule is None:
            await self._record_scheduler_hold("unbound")
            return
        if self._state_store is None:
            await self._record_scheduler_hold("scheduler_state_unbound")
            return
        due = due_window(schedule, now=self._now())
        if isinstance(due, str):
            await self._record_scheduler_hold(due)
            return
        key = f"{_SCHEDULED_PREFIX}{window_key(due)}"
        created = await self._state_store.write_state_if_absent(
            key,
            {
                "schema_version": "1.0.0",
                "revision": 1,
                "state": "claimed",
                "schedule_id": due.schedule_id,
                "window_start": due.window_start.isoformat(),
                "experiment_id": due.experiment_id,
                "claimed_at": self._now().isoformat(),
                "action_type": due.action_type,
                "targets": list(due.targets),
                "correlation_id": due.correlation_id,
                "causal_hypothesis_ref": due.causal_hypothesis_ref,
                "refutation_query_ref": due.refutation_query_ref,
                "impact_envelope_id": due.impact_envelope_id,
                "recovery_plan_id": due.recovery_plan_id,
                "dry_run_receipt": due.dry_run_receipt,
            },
        )
        if not created:
            existing = await self._state_store.read_state(key)
            if existing is not None and await self._recover_claimed_schedule_window(
                key,
                due,
                existing,
            ):
                return
            self.record_behavior("chaos_scheduler:duplicate_window")
            return
        proposal = await self.propose_experiment(
            experiment_id=due.experiment_id,
            action_type=due.action_type,
            targets=due.targets,
            correlation_id=due.correlation_id,
            causal_hypothesis_ref=due.causal_hypothesis_ref,
            refutation_query_ref=due.refutation_query_ref,
            impact_envelope_id=due.impact_envelope_id,
            recovery_plan_id=due.recovery_plan_id,
            dry_run_receipt=due.dry_run_receipt,
        )
        if proposal.accepted:
            await self._state_store.write_state(
                key,
                {
                    "schema_version": "1.0.0",
                    "revision": 2,
                    "state": "published",
                    "schedule_id": due.schedule_id,
                    "window_start": due.window_start.isoformat(),
                    "experiment_id": due.experiment_id,
                },
            )
            self.record_behavior("chaos_scheduler:published")
            return
        await self._state_store.write_state(
            key,
            {
                "schema_version": "1.0.0",
                "revision": 2,
                "state": "held",
                "reason": proposal.reason,
                "schedule_id": due.schedule_id,
                "window_start": due.window_start.isoformat(),
                "experiment_id": due.experiment_id,
            },
        )
        await self._record_scheduler_hold(proposal.reason, due=due)

    async def _recover_claimed_schedule_window(
        self,
        key: str,
        due: DueChaosWindow,
        existing: Mapping[str, Any],
    ) -> bool:
        state_store = self._state_store
        if state_store is None:
            return False
        if existing.get("state") != "claimed":
            return False
        if (
            existing.get("schedule_id") != due.schedule_id
            or existing.get("window_start") != due.window_start.isoformat()
            or existing.get("experiment_id") != due.experiment_id
        ):
            return False
        claimed_at = _parse_time_or_none(existing.get("claimed_at"))
        if claimed_at is None:
            await state_store.write_state(
                key,
                {
                    "schema_version": "1.0.0",
                    "revision": int(existing.get("revision") or 1) + 1,
                    "state": "held",
                    "reason": "claimed_window_unrecoverable",
                    "schedule_id": due.schedule_id,
                    "window_start": due.window_start.isoformat(),
                    "experiment_id": due.experiment_id,
                },
            )
            await self._record_scheduler_hold("claimed_window_unrecoverable", due=due)
            return True
        if self._now() - claimed_at > self._reservation_ttl:
            await state_store.write_state(
                key,
                {
                    "schema_version": "1.0.0",
                    "revision": int(existing.get("revision") or 1) + 1,
                    "state": "held",
                    "reason": "claimed_window_expired",
                    "schedule_id": due.schedule_id,
                    "window_start": due.window_start.isoformat(),
                    "experiment_id": due.experiment_id,
                    "claimed_at": claimed_at.isoformat(),
                },
            )
            await self._record_scheduler_hold("claimed_window_expired", due=due)
            return True
        self.record_behavior("chaos_scheduler:claimed_window_resumed")
        proposal = await self.propose_experiment(
            experiment_id=due.experiment_id,
            action_type=due.action_type,
            targets=due.targets,
            correlation_id=due.correlation_id,
            causal_hypothesis_ref=due.causal_hypothesis_ref,
            refutation_query_ref=due.refutation_query_ref,
            impact_envelope_id=due.impact_envelope_id,
            recovery_plan_id=due.recovery_plan_id,
            dry_run_receipt=due.dry_run_receipt,
        )
        if proposal.accepted:
            await state_store.write_state(
                key,
                {
                    "schema_version": "1.0.0",
                    "revision": int(existing.get("revision") or 1) + 1,
                    "state": "published",
                    "schedule_id": due.schedule_id,
                    "window_start": due.window_start.isoformat(),
                    "experiment_id": due.experiment_id,
                    "claimed_at": claimed_at.isoformat(),
                },
            )
            self.record_behavior("chaos_scheduler:published")
            return True
        await state_store.write_state(
            key,
            {
                "schema_version": "1.0.0",
                "revision": int(existing.get("revision") or 1) + 1,
                "state": "held",
                "reason": proposal.reason,
                "schedule_id": due.schedule_id,
                "window_start": due.window_start.isoformat(),
                "experiment_id": due.experiment_id,
                "claimed_at": claimed_at.isoformat(),
            },
        )
        await self._record_scheduler_hold(proposal.reason, due=due)
        return True

    async def _record_scheduler_hold(
        self,
        reason: str,
        *,
        due: DueChaosWindow | None = None,
    ) -> None:
        proposal = ChaosProposal(
            experiment_id=due.experiment_id if due is not None else "",
            action_type=due.action_type if due is not None else "",
            targets=(),
            accepted=False,
            reason=f"scheduler_{reason}",
            requested_target_count=len(due.targets) if due is not None else 0,
        )
        self._held_proposals.append(proposal)
        await self._persist_held_proposal(proposal)
        self.record_behavior(f"chaos_scheduler:{reason}")


def _proposal_from_record(record: dict[str, Any] | Any) -> ChaosProposal | None:
    if not isinstance(record, dict):
        return None
    raw_targets = record.get("targets")
    targets = (
        tuple(item for item in raw_targets if isinstance(item, str))
        if isinstance(raw_targets, list)
        else ()
    )
    return ChaosProposal(
        experiment_id=str(record.get("experiment_id") or ""),
        action_type=str(record.get("action_type") or ""),
        targets=targets,
        accepted=record.get("accepted") is True,
        reason=str(record.get("reason") or ""),
        requested_target_count=int(record.get("requested_target_count") or 0),
        targets_truncated=record.get("targets_truncated") is True,
        causal_hypothesis_ref=str(record.get("causal_hypothesis_ref") or ""),
        impact_envelope_id=str(record.get("impact_envelope_id") or ""),
        recovery_plan_id=str(record.get("recovery_plan_id") or ""),
    )


def _due_window_from_record(record: Mapping[str, Any]) -> DueChaosWindow | None:
    schedule_id = str(record.get("schedule_id") or "")
    window_start = _parse_time_or_none(record.get("window_start"))
    experiment_id = str(record.get("experiment_id") or "")
    action_type = str(record.get("action_type") or "")
    raw_targets = record.get("targets")
    targets = tuple(str(target) for target in raw_targets) if isinstance(raw_targets, list) else ()
    correlation_id = str(record.get("correlation_id") or "")
    causal_hypothesis_ref = str(record.get("causal_hypothesis_ref") or "")
    refutation_query_ref = str(record.get("refutation_query_ref") or "")
    impact_envelope_id = str(record.get("impact_envelope_id") or "")
    recovery_plan_id = str(record.get("recovery_plan_id") or "")
    dry_run_receipt = str(record.get("dry_run_receipt") or "")
    if (
        not schedule_id
        or window_start is None
        or not experiment_id
        or action_type not in CHAOS_ACTION_TYPES
        or not targets
        or any(not target for target in targets)
        or not correlation_id
        or not causal_hypothesis_ref
        or not refutation_query_ref
        or not impact_envelope_id
        or not recovery_plan_id
        or not dry_run_receipt
    ):
        return None
    return DueChaosWindow(
        schedule_id=schedule_id,
        window_start=window_start,
        experiment_id=experiment_id,
        action_type=action_type,
        targets=targets,
        correlation_id=correlation_id,
        causal_hypothesis_ref=causal_hypothesis_ref,
        refutation_query_ref=refutation_query_ref,
        impact_envelope_id=impact_envelope_id,
        recovery_plan_id=recovery_plan_id,
        dry_run_receipt=dry_run_receipt,
    )


def _scheduled_record_key(record: Mapping[str, Any]) -> str | None:
    schedule_id = str(record.get("schedule_id") or "")
    window_start = str(record.get("window_start") or "")
    if not schedule_id or not window_start:
        return None
    key = stable_idempotency_key(
        "loki-recurring-chaos-durable-window",
        schedule_id,
        window_start,
    )
    return f"{_SCHEDULED_PREFIX}{key}"


def _parse_time_or_none(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return _parse_time(value)
    except ValueError:
        return None
