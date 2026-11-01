"""Component-specific dual-slot controller role fencing and durable restart/recovery transitions.

Each component (``core_control_plane``, ``operator_service``, ``lifecycle_agent``) maintains a
dual-slot (``blue`` / ``green``) fencing epoch and lease boundary. At most one slot per component
may hold ``role == "active"`` at any fencing epoch. Pointer-only switching without epoch+lease
fencing cannot execute, schema downgrades are rejected, and Trial/clock continuity anchors are
preserved across upgrade, rollback, and crash recovery.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Literal, get_args

SlotId = Literal["blue", "green"]
SlotRole = Literal["active", "standby", "draining", "fenced"]
ComponentKind = Literal["core_control_plane", "operator_service", "lifecycle_agent"]

_VALID_SLOTS: frozenset[str] = frozenset(get_args(SlotId))
_VALID_ROLES: frozenset[str] = frozenset(get_args(SlotRole))
_VALID_COMPONENTS: frozenset[str] = frozenset(get_args(ComponentKind))
_SHA256_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}\Z", re.ASCII)
_TRANSITION_KINDS = frozenset(
    {
        "bootstrap",
        "stage_candidate",
        "fence_active",
        "promote_standby",
        "rollback",
        "recover",
    }
)


class RoleFencingError(RuntimeError, ValueError):
    """Execution or slot transition violated dual-slot role, epoch, lease, or schema fencing."""


class TrialContinuityViolationError(RoleFencingError):
    """An upgrade, rollback, or recovery attempted to reset Trial or monotonic clock continuity."""


class SchemaDowngradeError(RoleFencingError):
    """A candidate slot or rollback attempted to downgrade the component schema version."""


def _other_slot(slot: SlotId) -> SlotId:
    return "green" if slot == "blue" else "blue"


def _require_aware(name: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise RoleFencingError(f"{name} MUST be a timezone-aware datetime")
    return value


def _require_positive_int(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise RoleFencingError(f"{name} MUST be a positive integer")
    return value


def _require_non_negative_int(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RoleFencingError(f"{name} MUST be a non-negative integer")
    return value


def _require_digest(name: str, value: object) -> str:
    if not isinstance(value, str) or _SHA256_DIGEST.fullmatch(value) is None:
        raise RoleFencingError(f"{name} MUST be a canonical sha256:<64 hex> digest")
    return value


def _compute_record_digest(**fields: object) -> str:
    recorded_at = _require_aware("recorded_at", fields["recorded_at"])
    payload = {**fields, "recorded_at": recorded_at.astimezone(UTC).isoformat()}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class ComponentSlotFence:
    """Fenced execution and continuity state for one slot of a component."""

    component: ComponentKind
    slot: SlotId
    role: SlotRole
    fencing_epoch: int
    binary_digest: str
    schema_version: int
    trial_anchor_at: datetime
    monotonic_clock_floor_ns: int
    lease_expires_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if self.component not in _VALID_COMPONENTS:
            raise RoleFencingError(f"unsupported component: {self.component!r}")
        if self.slot not in _VALID_SLOTS:
            raise RoleFencingError(f"unsupported slot: {self.slot!r}")
        if self.role not in _VALID_ROLES:
            raise RoleFencingError(f"unsupported role: {self.role!r}")
        _require_positive_int("fencing_epoch", self.fencing_epoch)
        _require_digest("binary_digest", self.binary_digest)
        _require_positive_int("schema_version", self.schema_version)
        _require_aware("trial_anchor_at", self.trial_anchor_at)
        _require_non_negative_int("monotonic_clock_floor_ns", self.monotonic_clock_floor_ns)
        _require_aware("lease_expires_at", self.lease_expires_at)
        _require_aware("updated_at", self.updated_at)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable dictionary of the slot fence state."""
        return {
            "component": self.component,
            "slot": self.slot,
            "role": self.role,
            "fencing_epoch": self.fencing_epoch,
            "binary_digest": self.binary_digest,
            "schema_version": self.schema_version,
            "trial_anchor_at": self.trial_anchor_at.astimezone(UTC).isoformat(),
            "monotonic_clock_floor_ns": self.monotonic_clock_floor_ns,
            "lease_expires_at": self.lease_expires_at.astimezone(UTC).isoformat(),
            "updated_at": self.updated_at.astimezone(UTC).isoformat(),
        }


