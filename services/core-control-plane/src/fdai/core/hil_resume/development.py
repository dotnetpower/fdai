"""Full-authority development self-approval of one exact parked HIL action.

Core writes the ``development_authority`` park block when it parks an Owner's own request, inside
the park's request fingerprint. At resolve time the Owner's self-approval is admitted only when
the Operator's durable decision receipt carries the same fresh-authentication attestation, the
durable binding still matches the exact parked action and its re-read target revision, its scope
holds the action's whole declared blast radius inside the profile, and the shared development
evaluator admits it. Any other case keeps the no-self-approval refusal.

A parked category-only denial is Owner-only: no other approval counts, and the admitted Owner
self-approval dispatches only after the bound category revalidator reruns the full current
evaluation and still finds the same category-only denial.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from fdai_service_contracts.development_approval import (
    DEVELOPMENT_APPROVAL_ATTESTATION_FIELD,
    DEVELOPMENT_OWNER_ONLY_FIELD,
    DEVELOPMENT_PARK_BLOCK_FIELD,
    DevelopmentApprovalAttestation,
    development_owner_only,
    fresh_development_authentication,
)
from pydantic import ValidationError

from fdai.core.hil_resume.delegation import DelegationDecision, DelegationMode
from fdai.core.hil_resume.operator_receipt import OPERATOR_RECEIPT_PREFIX, operator_receipt_key
from fdai.core.hil_resume.results import ResolveOutcome, ResolveResult
from fdai.core.measurement.operational_promotion import action_type_digest
from fdai.shared.contracts.development_authority import (
    MAX_CONFIRMATION_AGE,
    DevelopmentAuthorityDecision,
    canonical_authority_digest,
    development_authority_audit,
    evaluate_development_authority,
    normalized_principal,
)
from fdai.shared.contracts.models import (
    Action,
    DevelopmentActionConfirmation,
    DevelopmentBindingVerification,
    ExecutionPath,
    FullAuthorityDevelopmentProfile,
    OntologyActionType,
    Rule,
)
from fdai.shared.providers.development_authority import (
    DevelopmentAuthorityBindingRequest,
    DevelopmentAuthorityBindingSource,
    DevelopmentBindingPreparer,
    RecordedDevelopmentBinding,
    resolve_development_binding,
)
from fdai.shared.providers.hil_channel import HilDecision
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.target_revision import TargetRevisionReader

DEVELOPMENT_ADMISSION_ACTOR = "system:development-admission"


@dataclass(frozen=True, slots=True)
class CategoryRevalidation:
    """Result of rerunning the full current evaluation for one admitted category park."""

    eligible: bool
    reason_code: str
    detail: Mapping[str, Any] = field(default_factory=dict)


class DevelopmentCategoryRevalidator(Protocol):
    """Rerun the current evaluation that parked one category-only denial.

    The ControlLoop implements it with its own kill switch, degradation, evidence, execution
    authorization, risk evaluation, and target-revision reads. Only an unchanged category-only
    denial with an unchanged target revision is eligible.
    """

    async def revalidate_category_park(
        self,
        parked: Mapping[str, Any],
        *,
        action: Action,
        rule: Rule,
    ) -> CategoryRevalidation: ...


def development_park_block(
    *,
    profile: FullAuthorityDevelopmentProfile,
    verification: DevelopmentBindingVerification,
    original_level: str,
    original_quorum: int,
    executor_identity_ref: str,
    category_denial: Mapping[str, Any] | None = None,
    evaluation_event: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the Core-written park block that records the original requirement exactly.

    ``category_denial`` marks a parked category-only denial as Owner-only and keeps the exact
    event it was evaluated on, so resolve can rerun that evaluation against current state.
    """
    binding = verification.binding
    body: dict[str, Any] = {
        "schema_version": "1.0.0",
        "owner_principal": profile.owner_principal,
        "action_id": binding.action_id,
        "binding_digest": binding.digest,
        "profile_digest": profile.digest,
        "target_revision": binding.target_revision,
        "dry_run_digest": binding.dry_run_digest,
        "scope_digest": canonical_authority_digest(binding.scope.model_dump(mode="json")),
        "original_level": original_level,
        "original_quorum": original_quorum,
        "effective_quorum": 1,
        "executor_identity_ref": executor_identity_ref,
        "expires_at": verification.expires_at.isoformat(),
    }
    if category_denial is not None:
        if evaluation_event is None:
            raise ValueError("a category park MUST keep the event it was evaluated on")
        body[DEVELOPMENT_OWNER_ONLY_FIELD] = True
        body["category_denial"] = dict(category_denial)
        body["evaluation_event"] = dict(evaluation_event)
    return {**body, "block_digest": canonical_authority_digest(body)}


