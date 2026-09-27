"""Trusted development-authority revalidation shared by Pantheon owners."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from fdai.shared.contracts.development_authority import (
    evaluate_development_authority,
    revalidate_development_authority,
)
from fdai.shared.contracts.models import (
    DevelopmentActionConfirmation,
    DevelopmentAuthorityEnvelope,
    DevelopmentAuthorityGrant,
    DevelopmentBindingVerification,
    FullAuthorityDevelopmentProfile,
)
from fdai.shared.providers.development_authority import (
    DevelopmentAuthorityBindingRequest,
    DevelopmentAuthorityBindingSource,
    resolve_development_binding,
)


def admit_development_authority(
    *,
    profile: FullAuthorityDevelopmentProfile | None,
    binding_source: DevelopmentAuthorityBindingSource | None,
    evidence: object,
    action: Mapping[str, Any],
    executor_principal: str | None,
    original_quorum: int,
    now: datetime,
) -> dict[str, Any] | None:
    """Resolve server-owned binding evidence and admit one exact confirmation."""

    if profile is None and evidence is None:
        return None
    if profile is None:
        raise ValueError("development authority evidence has no selected profile")
    if not isinstance(evidence, Mapping):
        raise ValueError("selected development profile requires authority evidence")
    if executor_principal is None or not executor_principal.strip():
        raise ValueError("development executor principal is unavailable")
    if evidence.get("schema_version") != "1.0.0":
        raise ValueError("development authority evidence schema is unsupported")
    try:
        confirmation = DevelopmentActionConfirmation.model_validate(evidence["confirmation"])
        request = _binding_request(
            action,
            executor_principal=executor_principal,
        )
        verification = resolve_development_binding(binding_source, request, now=now)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("development authority evidence is malformed") from exc

    supplied_verification = evidence.get("binding_verification")
    if supplied_verification is not None:
        try:
            persisted = DevelopmentBindingVerification.model_validate(supplied_verification)
        except (TypeError, ValueError) as exc:
            raise ValueError("development binding verification is malformed") from exc
        if persisted != verification:
            raise ValueError("development binding verification changed")

    raw_grant = evidence.get("grant")
    if raw_grant is None:
        decision = evaluate_development_authority(
            profile,
            confirmation,
            verification,
            now=now,
            original_quorum=original_quorum,
        )
    else:
        try:
            grant = DevelopmentAuthorityGrant.model_validate(raw_grant)
        except (TypeError, ValueError) as exc:
            raise ValueError("development authority grant is malformed") from exc
        decision = revalidate_development_authority(
            profile,
            confirmation,
            verification,
            grant,
            now=now,
            original_quorum=original_quorum,
        )
    if not decision.eligible or decision.grant is None:
        raise ValueError(f"development authority is ineligible: {decision.reason_code}")
    return DevelopmentAuthorityEnvelope(
        confirmation=confirmation,
        binding_verification=verification,
        grant=decision.grant,
    ).model_dump(mode="json")


def development_grant(evidence: object) -> DevelopmentAuthorityGrant | None:
    """Return the derived grant from one already validated envelope."""

    if not isinstance(evidence, Mapping):
        return None
    try:
        return DevelopmentAuthorityGrant.model_validate(evidence.get("grant"))
    except (TypeError, ValueError):
        return None


def development_binding_verification(
    evidence: object,
) -> DevelopmentBindingVerification | None:
    if not isinstance(evidence, Mapping):
        return None
    try:
        return DevelopmentBindingVerification.model_validate(evidence.get("binding_verification"))
    except (TypeError, ValueError):
        return None


def _binding_request(
    action: Mapping[str, Any],
    *,
    executor_principal: str,
) -> DevelopmentAuthorityBindingRequest:
    params = action.get("params")
    idempotency_key = action.get(
        "action_idempotency_key",
        action.get("idempotency_key"),
    )
    return DevelopmentAuthorityBindingRequest.from_action(
        action_type=str(action.get("action_type") or ""),
        action_id=str(action.get("action_id") or ""),
        target_ref=str(action.get("resource_id") or ""),
        params=dict(params) if isinstance(params, Mapping) else {},
        requester_principal=str(action.get("initiator_principal") or ""),
        executor_principal=executor_principal,
        idempotency_key=str(idempotency_key or ""),
        rollback_contract=str(action.get("rollback_contract") or ""),
    )


__all__ = [
    "admit_development_authority",
    "development_binding_verification",
    "development_grant",
]
