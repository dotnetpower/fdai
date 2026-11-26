"""Onboarding verification models (SRE-agent slides 6-7).

After a one-command provision (``azd`` + Terraform), slides 6-7 verify that
the expected resource set and role assignments actually landed. This module
models that check CSP-neutrally: an :class:`OnboardingSpec` declares the
resources and role assignments a healthy control plane MUST have, and the
verifier compares it to what a :class:`ResourceProbe` observes.

Everything here is read-only, inert data. No provisioning, no mutation - the
verifier reports readiness; it never creates a resource or a role.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum


class OnboardingResourceKind(StrEnum):
    """CSP-neutral resource kinds in the FDAI minimum inventory.

    Mirrors the Azure mapping in
    [app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md)
    without naming a vendor SKU - a fork's probe maps each kind to its
    concrete resource type.
    """

    EXECUTOR_IDENTITY = "executor_identity"
    RUNTIME = "runtime"
    CONTAINER_REGISTRY = "container_registry"
    STATE_STORE = "state_store"
    EVENT_BUS = "event_bus"
    SECRET_STORE = "secret_store"  # noqa: S105 - resource-kind label, not a secret
    OBSERVABILITY_LOGS = "observability_logs"
    OBSERVABILITY_APM = "observability_apm"


@dataclass(frozen=True, slots=True)
class ExpectedResource:
    """One resource the control plane MUST (or SHOULD) have after provision."""

    kind: OnboardingResourceKind
    description: str
    required: bool = True


@dataclass(frozen=True, slots=True)
class ExpectedRoleAssignment:
    """One role assignment the control plane MUST have.

    All fields are logical / CSP-neutral: ``principal_ref`` is a role name
    like ``executor``, ``role`` is a least-privilege role name, and
    ``scope_kind`` is the resource kind the assignment is scoped to. No
    tenant / subscription / principal object id ever appears here.
    """

    principal_ref: str
    role: str
    scope_kind: OnboardingResourceKind
    description: str = ""
    required: bool = True

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.principal_ref, self.role, self.scope_kind.value)


@dataclass(frozen=True, slots=True)
class ObservedResource:
    """A resource the probe found in the provisioned environment."""

    kind: OnboardingResourceKind


@dataclass(frozen=True, slots=True)
class ObservedRoleAssignment:
    """A role assignment the probe found."""

    principal_ref: str
    role: str
    scope_kind: OnboardingResourceKind

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.principal_ref, self.role, self.scope_kind.value)


@dataclass(frozen=True, slots=True)
class OnboardingSpec:
    """The declared expectation for a healthy control plane."""

    resources: tuple[ExpectedResource, ...]
    role_assignments: tuple[ExpectedRoleAssignment, ...]
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OnboardingReport:
    """The read-only outcome of an onboarding verification."""

    ready: bool
    missing_resources: tuple[OnboardingResourceKind, ...]
    missing_role_assignments: tuple[tuple[str, str, str], ...]
    present_resource_count: int
    present_role_count: int
    error: str | None = None

    @property
    def blocked(self) -> bool:
        return not self.ready


__all__ = [
    "ExpectedResource",
    "ExpectedRoleAssignment",
    "ObservedResource",
    "ObservedRoleAssignment",
    "OnboardingReport",
    "OnboardingResourceKind",
    "OnboardingSpec",
]