def park_block(parked: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return the park block only when its content still matches its digest."""
    raw = parked.get(DEVELOPMENT_PARK_BLOCK_FIELD)
    if not isinstance(raw, Mapping):
        return None
    body = {str(key): value for key, value in raw.items() if key != "block_digest"}
    digest = raw.get("block_digest")
    if not isinstance(digest, str) or canonical_authority_digest(body) != digest:
        return None
    return {**body, "block_digest": digest}


def _deny(reason_code: str) -> DevelopmentAuthorityDecision:
    return DevelopmentAuthorityDecision(False, reason_code)


def _attestation(raw: object) -> DevelopmentApprovalAttestation | None:
    if not isinstance(raw, Mapping):
        return None
    try:
        return DevelopmentApprovalAttestation.model_validate(dict(raw))
    except (TypeError, ValueError, ValidationError):
        return None


async def admit_development_self_approval(
    *,
    profile: FullAuthorityDevelopmentProfile | None,
    bindings: DevelopmentBindingPreparer | None,
    revisions: TargetRevisionReader | None,
    state_store: StateStore,
    action_types: Mapping[str, OntologyActionType],
    parked: Mapping[str, Any],
    approver_oid: str,
    attestation: Mapping[str, Any] | None,
    now: datetime,
) -> DevelopmentAuthorityDecision:
    """Admit one Owner self-approval of the exact parked action, or return a bounded denial."""
    if profile is None or bindings is None or revisions is None:
        return _deny("development_authority_unwired")
    block = park_block(parked)
    if block is None:
        return _deny("park_block_invalid")
    attested = _attestation(attestation)
    if attested is None:
        return _deny("attestation_invalid")
    approval_id = str(parked.get("approval_id") or "")
    if (
        attested.approval_id != approval_id
        or attested.block_digest != block["block_digest"]
        or attested.binding_digest != block["binding_digest"]
        or attested.profile_digest != block["profile_digest"]
        or block["profile_digest"] != profile.digest
    ):
        return _deny("attestation_digest_mismatch")
    owner = normalized_principal(profile.owner_principal)
    if {
        normalized_principal(approver_oid),
        normalized_principal(str(parked.get("submitter_oid") or "")),
        normalized_principal(str(block.get("owner_principal") or "")),
        normalized_principal(attested.authenticated_principal),
    } != {owner}:
        return _deny("owner_identity_mismatch")
    try:
        parked_at = datetime.fromisoformat(str(parked.get("parked_at")))
        action = Action.model_validate(parked["action"])
        original_quorum = int(block["original_quorum"])
    except (KeyError, TypeError, ValueError, ValidationError):
        return _deny("parked_action_invalid")
    if parked_at.tzinfo is None or not fresh_development_authentication(
        auth_time=attested.authenticated_at,
        parked_at=parked_at,
        now=now,
    ):
        return _deny("authentication_not_fresh")
    receipt = await state_store.read_state(operator_receipt_key(approval_id))
    if (
        not isinstance(receipt, Mapping)
        or receipt.get("decision") != "approve"
        or normalized_principal(str(receipt.get("approver_oid") or "")) != owner
        or _attestation(receipt.get(DEVELOPMENT_APPROVAL_ATTESTATION_FIELD)) != attested
    ):
        return _deny("operator_receipt_mismatch")
    if (
        str(action.action_id) != block["action_id"]
        or action.executor_identity_ref != block["executor_identity_ref"]
    ):
        return _deny("parked_action_mismatch")
    verification = await bindings.read_verification(str(action.action_id))
    if verification is None or verification.binding.digest != block["binding_digest"]:
        return _deny("binding_unavailable")
    binding = verification.binding
    # Execution resolves the ActionType loaded now, so it must still be the registered one.
    current = action_types.get(action.action_type)
    if (
        current is None
        or current.execution_path is not ExecutionPath.DIRECT_API
        or (current.name, current.version, "sha256:" + action_type_digest(current))
        != (binding.action_type, binding.action_type_version, binding.action_type_digest)
    ):
        return _deny("current_action_type_mismatch")
    # A binding authorizes only its recorded scope, which must hold the whole declared blast
    # radius; the shared evaluator then refuses any scope the profile does not cover.
    try:
        required_scope = bindings.required_scope(action=action, action_type=current)
    except ValueError:
        return _deny("binding_scope_mismatch")
    if binding.scope != required_scope:
        return _deny("binding_scope_mismatch")
    try:
        resolve_development_binding(
            RecordedDevelopmentBinding(verification),
            DevelopmentAuthorityBindingRequest.from_action(
                action_type=action.action_type,
                action_id=str(action.action_id),
                target_ref=action.target_resource_ref,
                params=action.params,
                requester_principal=profile.owner_principal,
                executor_principal=profile.executor_principal,
                idempotency_key=action.idempotency_key,
                rollback_contract=action.rollback_ref.kind.value,
            ),
            now=now,
        )
    except ValueError:
        return _deny("binding_mismatch")
    current_revision = await revisions.read_revision(action.target_resource_ref)
    if current_revision is None or current_revision != verification.binding.target_revision:
        return _deny("target_revision_drift")
    try:
        confirmation = DevelopmentActionConfirmation(
            confirmation_id=attested.confirmation_id,
            profile_digest=profile.digest,
            binding=verification.binding,
            authenticated_principal=attested.authenticated_principal,
            authenticated_role="Owner",
            authentication_evidence_digest=attested.authentication_evidence_digest,
            authenticated_at=attested.authenticated_at,
            confirmed_by=approver_oid,
            confirmed_at=attested.confirmed_at,
            expires_at=min(attested.confirmed_at + MAX_CONFIRMATION_AGE, verification.expires_at),
            explicit_confirmation=True,
        )
    except (TypeError, ValueError, ValidationError):
        return _deny("confirmation_invalid")
    return evaluate_development_authority(
        profile,
        confirmation,
        verification,
        now=now,
        original_quorum=original_quorum,
    )


class HilDevelopmentApprovalMixin:
    """Admit an Owner's development self-approval before the ordinary resume claim."""

    _state_store: StateStore
    _request_clock: Callable[[], datetime]
    _action_types_by_name: Mapping[str, OntologyActionType]
    _development_profile: FullAuthorityDevelopmentProfile | None
    _development_bindings: DevelopmentAuthorityBindingSource | None
    _development_revisions: TargetRevisionReader | None
    _development_category_revalidator: DevelopmentCategoryRevalidator | None

    def _resolve_rule(self, parked: Mapping[str, object], *, action: Action) -> Rule | None:
        raise NotImplementedError

    async def _audit(
        self,
        *,
        action_kind: str,
        idempotency_key: str,
        approval_id: str,
        correlation_id: str,
        detail: Mapping[str, Any],
    ) -> None:
        raise NotImplementedError

    async def _mark_resolved(
        self,
        parked: Mapping[str, Any],
        *,
        decision: HilDecision,
        approver_oid: str,
        action_kind: str,
        detail: Mapping[str, Any],
    ) -> bool:
        raise NotImplementedError

    async def _race_result(self, approval_id: str, *, attempted: HilDecision) -> ResolveResult:
        raise NotImplementedError

    async def _admit_development_self_approval(
        self,
        parked: Mapping[str, Any],
        *,
        approver_oid: str,
        attestation: Mapping[str, Any],
    ) -> DelegationDecision | ResolveResult:
        """Return a direct approval for an admitted grant, or close the refused park.

        The Operator records the Owner's decision as the approval's only receipt, so a refused
        development self-approval would otherwise leave the park undecidable until it expires.
        An Owner-only category park is admitted only after its full current revalidation.
        """
        bindings = self._development_bindings
        decision = await admit_development_self_approval(
            profile=self._development_profile,
            bindings=bindings if isinstance(bindings, DevelopmentBindingPreparer) else None,
            revisions=self._development_revisions,
            state_store=self._state_store,
            action_types=self._action_types_by_name,
            parked=parked,
            approver_oid=approver_oid,
            attestation=attestation,
            now=self._request_clock(),
        )
        owner_only = development_owner_only(parked)
        revalidation: CategoryRevalidation | None = None
        if owner_only and decision.eligible and decision.grant is not None:
            revalidation = await self._revalidate_development_category_park(parked)
            if not revalidation.eligible:
                decision = DevelopmentAuthorityDecision(False, revalidation.reason_code)
        approval_id = str(parked.get("approval_id") or "")
        admitted = decision.eligible and decision.grant is not None
        await self._audit(
            action_kind=(
                "hil.resolve.development_self_approval"
                if admitted
                else "hil.resolve.development_self_approval_refused"
            ),
            idempotency_key=(
                f"{parked.get('idempotency_key') or approval_id}:hil_development_self_approval"
            ),
            approval_id=approval_id,
            correlation_id=str(parked.get("correlation_id") or approval_id),
            detail={
                **development_authority_audit(decision),
                "approver_oid": approver_oid,
                "original_level": (park_block(parked) or {}).get("original_level"),
                **(
                    {
                        "owner_self_approval_only": True,
                        "category_revalidation": (
                            {
                                "eligible": revalidation.eligible,
                                "reason_code": revalidation.reason_code,
                                **dict(revalidation.detail),
                            }
                            if revalidation is not None
                            else None
                        ),
                    }
                    if owner_only
                    else {}
                ),
            },
        )
        if admitted:
            return DelegationDecision(allowed=True, mode=DelegationMode.DIRECT)
        closed = await self._mark_resolved(
            parked,
            decision=HilDecision.REJECT,
            approver_oid=DEVELOPMENT_ADMISSION_ACTOR,
            action_kind="hil.resolve.development_self_approval_closed",
            detail={"attempted_approver_oid": approver_oid, "reason": decision.reason_code},
        )
        if not closed:
            return await self._race_result(approval_id, attempted=HilDecision.APPROVE)
        return ResolveResult(
            outcome=ResolveOutcome.SELF_APPROVAL_REFUSED,
            approval_id=approval_id,
            reason=decision.reason_code,
        )

    async def _revalidate_development_category_park(
        self, parked: Mapping[str, Any]
    ) -> CategoryRevalidation:
        """Rerun the bound current evaluation for one admitted category park, failing closed."""
        revalidator = self._development_category_revalidator
        if revalidator is None:
            return CategoryRevalidation(False, "category_revalidation_unwired")
        try:
            action = Action.model_validate(parked["action"])
        except (KeyError, TypeError, ValueError, ValidationError):
            return CategoryRevalidation(False, "parked_action_invalid")
        rule = self._resolve_rule(parked, action=action)
        if rule is None:
            return CategoryRevalidation(False, "rule_not_in_catalog")
        try:
            return await revalidator.revalidate_category_park(parked, action=action, rule=rule)
        except Exception:  # noqa: BLE001 - an unreadable current evaluation never dispatches
            return CategoryRevalidation(False, "category_revalidation_failed")


__all__ = [
    "DEVELOPMENT_ADMISSION_ACTOR",
    "OPERATOR_RECEIPT_PREFIX",
    "CategoryRevalidation",
    "DevelopmentCategoryRevalidator",
    "HilDevelopmentApprovalMixin",
    "admit_development_self_approval",
    "development_park_block",
    "park_block",
]
