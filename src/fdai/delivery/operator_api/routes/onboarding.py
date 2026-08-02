"""Read-only onboarding readiness panel."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai.core.onboarding import OnboardingVerifier, ResourceProbe, default_onboarding_spec


class OnboardingPanel:
    """Project the post-provision resource and role verification report."""

    path = "/onboarding"
    name = "onboarding"

    def __init__(self, *, probe: ResourceProbe, configured: bool = True) -> None:
        self._verifier = OnboardingVerifier(probe=probe)
        self._configured = configured

    async def render(self, *, params: Mapping[str, str]) -> Mapping[str, Any]:
        del params
        report = await self._verifier.verify(default_onboarding_spec())
        return {
            "probe_mode": "configured" if self._configured else "not-configured",
            "ready": report.ready,
            "blocked": report.blocked,
            "missing_resources": [item.value for item in report.missing_resources],
            "missing_role_assignments": [list(item) for item in report.missing_role_assignments],
            "present_resource_count": report.present_resource_count,
            "present_role_count": report.present_role_count,
            "error": report.error,
        }


__all__ = ["OnboardingPanel"]
