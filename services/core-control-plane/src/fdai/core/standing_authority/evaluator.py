"""Deterministic eligibility for one A3-E standing authorization.

FDAI-CONST-008 lists eleven conditions that must **all** hold before a pre-authorized
emergency mitigation may run. This module is the executable form of that list: the answer
is `INELIGIBLE` unless every condition passes, and the decision always names the first
condition that failed.

Two properties matter more than any individual check:

- **Silence is never authority.** Absence of a record, an unparsable record, or a missing
  field produces `INELIGIBLE`, never a permissive default.
- **This module decides nothing operational.** It returns a value object. No risk gate, no
  executor, and no escalation supervisor imports it, and a focused test fails if one does.
  Wiring it would raise autonomy, which requires shadow-cohort evidence and an independent
  promotion review that do not exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from fdai.core.standing_authority.record import (
    ApproverRole,
    AuthorizationMode,
    AuthorizationStatus,
    ScopeLevel,
    StandingAuthorization,
)

#: How long a responder confirmation stays current. Beyond this the delegation suspends
#: until the responders confirm again, because an unconfirmed rotation means no human has
#: accepted the page this delegation depends on. This is a hard safety bound, not a governed
#: threshold: FDAI-CONST-004 keeps hard bounds non-adaptive, so it is deliberately not
#: configurable and is not registered in the adaptive-threshold table.
RESPONDER_CONFIRMATION_MAX_AGE = timedelta(days=30)


class Eligibility(StrEnum):
    """Whether the delegation may carry an action right now."""

    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"


class AutonomyClass(StrEnum):
    """The autonomy class a candidate action was classified into."""

    A0 = "autonomy.a0"
    A1 = "autonomy.a1"
    A2 = "autonomy.a2"
    A3_H = "autonomy.a3_h"
    A3_E = "autonomy.a3_e"
    A4 = "autonomy.a4"


@dataclass(frozen=True, slots=True)
class AuthorizationRequest:
    """The candidate action a standing authorization is being tested against."""

    autonomy_class: AutonomyClass
    service_ref: str
    incident_class: str
    action_type: str
    action_type_version: str
    scope_value: str
    target_revision: str
    policy_digest: str
    evidence_revisions: tuple[str, ...]
    blast_radius: int
    max_duration_seconds: int
    reversible: bool
    rollback_contract: str | None
    executor_principal: str
    requester_principal: str


@dataclass(frozen=True, slots=True)
class StandingAuthorizationDecision:
    """Why the delegation is or is not eligible, with the first failing condition."""

    eligibility: Eligibility
    reason_code: str
    authorization_id: str
    authorization_revision: str
    evaluated_at: datetime

    @property
    def is_eligible(self) -> bool:
        return self.eligibility is Eligibility.ELIGIBLE


def evaluate_standing_authorization(
    authorization: StandingAuthorization | None,
    request: AuthorizationRequest,
    *,
    now: datetime,
) -> StandingAuthorizationDecision:
    """Return whether ``authorization`` currently covers ``request``.

    ``now`` must be timezone aware; a naive instant cannot be compared with a pinned
    validity interval and is treated as a missing time authority.
    """

    evaluated_at = now.astimezone(UTC) if now.tzinfo is not None else now
    if now.tzinfo is None:
        return _deny(authorization, "clock_not_trusted", evaluated_at)
    if authorization is None:
        return _deny(None, "authorization_absent", evaluated_at)

    reason = _first_failure(authorization, request, evaluated_at)
    if reason is not None:
        return _deny(authorization, reason, evaluated_at)
    return StandingAuthorizationDecision(
        eligibility=Eligibility.ELIGIBLE,
        reason_code="eligible",
        authorization_id=authorization.id,
        authorization_revision=authorization.authorization_revision,
        evaluated_at=evaluated_at,
    )


def _first_failure(
    authorization: StandingAuthorization,
    request: AuthorizationRequest,
    now: datetime,
) -> str | None:
    """Return the first constitutional condition that fails, or ``None``."""

    if authorization.mode is not AuthorizationMode.SHADOW:
        return "mode_not_shadow"
    if request.autonomy_class is AutonomyClass.A4:
        return "a4_never_delegable"
    if request.autonomy_class is not AutonomyClass.A3_E:
        return "autonomy_class_not_a3e"
    if authorization.status is not AuthorizationStatus.ACTIVE:
        return "authorization_not_active"
    if not authorization.valid_from <= now < authorization.valid_until:
        return "outside_validity_interval"

    quorum_reason = _quorum_failure(authorization, request)
    if quorum_reason is not None:
        return quorum_reason

    if authorization.scope.level not in {ScopeLevel.RESOURCE, ScopeLevel.RESOURCE_GROUP}:
        return "scope_too_wide"
    if authorization.service_ref != request.service_ref:
        return "service_mismatch"
    if authorization.scope.value != request.scope_value:
        return "scope_mismatch"

    pin_reason = _pin_failure(authorization, request)
    if pin_reason is not None:
        return pin_reason

    envelope_reason = _envelope_failure(authorization, request)
    if envelope_reason is not None:
        return envelope_reason

    if now + timedelta(seconds=request.max_duration_seconds) > authorization.valid_until:
        return "run_would_outlive_authorization"
    if now - authorization.responders.confirmed_at > RESPONDER_CONFIRMATION_MAX_AGE:
        return "responder_confirmation_stale"
    if authorization.responders.confirmed_at > now:
        return "responder_confirmation_in_the_future"
    if not authorization.evidence.history_reviewed:
        return "history_not_reviewed"
    if not (authorization.evidence.precedent_ref or authorization.evidence.scenario_evidence_ref):
        return "no_precedent_or_scenario_evidence"
    return None


def _quorum_failure(
    authorization: StandingAuthorization,
    request: AuthorizationRequest,
) -> str | None:
    principals = {approval.normalized_principal for approval in authorization.approvals}
    if len(principals) < authorization.quorum_required:
        return "quorum_not_met"

    roles = {approval.role for approval in authorization.approvals}
    if ApproverRole.SERVICE_OWNER not in roles:
        return "service_owner_approval_missing"
    if ApproverRole.OWNER not in roles:
        return "owner_authority_approval_missing"

    ineligible = {
        request.requester_principal.strip().casefold(),
        request.executor_principal.strip().casefold(),
        authorization.requested_by.strip().casefold(),
    }
    if principals & ineligible:
        return "self_approval"
    return None


def _pin_failure(
    authorization: StandingAuthorization,
    request: AuthorizationRequest,
) -> str | None:
    pins = authorization.pins
    if pins.policy_digest != request.policy_digest:
        return "policy_digest_mismatch"
    if pins.target_revision != request.target_revision:
        return "target_revision_mismatch"
    requested_version = f"{request.action_type}@{request.action_type_version}"
    if requested_version not in pins.action_type_versions:
        return "action_type_version_not_pinned"
    if set(pins.evidence_revisions) != set(request.evidence_revisions):
        return "evidence_revision_mismatch"
    return None


def _envelope_failure(
    authorization: StandingAuthorization,
    request: AuthorizationRequest,
) -> str | None:
    envelope = authorization.envelope
    if request.action_type not in envelope.action_types:
        return "action_type_outside_envelope"
    if request.incident_class not in authorization.incident_classes:
        return "incident_class_outside_envelope"
    if request.blast_radius > envelope.max_blast_radius:
        return "blast_radius_exceeds_envelope"
    if request.max_duration_seconds > envelope.max_duration_seconds:
        return "duration_exceeds_envelope"
    if not envelope.reversible or not request.reversible:
        return "action_not_reversible"
    if request.rollback_contract != envelope.rollback_contract:
        return "rollback_contract_mismatch"
    return None


def _deny(
    authorization: StandingAuthorization | None,
    reason_code: str,
    evaluated_at: datetime,
) -> StandingAuthorizationDecision:
    revision = "" if authorization is None else authorization.authorization_revision
    return StandingAuthorizationDecision(
        eligibility=Eligibility.INELIGIBLE,
        reason_code=reason_code,
        authorization_id="" if authorization is None else authorization.id,
        authorization_revision=revision,
        evaluated_at=evaluated_at,
    )


__all__ = [
    "RESPONDER_CONFIRMATION_MAX_AGE",
    "AuthorizationRequest",
    "AutonomyClass",
    "Eligibility",
    "StandingAuthorizationDecision",
    "evaluate_standing_authorization",
]
