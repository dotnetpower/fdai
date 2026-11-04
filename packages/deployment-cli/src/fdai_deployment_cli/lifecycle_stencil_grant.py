"""Stencil variant identity, cross-layer Release/Plan/Bundle binding, and distribution grants.

Implements the shared contracts for:
- #2528: Same-version Stencil variant identity (`<base_release_version>@<stencil_id>`) without
  SemVer build-metadata ordering ambiguity, plus cross-layer verification across signed
  `ApplicationRelease`, `LifecyclePlan`, `RuntimeBundle`, customer configuration, and distribution
  grants.
- #2529 / #2530 / #2531: Installation-bound signed Stencil distribution grants
  (`fdai.stencil-distribution-grant.v1`) with domain-separated Ed25519 signatures, strict separation
  from runtime licensing (`fdai.installation-entitlement.v1`) and catalog export keys, and
  customer-channel (`RELEASE_CANDIDATE`, `RELEASE`) scoping.
"""

from __future__ import annotations

import hashlib
import re
from base64 import b64decode, b64encode
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest, load_json_object
from fdai_deployment_cli.lifecycle_plan import LifecyclePlan
from fdai_deployment_cli.lifecycle_release import (
    APPLICATION_COMPONENT_RELEASE_SCHEMA,
    ApplicationRelease,
    LifecycleRelease,
)
from fdai_deployment_cli.runtime_release import is_release_id

STENCIL_VARIANT_BINDING_SCHEMA: Literal["fdai.stencil-variant-binding.v1"] = (
    "fdai.stencil-variant-binding.v1"
)
STENCIL_DISTRIBUTION_GRANT_SCHEMA: Literal["fdai.stencil-distribution-grant.v1"] = (
    "fdai.stencil-distribution-grant.v1"
)
STENCIL_GRANT_PURPOSE: Literal["stencil-distribution-eligibility"] = (
    "stencil-distribution-eligibility"
)
STENCIL_GRANT_SIGNATURE_DOMAIN = b"fdai.stencil-distribution-grant.v1\n"

CUSTOMER_ENTITLED_CHANNELS: frozenset[str] = frozenset({"RELEASE_CANDIDATE", "RELEASE"})
LOCKED_SAFETY_CORE_WORKLOADS: frozenset[str] = frozenset({"core-control-plane", "operator-service"})
LOCKED_SAFETY_CORE_PANELS: frozenset[str] = frozenset({"audit", "dashboard", "settings-general"})

_STENCIL_ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,62}\Z", re.ASCII)
_GRANT_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{2,127}\Z", re.ASCII)
_INSTALLATION_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{1,127}\Z", re.ASCII)
_PRINCIPAL_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:@/-]{1,159}\Z", re.ASCII)
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}\Z", re.ASCII)
_BASE_SEMVER_RE = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z",
    re.ASCII,
)


class StencilBindingError(ValueError):
    """Raised when Stencil variant or distribution grant verification fails."""

    def __init__(self, reason_code: str, message: str | None = None) -> None:
        super().__init__(message or reason_code)
        self.reason_code = reason_code


def grant_issuer_key_id(public_key: Ed25519PublicKey) -> str:
    """Compute a domain-distinct key identifier for a Stencil distribution grant issuer."""
    raw = public_key.public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    digest = hashlib.sha256(b"fdai.stencil-grant-issuer-key.v1\n" + raw).hexdigest()[:16]
    return f"stencil-grant-key-{digest}"


def format_variant_release_id(base_release_version: str, stencil_id: str) -> str:
    """Format a canonical SemVer release ID for a Stencil variant without '+' build metadata."""
    if _BASE_SEMVER_RE.fullmatch(base_release_version) is None:
        raise StencilBindingError(
            "invalid_base_release_version",
            "base_release_version must be canonical X.Y.Z SemVer without prerelease or build metadata.",
        )
    if _STENCIL_ID_RE.fullmatch(stencil_id) is None:
        raise StencilBindingError(
            "invalid_stencil_id",
            "stencil_id must be lowercase ASCII kebab-case.",
        )
    return f"{base_release_version}-{stencil_id}"


