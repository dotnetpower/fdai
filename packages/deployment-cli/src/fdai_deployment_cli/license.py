"""Offline capability-license inspection without runtime dependencies."""

from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from fdai_deployment_cli.contracts import canonical_bytes, load_json_object

_B64URL = re.compile(r"^[A-Za-z0-9_-]+$")
_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,127}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_MAX_CAPABILITIES = 512


class LicenseInspectionError(ValueError):
    """A license token is malformed, untrusted, or inactive."""


@dataclass(frozen=True, slots=True)
class LicenseInspection:
    """Sanitized active-license result."""

    license_id: str
    distribution_id: str
    capability_ids: tuple[str, ...]
    not_before: str
    not_after: str
    active: bool

    def to_json(self) -> str:
        """Return stable JSON without the bearer token."""

        return json.dumps(
            {
                "schema_version": "fdai.license-inspection.v1",
                "license_id": self.license_id,
                "distribution_id": self.distribution_id,
                "capability_ids": list(self.capability_ids),
                "not_before": self.not_before,
                "not_after": self.not_after,
                "active": self.active,
            },
            sort_keys=True,
            separators=(",", ":"),
        )


def inspect_license(
    token: str,
    *,
    public_key_pem: bytes,
    now: datetime | None = None,
    expected_image_digest: str | None = None,
    expected_tenant_binding: str | None = None,
) -> LicenseInspection:
    """Verify one signed canonical token and report active entitlement."""

    if not token or len(token) > 8192:
        raise LicenseInspectionError("license token is empty or exceeds its size limit")
    parts = token.split(".")
    if len(parts) != 2:
        raise LicenseInspectionError("license token MUST contain document and signature")
    document = _decode(parts[0], "document")
    signature = _decode(parts[1], "signature")
    if len(signature) != 64:
        raise LicenseInspectionError("license signature MUST be 64 bytes")
    _verify(public_key_pem, document, signature)
    payload = load_json_object(document, label="license document", max_bytes=6144)
    expected = {
        "schema_version",
        "license_id",
        "distribution_id",
        "capability_ids",
        "not_before",
        "not_after",
        "image_digest",
        "tenant_binding",
    }
    if set(payload) != expected or payload["schema_version"] != "fdai.license.v1":
        raise LicenseInspectionError("license document schema does not match")
    if canonical_bytes(payload) != document:
        raise LicenseInspectionError("license document is not canonical")
    not_before = _moment(payload, "not_before")
    not_after = _moment(payload, "not_after")
    if _text(payload, "not_before") != _canonical_moment(not_before) or _text(
        payload, "not_after"
    ) != _canonical_moment(not_after):
        raise LicenseInspectionError("license timestamps are not canonically encoded")
    if not_after <= not_before:
        raise LicenseInspectionError("license validity window is invalid")
    evaluated = now or datetime.now(UTC)
    if evaluated.tzinfo is None:
        raise LicenseInspectionError("license evaluation time MUST be timezone-aware")
    capabilities = payload["capability_ids"]
    if (
        not isinstance(capabilities, list)
        or not capabilities
        or not all(isinstance(item, str) and item for item in capabilities)
    ):
        raise LicenseInspectionError("license capability_ids are invalid")
    if capabilities != sorted(set(capabilities)):
        raise LicenseInspectionError("license capability_ids MUST be unique and sorted")
    if len(capabilities) > _MAX_CAPABILITIES:
        raise LicenseInspectionError("license capability_ids exceeds the supported count")
    license_id = _text(payload, "license_id")
    distribution_id = _text(payload, "distribution_id")
    if _ID.fullmatch(license_id) is None or _ID.fullmatch(distribution_id) is None:
        raise LicenseInspectionError("license identifiers MUST be lowercase stable identifiers")
    if any(_ID.fullmatch(item) is None for item in capabilities):
        raise LicenseInspectionError("license capability_ids MUST be lowercase stable identifiers")
    _verify_optional_binding(
        payload,
        field="image_digest",
        expected=expected_image_digest,
    )
    _verify_optional_binding(
        payload,
        field="tenant_binding",
        expected=expected_tenant_binding,
    )
    active = not_before <= evaluated < not_after
    if not active:
        raise LicenseInspectionError("license is not active")
    return LicenseInspection(
        license_id=license_id,
        distribution_id=distribution_id,
        capability_ids=tuple(capabilities),
        not_before=not_before.isoformat(),
        not_after=not_after.isoformat(),
        active=True,
    )


def _decode(value: str, label: str) -> bytes:
    if _B64URL.fullmatch(value) is None:
        raise LicenseInspectionError(f"license {label} is not canonical base64url")
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, binascii.Error) as exc:
        raise LicenseInspectionError(f"license {label} is not base64url") from exc
    if base64.urlsafe_b64encode(decoded).rstrip(b"=").decode() != value:
        raise LicenseInspectionError(f"license {label} is not canonical base64url")
    return decoded


def _verify_optional_binding(
    payload: dict[str, object],
    *,
    field: str,
    expected: str | None,
) -> None:
    value = payload[field]
    if value is not None and (not isinstance(value, str) or _DIGEST.fullmatch(value) is None):
        raise LicenseInspectionError(f"license {field} MUST be a lowercase SHA-256 or null")
    if expected is not None and _DIGEST.fullmatch(expected) is None:
        raise LicenseInspectionError(f"expected {field} MUST be a lowercase SHA-256")
    if value is not None and expected is None:
        raise LicenseInspectionError(f"license {field} requires an expected binding")
    if expected is not None and value != expected:
        raise LicenseInspectionError(f"license {field} does not match")


def _verify(public_pem: bytes, document: bytes, signature: bytes) -> None:
    try:
        key = load_pem_public_key(public_pem)
    except (TypeError, ValueError) as exc:
        raise LicenseInspectionError("license public key is invalid") from exc
    if not isinstance(key, Ed25519PublicKey):
        raise LicenseInspectionError("license public key MUST be Ed25519")
    try:
        key.verify(signature, document)
    except InvalidSignature as exc:
        raise LicenseInspectionError("license signature is invalid") from exc


def _moment(value: dict[str, object], field: str) -> datetime:
    raw = _text(value, field)
    try:
        moment = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise LicenseInspectionError(f"license {field} MUST be ISO 8601") from exc
    if moment.tzinfo is None:
        raise LicenseInspectionError(f"license {field} MUST be timezone-aware")
    return moment


def _canonical_moment(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _text(value: dict[str, object], field: str) -> str:
    item = value[field]
    if not isinstance(item, str) or not item:
        raise LicenseInspectionError(f"license {field} MUST be text")
    return item