@dataclass(frozen=True, slots=True)
class SelfUpgradeTransitionRecord:
    """Append-only durable transition record for dual-slot self-upgrade and crash recovery."""

    sequence: int
    component: ComponentKind
    from_slot: SlotId
    to_slot: SlotId
    fencing_epoch: int
    transition_kind: str
    health_verified: bool
    schema_version: int
    trial_anchor_preserved: bool
    recorded_at: datetime
    record_digest: str = ""

    def __post_init__(self) -> None:
        _require_positive_int("sequence", self.sequence)
        if self.component not in _VALID_COMPONENTS:
            raise RoleFencingError(f"unsupported component: {self.component!r}")
        if self.from_slot not in _VALID_SLOTS or self.to_slot not in _VALID_SLOTS:
            raise RoleFencingError("from_slot and to_slot MUST be 'blue' or 'green'")
        _require_positive_int("fencing_epoch", self.fencing_epoch)
        if self.transition_kind not in _TRANSITION_KINDS:
            raise RoleFencingError(f"unsupported transition_kind: {self.transition_kind!r}")
        if not isinstance(self.health_verified, bool) or not isinstance(
            self.trial_anchor_preserved, bool
        ):
            raise RoleFencingError("health_verified and trial_anchor_preserved MUST be booleans")
        if not self.trial_anchor_preserved:
            raise TrialContinuityViolationError(
                "transition record MUST preserve Trial continuity anchor"
            )
        _require_positive_int("schema_version", self.schema_version)
        _require_aware("recorded_at", self.recorded_at)
        expected = _compute_record_digest(
            sequence=self.sequence,
            component=self.component,
            from_slot=self.from_slot,
            to_slot=self.to_slot,
            fencing_epoch=self.fencing_epoch,
            transition_kind=self.transition_kind,
            health_verified=self.health_verified,
            schema_version=self.schema_version,
            trial_anchor_preserved=self.trial_anchor_preserved,
            recorded_at=self.recorded_at,
        )
        if not self.record_digest:
            object.__setattr__(self, "record_digest", expected)
        elif _require_digest("record_digest", self.record_digest) != expected:
            raise RoleFencingError("transition record_digest does not match canonical payload")


