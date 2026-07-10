"""Tests for post-provision onboarding verification (slides 6-7)."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from fdai.core.onboarding import (
    EmptyResourceProbe,
    ObservedResource,
    ObservedRoleAssignment,
    OnboardingProbeError,
    OnboardingResourceKind,
    OnboardingVerifier,
    default_onboarding_spec,
)


def _all_resources() -> list[ObservedResource]:
    return [ObservedResource(kind=k) for k in OnboardingResourceKind]


def _all_roles() -> list[ObservedRoleAssignment]:
    spec = default_onboarding_spec()
    return [
        ObservedRoleAssignment(principal_ref=a.principal_ref, role=a.role, scope_kind=a.scope_kind)
        for a in spec.role_assignments
    ]


class _FakeProbe:
    def __init__(
        self,
        resources: Sequence[ObservedResource],
        roles: Sequence[ObservedRoleAssignment],
    ) -> None:
        self._resources = tuple(resources)
        self._roles = tuple(roles)

    async def observed_resources(self) -> Sequence[ObservedResource]:
        return self._resources

    async def observed_role_assignments(self) -> Sequence[ObservedRoleAssignment]:
        return self._roles


class _RaisingProbe:
    async def observed_resources(self) -> Sequence[ObservedResource]:
        raise OnboardingProbeError("ARG query failed")

    async def observed_role_assignments(self) -> Sequence[ObservedRoleAssignment]:
        return ()


@pytest.mark.asyncio
async def test_fully_provisioned_environment_is_ready() -> None:
    verifier = OnboardingVerifier(probe=_FakeProbe(_all_resources(), _all_roles()))

    report = await verifier.verify(default_onboarding_spec())

    assert report.ready is True
    assert report.missing_resources == ()
    assert report.missing_role_assignments == ()


@pytest.mark.asyncio
async def test_missing_resource_blocks_readiness() -> None:
    resources = [r for r in _all_resources() if r.kind is not OnboardingResourceKind.EVENT_BUS]
    verifier = OnboardingVerifier(probe=_FakeProbe(resources, _all_roles()))

    report = await verifier.verify(default_onboarding_spec())

    assert report.blocked is True
    assert OnboardingResourceKind.EVENT_BUS in report.missing_resources


@pytest.mark.asyncio
async def test_missing_role_assignment_blocks_readiness() -> None:
    verifier = OnboardingVerifier(probe=_FakeProbe(_all_resources(), []))

    report = await verifier.verify(default_onboarding_spec())

    assert report.blocked is True
    assert len(report.missing_role_assignments) == len(default_onboarding_spec().role_assignments)


@pytest.mark.asyncio
async def test_empty_probe_reports_everything_missing() -> None:
    verifier = OnboardingVerifier(probe=EmptyResourceProbe())

    report = await verifier.verify(default_onboarding_spec())

    assert report.ready is False
    assert len(report.missing_resources) == len(default_onboarding_spec().resources)


@pytest.mark.asyncio
async def test_probe_error_fails_closed_not_ready() -> None:
    verifier = OnboardingVerifier(probe=_RaisingProbe())

    report = await verifier.verify(default_onboarding_spec())

    assert report.ready is False
    assert report.error is not None
    assert "OnboardingProbeError" in report.error