def split_variant_release_id(release_id: str, stencil_id: str | None = None) -> str:
    """Extract the base X.Y.Z SemVer from a release_id or `<base>-<stencil_id>` variant ID."""
    if not is_release_id(release_id) or "+" in release_id:
        raise StencilBindingError(
            "invalid_release_id",
            "release_id must be canonical SemVer without '+' build-metadata ordering ambiguity.",
        )
    if stencil_id and release_id.endswith(f"-{stencil_id}"):
        candidate_base = release_id[: -(len(stencil_id) + 1)]
        if _BASE_SEMVER_RE.fullmatch(candidate_base) is not None:
            return candidate_base
    base_part = release_id.split("-", 1)[0]
    if _BASE_SEMVER_RE.fullmatch(base_part) is None:
        raise StencilBindingError(
            "invalid_base_release_version",
            "release_id base version must be canonical X.Y.Z SemVer.",
        )
    return base_part


@dataclass(frozen=True, slots=True)
class StencilVariantBinding:
    """Immutable identity binding one Stencil variant at a base semantic version (#2528)."""

    base_release_version: str
    release_id: str
    stencil_id: str
    stencil_digest: str
    release_digest: str
    source_commit: str
    component_digests: Mapping[str, str]
    feature_flags_digest: str | None = None

    @property
    def variant_key(self) -> str:
        return f"{self.base_release_version}@{self.stencil_id}"

    @property
    def digest(self) -> str:
        return "sha256:" + canonical_digest(self.to_payload())

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": STENCIL_VARIANT_BINDING_SCHEMA,
            "variant_key": self.variant_key,
            "base_release_version": self.base_release_version,
            "release_id": self.release_id,
            "stencil_id": self.stencil_id,
            "stencil_digest": self.stencil_digest,
            "release_digest": self.release_digest,
            "source_commit": self.source_commit,
            "component_digests": dict(sorted(self.component_digests.items())),
        }
        if self.feature_flags_digest is not None:
            payload["feature_flags_digest"] = self.feature_flags_digest
        return payload


def extract_stencil_variant_binding(
    release_id: str,
    release: LifecycleRelease,
) -> StencilVariantBinding | None:
    """Extract and validate a `StencilVariantBinding` from a parsed `LifecycleRelease`."""
    if "+" in release_id:
        raise StencilBindingError(
            "semver_build_metadata_forbidden",
            "SemVer '+' build metadata is forbidden for Stencil variant ordering.",
        )
    if not isinstance(release, ApplicationRelease) or release.stencil is None:
        return None
    if release.schema_version != APPLICATION_COMPONENT_RELEASE_SCHEMA:
        raise StencilBindingError(
            "unsupported_contract_version",
            "Stencil metadata is only supported on fdai.application-release.v2.",
        )
    stencil = release.stencil
    stencil_id = stencil.get("stencil_id")
    stencil_digest = stencil.get("stencil_digest")
    if not isinstance(stencil_id, str) or _STENCIL_ID_RE.fullmatch(stencil_id) is None:
        raise StencilBindingError("invalid_stencil_id", "Release stencil_id is invalid.")
    if not isinstance(stencil_digest, str) or _DIGEST_RE.fullmatch(stencil_digest) is None:
        raise StencilBindingError("invalid_stencil_digest", "Release stencil_digest is invalid.")
    base_version = split_variant_release_id(release_id, stencil_id)
    ff = stencil.get("feature_flags")
    ff_digest: str | None = None
    if isinstance(ff, Mapping):
        raw_ff_digest = ff.get("feature_flags_digest")
        if isinstance(raw_ff_digest, str) and _DIGEST_RE.fullmatch(raw_ff_digest):
            ff_digest = raw_ff_digest
    return StencilVariantBinding(
        base_release_version=base_version,
        release_id=release_id,
        stencil_id=stencil_id,
        stencil_digest=stencil_digest,
        release_digest=f"sha256:{release.digest}"
        if not release.digest.startswith("sha256:")
        else release.digest,
        source_commit=release.source_commit,
        component_digests=dict(sorted(release.components.items())),
        feature_flags_digest=ff_digest,
    )


