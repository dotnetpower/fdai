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
    active = not_before <= evaluated <= not_after
    if not active:
        raise LicenseInspectionError("license is not active")
    return LicenseInspection(
        license_id=_text(payload, "license_id"),
        distribution_id=_text(payload, "distribution_id"),
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


def _text(value: dict[str, object], field: str) -> str:
    item = value[field]
    if not isinstance(item, str) or not item:
        raise LicenseInspectionError(f"license {field} MUST be text")
    return item
