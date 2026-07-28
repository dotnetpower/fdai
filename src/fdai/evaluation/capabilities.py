"""Pure capability and authority attenuation for evaluation sessions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from fdai_evaluation_sdk import AuthorityCeiling, Capability, SideEffectClass

_AUTHORITY_RANK = {
    AuthorityCeiling.SHADOW: 0,
    AuthorityCeiling.HIL: 1,
    AuthorityCeiling.ENFORCE: 2,
}


@dataclass(frozen=True, slots=True)
class CapabilityAxes:
    """Server-owned capability sets that must all authorize a request."""

    host_allowlist: frozenset[str]
    session_scope: frozenset[str]
    rbac_allowed: frozenset[str]
    promotion_allowed: frozenset[str]
    risk_allowed: frozenset[str]
    approval_allowed: frozenset[str]


@dataclass(frozen=True, slots=True)
class AuthorityAxes:
    """Independent ceilings whose minimum bounds the effective mode."""

    host: AuthorityCeiling
    session: AuthorityCeiling
    rbac: AuthorityCeiling
    promotion: AuthorityCeiling
    risk: AuthorityCeiling
    approval: AuthorityCeiling


@dataclass(frozen=True, slots=True)
class EffectiveCapabilities:
    """Allowed capabilities plus deterministic denial evidence."""

    allowed: tuple[Capability, ...]
    denied: tuple[str, ...]

    @property
    def allowed_ids(self) -> frozenset[str]:
        return frozenset(capability.capability_id for capability in self.allowed)


def attenuate_capabilities(
    *,
    requested: tuple[Capability, ...],
    catalog: Mapping[str, SideEffectClass],
    axes: CapabilityAxes,
) -> EffectiveCapabilities:
    """Intersect every authority axis and trust the host side-effect catalog."""

    common = (
        axes.host_allowlist
        & axes.session_scope
        & axes.rbac_allowed
        & axes.promotion_allowed
        & axes.risk_allowed
        & axes.approval_allowed
    )
    allowed: list[Capability] = []
    denied: list[str] = []
    for capability in requested:
        authoritative_class = catalog.get(capability.capability_id)
        if (
            capability.capability_id not in common
            or authoritative_class is None
            or capability.side_effect_class is not authoritative_class
        ):
            denied.append(capability.capability_id)
            continue
        allowed.append(capability)
    return EffectiveCapabilities(allowed=tuple(allowed), denied=tuple(sorted(denied)))


def attenuate_authority(
    requested: AuthorityCeiling,
    *,
    axes: AuthorityAxes,
) -> AuthorityCeiling:
    """Return the least authority granted by the request and every host axis."""

    ceilings = (
        requested,
        axes.host,
        axes.session,
        axes.rbac,
        axes.promotion,
        axes.risk,
        axes.approval,
    )
    return min(ceilings, key=_AUTHORITY_RANK.__getitem__)


__all__ = [
    "AuthorityAxes",
    "CapabilityAxes",
    "EffectiveCapabilities",
    "attenuate_authority",
    "attenuate_capabilities",
]
