"""Fail-closed admission for the full-authority development profile."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import ValidationError

from fdai.shared.contracts.development_authority_digest import (
    authority_text_digest,
    canonical_authority_digest,
    development_promotion_target_digest,
    normalized_principal,
)
from fdai.shared.contracts.models import (
    DevelopmentActionConfirmation,
    DevelopmentAuthorityGrant,
    DevelopmentBindingVerification,
    FullAuthorityDevelopmentProfile,
)

MAX_AUTHENTICATION_AGE = timedelta(minutes=10)
MAX_CONFIRMATION_AGE = timedelta(minutes=5)
MAX_CONFIRMATION_LIFETIME = timedelta(minutes=10)


@dataclass(frozen=True, slots=True)
class DevelopmentAuthorityDecision:
    """Eligibility and bounded reason for one development-authority attempt."""

    eligible: bool
    reason_code: str
    grant: DevelopmentAuthorityGrant | None = None
    binding_verification: DevelopmentBindingVerification | None = None


def evaluate_development_authority(
    profile: FullAuthorityDevelopmentProfile | Mapping[str, Any] | None,
    confirmation: DevelopmentActionConfirmation | Mapping[str, Any] | None,
    binding_verification: DevelopmentBindingVerification | Mapping[str, Any] | None,
    *,
    now: datetime,
    original_quorum: int,
) -> DevelopmentAuthorityDecision:
    """Validate exact profile, confirmation, current binding, and time.

    The optional profile is the sole selection mechanism. No environment,
    fork marker, role label, or caller language selects this path.
    """

    if profile is None:
        return _deny("profile_absent")
    if confirmation is None:
        return _deny("confirmation_absent")
    if binding_verification is None:
        return _deny("binding_verification_absent")
    if now.tzinfo is None or now.utcoffset() is None:
        return _deny("clock_not_trusted")
    if isinstance(original_quorum, bool) or original_quorum < 1:
        return _deny("original_quorum_invalid")
    try:
        parsed_profile = FullAuthorityDevelopmentProfile.model_validate(
            profile.model_dump(mode="python")
            if isinstance(profile, FullAuthorityDevelopmentProfile)
            else profile
        )
        parsed_confirmation = DevelopmentActionConfirmation.model_validate(
            confirmation.model_dump(mode="python")
            if isinstance(confirmation, DevelopmentActionConfirmation)
            else confirmation
        )
        parsed_verification = DevelopmentBindingVerification.model_validate(
            binding_verification.model_dump(mode="python")
            if isinstance(binding_verification, DevelopmentBindingVerification)
            else binding_verification
        )
    except (TypeError, ValueError, ValidationError):
        return _deny("authority_evidence_malformed")

    evaluated_at = now.astimezone(UTC)
    parsed_binding = parsed_verification.binding
    if not parsed_profile.valid_from <= evaluated_at < parsed_profile.valid_until:
        return _deny("profile_expired")
    if not parsed_verification.verified_at <= evaluated_at < parsed_verification.expires_at:
        return _deny("binding_verification_stale")
    if parsed_confirmation.profile_digest != parsed_profile.digest:
        return _deny("profile_digest_mismatch")
    if parsed_confirmation.binding != parsed_binding:
        return _deny("action_binding_mismatch")
    if not parsed_profile.scope.covers(parsed_binding.scope):
        return _deny("scope_escape")
    if (
        parsed_binding.source_revision != parsed_profile.source_revision
        or parsed_binding.catalog_revision != parsed_profile.catalog_revision
        or parsed_binding.policy_revision != parsed_profile.policy_revision
    ):
        return _deny("revision_mismatch")
    registered = (
        parsed_binding.action_type,
        parsed_binding.action_type_version,
        parsed_binding.action_type_digest,
    )
    if registered not in {
        (item.action_type, item.version, item.action_type_digest)
        for item in parsed_profile.registered_actions
    }:
        return _deny("action_not_registered")

    owner = normalized_principal(parsed_profile.owner_principal)
    executor = normalized_principal(parsed_profile.executor_principal)
    if (
        normalized_principal(parsed_confirmation.confirmed_by) != owner
        or normalized_principal(parsed_confirmation.authenticated_principal) != owner
        or normalized_principal(parsed_binding.requester_principal) != owner
    ):
        return _deny("owner_identity_mismatch")
    if normalized_principal(parsed_binding.executor_principal) != executor or owner == executor:
        return _deny("executor_identity_mismatch")

    if not (
        parsed_profile.valid_from
        <= parsed_confirmation.authenticated_at
        <= parsed_confirmation.confirmed_at
        <= evaluated_at
        < parsed_confirmation.expires_at
        <= parsed_profile.valid_until
    ):
        return _deny("confirmation_outside_validity")
    if evaluated_at - parsed_confirmation.authenticated_at > MAX_AUTHENTICATION_AGE:
        return _deny("authentication_stale")
    if evaluated_at - parsed_confirmation.confirmed_at > MAX_CONFIRMATION_AGE:
        return _deny("confirmation_stale")
    if (
        parsed_confirmation.expires_at - parsed_confirmation.confirmed_at
        > MAX_CONFIRMATION_LIFETIME
    ):
        return _deny("confirmation_lifetime_too_long")

    grant = DevelopmentAuthorityGrant(
        profile_id=parsed_profile.profile_id,
        profile_digest=parsed_profile.digest,
        confirmation_id=parsed_confirmation.confirmation_id,
        confirmation_digest=parsed_confirmation.digest,
        action_binding_digest=parsed_binding.digest,
        binding_verification_digest=parsed_verification.digest,
        owner_principal=parsed_profile.owner_principal,
        executor_principal=parsed_profile.executor_principal,
        original_quorum=original_quorum,
        valid_until=min(parsed_profile.valid_until, parsed_confirmation.expires_at),
    )
    return DevelopmentAuthorityDecision(
        True,
        "eligible",
        grant,
        parsed_verification,
    )


def revalidate_development_authority(
    profile: FullAuthorityDevelopmentProfile | Mapping[str, Any] | None,
    confirmation: DevelopmentActionConfirmation | Mapping[str, Any] | None,
    binding_verification: DevelopmentBindingVerification | Mapping[str, Any] | None,
    grant: DevelopmentAuthorityGrant | Mapping[str, Any] | None,
    *,
    now: datetime,
    original_quorum: int,
) -> DevelopmentAuthorityDecision:
    """Recompute and compare a previously derived grant exactly."""

    decision = evaluate_development_authority(
        profile,
        confirmation,
        binding_verification,
        now=now,
        original_quorum=original_quorum,
    )
    if not decision.eligible or decision.grant is None:
        return decision
    try:
        parsed_grant = DevelopmentAuthorityGrant.model_validate(
            grant.model_dump(mode="python")
            if isinstance(grant, DevelopmentAuthorityGrant)
            else grant
        )
    except (TypeError, ValueError, ValidationError):
        return _deny("grant_malformed")
    if parsed_grant != decision.grant:
        return _deny("grant_mismatch")
    return decision


def development_authority_audit(
    decision: DevelopmentAuthorityDecision,
) -> dict[str, object]:
    """Return an identity-safe audit projection without fabricating people."""

    grant = decision.grant
    return {
        "eligible": decision.eligible,
        "reason_code": decision.reason_code,
        "profile_id": grant.profile_id if grant is not None else None,
        "profile_digest": grant.profile_digest if grant is not None else None,
        "confirmation_id": grant.confirmation_id if grant is not None else None,
        "confirmation_digest": grant.confirmation_digest if grant is not None else None,
        "action_binding_digest": grant.action_binding_digest if grant is not None else None,
        "binding_verification_digest": (
            grant.binding_verification_digest if grant is not None else None
        ),
        "owner_principal": grant.owner_principal if grant is not None else None,
        "executor_principal": grant.executor_principal if grant is not None else None,
        "original_quorum": grant.original_quorum if grant is not None else None,
        "effective_quorum": grant.effective_quorum if grant is not None else None,
        "development_only": grant.development_only if grant is not None else None,
        "grant_digest": canonical_authority_digest(grant) if grant is not None else None,
        "current_binding_verification_digest": (
            decision.binding_verification.digest
            if decision.binding_verification is not None
            else None
        ),
    }


def _deny(reason_code: str) -> DevelopmentAuthorityDecision:
    return DevelopmentAuthorityDecision(False, reason_code)


__all__ = [
    "DevelopmentAuthorityDecision",
    "MAX_AUTHENTICATION_AGE",
    "MAX_CONFIRMATION_AGE",
    "MAX_CONFIRMATION_LIFETIME",
    "authority_text_digest",
    "canonical_authority_digest",
    "development_authority_audit",
    "development_promotion_target_digest",
    "evaluate_development_authority",
    "normalized_principal",
    "revalidate_development_authority",
]
