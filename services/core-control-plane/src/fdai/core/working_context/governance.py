"""Revision-safe lifecycle and promotion authority for selection policies."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from threading import RLock
from types import MappingProxyType

from fdai.core.capability_catalog import CapabilityBindingKind, CapabilityRuntime
from fdai.core.working_context.composer import DEFAULT_CONTEXT_SELECTION_POLICY
from fdai.core.working_context.selection import ContextSelectionInput, ContextSelectionPolicy
from fdai.core.working_context.types import WorkingContext
from fdai.core.working_context.validation import (
    ContextSelectionInvariantError,
    execute_context_selection_policy,
)

_ID_PATTERN = re.compile(r"^[a-z][a-z0-9.-]{2,127}$")
_VERSION_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


class _Unchanged:
    pass


_UNCHANGED = _Unchanged()


class ContextPolicyState(StrEnum):
    DISABLED = "disabled"
    SHADOW = "shadow"
    ACTIVE = "active"
    KILLED = "killed"


@dataclass(frozen=True, slots=True, order=True)
class ContextPolicyIdentity:
    policy_id: str
    version: str

    def __post_init__(self) -> None:
        if _ID_PATTERN.fullmatch(self.policy_id) is None:
            raise ValueError("policy_id MUST be lowercase ASCII with dot or hyphen separators")
        if _VERSION_PATTERN.fullmatch(self.version) is None:
            raise ValueError("policy version MUST use MAJOR.MINOR.PATCH")

    @property
    def ref(self) -> str:
        return f"{self.policy_id}@{self.version}"


@dataclass(frozen=True, slots=True)
class ContextPolicyEvidence:
    """Frozen evidence window required for one explicit promotion."""

    evidence_id: str
    policy: ContextPolicyIdentity
    window_start: datetime
    window_end: datetime
    sample_count: int
    invariant_failures: int

    def __post_init__(self) -> None:
        if not self.evidence_id:
            raise ValueError("evidence_id MUST be non-empty")
        if self.window_start.tzinfo is None or self.window_end.tzinfo is None:
            raise ValueError("evidence window timestamps MUST be timezone-aware")
        if self.window_end <= self.window_start:
            raise ValueError("evidence window_end MUST be after window_start")
        if self.sample_count < 1:
            raise ValueError("evidence sample_count MUST be >= 1")
        if self.invariant_failures < 0:
            raise ValueError("evidence invariant_failures MUST be >= 0")


@dataclass(frozen=True, slots=True)
class ContextPolicyRecord:
    identity: ContextPolicyIdentity
    policy: ContextSelectionPolicy
    capability_id: str
    state: ContextPolicyState
    evidence: ContextPolicyEvidence | None = None
    rollback_to: ContextPolicyIdentity | None = None
    failure_reason: str | None = None
    kill_switch: bool = False


@dataclass(frozen=True, slots=True)
class ContextPolicySnapshot:
    revision: int
    active: ContextPolicyIdentity | None
    records: Mapping[ContextPolicyIdentity, ContextPolicyRecord]

    def __post_init__(self) -> None:
        object.__setattr__(self, "records", MappingProxyType(dict(self.records)))


class ContextPolicyGovernanceError(RuntimeError):
    """A lifecycle transition failed without changing the registry."""


class ContextSelectionPolicyAuthority:
    """Authoritative, capability-gated policy lifecycle with CAS updates."""

    def __init__(self, *, capability_runtime: CapabilityRuntime) -> None:
        baseline = DEFAULT_CONTEXT_SELECTION_POLICY
        identity = _identity_of(baseline)
        self._capability_runtime = capability_runtime
        self._lock = RLock()
        self._snapshot = ContextPolicySnapshot(
            revision=0,
            active=identity,
            records={
                identity: ContextPolicyRecord(
                    identity=identity,
                    policy=baseline,
                    capability_id="builtin.context-selection",
                    state=ContextPolicyState.ACTIVE,
                )
            },
        )

    def snapshot(self) -> ContextPolicySnapshot:
        with self._lock:
            return self._snapshot

    def with_capability_runtime(
        self,
        capability_runtime: CapabilityRuntime,
    ) -> ContextSelectionPolicyAuthority:
        """Return an authority over a new immutable runtime and the same snapshot."""

        replacement = ContextSelectionPolicyAuthority(capability_runtime=capability_runtime)
        with self._lock:
            replacement._snapshot = self._snapshot
        return replacement

    def install(
        self,
        policy: ContextSelectionPolicy,
        *,
        capability_id: str,
        expected_revision: int,
    ) -> ContextPolicySnapshot:
        identity = _identity_of(policy)
        self._require_capability(capability_id, identity)
        with self._lock:
            current = self._expect_revision(expected_revision)
            if identity in current.records:
                raise ContextPolicyGovernanceError(f"policy {identity.ref!r} is installed")
            records = dict(current.records)
            records[identity] = ContextPolicyRecord(
                identity=identity,
                policy=policy,
                capability_id=capability_id,
                state=ContextPolicyState.DISABLED,
            )
            return self._publish(current, records=records)

    def enable_shadow(
        self,
        identity: ContextPolicyIdentity,
        *,
        expected_revision: int,
    ) -> ContextPolicySnapshot:
        with self._lock:
            current = self._expect_revision(expected_revision)
            record = _require_record(current, identity)
            if record.kill_switch:
                raise ContextPolicyGovernanceError(
                    "clear review findings before re-enabling policy"
                )
            if record.state is not ContextPolicyState.DISABLED:
                raise ContextPolicyGovernanceError("only a disabled policy can enter shadow")
            records = dict(current.records)
            records[identity] = replace(record, state=ContextPolicyState.SHADOW)
            return self._publish(current, records=records)

    def promote(
        self,
        identity: ContextPolicyIdentity,
        *,
        evidence: ContextPolicyEvidence,
        rollback_to: ContextPolicyIdentity,
        expected_revision: int,
    ) -> ContextPolicySnapshot:
        if evidence.policy != identity:
            raise ContextPolicyGovernanceError("promotion evidence targets a different policy")
        if evidence.invariant_failures:
            raise ContextPolicyGovernanceError("promotion evidence contains invariant failures")
        with self._lock:
            current = self._expect_revision(expected_revision)
            candidate = _require_record(current, identity)
            if candidate.state is not ContextPolicyState.SHADOW or candidate.kill_switch:
                raise ContextPolicyGovernanceError("only a healthy shadow policy can be promoted")
            if current.active != rollback_to:
                raise ContextPolicyGovernanceError(
                    "rollback_to MUST name the current active policy"
                )
            active = _require_record(current, rollback_to)
            self._require_capability(candidate.capability_id, identity)
            records = dict(current.records)
            records[rollback_to] = replace(active, state=ContextPolicyState.SHADOW)
            records[identity] = replace(
                candidate,
                state=ContextPolicyState.ACTIVE,
                evidence=evidence,
                rollback_to=rollback_to,
                failure_reason=None,
            )
            return self._publish(current, records=records, active=identity)

    def demote(
        self,
        identity: ContextPolicyIdentity,
        *,
        reason: str,
        expected_revision: int,
    ) -> ContextPolicySnapshot:
        if not reason.strip():
            raise ContextPolicyGovernanceError("demotion reason MUST be non-empty")
        with self._lock:
            current = self._expect_revision(expected_revision)
            return self._demote_locked(current, identity, reason=reason, killed=False)

    def engage_kill_switch(
        self,
        identity: ContextPolicyIdentity,
        *,
        reason: str,
        expected_revision: int,
    ) -> ContextPolicySnapshot:
        if not reason.strip():
            raise ContextPolicyGovernanceError("kill-switch reason MUST be non-empty")
        with self._lock:
            current = self._expect_revision(expected_revision)
            return self._demote_locked(current, identity, reason=reason, killed=True)

    def active_policy(self) -> ContextSelectionPolicy:
        with self._lock:
            identity = self._snapshot.active
            if identity is None:
                raise ContextPolicyGovernanceError("no active context-selection policy")
            return _require_record(self._snapshot, identity).policy

    def shadow_policies(self, *, limit: int) -> tuple[ContextSelectionPolicy, ...]:
        if limit < 0:
            raise ValueError("shadow policy limit MUST be >= 0")
        with self._lock:
            records = sorted(self._snapshot.records.values(), key=lambda item: item.identity)
            return tuple(
                record.policy
                for record in records
                if record.state is ContextPolicyState.SHADOW and not record.kill_switch
            )[:limit]

    def select(self, selection_input: ContextSelectionInput) -> WorkingContext:
        with self._lock:
            active = self._snapshot.active
            if active is None:
                raise ContextPolicyGovernanceError("no active context-selection policy")
            policy = _require_record(self._snapshot, active).policy
        try:
            return execute_context_selection_policy(policy=policy, selection_input=selection_input)
        except ContextSelectionInvariantError as exc:
            with self._lock:
                if self._snapshot.active == active:
                    self._demote_locked(
                        self._snapshot,
                        active,
                        reason=f"invariant:{exc.code}",
                        killed=True,
                    )
            raise

    def _demote_locked(
        self,
        current: ContextPolicySnapshot,
        identity: ContextPolicyIdentity,
        *,
        reason: str,
        killed: bool,
    ) -> ContextPolicySnapshot:
        record = _require_record(current, identity)
        next_state = ContextPolicyState.KILLED if killed else ContextPolicyState.SHADOW
        records = dict(current.records)
        records[identity] = replace(
            record,
            state=next_state,
            failure_reason=reason,
            kill_switch=killed or record.kill_switch,
        )
        active = current.active
        if current.active == identity:
            active = record.rollback_to
            if active is not None:
                rollback = _require_record(current, active)
                if rollback.kill_switch:
                    active = None
                else:
                    records[active] = replace(rollback, state=ContextPolicyState.ACTIVE)
        return self._publish(current, records=records, active=active)

    def _require_capability(
        self,
        capability_id: str,
        identity: ContextPolicyIdentity,
    ) -> None:
        try:
            resolved = self._capability_runtime.resolve(capability_id)
        except LookupError as exc:
            raise ContextPolicyGovernanceError("policy capability is not active") from exc
        if resolved.binding.kind is not CapabilityBindingKind.CONTEXT_SELECTION_POLICY:
            raise ContextPolicyGovernanceError("capability is not a context-selection policy")
        if resolved.binding.target_ref != identity.ref:
            raise ContextPolicyGovernanceError("capability target does not match policy id/version")

    def _expect_revision(self, expected_revision: int) -> ContextPolicySnapshot:
        if self._snapshot.revision != expected_revision:
            raise ContextPolicyGovernanceError(
                f"context policy registry changed concurrently: expected={expected_revision}, "
                f"current={self._snapshot.revision}"
            )
        return self._snapshot

    def _publish(
        self,
        current: ContextPolicySnapshot,
        *,
        records: Mapping[ContextPolicyIdentity, ContextPolicyRecord],
        active: ContextPolicyIdentity | None | _Unchanged = _UNCHANGED,
    ) -> ContextPolicySnapshot:
        next_active = current.active if isinstance(active, _Unchanged) else active
        self._snapshot = ContextPolicySnapshot(
            revision=current.revision + 1,
            active=next_active,
            records=records,
        )
        return self._snapshot


def _identity_of(policy: ContextSelectionPolicy) -> ContextPolicyIdentity:
    return ContextPolicyIdentity(policy_id=policy.policy_id, version=policy.policy_version)


def _require_record(
    snapshot: ContextPolicySnapshot,
    identity: ContextPolicyIdentity,
) -> ContextPolicyRecord:
    try:
        return snapshot.records[identity]
    except KeyError as exc:
        raise ContextPolicyGovernanceError(f"policy {identity.ref!r} is not installed") from exc


__all__ = [
    "ContextPolicyEvidence",
    "ContextPolicyGovernanceError",
    "ContextPolicyIdentity",
    "ContextPolicyRecord",
    "ContextPolicySnapshot",
    "ContextPolicyState",
    "ContextSelectionPolicyAuthority",
]
