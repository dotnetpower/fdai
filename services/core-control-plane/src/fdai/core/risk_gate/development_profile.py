"""Profile-scoped development promotion and current-authority verification."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any, Protocol

from fdai.core.measurement import OperationalPromotionReceipt
from fdai.core.measurement.operational_promotion import action_type_digest
from fdai.shared.contracts.development_authority import (
    authority_text_digest,
    canonical_authority_digest,
    development_promotion_target_digest,
    revalidate_development_authority,
)
from fdai.shared.contracts.models import (
    Action,
    DevelopmentActionConfirmation,
    DevelopmentAuthorityEnvelope,
    DevelopmentAuthorityGrant,
    DevelopmentBindingVerification,
    DevelopmentPromotionApproval,
    FullAuthorityDevelopmentProfile,
    Mode,
    OntologyActionType,
)
from fdai.shared.providers.development_authority import (
    DevelopmentAuthorityBindingRequest,
    DevelopmentAuthorityBindingSource,
    resolve_development_binding,
)


class DevelopmentPromotionReceiptVerifier(Protocol):
    def verify_development(
        self,
        *,
        profile_digest: str,
        action_type: OntologyActionType,
        receipt: OperationalPromotionReceipt,
    ) -> bool: ...


def mode_of(
    records: Mapping[tuple[str, str], Any],
    *,
    profile_digest: str,
    action_type: str,
    clock: Callable[[], datetime],
) -> Mode:
    record = records.get((profile_digest, action_type))
    if (
        record is not None
        and record.development_valid_until is not None
        and clock() >= record.development_valid_until
    ):
        return Mode.SHADOW
    return record.mode if record is not None else Mode.SHADOW


def record_of(
    records: Mapping[tuple[str, str], Any],
    *,
    profile_digest: str,
    action_type: str,
) -> Any:
    return records.get((profile_digest, action_type))


def consider_promotion(
    records: dict[tuple[str, str], Any],
    *,
    record_factory: Callable[..., Any],
    clock: Callable[[], datetime],
    profile: FullAuthorityDevelopmentProfile,
    confirmation: DevelopmentActionConfirmation,
    binding_source: DevelopmentAuthorityBindingSource,
    binding_request: DevelopmentAuthorityBindingRequest,
    binding_verification: DevelopmentBindingVerification,
    grant: DevelopmentAuthorityGrant,
    action_type: OntologyActionType,
    approval: DevelopmentPromotionApproval,
    metrics: Any = None,
) -> Any:
    """Promote only one exact development namespace under current Owner authority."""

    now = clock()
    current_verification = resolve_development_binding(
        binding_source,
        binding_request,
        now=now,
    )
    if current_verification != binding_verification:
        raise ValueError("development promotion binding changed")
    decision = revalidate_development_authority(
        profile,
        confirmation,
        current_verification,
        grant,
        now=now,
        original_quorum=grant.original_quorum,
    )
    if not decision.eligible:
        raise ValueError(f"development promotion authority is ineligible: {decision.reason_code}")
    binding = current_verification.binding
    current_target_digest = "sha256:" + action_type_digest(action_type)
    current_target = (action_type.name, action_type.version, current_target_digest)
    registered_targets = {
        (item.action_type, item.version, item.action_type_digest)
        for item in profile.registered_actions
    }
    expected_target = development_promotion_target_digest(
        action_type=action_type.name,
        action_type_version=action_type.version,
        action_type_digest=current_target_digest,
        reviewed_replay_digest=approval.reviewed_replay_digest,
        source_revision=approval.fdai_revision,
        scenario_set_version=approval.scenario_set_version,
        promotion_evidence_digest=approval.promotion_evidence_digest,
    )
    if (
        current_target not in registered_targets
        or approval.profile_digest != grant.profile_digest
        or approval.confirmation_digest != grant.confirmation_digest
        or approval.binding_verification_digest != current_verification.digest
        or approval.promotion_action_type != binding.action_type
        or approval.target_action_type != action_type.name
        or approval.target_action_type_version != action_type.version
        or approval.target_action_type_digest != current_target_digest
        or approval.promotion_target_digest != expected_target
        or binding.params_digest != expected_target
        or approval.reviewer_principal != grant.owner_principal
        or approval.valid_until != grant.valid_until
        or now >= approval.valid_until
        or approval.development_only is not True
        or approval.production_ready is not False
    ):
        raise ValueError("development promotion approval does not match current authority")
    if metrics is not None and metrics.action_type != action_type.name:
        raise ValueError("development promotion metrics action type does not match")
    key = (grant.profile_digest, action_type.name)
    prior = records.get(key)
    same_authority = (
        prior is not None
        and prior.mode is Mode.ENFORCE
        and prior.promotion_evidence_digest == approval.reviewed_replay_digest
    )
    record = record_factory(
        action_type=action_type.name,
        mode=Mode.ENFORCE,
        promoted_at=prior.promoted_at if same_authority and prior else now,
        metrics=metrics,
        promotion_evidence_digest=approval.reviewed_replay_digest,
        fdai_revision=approval.fdai_revision,
        scenario_set_version=approval.scenario_set_version,
        action_type_version=action_type.version,
        action_type_digest=action_type_digest(action_type),
        development_profile_digest=grant.profile_digest,
        development_only=True,
        production_ready=False,
        development_valid_until=grant.valid_until,
        original_quorum=grant.original_quorum,
        effective_quorum=grant.effective_quorum,
    )
    records[key] = record
    return record


def demote(
    records: dict[tuple[str, str], Any],
    *,
    record_factory: Callable[..., Any],
    clock: Callable[[], datetime],
    profile_digest: str,
    action_type_name: str,
) -> Any:
    if not profile_digest or not action_type_name:
        raise ValueError("development demotion identity MUST be complete")
    key = (profile_digest, action_type_name)
    prior = records.get(key)
    now = clock()
    record = record_factory(
        action_type=action_type_name,
        mode=Mode.SHADOW,
        promoted_at=prior.promoted_at if prior else None,
        demoted_at=now if prior is not None and prior.mode is Mode.ENFORCE else None,
        metrics=prior.metrics if prior else None,
        development_profile_digest=profile_digest,
        development_only=True,
        production_ready=False,
        development_valid_until=prior.development_valid_until if prior else None,
        original_quorum=prior.original_quorum if prior else None,
        effective_quorum=prior.effective_quorum if prior else None,
    )
    records[key] = record
    return record


def current_profile_digest(
    authority: DevelopmentAuthorityEnvelope,
    *,
    action: Action,
    action_type: OntologyActionType,
    profile: FullAuthorityDevelopmentProfile | None,
    binding_source: DevelopmentAuthorityBindingSource | None,
    executor_principal: str | None,
    clock: Callable[[], datetime],
) -> str | None:
    """Revalidate caller evidence against current trusted deployment state."""

    try:
        envelope = DevelopmentAuthorityEnvelope.model_validate(authority.model_dump(mode="python"))
    except (TypeError, ValueError):
        return None
    if profile is None or binding_source is None or not executor_principal:
        return None
    confirmation = envelope.confirmation
    grant = envelope.grant
    now = clock()
    if now.tzinfo is None or now.utcoffset() is None:
        return None
    request = DevelopmentAuthorityBindingRequest.from_action(
        action_type=action_type.name,
        action_id=str(action.action_id),
        target_ref=action.target_resource_ref,
        params=action.params,
        requester_principal=profile.owner_principal,
        executor_principal=executor_principal,
        idempotency_key=action.idempotency_key,
        rollback_contract=action.rollback_ref.kind.value,
    )
    try:
        verification = resolve_development_binding(binding_source, request, now=now)
    except ValueError:
        return None
    if verification != envelope.binding_verification:
        return None
    decision = revalidate_development_authority(
        profile,
        confirmation,
        verification,
        grant,
        now=now,
        original_quorum=grant.original_quorum,
    )
    if not decision.eligible or decision.grant != grant:
        return None
    binding = verification.binding
    registered = {
        (item.action_type, item.version, item.action_type_digest)
        for item in profile.registered_actions
    }
    current_action_type = (
        action_type.name,
        action_type.version,
        "sha256:" + action_type_digest(action_type),
    )
    if (
        grant.development_only is not True
        or grant.profile_digest != profile.digest
        or confirmation.profile_digest != grant.profile_digest
        or confirmation.digest != grant.confirmation_digest
        or confirmation.binding != binding
        or binding.digest != grant.action_binding_digest
        or verification.digest != grant.binding_verification_digest
        or not now < confirmation.expires_at
        or not now < verification.expires_at
        or not now < grant.valid_until
        or binding.action_type != action_type.name
        or binding.action_type_version != action_type.version
        or binding.action_type_digest != "sha256:" + action_type_digest(action_type)
        or binding.action_id != str(action.action_id)
        or binding.target_digest != authority_text_digest(action.target_resource_ref)
        or binding.params_digest != canonical_authority_digest(action.params)
        or binding.safeguards.idempotency_key != action.idempotency_key
        or binding.safeguards.rollback_contract_digest
        != authority_text_digest(action.rollback_ref.kind.value)
        or current_action_type not in registered
    ):
        return None
    return grant.profile_digest


__all__ = [
    "DevelopmentPromotionReceiptVerifier",
    "consider_promotion",
    "current_profile_digest",
    "demote",
    "mode_of",
    "record_of",
]
