"""Post-provision onboarding verification (SRE-agent slides 6-7).

Verifies that a one-command-provisioned control plane has the expected
resource set and role assignments. Read-only and CSP-neutral: it reports
readiness, it never provisions or mutates.
"""

from __future__ import annotations

from fdai.core.onboarding.models import (
    ExpectedResource,
    ExpectedRoleAssignment,
    ObservedResource,
    ObservedRoleAssignment,
    OnboardingReport,
    OnboardingResourceKind,
    OnboardingSpec,
)
from fdai.core.onboarding.verifier import (
    EmptyResourceProbe,
    OnboardingProbeError,
    OnboardingVerifier,
    ResourceProbe,
    default_onboarding_spec,
)

__all__ = [
    "EmptyResourceProbe",
    "ExpectedResource",
    "ExpectedRoleAssignment",
    "ObservedResource",
    "ObservedRoleAssignment",
    "OnboardingProbeError",
    "OnboardingReport",
    "OnboardingResourceKind",
    "OnboardingSpec",
    "OnboardingVerifier",
    "ResourceProbe",
    "default_onboarding_spec",
]