@dataclass(frozen=True, slots=True)
class StencilDistributionGrant:
    """Installation-bound distribution grant limiting catalog discovery and pulls (#2529)."""

    grant_id: str
    issuer_key_id: str
    installation_id: str
    customer_principal: str
    allowed_stencil_ids: tuple[str, ...]
    allowed_channels: tuple[str, ...]
    revision: int
    issued_at: str
    expires_at: str
    revoked: bool = False
    revocation_reason: str | None = None
    schema_version: str = STENCIL_DISTRIBUTION_GRANT_SCHEMA
    purpose: str = STENCIL_GRANT_PURPOSE
    runtime_license_granted: Literal[False] = False
    execution_authority_granted: Literal[False] = False

    def __post_init__(self) -> None:
        if self.schema_version != STENCIL_DISTRIBUTION_GRANT_SCHEMA:
            raise StencilBindingError(
                "unsupported_grant_schema",
                f"Unsupported grant schema: {self.schema_version!r}",
            )
        if self.purpose != STENCIL_GRANT_PURPOSE:
            raise StencilBindingError(
                "invalid_grant_purpose",
                "Grant purpose must be 'stencil-distribution-eligibility'.",
            )
        if (
            self.runtime_license_granted is not False
            or self.execution_authority_granted is not False
        ):
            raise StencilBindingError(
                "grant_authority_escalation_forbidden",
                "Distribution grants never confer runtime licensing or execution authority.",
            )
        if _GRANT_ID_RE.fullmatch(self.grant_id) is None:
            raise StencilBindingError("invalid_grant_id", "grant_id is invalid.")
        if not self.issuer_key_id.startswith("stencil-grant-key-"):
            raise StencilBindingError(
                "invalid_grant_issuer_key_id",
                "issuer_key_id must use the domain-separated stencil-grant-key-* prefix.",
            )
        if _INSTALLATION_ID_RE.fullmatch(self.installation_id) is None:
            raise StencilBindingError("invalid_installation_id", "installation_id is invalid.")
        if _PRINCIPAL_RE.fullmatch(self.customer_principal) is None:
            raise StencilBindingError(
                "invalid_customer_principal", "customer_principal is invalid."
            )
        if type(self.revision) is not int or self.revision < 1:
            raise StencilBindingError("invalid_grant_revision", "grant revision must be >= 1.")
        if not self.allowed_stencil_ids:
            raise StencilBindingError(
                "empty_allowed_stencils",
                "allowed_stencil_ids must name at least one Stencil.",
            )
        for st_id in self.allowed_stencil_ids:
            if _STENCIL_ID_RE.fullmatch(st_id) is None:
                raise StencilBindingError(
                    "invalid_stencil_id",
                    f"Invalid stencil_id in grant: {st_id!r}",
                )
        if tuple(self.allowed_stencil_ids) != tuple(sorted(set(self.allowed_stencil_ids))):
            raise StencilBindingError(
                "unsorted_or_duplicate_stencils",
                "allowed_stencil_ids must be sorted and unique.",
            )
        if not self.allowed_channels:
            raise StencilBindingError(
                "empty_allowed_channels",
                "allowed_channels must name at least one customer channel.",
            )
        if "DEV" in self.allowed_channels:
            raise StencilBindingError(
                "dev_channel_forbidden_in_customer_grant",
                "Customer distribution grants cannot authorize the DEV channel.",
            )
        if not set(self.allowed_channels).issubset(CUSTOMER_ENTITLED_CHANNELS):
            raise StencilBindingError(
                "invalid_allowed_channels",
                "Customer distribution grants only allow RELEASE_CANDIDATE and RELEASE.",
            )
        if tuple(self.allowed_channels) != tuple(sorted(set(self.allowed_channels))):
            raise StencilBindingError(
                "unsorted_or_duplicate_channels",
                "allowed_channels must be sorted and unique.",
            )
        issued_dt = _parse_utc(self.issued_at, "issued_at")
        expires_dt = _parse_utc(self.expires_at, "expires_at")
        if expires_dt <= issued_dt:
            raise StencilBindingError(
                "invalid_grant_validity_window",
                "expires_at must be strictly after issued_at.",
            )
        if self.revoked and (not self.revocation_reason or not self.revocation_reason.strip()):
            raise StencilBindingError(
                "missing_revocation_reason",
                "Revoked grants require a non-blank revocation_reason.",
            )

    @property
    def scope_digest(self) -> str:
        """Scope fingerprint binding installation, principal, revision, Stencils, and channels."""
        return "sha256:" + canonical_digest(
            {
                "grant_id": self.grant_id,
                "installation_id": self.installation_id,
                "customer_principal": self.customer_principal,
                "revision": self.revision,
                "allowed_stencil_ids": list(self.allowed_stencil_ids),
                "allowed_channels": list(self.allowed_channels),
                "revoked": self.revoked,
            }
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "purpose": self.purpose,
            "grant_id": self.grant_id,
            "issuer_key_id": self.issuer_key_id,
            "installation_id": self.installation_id,
            "customer_principal": self.customer_principal,
            "allowed_stencil_ids": list(self.allowed_stencil_ids),
            "allowed_channels": list(self.allowed_channels),
            "revision": self.revision,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "revoked": self.revoked,
            "revocation_reason": self.revocation_reason,
            "runtime_license_granted": False,
            "execution_authority_granted": False,
        }


