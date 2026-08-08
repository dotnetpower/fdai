"""Onboarding verifier + probe seam + default spec (slides 6-7).

:class:`OnboardingVerifier` compares an :class:`OnboardingSpec` to what a
:class:`ResourceProbe` observes and returns an :class:`OnboardingReport`.
Fail-closed: a probe error yields a not-ready report with the error noted,
never a false "ready". Read-only throughout - it verifies, never provisions.

The upstream default probe is :class:`EmptyResourceProbe` (nothing observed
-> everything reported missing), so an unwired verifier reports "not ready"
rather than a fabricated success. A fork binds an Azure Resource Graph probe
under ``delivery/azure`` at the composition root.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from fdai.core.onboarding.models import (
    ExpectedResource,
    ExpectedRoleAssignment,
    ObservedResource,
    ObservedRoleAssignment,
    OnboardingReport,
    OnboardingResourceKind,
    OnboardingSpec,
)

_LOGGER = logging.getLogger(__name__)


class OnboardingProbeError(RuntimeError):
    """Raised by a probe when the environment cannot be inspected."""


@runtime_checkable
class ResourceProbe(Protocol):
    """Read the provisioned resource set + role assignments (read-only)."""

    async def observed_resources(self) -> Sequence[ObservedResource]:
        """Return the resources present in the provisioned environment."""
        ...

    async def observed_role_assignments(self) -> Sequence[ObservedRoleAssignment]:
        """Return the role assignments present in the environment."""
        ...


class EmptyResourceProbe:
    """Upstream default - observes nothing (everything reports missing)."""

    async def observed_resources(self) -> Sequence[ObservedResource]:
        return ()

    async def observed_role_assignments(self) -> Sequence[ObservedRoleAssignment]:
        return ()


class OnboardingVerifier:
    """Verify a provisioned control plane against its onboarding spec."""

    __slots__ = ("_probe",)

    def __init__(self, *, probe: ResourceProbe) -> None:
        self._probe = probe

    async def verify(self, spec: OnboardingSpec) -> OnboardingReport:
        try:
            resources = tuple(await self._probe.observed_resources())
            roles = tuple(await self._probe.observed_role_assignments())
        except OnboardingProbeError as exc:
            _LOGGER.warning("onboarding_probe_failed", extra={"error": str(exc)})
            return OnboardingReport(
                ready=False,
                missing_resources=tuple(r.kind for r in spec.resources if r.required),
                missing_role_assignments=tuple(a.key for a in spec.role_assignments if a.required),
                present_resource_count=0,
                present_role_count=0,
                error=f"{type(exc).__name__}:{exc}",
            )

        present_kinds = {r.kind for r in resources}
        present_role_keys = {a.key for a in roles}

        missing_resources = tuple(
            expected.kind
            for expected in spec.resources
            if expected.required and expected.kind not in present_kinds
        )
        missing_roles = tuple(
            expected.key
            for expected in spec.role_assignments
            if expected.required and expected.key not in present_role_keys
        )

        return OnboardingReport(
            ready=not missing_resources and not missing_roles,
            missing_resources=missing_resources,
            missing_role_assignments=missing_roles,
            present_resource_count=len(present_kinds),
            present_role_count=len(present_role_keys),
        )


def default_onboarding_spec() -> OnboardingSpec:
    """The FDAI minimum-inventory onboarding expectation (customer-agnostic)."""
    resources = (
        ExpectedResource(
            kind=OnboardingResourceKind.EXECUTOR_IDENTITY,
            description="User-assigned managed identity for the executor.",
        ),
        ExpectedResource(
            kind=OnboardingResourceKind.RUNTIME,
            description="Container Apps runtime hosting the core engine.",
        ),
        ExpectedResource(
            kind=OnboardingResourceKind.CONTAINER_REGISTRY,
            description="Registry for the compute image.",
        ),
        ExpectedResource(
            kind=OnboardingResourceKind.STATE_STORE,
            description="Postgres (audit + KPI + pgvector).",
        ),
        ExpectedResource(
            kind=OnboardingResourceKind.EVENT_BUS,
            description="Kafka-wire event bus (Event Hubs).",
        ),
        ExpectedResource(
            kind=OnboardingResourceKind.SECRET_STORE,
            description="Secret store (Key Vault) bridged to env.",
        ),
        ExpectedResource(
            kind=OnboardingResourceKind.OBSERVABILITY_LOGS,
            description="Log Analytics workspace.",
        ),
        ExpectedResource(
            kind=OnboardingResourceKind.OBSERVABILITY_APM,
            description="App Insights bound to the workspace.",
        ),
    )
    role_assignments = (
        ExpectedRoleAssignment(
            principal_ref="executor",
            role="event_bus_data_owner",
            scope_kind=OnboardingResourceKind.EVENT_BUS,
            description="Executor MI can consume and publish the governed Kafka stream.",
        ),
        ExpectedRoleAssignment(
            principal_ref="executor",
            role="secret_reader",
            scope_kind=OnboardingResourceKind.SECRET_STORE,
            description="Executor MI reads its secrets via Key Vault reference.",
        ),
    )
    return OnboardingSpec(resources=resources, role_assignments=role_assignments)


__all__ = [
    "EmptyResourceProbe",
    "OnboardingProbeError",
    "OnboardingVerifier",
    "ResourceProbe",
    "default_onboarding_spec",
]
