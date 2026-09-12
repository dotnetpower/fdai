"""Inert content-addressed shadow-reversion command, writer seam, and orchestration.

``plan_effect_shadow_reversion`` in
[effect_shadow_reversion.py](effect_shadow_reversion.py) is proposal-only: it maps a
failed, timed-out, missing, stale, conflicting, censored, or otherwise unscorable effect
observation to ``RETURN_TO_SHADOW`` and stops there. Nothing can consume that proposal,
so a capability that failed independent effect verification has no represented path back
to shadow mode.

This module adds the missing consumer *contract* without adding a consumer. It defines:

- :class:`ShadowReversionCommand` - a content-addressed, no-authority command that binds
  the exact source revision, the ActionTypes being returned to shadow, the failed or
  unknown observation evidence, the reason code, the stop/rollback/kill-switch bindings,
  the expected current standing-authorization state, distinct human proposer and reviewer
  identities, and a stable idempotency key.
- :class:`ShadowReversionIntent` and :class:`ShadowReversionTerminal` - the two-phase
  audit records. The intent digest is computed before any mutation; the terminal digest
  covers that intent digest plus the outcome.
- :class:`ShadowReversionWriter` - the persistence Protocol a later, separately reviewed
  and authorized adapter would implement.
- :func:`apply_shadow_reversion` - a fail-closed orchestration seam that validates the
  command, records intent, delegates, and records a terminal outcome.

**Nothing here is wired.** No adapter implements :class:`ShadowReversionWriter`, and
``test_shadow_reversion_command.py`` proves that no agent, risk gate, executor, HIL
resume, workflow, control loop, composition, runtime, or delivery path imports this
module and that it never imports ``ActionPromotionRegistry``. A command grants no
execution or promotion authority and mutates no registry. Lowering an ActionType's real
autonomy still requires the durable provider boundary, the governed runtime cohort, the
independent review, and the explicit current human approval tracked by issue #632.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Literal, Protocol, runtime_checkable

from fdai.core.standing_authority.effect_shadow_reversion import (
    EffectEvidenceDisposition,
    ShadowReversionPlan,
    ShadowReversionTransition,
)
from fdai.core.standing_authority.lifecycle import LifecycleFence
from fdai.core.standing_authority.lifecycle_codec import (
    AuthorizationLifecycleError,
    aware_utc,
    content_digest,
    instant,
    require_aware,
    require_digest,
    require_text,
)

#: Contract version pinned into every command digest.
SHADOW_REVERSION_CONTRACT_VERSION: str = "a3e-shadow-reversion-v1"

_REVISION = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_ACTION_TYPE_ID = re.compile(r"^[a-z][a-z0-9.-]{0,63}@\d+\.\d+\.\d+$")
_BINDING_REF = re.compile(r"^[a-z][a-z0-9-]{0,31}:[A-Za-z0-9._/-]{1,128}$")

#: Only these dispositions may justify a reversion command. ``MATCHED`` and ``PENDING``
#: evidence never lowers authority, so a command carrying either is rejected.
REVERTIBLE_DISPOSITIONS: frozenset[EffectEvidenceDisposition] = frozenset(
    {
        EffectEvidenceDisposition.FAILED,
        EffectEvidenceDisposition.TIMED_OUT,
        EffectEvidenceDisposition.MISSING,
        EffectEvidenceDisposition.STALE,
        EffectEvidenceDisposition.CONFLICTING,
        EffectEvidenceDisposition.CENSORED,
        EffectEvidenceDisposition.UNSCORABLE,
    }
)


class ExpectedAuthorizationState(StrEnum):
    """Standing-authorization state the command expects to still observe."""

    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"


class ShadowReversionOutcome(StrEnum):
    """Terminal outcome of one orchestrated reversion attempt."""

    APPLIED = "applied"
    DUPLICATE = "duplicate"
    REJECTED_INTENT_NOT_RECORDED = "rejected_intent_not_recorded"
    REJECTED_STALE_AUTHORIZATION = "rejected_stale_authorization"
    REJECTED_WRITER_FAILURE = "rejected_writer_failure"
    REJECTED_TERMINAL_NOT_RECORDED = "rejected_terminal_not_recorded"


def _require_distinct_human(name: str, principal: str) -> None:
    if principal.startswith("agent:") or principal.startswith("identity:thor"):
        raise AuthorizationLifecycleError(f"{name} MUST be human, not agent/executor")
    if not principal.startswith("human:"):
        raise AuthorizationLifecycleError(f"{name} MUST start with 'human:'")
    require_text(name, principal)


@dataclass(frozen=True, slots=True)
class ShadowReversionSafetyBindings:
    """Stop condition, tested rollback, and kill switch bound to one command."""

    stop_condition_ref: str
    rollback_plan_ref: str
    kill_switch_ref: str
    blast_radius_scope: Literal["resource", "resource_group"]
    rollback_tested: Literal[True] = True

    def __post_init__(self) -> None:
        for name, value in (
            ("stop_condition_ref", self.stop_condition_ref),
            ("rollback_plan_ref", self.rollback_plan_ref),
            ("kill_switch_ref", self.kill_switch_ref),
        ):
            if _BINDING_REF.fullmatch(value) is None:
                raise AuthorizationLifecycleError(f"{name} MUST be a canonical scheme:path ref")
        if self.blast_radius_scope not in {"resource", "resource_group"}:
            raise AuthorizationLifecycleError("blast_radius_scope MUST be resource-bounded")
        if self.rollback_tested is not True:
            raise AuthorizationLifecycleError("reversion requires a tested rollback")

    def as_body(self) -> dict[str, object]:
        """Return the canonical digest body for these bindings."""

        return {
            "stop_condition_ref": self.stop_condition_ref,
            "rollback_plan_ref": self.rollback_plan_ref,
            "kill_switch_ref": self.kill_switch_ref,
            "blast_radius_scope": self.blast_radius_scope,
            "rollback_tested": True,
        }


@dataclass(frozen=True, slots=True)
class ShadowReversionCommand:
    """Content-addressed no-authority command to return ActionTypes to shadow mode."""

    source_revision_id: str
    reverted_action_types: tuple[str, ...]
    finding_id: str
    plan_id: str
    disposition: EffectEvidenceDisposition
    required_transition: ShadowReversionTransition
    reason_code: str
    expected_authorization: LifecycleFence
    expected_authorization_state: ExpectedAuthorizationState
    safety: ShadowReversionSafetyBindings
    proposer_principal: str
    reviewer_principal: str
    authentication_evidence_digest: str
    proposed_at: datetime
    contract_version: str = SHADOW_REVERSION_CONTRACT_VERSION
    execution_authority: Literal[False] = False
    promotion_authority: Literal[False] = False
    registry_mutated: Literal[False] = False
    recovery_authority: Literal[False] = False
    idempotency_key: str = field(init=False)
    command_id: str = field(init=False)

    def __post_init__(self) -> None:
        if self.contract_version != SHADOW_REVERSION_CONTRACT_VERSION:
            raise AuthorizationLifecycleError(
                f"contract_version MUST be {SHADOW_REVERSION_CONTRACT_VERSION!r}"
            )
        if _REVISION.fullmatch(self.source_revision_id) is None:
            raise AuthorizationLifecycleError(
                "source_revision_id MUST be a full immutable revision"
            )
        if not self.reverted_action_types:
            raise AuthorizationLifecycleError("reverted_action_types MUST be non-empty")
        if len(set(self.reverted_action_types)) != len(self.reverted_action_types):
            raise AuthorizationLifecycleError("reverted_action_types MUST contain distinct values")
        if self.reverted_action_types != tuple(sorted(self.reverted_action_types)):
            raise AuthorizationLifecycleError("reverted_action_types MUST use canonical order")
        for action_type_id in self.reverted_action_types:
            if _ACTION_TYPE_ID.fullmatch(action_type_id) is None:
                raise AuthorizationLifecycleError(
                    "reverted ActionType MUST be a canonical name@major.minor.patch id"
                )
        require_digest("finding_id", self.finding_id)
        require_digest("plan_id", self.plan_id)
        # A command exists only to lower authority. Matched or pending evidence
        # never justifies one, and NONE is not a reversion.
        if self.required_transition is not ShadowReversionTransition.RETURN_TO_SHADOW:
            raise AuthorizationLifecycleError(
                "shadow reversion command requires a RETURN_TO_SHADOW transition"
            )
        if self.disposition not in REVERTIBLE_DISPOSITIONS:
            raise AuthorizationLifecycleError(
                "shadow reversion command requires failed or unknown effect evidence"
            )
        require_text("reason_code", self.reason_code)
        _require_distinct_human("proposer_principal", self.proposer_principal)
        _require_distinct_human("reviewer_principal", self.reviewer_principal)
        if self.proposer_principal == self.reviewer_principal:
            raise AuthorizationLifecycleError(
                "proposer and reviewer MUST be distinct human principals"
            )
        require_digest("authentication_evidence_digest", self.authentication_evidence_digest)
        require_aware("proposed_at", self.proposed_at)
        if (
            self.execution_authority is not False
            or self.promotion_authority is not False
            or self.registry_mutated is not False
            or self.recovery_authority is not False
        ):
            raise AuthorizationLifecycleError("reversion command authority flags MUST be False")
        object.__setattr__(self, "idempotency_key", _idempotency_key(self))
        object.__setattr__(self, "command_id", content_digest(_command_body(self)))

    def audit_body(self) -> dict[str, object]:
        """Return the canonical replayable body of this command."""

        body = dict(_command_body(self))
        body["idempotency_key"] = self.idempotency_key
        body["command_id"] = self.command_id
        return body


@dataclass(frozen=True, slots=True)
class ShadowReversionIntent:
    """Phase-one audit record captured before any mutation is attempted."""

    command_id: str
    idempotency_key: str
    expected_authorization: LifecycleFence
    recorded_at: datetime
    intent_digest: str = field(init=False)

    def __post_init__(self) -> None:
        require_digest("command_id", self.command_id)
        require_digest("idempotency_key", self.idempotency_key)
        require_aware("recorded_at", self.recorded_at)
        object.__setattr__(
            self,
            "intent_digest",
            content_digest(
                {
                    "command_id": self.command_id,
                    "idempotency_key": self.idempotency_key,
                    "expected_authorization": _fence_body(self.expected_authorization),
                    "recorded_at": instant(aware_utc(self.recorded_at)),
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class ShadowReversionTerminal:
    """Phase-two audit record binding the intent digest to the terminal outcome."""

    command_id: str
    idempotency_key: str
    intent_digest: str
    outcome: ShadowReversionOutcome
    detail: str
    recorded_at: datetime
    execution_authority: Literal[False] = False
    promotion_authority: Literal[False] = False
    terminal_audit_digest: str = field(init=False)

    def __post_init__(self) -> None:
        require_digest("command_id", self.command_id)
        require_digest("idempotency_key", self.idempotency_key)
        require_digest("intent_digest", self.intent_digest)
        require_text("detail", self.detail)
        require_aware("recorded_at", self.recorded_at)
        if self.execution_authority is not False or self.promotion_authority is not False:
            raise AuthorizationLifecycleError("terminal authority flags MUST be False")
        object.__setattr__(
            self,
            "terminal_audit_digest",
            content_digest(
                {
                    "command_id": self.command_id,
                    "idempotency_key": self.idempotency_key,
                    "intent_digest": self.intent_digest,
                    "outcome": self.outcome.value,
                    "detail": self.detail,
                    "recorded_at": instant(aware_utc(self.recorded_at)),
                }
            ),
        )


@runtime_checkable
class ShadowReversionWriter(Protocol):
    """Persistence boundary a later authorized reversion adapter must implement.

    Every method fails closed. No adapter implements this Protocol today, so the
    orchestration below cannot run in the shipped runtime.
    """

    async def record_intent(self, intent: ShadowReversionIntent) -> bool:
        """Durably record phase-one intent. ``False`` blocks the attempt."""

        ...

    async def current_fence_matches(self, fence: LifecycleFence) -> bool:
        """Compare the exact expected authorization state against the primary store."""

        ...

    async def apply(
        self,
        command: ShadowReversionCommand,
        intent: ShadowReversionIntent,
    ) -> bool:
        """Return ``True`` when this call performed the reversion.

        ``False`` means the same ``idempotency_key`` already applied. Any
        uncertainty MUST raise instead of returning a permissive default.
        """

        ...

    async def record_terminal(self, terminal: ShadowReversionTerminal) -> bool:
        """Durably record the phase-two terminal audit record."""

        ...


async def apply_shadow_reversion(
    *,
    command: ShadowReversionCommand,
    writer: ShadowReversionWriter,
    recorded_at: datetime,
) -> ShadowReversionTerminal:
    """Fail-closed orchestration: intent, fence recheck, apply, terminal audit."""

    intent = ShadowReversionIntent(
        command_id=command.command_id,
        idempotency_key=command.idempotency_key,
        expected_authorization=command.expected_authorization,
        recorded_at=recorded_at,
    )

    def _terminal(outcome: ShadowReversionOutcome, detail: str) -> ShadowReversionTerminal:
        return ShadowReversionTerminal(
            command_id=command.command_id,
            idempotency_key=command.idempotency_key,
            intent_digest=intent.intent_digest,
            outcome=outcome,
            detail=detail,
            recorded_at=recorded_at,
        )

    try:
        if not await writer.record_intent(intent):
            return _terminal(
                ShadowReversionOutcome.REJECTED_INTENT_NOT_RECORDED,
                "phase-one intent was not durably recorded",
            )
        if not await writer.current_fence_matches(command.expected_authorization):
            terminal = _terminal(
                ShadowReversionOutcome.REJECTED_STALE_AUTHORIZATION,
                "expected standing-authorization state is no longer current",
            )
            await writer.record_terminal(terminal)
            return terminal
        applied = await writer.apply(command, intent)
    except Exception as error:  # noqa: BLE001 - any writer error fails closed
        return _terminal(
            ShadowReversionOutcome.REJECTED_WRITER_FAILURE,
            f"reversion writer failed: {type(error).__name__}",
        )

    terminal = _terminal(
        ShadowReversionOutcome.APPLIED if applied else ShadowReversionOutcome.DUPLICATE,
        "reversion applied" if applied else "idempotency key already applied",
    )
    try:
        recorded = await writer.record_terminal(terminal)
    except Exception as error:  # noqa: BLE001 - audit failure is reported, never swallowed
        return _terminal(
            ShadowReversionOutcome.REJECTED_TERMINAL_NOT_RECORDED,
            f"terminal audit failed: {type(error).__name__}",
        )
    if not recorded:
        return _terminal(
            ShadowReversionOutcome.REJECTED_TERMINAL_NOT_RECORDED,
            "phase-two terminal audit was not durably recorded",
        )
    return terminal


def build_shadow_reversion_command(
    *,
    plan: ShadowReversionPlan,
    source_revision_id: str,
    reverted_action_types: tuple[str, ...],
    expected_authorization: LifecycleFence,
    expected_authorization_state: ExpectedAuthorizationState,
    safety: ShadowReversionSafetyBindings,
    proposer_principal: str,
    reviewer_principal: str,
    authentication_evidence_digest: str,
    proposed_at: datetime,
) -> ShadowReversionCommand:
    """Build a command from a reversion plan, deriving identity from the plan."""

    if plan.required_transition is not ShadowReversionTransition.RETURN_TO_SHADOW:
        raise AuthorizationLifecycleError(
            "only a RETURN_TO_SHADOW plan can produce a reversion command"
        )
    return ShadowReversionCommand(
        source_revision_id=source_revision_id,
        reverted_action_types=tuple(sorted(set(reverted_action_types))),
        finding_id=plan.finding_id,
        plan_id=plan.plan_id,
        disposition=plan.disposition,
        required_transition=plan.required_transition,
        reason_code=plan.reason_code,
        expected_authorization=expected_authorization,
        expected_authorization_state=expected_authorization_state,
        safety=safety,
        proposer_principal=proposer_principal,
        reviewer_principal=reviewer_principal,
        authentication_evidence_digest=authentication_evidence_digest,
        proposed_at=proposed_at,
    )


def _fence_body(fence: LifecycleFence) -> dict[str, object]:
    return {
        "family_id": fence.family_id,
        "revision_id": fence.revision_id,
        "fencing_generation": fence.fencing_generation,
        "transition_digest": fence.transition_digest,
    }


def _idempotency_key(command: ShadowReversionCommand) -> str:
    """Stable across retries and proposers; distinct per revision, plan, and fence."""

    return content_digest(
        {
            "contract_version": SHADOW_REVERSION_CONTRACT_VERSION,
            "source_revision_id": command.source_revision_id,
            "reverted_action_types": list(command.reverted_action_types),
            "finding_id": command.finding_id,
            "plan_id": command.plan_id,
            "expected_authorization": _fence_body(command.expected_authorization),
        }
    )


def _command_body(command: ShadowReversionCommand) -> dict[str, object]:
    return {
        "contract_version": SHADOW_REVERSION_CONTRACT_VERSION,
        "source_revision_id": command.source_revision_id,
        "reverted_action_types": list(command.reverted_action_types),
        "finding_id": command.finding_id,
        "plan_id": command.plan_id,
        "disposition": command.disposition.value,
        "required_transition": command.required_transition.value,
        "reason_code": command.reason_code,
        "expected_authorization": _fence_body(command.expected_authorization),
        "expected_authorization_state": command.expected_authorization_state.value,
        "safety": command.safety.as_body(),
        "proposer_principal": command.proposer_principal,
        "reviewer_principal": command.reviewer_principal,
        "authentication_evidence_digest": command.authentication_evidence_digest,
        "proposed_at": instant(aware_utc(command.proposed_at)),
        "execution_authority": False,
        "promotion_authority": False,
        "registry_mutated": False,
        "recovery_authority": False,
    }


__all__ = [
    "REVERTIBLE_DISPOSITIONS",
    "SHADOW_REVERSION_CONTRACT_VERSION",
    "ExpectedAuthorizationState",
    "ShadowReversionCommand",
    "ShadowReversionIntent",
    "ShadowReversionOutcome",
    "ShadowReversionSafetyBindings",
    "ShadowReversionTerminal",
    "ShadowReversionWriter",
    "apply_shadow_reversion",
    "build_shadow_reversion_command",
]
