"""Convert effective provider probes into resolver observations."""

from __future__ import annotations

from fdai.shared.providers.execution_authorization import (
    EffectiveAuthorizationProbe,
    EffectiveAuthorizationProbeRequest,
    ExecutionIdentityBinding,
    ProviderPermissionMapping,
)

from ._canonical import canonical_digest
from .models import AccessObservationStatus, AuthorizationObservation


async def probe_authorization_observation(
    *,
    probe: EffectiveAuthorizationProbe,
    identity: ExecutionIdentityBinding,
    mapping: ProviderPermissionMapping,
    capability_id: str,
    scope_ref: str,
) -> AuthorizationObservation:
    result = await probe.probe(
        EffectiveAuthorizationProbeRequest(
            identity_ref=identity.identity_ref,
            capability_id=capability_id,
            operations=mapping.operations,
            audience_ref=mapping.audience_ref,
            scope_ref=scope_ref,
            mapping_digest=mapping.mapping_digest,
        )
    )
    status = AccessObservationStatus(result.status.value)
    observation_id = "authorization-observation:" + canonical_digest(
        {
            "identity_ref": identity.identity_ref,
            "capability_id": capability_id,
            "scope_ref": scope_ref,
            "mapping_digest": mapping.mapping_digest,
            "status": status.value,
            "observed_at": result.observed_at.isoformat(),
            "evidence_digest": result.evidence_digest,
        }
    )
    return AuthorizationObservation(
        observation_id=observation_id,
        identity_ref=identity.identity_ref,
        capability_id=capability_id,
        scope_ref=scope_ref,
        mapping_digest=mapping.mapping_digest,
        status=status,
        observed_at=result.observed_at,
        expires_at=result.expires_at,
        evidence_digest=result.evidence_digest,
    )


__all__ = ["probe_authorization_observation"]