@dataclass(frozen=True, slots=True)
class SignedStencilDistributionGrant:
    """Detached Ed25519 signature envelope over a `StencilDistributionGrant`."""

    grant: StencilDistributionGrant
    canonical_payload: bytes
    signature: str

    @property
    def digest(self) -> str:
        return "sha256:" + hashlib.sha256(self.canonical_payload).hexdigest()

    def to_envelope(self) -> dict[str, Any]:
        return {
            "grant": self.grant.to_payload(),
            "signature": self.signature,
            "digest": self.digest,
        }


def _parse_utc(raw: str, label: str) -> datetime:
    try:
        dt = datetime.fromisoformat(raw)
    except (TypeError, ValueError) as exc:
        raise StencilBindingError("invalid_timestamp", f"{label} is not valid ISO-8601.") from exc
    if dt.tzinfo is None:
        raise StencilBindingError("invalid_timestamp", f"{label} must be timezone-aware.")
    return dt.astimezone(UTC)


def issue_stencil_distribution_grant(
    *,
    private_key: Ed25519PrivateKey,
    grant_id: str,
    installation_id: str,
    customer_principal: str,
    allowed_stencil_ids: Iterable[str],
    allowed_channels: Iterable[str] = ("RELEASE_CANDIDATE", "RELEASE"),
    revision: int = 1,
    issued_at: datetime,
    expires_at: datetime,
    revoked: bool = False,
    revocation_reason: str | None = None,
    forbidden_key_ids: Iterable[str] = (),
) -> SignedStencilDistributionGrant:
    """Issue a domain-separated signed Stencil distribution grant."""
    pub = private_key.public_key()
    issuer_kid = grant_issuer_key_id(pub)
    raw_pub = pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    hub_kid = "hub-" + hashlib.sha256(raw_pub).hexdigest()[:16]
    forbidden = set(forbidden_key_ids)
    if issuer_kid in forbidden or hub_kid in forbidden:
        raise StencilBindingError(
            "grant_key_reuse_forbidden",
            "Grant signing key cannot reuse a catalog export or runtime entitlement signing key.",
        )
    grant = StencilDistributionGrant(
        grant_id=grant_id,
        issuer_key_id=issuer_kid,
        installation_id=installation_id,
        customer_principal=customer_principal,
        allowed_stencil_ids=tuple(sorted(set(allowed_stencil_ids))),
        allowed_channels=tuple(sorted(set(allowed_channels))),
        revision=revision,
        issued_at=_parse_utc(issued_at.isoformat(), "issued_at").isoformat(),
        expires_at=_parse_utc(expires_at.isoformat(), "expires_at").isoformat(),
        revoked=revoked,
        revocation_reason=revocation_reason,
    )
    payload_bytes = canonical_bytes(grant.to_payload())
    sig_bytes = private_key.sign(STENCIL_GRANT_SIGNATURE_DOMAIN + payload_bytes)
    return SignedStencilDistributionGrant(
        grant=grant,
        canonical_payload=payload_bytes,
        signature=b64encode(sig_bytes).decode("ascii"),
    )


