"""Deterministic ActionType-to-license-capability map and sticky clock-rollback detector."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Final, Literal

from fdai.core.licensing.entitlement import Entitlement, LicenseEntitlementAuthority
from fdai.core.licensing.trial import TrialRecord, TrialStatus

BASE_MUTATION_CAPABILITY_ID: Final = "operations.typed-mutation"
DEFAULT_MAX_TRUSTED_SKEW: Final = timedelta(seconds=30)
_ACTION_TYPE_PATTERN: Final = re.compile(r"^[a-z][a-z0-9_]*\.[a-z0-9_.-]+$")

_EXACT_ACTION_CAPABILITY_MAP: Final[dict[str, frozenset[str]]] = {
    "tool.run-chaos-experiment": frozenset({BASE_MUTATION_CAPABILITY_ID, "chaos.run_experiment"}),
    "ops.rollback-kubernetes-rollout": frozenset(
        {BASE_MUTATION_CAPABILITY_ID, "operations.kubectl"}
    ),
    "remediate.kubernetes-network-policy": frozenset(
        {BASE_MUTATION_CAPABILITY_ID, "operations.kubectl"}
    ),
    "tool.open-incident-ticket": frozenset({BASE_MUTATION_CAPABILITY_ID, "incident.create"}),
    "tool.file-irp-followup": frozenset(
        {BASE_MUTATION_CAPABILITY_ID, "incident.platform-writeback"}
    ),
    "tool.file-security-followup": frozenset(
        {BASE_MUTATION_CAPABILITY_ID, "incident.platform-writeback"}
    ),
    "scheduler.create_task": frozenset({BASE_MUTATION_CAPABILITY_ID, "scheduler.create_task"}),
    "knowledge.register": frozenset({BASE_MUTATION_CAPABILITY_ID, "knowledge.register"}),
}

_ALLOWED_PREFIXES: Final = frozenset(
    {"governance", "ops", "remediate", "tool", "chaos", "scheduler", "knowledge"}
)


def required_license_capabilities_for_action_type(action_type_id: str) -> frozenset[str]:
    """Return the deterministic set of catalog capabilities required for an ActionType.

    Every acting ActionType requires the shared Thor ceiling ``operations.typed-mutation``
    plus any domain-specific selective acting capability mapped to that ActionType.
    """
    if (
        not isinstance(action_type_id, str)
        or _ACTION_TYPE_PATTERN.fullmatch(action_type_id) is None
    ):
        raise ValueError("action_type_id MUST be a canonical non-empty ActionType identifier")
    prefix = action_type_id.split(".", 1)[0]
    if prefix not in _ALLOWED_PREFIXES:
        raise ValueError(f"unsupported ActionType namespace for licensing: {prefix}")
    exact = _EXACT_ACTION_CAPABILITY_MAP.get(action_type_id)
    if exact is not None:
        return exact
    if prefix == "chaos":
        return frozenset({BASE_MUTATION_CAPABILITY_ID, "chaos.run_experiment"})
    if prefix == "scheduler":
        return frozenset({BASE_MUTATION_CAPABILITY_ID, "scheduler.create_task"})
    if prefix == "knowledge":
        return frozenset({BASE_MUTATION_CAPABILITY_ID, "knowledge.register"})
    if "kubernetes" in action_type_id or "kubectl" in action_type_id:
        return frozenset({BASE_MUTATION_CAPABILITY_ID, "operations.kubectl"})
    return frozenset({BASE_MUTATION_CAPABILITY_ID})


@dataclass(frozen=True, slots=True)
class ClockIntegrityDecision:
    """Result of evaluating host wall-clock monotonicity against trusted references."""

    clock_regressed: bool
    reason: str | None
    high_water_mark_utc: datetime
    host_now_utc: datetime
    trusted_now_utc: datetime | None = None


@dataclass(slots=True)
class TrustedTimeRollbackDetector:
    """Sticky wall-clock rollback detector with optional trusted-time reference anchor.

    Once a host clock regression or backward skew beyond ``max_trusted_skew`` is
    observed, ``clock_regressed`` latches True permanently for this detector and
    propagates into durable ``TrialRecord`` observations.
    """

    max_trusted_skew: timedelta = DEFAULT_MAX_TRUSTED_SKEW
    _high_water_mark_utc: datetime | None = None
    _clock_regressed: bool = False
    _reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.max_trusted_skew, timedelta) or self.max_trusted_skew < timedelta(0):
            raise ValueError("max_trusted_skew MUST be a non-negative timedelta")
        if self._high_water_mark_utc is not None:
            _require_utc(self._high_water_mark_utc)

    @property
    def clock_regressed(self) -> bool:
        return self._clock_regressed

    @property
    def high_water_mark_utc(self) -> datetime | None:
        return self._high_water_mark_utc

    def observe(
        self,
        *,
        host_now: datetime,
        trusted_now: datetime | None = None,
    ) -> ClockIntegrityDecision:
        """Observe ``host_now`` and latch sticky denial on any backward rollback."""
        _require_utc(host_now)
        if trusted_now is not None:
            _require_utc(trusted_now)
            if self._high_water_mark_utc is None or trusted_now > self._high_water_mark_utc:
                self._high_water_mark_utc = trusted_now
            if host_now + self.max_trusted_skew < trusted_now:
                self._clock_regressed = True
                self._reason = "host wall-clock trails trusted time reference beyond allowed skew"
        if self._high_water_mark_utc is not None and host_now < self._high_water_mark_utc:
            self._clock_regressed = True
            if self._reason is None:
                self._reason = "host wall-clock regressed behind previously observed UTC time"
        if self._high_water_mark_utc is None or host_now > self._high_water_mark_utc:
            self._high_water_mark_utc = host_now
        return ClockIntegrityDecision(
            clock_regressed=self._clock_regressed,
            reason=self._reason,
            high_water_mark_utc=self._high_water_mark_utc,
            host_now_utc=host_now,
            trusted_now_utc=trusted_now,
        )

    def observe_trial_record(
        self,
        record: TrialRecord,
        *,
        host_now: datetime,
        trusted_now: datetime | None = None,
    ) -> tuple[TrialRecord, ClockIntegrityDecision]:
        """Apply trusted-time and wall-clock rollback detection to a durable TrialRecord."""
        _require_utc(host_now)
        if self._high_water_mark_utc is None or record.last_observed_at > self._high_water_mark_utc:
            self._high_water_mark_utc = record.last_observed_at
        if record.clock_blocked:
            self._clock_regressed = True
            self._reason = self._reason or "durable Trial record is already clock-blocked"
        decision = self.observe(host_now=host_now, trusted_now=trusted_now)
        updated = record.observe(now=host_now)
        if decision.clock_regressed and not updated.clock_blocked:
            updated = TrialRecord(
                installation_binding=updated.installation_binding,
                deployment_binding=updated.deployment_binding,
                activated_at=updated.activated_at,
                last_observed_at=max(updated.last_observed_at, decision.high_water_mark_utc),
                revision=updated.revision,
                clock_blocked=True,
            )
        return updated, decision


@dataclass(frozen=True, slots=True)
class SelectiveActingLicenseDecision:
    """Secret-free selective capability decision for one ActionType."""

    allowed: bool
    action_type_id: str
    required_capability_ids: frozenset[str]
    missing_capability_ids: frozenset[str] = field(default_factory=frozenset)
    status: str = "absent"
    reason: str | None = None
    execution_authority: Literal[False] = False


@dataclass(frozen=True, slots=True)
class SelectiveActingLicenseVerifier:
    """Verify selective ActionType capability availability and clock integrity."""

    authority: LicenseEntitlementAuthority
    clock_detector: TrustedTimeRollbackDetector | None = None

    def evaluate(
        self,
        *,
        action_type_id: str,
        now: datetime,
        trusted_now: datetime | None = None,
    ) -> SelectiveActingLicenseDecision:
        """Evaluate whether ``action_type_id`` is licensed at ``now``."""
        _require_utc(now)
        required = required_license_capabilities_for_action_type(action_type_id)
        if self.clock_detector is not None:
            clock_decision = self.clock_detector.observe(host_now=now, trusted_now=trusted_now)
            if clock_decision.clock_regressed:
                return SelectiveActingLicenseDecision(
                    allowed=False,
                    action_type_id=action_type_id,
                    required_capability_ids=required,
                    missing_capability_ids=required,
                    status="clock_regression",
                    reason=clock_decision.reason,
                )
        entitlement: Entitlement = self.authority.resolve(now=now)
        if entitlement.reason and "clock regression" in entitlement.reason.lower():
            return SelectiveActingLicenseDecision(
                allowed=False,
                action_type_id=action_type_id,
                required_capability_ids=required,
                missing_capability_ids=required,
                status="clock_regression",
                reason=entitlement.reason,
            )
        missing = required - entitlement.available_capability_ids
        if not entitlement.is_active or missing:
            return SelectiveActingLicenseDecision(
                allowed=False,
                action_type_id=action_type_id,
                required_capability_ids=required,
                missing_capability_ids=missing or required,
                status=entitlement.status.value,
                reason=entitlement.reason
                or "selective acting license omits required ActionType capability",
            )
        return SelectiveActingLicenseDecision(
            allowed=True,
            action_type_id=action_type_id,
            required_capability_ids=required,
            missing_capability_ids=frozenset(),
            status=entitlement.status.value,
            reason=entitlement.reason,
        )


@dataclass(frozen=True, slots=True)
class ActionTypeCapabilityRegistry:
    """Deterministic registry mapping ActionType identifiers to required license capabilities."""

    overrides: Mapping[str, frozenset[str]] = field(default_factory=dict)

    def capabilities_for(self, action_type_id: str) -> frozenset[str]:
        base = required_license_capabilities_for_action_type(action_type_id)
        custom = self.overrides.get(action_type_id)
        if custom is None:
            return base
        return frozenset(custom) | {BASE_MUTATION_CAPABILITY_ID}


def evaluate_selective_capability(
    authority: LicenseEntitlementAuthority,
    *,
    action_type_id: str,
    now: datetime,
    trusted_now: datetime | None = None,
    clock_detector: TrustedTimeRollbackDetector | None = None,
) -> SelectiveActingLicenseDecision:
    """Evaluate selective ActionType capability availability and clock integrity."""
    verifier = SelectiveActingLicenseVerifier(
        authority=authority,
        clock_detector=clock_detector,
    )
    return verifier.evaluate(
        action_type_id=action_type_id,
        now=now,
        trusted_now=trusted_now,
    )


def _require_utc(moment: datetime) -> None:
    if (
        not isinstance(moment, datetime)
        or moment.tzinfo is None
        or moment.utcoffset() != timedelta(0)
        or moment.tzinfo is not UTC
    ):
        raise ValueError("licensing clock checks require an explicit UTC datetime")


__all__ = [
    "ActionTypeCapabilityRegistry",
    "BASE_MUTATION_CAPABILITY_ID",
    "ClockIntegrityDecision",
    "DEFAULT_MAX_TRUSTED_SKEW",
    "SelectiveActingLicenseDecision",
    "SelectiveActingLicenseVerifier",
    "TrialStatus",
    "TrustedTimeRollbackDetector",
    "evaluate_selective_capability",
    "required_license_capabilities_for_action_type",
]
