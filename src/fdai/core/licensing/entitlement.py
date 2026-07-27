"""Resolve which catalog capabilities a signed license makes available.

One safety rule governs this module: **a license moves the `available` axis
only**. It can never promote a capability out of shadow, widen a role, relax a
risk decision, or grant approval authority - those stay with the promotion
registry, RBAC, and the risk gate
(`.github/instructions/coding-conventions.instructions.md`). The worst outcome
of a forged token is therefore that an operator sees a capability listed, never
that a high-risk action executes.

Resolution fails toward safety. An absent, malformed, untrusted, out-of-window,
or misbound token degrades to the read-only subset of the catalog rather than
raising, so an expired license leaves an operator able to observe while unable
to act. Read-only capabilities are therefore never licensed: a license that
omits them still leaves them available, because a valid license must never make
a deployment less observable than an expired one. An unlicensed upstream
deployment keeps the full catalog, because licensing is a downstream
distribution concern; a distribution that wants fail-closed behavior sets
``require_license``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Final, Protocol

from fdai.core.capability_catalog.catalog import CapabilityCatalog, SideEffectClass
from fdai.core.licensing.token import LicenseClaims, LicenseTokenError, parse_license_token


class LicenseStatus(StrEnum):
    """Why the current entitlement looks the way it does."""

    ACTIVE = "active"
    ABSENT = "absent"
    UNTRUSTED = "untrusted"
    NOT_YET_VALID = "not-yet-valid"
    EXPIRED = "expired"
    MISBOUND = "misbound"


class LicenseVerifier(Protocol):
    """Verify a detached signature over a canonical license document."""

    def verify(self, document: bytes, signature: bytes) -> bool: ...


@dataclass(frozen=True, slots=True)
class DeploymentBinding:
    """What this deployment can prove about itself, as digests only."""

    image_digest: str | None = None
    tenant_binding: str | None = None


UNBOUND: Final = DeploymentBinding()
"""A deployment that asserts no image or tenant binding."""


@dataclass(frozen=True, slots=True)
class Entitlement:
    """The resolved availability decision. It grants no autonomy."""

    status: LicenseStatus
    available_capability_ids: frozenset[str] = field(default_factory=frozenset)
    reason: str | None = None
    license_id: str | None = None
    not_after: datetime | None = None

    @property
    def is_active(self) -> bool:
        return self.status is LicenseStatus.ACTIVE


def resolve_entitlement(
    *,
    catalog: CapabilityCatalog,
    token: str | None,
    verifier: LicenseVerifier,
    now: datetime,
    binding: DeploymentBinding = UNBOUND,
    require_license: bool = False,
) -> Entitlement:
    """Decide which capability ids are available under the supplied token."""
    if now.tzinfo is None:
        raise ValueError("entitlement resolution requires a timezone-aware clock")
    if token is None or not token.strip():
        if require_license:
            return _degraded(
                catalog,
                LicenseStatus.ABSENT,
                "this distribution requires a license token",
            )
        return Entitlement(
            status=LicenseStatus.ABSENT,
            available_capability_ids=_all_ids(catalog),
            reason="no license token is configured; the upstream catalog applies",
        )
    try:
        claims, document, signature = parse_license_token(token)
    except LicenseTokenError as exc:
        return _degraded(catalog, LicenseStatus.UNTRUSTED, f"license token is malformed: {exc}")
    try:
        verified = verifier.verify(document, signature)
    except Exception as exc:  # noqa: BLE001 - a broken verifier degrades, it never crashes the runtime
        return _degraded(
            catalog,
            LicenseStatus.UNTRUSTED,
            f"license signature could not be checked: {exc}",
        )
    if not verified:
        return _degraded(
            catalog,
            LicenseStatus.UNTRUSTED,
            "license signature does not verify against the packaged public key",
        )
    if now < claims.not_before:
        return _degraded(
            catalog,
            LicenseStatus.NOT_YET_VALID,
            "license is not valid yet",
            claims=claims,
        )
    if now >= claims.not_after:
        return _degraded(
            catalog,
            LicenseStatus.EXPIRED,
            "license expired; renew it to restore acting capabilities",
            claims=claims,
        )
    mismatch = _binding_mismatch(claims, binding)
    if mismatch is not None:
        return _degraded(catalog, LicenseStatus.MISBOUND, mismatch, claims=claims)
    return Entitlement(
        status=LicenseStatus.ACTIVE,
        available_capability_ids=(
            (_all_ids(catalog) & frozenset(claims.capability_ids)) | _read_only_ids(catalog)
        ),
        license_id=claims.license_id,
        not_after=claims.not_after,
    )


def _binding_mismatch(claims: LicenseClaims, binding: DeploymentBinding) -> str | None:
    if claims.image_digest is not None and claims.image_digest != binding.image_digest:
        return "license is bound to a different image digest"
    if claims.tenant_binding is not None and claims.tenant_binding != binding.tenant_binding:
        return "license is bound to a different deployment"
    return None


def _degraded(
    catalog: CapabilityCatalog,
    status: LicenseStatus,
    reason: str,
    *,
    claims: LicenseClaims | None = None,
) -> Entitlement:
    return Entitlement(
        status=status,
        available_capability_ids=_read_only_ids(catalog),
        reason=reason,
        license_id=None if claims is None else claims.license_id,
        not_after=None if claims is None else claims.not_after,
    )


def _all_ids(catalog: CapabilityCatalog) -> frozenset[str]:
    return frozenset(capability.capability_id for capability in catalog.list())


def _read_only_ids(catalog: CapabilityCatalog) -> frozenset[str]:
    return frozenset(
        capability.capability_id
        for capability in catalog.list()
        if capability.side_effect_class is SideEffectClass.READ
    )


__all__ = [
    "UNBOUND",
    "DeploymentBinding",
    "Entitlement",
    "LicenseStatus",
    "LicenseVerifier",
    "resolve_entitlement",
]