def verify_stencil_distribution_grant(
    envelope: Mapping[str, Any] | bytes,
    *,
    trusted_public_keys: Ed25519PublicKey | Sequence[Ed25519PublicKey],
    expected_installation_id: str | None = None,
    expected_customer_principal: str | None = None,
    minimum_revision: int = 1,
    previous_issued_at: datetime | None = None,
    now: datetime | None = None,
    allow_expired_or_revoked_for_recovery: bool = False,
) -> SignedStencilDistributionGrant:
    """Independently verify signature, issuer, binding, revision floor, and validity window."""
    if isinstance(envelope, bytes):
        try:
            doc = load_json_object(
                envelope, label="stencil distribution grant", max_bytes=32768, strict=True
            )
        except ValueError as exc:
            raise StencilBindingError("malformed_grant_envelope", str(exc)) from exc
    elif isinstance(envelope, Mapping):
        doc = dict(envelope)
    else:
        raise StencilBindingError("malformed_grant_envelope", "Grant envelope must be a mapping.")

    raw_grant = doc.get("grant")
    signature = doc.get("signature")
    if not isinstance(raw_grant, Mapping) or not isinstance(signature, str) or not signature:
        raise StencilBindingError(
            "malformed_grant_envelope",
            "Grant envelope requires 'grant' object and non-empty 'signature'.",
        )
    allowed_grant_keys = {
        "schema_version",
        "purpose",
        "grant_id",
        "issuer_key_id",
        "installation_id",
        "customer_principal",
        "allowed_stencil_ids",
        "allowed_channels",
        "revision",
        "issued_at",
        "expires_at",
        "revoked",
        "revocation_reason",
        "runtime_license_granted",
        "execution_authority_granted",
    }
    if set(raw_grant.keys()) != allowed_grant_keys:
        raise StencilBindingError(
            "invalid_grant_fields",
            "Grant object fields do not match fdai.stencil-distribution-grant.v1.",
        )
    if (
        raw_grant.get("runtime_license_granted") is not False
        or raw_grant.get("execution_authority_granted") is not False
    ):
        raise StencilBindingError(
            "grant_authority_escalation_forbidden",
            "Distribution grants cannot grant runtime licenses or execution authority.",
        )
    raw_stencils = raw_grant.get("allowed_stencil_ids")
    raw_channels = raw_grant.get("allowed_channels")
    if not isinstance(raw_stencils, list) or not all(isinstance(x, str) for x in raw_stencils):
        raise StencilBindingError("invalid_stencil_id", "allowed_stencil_ids must be a list.")
    if not isinstance(raw_channels, list) or not all(isinstance(x, str) for x in raw_channels):
        raise StencilBindingError("invalid_allowed_channels", "allowed_channels must be a list.")

    grant = StencilDistributionGrant(
        schema_version=str(raw_grant["schema_version"]),
        purpose=str(raw_grant["purpose"]),
        grant_id=str(raw_grant["grant_id"]),
        issuer_key_id=str(raw_grant["issuer_key_id"]),
        installation_id=str(raw_grant["installation_id"]),
        customer_principal=str(raw_grant["customer_principal"]),
        allowed_stencil_ids=tuple(raw_stencils),
        allowed_channels=tuple(raw_channels),
        revision=raw_grant["revision"],
        issued_at=str(raw_grant["issued_at"]),
        expires_at=str(raw_grant["expires_at"]),
        revoked=bool(raw_grant["revoked"]),
        revocation_reason=(
            str(raw_grant["revocation_reason"])
            if raw_grant["revocation_reason"] is not None
            else None
        ),
        runtime_license_granted=False,
        execution_authority_granted=False,
    )

    keys = (
        (trusted_public_keys,)
        if isinstance(trusted_public_keys, Ed25519PublicKey)
        else tuple(trusted_public_keys)
    )
    matching_keys = [k for k in keys if grant_issuer_key_id(k) == grant.issuer_key_id]
    if not matching_keys:
        raise StencilBindingError(
            "untrusted_grant_issuer",
            f"Grant issuer {grant.issuer_key_id!r} is not in trusted grant issuers.",
        )

    payload_bytes = canonical_bytes(grant.to_payload())
    try:
        sig_raw = b64decode(signature, validate=True)
    except ValueError as exc:
        raise StencilBindingError("invalid_grant_signature", "Malformed base64 signature.") from exc

    verified = False
    for key in matching_keys:
        try:
            key.verify(sig_raw, STENCIL_GRANT_SIGNATURE_DOMAIN + payload_bytes)
            verified = True
            break
        except InvalidSignature:
            continue
    if not verified:
        raise StencilBindingError(
            "invalid_grant_signature",
            "Grant signature verification failed.",
        )

    if expected_installation_id is not None and grant.installation_id != expected_installation_id:
        raise StencilBindingError(
            "grant_installation_mismatch",
            f"Grant installation {grant.installation_id!r} != {expected_installation_id!r}.",
        )
    if (
        expected_customer_principal is not None
        and grant.customer_principal != expected_customer_principal
    ):
        raise StencilBindingError(
            "grant_principal_mismatch",
            f"Grant principal {grant.customer_principal!r} != {expected_customer_principal!r}.",
        )
    if grant.revision < minimum_revision:
        raise StencilBindingError(
            "grant_revision_rollback",
            f"Grant revision {grant.revision} is below minimum revision {minimum_revision}.",
        )
    issued_dt = _parse_utc(grant.issued_at, "issued_at")
    if previous_issued_at is not None and issued_dt < _parse_utc(
        previous_issued_at.isoformat(), "previous_issued_at"
    ):
        raise StencilBindingError(
            "grant_clock_regression",
            "Grant issued_at regressed below previously accepted grant timestamp.",
        )
    check_now = _parse_utc((now or datetime.now(UTC)).isoformat(), "now")
    expires_dt = _parse_utc(grant.expires_at, "expires_at")
    if not allow_expired_or_revoked_for_recovery:
        if grant.revoked:
            raise StencilBindingError(
                "grant_revoked",
                f"Distribution grant {grant.grant_id!r} is revoked: {grant.revocation_reason}",
            )
        if check_now >= expires_dt:
            raise StencilBindingError(
                "grant_expired",
                f"Distribution grant {grant.grant_id!r} expired at {grant.expires_at}.",
            )

    return SignedStencilDistributionGrant(
        grant=grant,
        canonical_payload=payload_bytes,
        signature=signature,
    )


