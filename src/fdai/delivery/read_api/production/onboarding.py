"""Production Azure onboarding probe composition."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

import httpx

from fdai.core.onboarding import EmptyResourceProbe, ResourceProbe
from fdai.delivery.read_api.production import env_contract as _env
from fdai.delivery.read_api.production.config import ProdReadApiConfigError


@dataclass(frozen=True, slots=True)
class ProductionOnboarding:
    probe: ResourceProbe
    configured: bool
    shutdown_callbacks: tuple[Callable[[], Awaitable[None]], ...]


def build_production_onboarding(
    *,
    env: Mapping[str, str],
    shutdown_callbacks: tuple[Callable[[], Awaitable[None]], ...],
) -> ProductionOnboarding:
    """Build the all-or-none Azure onboarding probe from environment."""
    values = {name: env.get(name, "").strip() for name in _env.ONBOARDING_ENV}
    configured = {name for name, value in values.items() if value}
    if configured and len(configured) != len(_env.ONBOARDING_ENV):
        missing = sorted(set(_env.ONBOARDING_ENV) - configured)
        raise ProdReadApiConfigError(
            "Azure onboarding probe configuration is incomplete; missing: " + ", ".join(missing)
        )
    if not configured:
        return ProductionOnboarding(
            probe=EmptyResourceProbe(),
            configured=False,
            shutdown_callbacks=shutdown_callbacks,
        )

    from fdai.delivery.azure.onboarding import AzureOnboardingProbeConfig, AzureResourceProbe
    from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity

    http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=30.0, write=15.0, pool=5.0)
    )
    probe = AzureResourceProbe(
        config=AzureOnboardingProbeConfig(
            subscription_id=values["AZURE_SUBSCRIPTION_ID"],
            resource_group=values["AZURE_RESOURCE_GROUP"],
            executor_principal_id=values["FDAI_EXECUTOR_PRINCIPAL_ID"],
            event_role_definition_id=values["FDAI_EXECUTOR_EVENT_ROLE_DEFINITION_ID"],
            secret_role_definition_id=values["FDAI_EXECUTOR_SECRET_ROLE_DEFINITION_ID"],
        ),
        identity=ManagedIdentityWorkloadIdentity(http_client=http_client),
        http_client=http_client,
    )

    async def _close_onboarding_http() -> None:
        await http_client.aclose()

    return ProductionOnboarding(
        probe=probe,
        configured=True,
        shutdown_callbacks=(*shutdown_callbacks, _close_onboarding_http),
    )


__all__ = ["ProductionOnboarding", "build_production_onboarding"]
