"""Default tag-effect observation bindings for governed execution."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

import httpx

from fdai.core.mscp_profile import (
    ExpectedEffect,
    ExpectedEffectProvider,
    IndependentEffectObserver,
    ObservedEffect,
)
from fdai.shared.contracts.models import Action
from fdai.shared.providers.workload_identity import WorkloadIdentity


class _TagEffectVerifier(Protocol):
    async def expected(self, action: Action) -> ExpectedEffect | None: ...

    async def observe(
        self,
        action: Action,
        expected: ExpectedEffect,
    ) -> ObservedEffect | None: ...


def build_default_tag_effect_bindings(
    *,
    environment: Mapping[str, str],
    governed_execution_enabled: bool,
    expected_effect_provider: ExpectedEffectProvider | None,
    effect_observer: IndependentEffectObserver | None,
    execution_identities: Mapping[str, WorkloadIdentity] | None,
    identity: WorkloadIdentity | None,
    http_client: httpx.AsyncClient | None,
) -> tuple[ExpectedEffectProvider | None, IndependentEffectObserver | None]:
    """Compose built-in tag observers without overriding injected providers."""

    if (
        not governed_execution_enabled
        or expected_effect_provider is not None
        or effect_observer is not None
        or http_client is None
    ):
        return expected_effect_provider, effect_observer

    verifier: _TagEffectVerifier | None = None
    gateway_url = environment.get("FDAI_DEV_OPERATIONS_GATEWAY_URL", "").strip()
    gateway_audience = environment.get("FDAI_DEV_OPERATIONS_GATEWAY_AUDIENCE", "").strip()
    gateway_identity = (execution_identities or {}).get("identity/change") or identity
    if gateway_url and gateway_audience and gateway_identity is not None:
        from fdai.delivery.azure.gateway_tag_effect import GatewayTagEffectVerifier

        verifier = GatewayTagEffectVerifier(
            base_url=gateway_url,
            audience=gateway_audience,
            identity=gateway_identity,
            http_client=http_client,
        )

    subscription_id = environment.get("AZURE_SUBSCRIPTION_ID", "").strip()
    if subscription_id and identity is not None:
        from fdai.delivery.azure.subscription_tag_effect import (
            AzureSubscriptionTagEffectVerifier,
            TagEffectVerifierRouter,
        )

        verifier = TagEffectVerifierRouter(
            AzureSubscriptionTagEffectVerifier(
                subscription_id=subscription_id,
                identity=identity,
                http_client=http_client,
            ),
            verifier,
        )
    if verifier is None:
        return None, None
    return verifier.expected, verifier.observe


__all__ = [
    "build_default_tag_effect_bindings",
]