def verify_release_plan_bundle_stencil_binding(
    *,
    release_id: str,
    release: LifecycleRelease,
    expected_stencil_id: str | None = None,
    expected_stencil_digest: str | None = None,
    plan: LifecyclePlan | None = None,
    runtime_bundle_workloads: Iterable[str] | None = None,
    runtime_bundle_component_images: Mapping[str, str] | None = None,
    runtime_bundle_stencil_id: str | None = None,
    configuration_stencil_id: str | None = None,
    grant: StencilDistributionGrant | None = None,
    channel: str | None = None,
) -> StencilVariantBinding | None:
    """Verify cross-layer Stencil variant identity across Release, Plan, Bundle, and Grant (#2528)."""
    binding = extract_stencil_variant_binding(release_id, release)
    if binding is None:
        if any(
            x is not None
            for x in (
                expected_stencil_id,
                expected_stencil_digest,
                runtime_bundle_stencil_id,
                configuration_stencil_id,
            )
        ):
            raise StencilBindingError(
                "missing_release_stencil_metadata",
                "Release does not carry Stencil metadata required by the caller.",
            )
        return None

    if not isinstance(release, ApplicationRelease) or release.stencil is None:
        raise StencilBindingError(
            "missing_release_stencil_metadata",
            "Release does not carry Stencil metadata.",
        )
    stencil = release.stencil
    raw_enabled_wl = stencil.get("enabled_workloads")
    raw_omitted_wl = stencil.get("omitted_workloads")
    enabled_workloads = {
        str(w)
        for w in (raw_enabled_wl if isinstance(raw_enabled_wl, list) else ())
        if isinstance(w, str)
    }
    omitted_workloads = {
        str(w)
        for w in (raw_omitted_wl if isinstance(raw_omitted_wl, list) else ())
        if isinstance(w, str)
    }

    if expected_stencil_id is not None and binding.stencil_id != expected_stencil_id:
        raise StencilBindingError(
            "stencil_id_mismatch",
            f"Release stencil_id {binding.stencil_id!r} != expected {expected_stencil_id!r}.",
        )
    if expected_stencil_digest is not None and binding.stencil_digest != expected_stencil_digest:
        raise StencilBindingError(
            "stencil_digest_mismatch",
            f"Release stencil_digest {binding.stencil_digest!r} != {expected_stencil_digest!r}.",
        )
    if configuration_stencil_id is not None and binding.stencil_id != configuration_stencil_id:
        raise StencilBindingError(
            "configuration_stencil_mismatch",
            f"Customer configuration stencil {configuration_stencil_id!r} != {binding.stencil_id!r}.",
        )
    if runtime_bundle_stencil_id is not None and binding.stencil_id != runtime_bundle_stencil_id:
        raise StencilBindingError(
            "bundle_stencil_id_mismatch",
            f"RuntimeBundle stencil_id {runtime_bundle_stencil_id!r} != {binding.stencil_id!r}.",
        )

    if plan is not None:
        if plan.target_release_id != release_id:
            raise StencilBindingError(
                "plan_release_id_mismatch",
                f"Plan target_release_id {plan.target_release_id!r} != {release_id!r}.",
            )
        norm_plan_digest = (
            plan.target_release_digest
            if plan.target_release_digest.startswith("sha256:")
            else f"sha256:{plan.target_release_digest}"
        )
        if norm_plan_digest != binding.release_digest:
            raise StencilBindingError(
                "plan_release_digest_mismatch",
                "Plan target_release_digest does not match the signed Release digest.",
            )
        expected_cap = f"stencil:{binding.stencil_id}"
        stencil_caps = [c for c in plan.capability_ids if c.startswith("stencil:")]
        if expected_cap not in plan.capability_ids or any(c != expected_cap for c in stencil_caps):
            raise StencilBindingError(
                "plan_stencil_capability_mismatch",
                f"Plan capability_ids must bind {expected_cap!r}.",
            )

    if runtime_bundle_workloads is not None:
        bundle_wl = set(runtime_bundle_workloads)
        if bundle_wl & omitted_workloads:
            leaked = ", ".join(sorted(bundle_wl & omitted_workloads))
            raise StencilBindingError(
                "bundle_excluded_workload_present",
                f"RuntimeBundle retains Stencil-excluded workload(s): {leaked}",
            )
        if bundle_wl != enabled_workloads:
            raise StencilBindingError(
                "bundle_workload_inclusion_mismatch",
                f"RuntimeBundle workloads {sorted(bundle_wl)} != {sorted(enabled_workloads)}.",
            )

    if runtime_bundle_component_images is not None:
        for comp_name, image_ref in runtime_bundle_component_images.items():
            if comp_name not in binding.component_digests:
                raise StencilBindingError(
                    "bundle_unexpected_component",
                    f"RuntimeBundle component {comp_name!r} is not in the Stencil Release.",
                )
            expected_digest = binding.component_digests[comp_name]
            observed_digest = image_ref.rsplit("@", 1)[1] if "@" in image_ref else image_ref
            if observed_digest != expected_digest:
                raise StencilBindingError(
                    "bundle_component_digest_mismatch",
                    f"Component {comp_name!r} digest {observed_digest!r} != {expected_digest!r}.",
                )

    if grant is not None:
        if grant.revoked:
            raise StencilBindingError("grant_revoked", "Distribution grant is revoked.")
        if binding.stencil_id not in grant.allowed_stencil_ids:
            raise StencilBindingError(
                "grant_stencil_not_permitted",
                f"Grant does not permit Stencil {binding.stencil_id!r}.",
            )
        if channel is not None and channel not in grant.allowed_channels:
            raise StencilBindingError(
                "grant_channel_not_permitted",
                f"Grant does not permit channel {channel!r}.",
            )

    return binding


__all__ = [
    "CUSTOMER_ENTITLED_CHANNELS",
    "LOCKED_SAFETY_CORE_PANELS",
    "LOCKED_SAFETY_CORE_WORKLOADS",
    "STENCIL_DISTRIBUTION_GRANT_SCHEMA",
    "STENCIL_GRANT_PURPOSE",
    "STENCIL_GRANT_SIGNATURE_DOMAIN",
    "STENCIL_VARIANT_BINDING_SCHEMA",
    "SignedStencilDistributionGrant",
    "StencilBindingError",
    "StencilDistributionGrant",
    "StencilVariantBinding",
    "extract_stencil_variant_binding",
    "format_variant_release_id",
    "grant_issuer_key_id",
    "issue_stencil_distribution_grant",
    "split_variant_release_id",
    "verify_release_plan_bundle_stencil_binding",
    "verify_stencil_distribution_grant",
]