class ComponentSelfUpgradeController:
    """Enforce single-active-slot role fencing, continuity preservation, and crash recovery."""

    def __init__(self) -> None:
        self._slots: dict[ComponentKind, dict[SlotId, ComponentSlotFence]] = {}
        self._current_epoch: dict[ComponentKind, int] = {}
        self._rolled_back_digests: dict[ComponentKind, set[str]] = {}
        self._transition_log: list[SelfUpgradeTransitionRecord] = []

    @property
    def transition_log(self) -> tuple[SelfUpgradeTransitionRecord, ...]:
        return tuple(self._transition_log)

    def verify_transition_chain(self) -> bool:
        """Verify that `_transition_log` sequences are strictly 1..N and digests match."""
        for idx, rec in enumerate(self._transition_log, start=1):
            if rec.sequence != idx:
                return False
            try:
                expected = _compute_record_digest(
                    sequence=rec.sequence,
                    component=rec.component,
                    from_slot=rec.from_slot,
                    to_slot=rec.to_slot,
                    fencing_epoch=rec.fencing_epoch,
                    transition_kind=rec.transition_kind,
                    health_verified=rec.health_verified,
                    schema_version=rec.schema_version,
                    trial_anchor_preserved=rec.trial_anchor_preserved,
                    recorded_at=rec.recorded_at,
                )
            except Exception:  # noqa: BLE001
                return False
            if rec.record_digest != expected:
                return False
        return True

    def component_slots(self, component: ComponentKind) -> dict[SlotId, ComponentSlotFence]:
        if component not in self._slots:
            raise RoleFencingError(f"component {component!r} is not registered")
        return dict(self._slots[component])

    def current_epoch(self, component: ComponentKind) -> int:
        if component not in self._current_epoch:
            raise RoleFencingError(f"component {component!r} is not registered")
        return self._current_epoch[component]

    def register_component(
        self,
        *,
        component: ComponentKind,
        active_slot: SlotId = "blue",
        fencing_epoch: int = 1,
        binary_digest: str,
        schema_version: int,
        trial_anchor_at: datetime,
        monotonic_clock_floor_ns: int,
        lease_expires_at: datetime,
        now: datetime,
    ) -> dict[SlotId, ComponentSlotFence]:
        """Bootstrap dual-slot fences for a component with one active and one fenced slot."""
        _require_aware("now", now)
        _require_aware("trial_anchor_at", trial_anchor_at)
        if trial_anchor_at > now:
            raise TrialContinuityViolationError(
                "trial_anchor_at MUST NOT be in the future (trial_anchor_at <= now)"
            )
        if lease_expires_at <= now:
            raise RoleFencingError("initial active slot lease_expires_at MUST be in the future")
        standby_slot = _other_slot(active_slot)
        active_fence = ComponentSlotFence(
            component,
            active_slot,
            "active",
            fencing_epoch,
            binary_digest,
            schema_version,
            trial_anchor_at,
            monotonic_clock_floor_ns,
            lease_expires_at,
            now,
        )
        other_fence = replace(active_fence, slot=standby_slot, role="fenced", lease_expires_at=now)
        self._slots[component] = {active_slot: active_fence, standby_slot: other_fence}
        self._current_epoch[component] = fencing_epoch
        self._rolled_back_digests.setdefault(component, set())
        self._assert_single_active_invariant(component)
        self._append_transition(
            component,
            active_slot,
            active_slot,
            fencing_epoch,
            "bootstrap",
            True,
            schema_version,
            now,
        )
        return dict(self._slots[component])

    def assert_execution_allowed(
        self, component: ComponentKind, slot: SlotId, epoch: int, now: datetime
    ) -> ComponentSlotFence:
        """Verify that ``slot`` is the sole active writer at the current fencing epoch and lease."""
        _require_aware("now", now)
        _require_positive_int("epoch", epoch)
        slots = self._slots.get(component)
        if slots is None or slot not in slots:
            raise RoleFencingError(f"component {component!r} slot {slot!r} is not registered")
        self._assert_single_active_invariant(component)
        fence, auth_epoch = slots[slot], self._current_epoch[component]
        if fence.role != "active":
            raise RoleFencingError(
                f"execution denied for {component}:{slot} with non-active role {fence.role!r}"
            )
        if epoch != auth_epoch or fence.fencing_epoch != auth_epoch:
            raise RoleFencingError(
                f"execution denied for {component}:{slot} due to stale fencing epoch {epoch}"
            )
        if now >= fence.lease_expires_at:
            raise RoleFencingError(f"execution denied for {component}:{slot} due to expired lease")
        return fence

    def stage_candidate_slot(
        self,
        *,
        component: ComponentKind,
        candidate_slot: SlotId,
        binary_digest: str,
        candidate_schema_version: int,
        trial_anchor_at: datetime,
        monotonic_clock_floor_ns: int,
        lease_expires_at: datetime,
        now: datetime,
    ) -> ComponentSlotFence:
        """Stage a standby candidate slot while enforcing schema and Trial/clock continuity."""
        _require_aware("now", now)
        _require_aware("trial_anchor_at", trial_anchor_at)
        if trial_anchor_at > now:
            raise TrialContinuityViolationError(
                "trial_anchor_at MUST NOT be in the future (trial_anchor_at <= now)"
            )
        active = self._require_active_slot(component)
        if candidate_slot == active.slot:
            raise RoleFencingError("cannot stage candidate onto the currently active slot")
        if candidate_schema_version < active.schema_version:
            raise SchemaDowngradeError("candidate schema_version downgrades active schema_version")
        if trial_anchor_at != active.trial_anchor_at:
            raise TrialContinuityViolationError(
                "candidate MUST preserve installation trial_anchor_at"
            )
        if monotonic_clock_floor_ns < active.monotonic_clock_floor_ns:
            raise TrialContinuityViolationError("candidate MUST NOT lower monotonic_clock_floor_ns")
        epoch = self._current_epoch[component]
        staged = ComponentSlotFence(
            component,
            candidate_slot,
            "standby",
            epoch,
            binary_digest,
            candidate_schema_version,
            trial_anchor_at,
            monotonic_clock_floor_ns,
            lease_expires_at,
            now,
        )
        self._slots[component][candidate_slot] = staged
        self._assert_single_active_invariant(component)
        self._append_transition(
            component,
            active.slot,
            candidate_slot,
            epoch,
            "stage_candidate",
            False,
            candidate_schema_version,
            now,
        )
        return staged

    def promote_standby_slot(
        self,
        *,
        component: ComponentKind,
        standby_slot: SlotId,
        health_verified: bool,
        lease_expires_at: datetime,
        now: datetime,
        monotonic_clock_floor_ns: int | None = None,
        interrupt_after_fence: bool = False,
        allow_previously_rolled_back_digest: bool = False,
        allow_same_binary_digest: bool = False,
    ) -> ComponentSlotFence:
        """Fence the prior active slot first, bump epoch, and promote a verified standby slot."""
        _require_aware("now", now)
        _require_aware("lease_expires_at", lease_expires_at)
        if not health_verified:
            raise RoleFencingError(
                "standby slot promotion requires independent health/readiness verification"
            )
        if lease_expires_at <= now:
            raise RoleFencingError("promoted active lease_expires_at MUST be in the future")
        active = self._require_active_slot(component)
        if standby_slot == active.slot:
            raise RoleFencingError("standby_slot is already the active slot")
        candidate = self._slots[component][standby_slot]
        if candidate.role != "standby":
            raise RoleFencingError(
                f"only a 'standby' slot can be promoted (found role={candidate.role!r})"
            )
        if not allow_same_binary_digest and candidate.binary_digest == active.binary_digest:
            raise RoleFencingError(
                "cannot promote standby slot with identical binary_digest to active slot"
            )
        if (
            not allow_previously_rolled_back_digest
            and candidate.binary_digest in self._rolled_back_digests.get(component, set())
        ):
            raise RoleFencingError(
                "cannot promote standby slot with previously rolled-back binary_digest"
            )
        if candidate.schema_version < active.schema_version:
            raise SchemaDowngradeError("cannot promote standby slot with lower schema_version")
        if candidate.trial_anchor_at != active.trial_anchor_at:
            raise TrialContinuityViolationError("standby slot trial_anchor_at mismatch")
        clock_floor = (
            candidate.monotonic_clock_floor_ns
            if monotonic_clock_floor_ns is None
            else monotonic_clock_floor_ns
        )
        if clock_floor < max(active.monotonic_clock_floor_ns, candidate.monotonic_clock_floor_ns):
            raise TrialContinuityViolationError("promotion MUST NOT lower monotonic_clock_floor_ns")

        next_epoch = self._current_epoch[component] + 1
        self._slots[component][active.slot] = replace(
            active,
            role="fenced",
            fencing_epoch=next_epoch,
            monotonic_clock_floor_ns=clock_floor,
            lease_expires_at=now,
            updated_at=now,
        )
        self._current_epoch[component] = next_epoch
        self._append_transition(
            component,
            active.slot,
            standby_slot,
            next_epoch,
            "fence_active",
            True,
            candidate.schema_version,
            now,
        )
        if interrupt_after_fence:
            raise RoleFencingError("simulated crash after fencing prior active slot")

        promoted = replace(
            candidate,
            role="active",
            fencing_epoch=next_epoch,
            monotonic_clock_floor_ns=clock_floor,
            lease_expires_at=lease_expires_at,
            updated_at=now,
        )
        self._slots[component][standby_slot] = promoted
        self._assert_single_active_invariant(component)
        self._append_transition(
            component,
            active.slot,
            standby_slot,
            next_epoch,
            "promote_standby",
            True,
            promoted.schema_version,
            now,
        )
        return promoted

    def rollback_to_slot(
        self,
        *,
        component: ComponentKind,
        target_slot: SlotId,
        lease_expires_at: datetime,
        now: datetime,
        monotonic_clock_floor_ns: int | None = None,
    ) -> ComponentSlotFence:
        """Roll back to ``target_slot`` without schema downgrade or Trial/clock reset."""
        _require_aware("now", now)
        _require_aware("lease_expires_at", lease_expires_at)
        if lease_expires_at <= now:
            raise RoleFencingError("rollback lease_expires_at MUST be in the future")
        active = self._require_active_slot(component)
        if target_slot == active.slot:
            raise RoleFencingError("target_slot is already active")
        target = self._slots[component][target_slot]
        if target.schema_version < active.schema_version:
            raise SchemaDowngradeError(
                f"rollback to {target_slot} rejected due to schema downgrade"
            )
        if target.trial_anchor_at != active.trial_anchor_at:
            raise TrialContinuityViolationError("rollback target trial_anchor_at mismatch")
        floor_ns = max(active.monotonic_clock_floor_ns, target.monotonic_clock_floor_ns)
        if monotonic_clock_floor_ns is not None:
            if monotonic_clock_floor_ns < floor_ns:
                raise TrialContinuityViolationError(
                    "rollback MUST NOT lower monotonic_clock_floor_ns"
                )
            floor_ns = monotonic_clock_floor_ns

        next_epoch = self._current_epoch[component] + 1
        self._rolled_back_digests.setdefault(component, set()).add(active.binary_digest)
        self._slots[component][active.slot] = replace(
            active,
            role="fenced",
            fencing_epoch=next_epoch,
            monotonic_clock_floor_ns=floor_ns,
            lease_expires_at=now,
            updated_at=now,
        )
        restored = replace(
            target,
            role="active",
            fencing_epoch=next_epoch,
            schema_version=max(active.schema_version, target.schema_version),
            trial_anchor_at=active.trial_anchor_at,
            monotonic_clock_floor_ns=floor_ns,
            lease_expires_at=lease_expires_at,
            updated_at=now,
        )
        self._slots[component][target_slot] = restored
        self._current_epoch[component] = next_epoch
        self._assert_single_active_invariant(component)
        self._append_transition(
            component,
            active.slot,
            target_slot,
            next_epoch,
            "rollback",
            True,
            restored.schema_version,
            now,
        )
        return restored

    def recover_after_restart(
        self, *, component: ComponentKind, lease_expires_at: datetime, now: datetime
    ) -> ComponentSlotFence:
        """Recover one active slot from the durable transition log after a crash mid-cutover."""
        _require_aware("now", now)
        _require_aware("lease_expires_at", lease_expires_at)
        if lease_expires_at <= now:
            raise RoleFencingError("recovery lease_expires_at MUST be in the future")
        slots = self._slots.get(component)
        if slots is None:
            raise RoleFencingError(f"component {component!r} is not registered")
        component_records = [r for r in self._transition_log if r.component == component]
        if not component_records:
            raise RoleFencingError(f"no transition log records found for {component!r}")
        for idx, rec in enumerate(self._transition_log, start=1):
            if rec.sequence != idx:
                raise RoleFencingError("transition log sequence gap or corruption detected")

        last_record = component_records[-1]
        blue, green = slots["blue"], slots["green"]
        if blue.trial_anchor_at != green.trial_anchor_at:
            raise TrialContinuityViolationError("slot trial_anchor_at diverged across slots")
        max_schema = max(blue.schema_version, green.schema_version, last_record.schema_version)
        max_clock_floor = max(blue.monotonic_clock_floor_ns, green.monotonic_clock_floor_ns)
        winner_slot = last_record.to_slot if last_record.health_verified else last_record.from_slot
        if slots[winner_slot].schema_version < max_schema:
            other = _other_slot(winner_slot)
            if slots[other].schema_version >= max_schema:
                winner_slot = other
            else:
                raise SchemaDowngradeError("recovery cannot downgrade schema_version")

        fenced_slot = _other_slot(winner_slot)
        next_epoch = max(self._current_epoch[component], last_record.fencing_epoch) + 1
        self._slots[component][fenced_slot] = replace(
            slots[fenced_slot],
            role="fenced",
            fencing_epoch=next_epoch,
            monotonic_clock_floor_ns=max_clock_floor,
            lease_expires_at=now,
            updated_at=now,
        )
        recovered_active = replace(
            slots[winner_slot],
            role="active",
            fencing_epoch=next_epoch,
            schema_version=max_schema,
            trial_anchor_at=blue.trial_anchor_at,
            monotonic_clock_floor_ns=max_clock_floor,
            lease_expires_at=lease_expires_at,
            updated_at=now,
        )
        self._slots[component][winner_slot] = recovered_active
        self._current_epoch[component] = next_epoch
        self._assert_single_active_invariant(component)
        self._append_transition(
            component,
            last_record.from_slot,
            winner_slot,
            next_epoch,
            "recover",
            True,
            recovered_active.schema_version,
            now,
        )
        return recovered_active

    def _require_active_slot(self, component: ComponentKind) -> ComponentSlotFence:
        if component not in self._slots:
            raise RoleFencingError(f"component {component!r} is not registered")
        self._assert_single_active_invariant(component, require_one=True)
        for fence in self._slots[component].values():
            if fence.role == "active":
                return fence
        raise RoleFencingError(f"component {component!r} has no active slot")

    def _assert_single_active_invariant(
        self, component: ComponentKind, *, require_one: bool = False
    ) -> None:
        active_slots = [f.slot for f in self._slots[component].values() if f.role == "active"]
        if len(active_slots) > 1:
            raise RoleFencingError(
                f"dual-active split-brain detected for {component!r}: {active_slots}"
            )
        if require_one and not active_slots:
            raise RoleFencingError(f"no active slot currently available for {component!r}")

    def _append_transition(
        self,
        component: ComponentKind,
        from_slot: SlotId,
        to_slot: SlotId,
        fencing_epoch: int,
        transition_kind: str,
        health_verified: bool,
        schema_version: int,
        recorded_at: datetime,
    ) -> SelfUpgradeTransitionRecord:
        record = SelfUpgradeTransitionRecord(
            len(self._transition_log) + 1,
            component,
            from_slot,
            to_slot,
            fencing_epoch,
            transition_kind,
            health_verified,
            schema_version,
            True,
            recorded_at,
        )
        self._transition_log.append(record)
        return record


__all__ = [
    "ComponentKind",
    "ComponentSelfUpgradeController",
    "ComponentSlotFence",
    "RoleFencingError",
    "SchemaDowngradeError",
    "SelfUpgradeTransitionRecord",
    "SlotId",
    "SlotRole",
    "TrialContinuityViolationError",
]
