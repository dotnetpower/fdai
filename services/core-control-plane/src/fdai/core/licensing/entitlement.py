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
a deployment less observable than an expired one. The crypto-free primitive
retains an explicit ``require_license`` input; the shipped runtime sets it and
may separately assert a composition-verified local issuer workstation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Final, Protocol

from fdai.core.capability_catalog.catalog import CapabilityCatalog, SideEffectClass
from fdai.core.licensing.installation_entitlement import (
    INSTALLATION_ENTITLEMENT_SCHEMA,
    InstallationEntitlementClaims,
    parse_installation_entitlement,
    signed_document_schema,
)
from fdai.core.licensing.token import LicenseClaims, LicenseTokenError, parse_license_token


class LicenseStatus(StrEnum):
    """Why the current entitlement looks the way it does."""

    ISSUER_WORKSTATION = "issuer-workstation"
    ACTIVE = "active"
    ABSENT = "absent"
    UNTRUSTED = "untrusted"
    NOT_YET_VALID = "not-yet-valid"
    EXPIRED = "expired"
    MISBOUND = "misbound"


class LicenseVerifier(Protocol):
    """Verify a detached signature over a canonical license document."""

    def verify(self, document: bytes, signature: bytes) -> bool: ...


class TrialEntitlementSource(Protocol):
    """Resolve durable Trial state into an entitlement at an exact time.

    Declared here so the token path never imports Trial storage. The concrete
    resolver lives in `trial_entitlement.py` and decides only from a committed,
    installation-bound record.
    """

    def resolve(self, *, now: datetime) -> Entitlement: ...


@dataclass(frozen=True, slots=True)
class DeploymentBinding:
    """Non-secret distribution identity and deployment digests."""

    distribution_id: str | None = None
    image_digest: str | None = None
    tenant_binding: str | None = None
    installation_binding: str | None = None


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
        """Return whether acting capabilities may be licensed in this mode."""

        return self.status in {
            LicenseStatus.ACTIVE,
            LicenseStatus.ISSUER_WORKSTATION,
        }


@dataclass(frozen=True, slots=True)
class LicenseEntitlementAuthority:
    """Resolve current capability availability without caching token validity.

    Composition may assert ``issuer_workstation`` only after proving possession
    of the dedicated matching private key. The domain layer never reads that
    key. Every ordinary call rechecks the signed token against the supplied
    time, so crossing ``not_after`` cannot retain a startup-time entitlement.
    """

    catalog: CapabilityCatalog
    token: str | None
    verifier: LicenseVerifier
    binding: DeploymentBinding = UNBOUND
    require_license: bool = True
    issuer_workstation: bool = False
    trial: TrialEntitlementSource | None = None

    def resolve(self, *, now: datetime) -> Entitlement:
        """Return the availability decision that applies at ``now``."""

        if self.issuer_workstation:
            if now.tzinfo is None:
                raise ValueError("entitlement resolution requires a timezone-aware clock")
            return Entitlement(
                status=LicenseStatus.ISSUER_WORKSTATION,
                available_capability_ids=_all_ids(self.catalog),
                reason="matching local issuer key bypasses the token requirement",
            )
        entitlement = resolve_entitlement(
            catalog=self.catalog,
            token=self.token,
            verifier=self.verifier,
            now=now,
            binding=self.binding,
            require_license=self.require_license,
        )
        if self.trial is None:
            return entitlement
        # Read-only capabilities always remain available, so a Trial is consulted by
        # whether acting capability is missing, not by whether the set is empty.
        if entitlement.available_capability_ids > _read_only_ids(self.catalog):
            return entitlement
        # A Trial substitutes for an absent or lapsed token; it never rescues one that
        # was rejected, misbound, or not yet valid.
        if entitlement.status not in {LicenseStatus.ABSENT, LicenseStatus.EXPIRED}:
            return entitlement
        trial_entitlement = self.trial.resolve(now=now)
        if not trial_entitlement.available_capability_ids:
            return entitlement
        return trial_entitlement


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
    if signed_document_schema(token) == INSTALLATION_ENTITLEMENT_SCHEMA:
        return _resolve_installation_entitlement(
            catalog=catalog, token=token, verifier=verifier, binding=binding
        )
    try:
        claims, document, signature = parse_license_token(token)
    except LicenseTokenError as exc:
        return _degraded(catalog, LicenseStatus.UNTRUSTED, f"license token is malformed: {exc}")
    failure = _signature_failure(catalog, verifier, document, signature)
    if failure is not None:
        return failure
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


def _signature_failure(
    catalog: CapabilityCatalog,
    verifier: LicenseVerifier,
    document: bytes,
    signature: bytes,
) -> Entitlement | None:
    try:
        verified = verifier.verify(document, signature)
    except Exception:  # noqa: BLE001 - a broken verifier degrades, it never crashes the runtime
        return _degraded(
            catalog,
            LicenseStatus.UNTRUSTED,
            "license signature could not be checked",
        )
    if not verified:
        return _degraded(
            catalog,
            LicenseStatus.UNTRUSTED,
            "license signature does not verify against the packaged public key",
        )
    return None


def _resolve_installation_entitlement(
    *,
    catalog: CapabilityCatalog,
    token: str,
    verifier: LicenseVerifier,
    binding: DeploymentBinding,
) -> Entitlement:
    """Grant the complete catalog only to the exact installation the document binds.

    The entitlement has no validity window, so its bindings are its only limit. Each
    must match exactly; a runtime that cannot assert one is misbound, never trusted.
    """
    try:
        claims, document, signature = parse_installation_entitlement(token)
    except LicenseTokenError as exc:
        return _degraded(
            catalog, LicenseStatus.UNTRUSTED, f"installation entitlement is malformed: {exc}"
        )
    failure = _signature_failure(catalog, verifier, document, signature)
    if failure is not None:
        return failure
    mismatch = _installation_mismatch(claims, binding)
    if mismatch is not None:
        return Entitlement(
            status=LicenseStatus.MISBOUND,
            available_capability_ids=_read_only_ids(catalog),
            reason=mismatch,
            license_id=claims.entitlement_id,
        )
    return Entitlement(
        status=LicenseStatus.ACTIVE,
        available_capability_ids=_all_ids(catalog),
        reason="installation entitlement grants the complete catalog",
        license_id=claims.entitlement_id,
    )


def _installation_mismatch(
    claims: InstallationEntitlementClaims, binding: DeploymentBinding
) -> str | None:
    if claims.distribution_id != binding.distribution_id:
        return "installation entitlement is bound to a different distribution"
    if claims.installation_binding != binding.installation_binding:
        return "installation entitlement is bound to a different installation"
    if claims.deployment_binding != binding.tenant_binding:
        return "installation entitlement is bound to a different deployment"
    return None


def _binding_mismatch(claims: LicenseClaims, binding: DeploymentBinding) -> str | None:
    if binding.distribution_id is not None and claims.distribution_id != binding.distribution_id:
        return "license is bound to a different distribution"
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
    "LicenseEntitlementAuthority",
    "LicenseStatus",
    "LicenseVerifier",
    "resolve_entitlement",
]
