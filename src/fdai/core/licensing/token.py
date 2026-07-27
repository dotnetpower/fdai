"""Signed capability-license token contract.

A distribution ships one image; the image carries only a **public** verification
key. Entitlement arrives separately as a compact signed token that an operator
injects through the normal secret path, so nothing secret is ever baked into a
layer an image recipient can unpack.

The token is ``base64url(canonical-document) "." base64url(signature)`` - one
ASCII string that fits an environment variable, a Container Apps secret, or a
Kubernetes Secret mount. The signature covers the exact canonical document
bytes, so field order can never be reinterpreted, and ``schema_version`` inside
the document keeps the payload domain-separated from every other FDAI
signature.

This module stays crypto-free and transport-free: it validates shape only.
Signature verification is a ``LicenseVerifier`` implemented in the delivery
layer, matching the extension and skill trust seams. Parsing establishes no
trust - holding claims grants nothing.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

LICENSE_SCHEMA: Final = "fdai.license.v1"
_MAX_TOKEN_CHARS: Final = 8192
_MAX_CAPABILITY_IDS: Final = 512
_SIGNATURE_BYTES: Final = 64
_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{2,127}$")
_SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_B64URL_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
_FIELDS: Final = frozenset(
    {
        "schema_version",
        "license_id",
        "distribution_id",
        "capability_ids",
        "not_before",
        "not_after",
        "image_digest",
        "tenant_binding",
    }
)


class LicenseTokenError(ValueError):
    """A license token is not a well-formed document."""


@dataclass(frozen=True, slots=True)
class LicenseClaims:
    """Inert entitlement claims.

    ``tenant_binding`` is a digest, never a tenant identifier, so a token can
    be bound to a deployment without putting a customer value in an image, a
    repository, or a log line.
    """

    license_id: str
    distribution_id: str
    capability_ids: tuple[str, ...]
    not_before: datetime
    not_after: datetime
    image_digest: str | None = None
    tenant_binding: str | None = None

    def __post_init__(self) -> None:
        for label, value in (
            ("license_id", self.license_id),
            ("distribution_id", self.distribution_id),
        ):
            if _ID_PATTERN.fullmatch(value) is None:
                raise LicenseTokenError(f"{label} MUST be lowercase ASCII")
        if not self.capability_ids:
            raise LicenseTokenError("capability_ids MUST list at least one capability")
        if len(self.capability_ids) > _MAX_CAPABILITY_IDS:
            raise LicenseTokenError("capability_ids exceeds the supported count")
        if len(set(self.capability_ids)) != len(self.capability_ids):
            raise LicenseTokenError("capability_ids MUST NOT contain duplicates")
        if any(_ID_PATTERN.fullmatch(value) is None for value in self.capability_ids):
            raise LicenseTokenError("every capability id MUST be lowercase ASCII")
        for label, moment in (("not_before", self.not_before), ("not_after", self.not_after)):
            if moment.tzinfo is None:
                raise LicenseTokenError(f"{label} MUST be timezone aware")
        if self.not_after <= self.not_before:
            raise LicenseTokenError("not_after MUST be later than not_before")
        for label, digest in (
            ("image_digest", self.image_digest),
            ("tenant_binding", self.tenant_binding),
        ):
            if digest is not None and _SHA256_PATTERN.fullmatch(digest) is None:
                raise LicenseTokenError(f"{label} MUST be a lowercase SHA-256 digest")

    def canonical_document(self) -> bytes:
        """Return the exact bytes an issuer signs and a verifier checks."""
        document: dict[str, Any] = {
            "schema_version": LICENSE_SCHEMA,
            "license_id": self.license_id,
            "distribution_id": self.distribution_id,
            "capability_ids": sorted(self.capability_ids),
            "not_before": _format_moment(self.not_before),
            "not_after": _format_moment(self.not_after),
            "image_digest": self.image_digest,
            "tenant_binding": self.tenant_binding,
        }
        return json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")


def encode_license_token(document: bytes, signature: bytes) -> str:
    """Join a canonical document and its detached signature into one token."""
    if len(signature) != _SIGNATURE_BYTES:
        raise LicenseTokenError("license signature MUST be 64 bytes")
    token = f"{_b64encode(document)}.{_b64encode(signature)}"
    if len(token) > _MAX_TOKEN_CHARS:
        raise LicenseTokenError("license token exceeds the supported length")
    return token


def parse_license_token(token: str) -> tuple[LicenseClaims, bytes, bytes]:
    """Return claims, the signed document bytes, and the detached signature.

    Parsing never establishes trust. The caller MUST verify the signature over
    the returned document before acting on the claims.
    """
    if not token or len(token) > _MAX_TOKEN_CHARS:
        raise LicenseTokenError("license token is empty or exceeds the supported length")
    parts = token.strip().split(".")
    if len(parts) != 2:
        raise LicenseTokenError("license token MUST be document.signature")
    document = _b64decode(parts[0], "document")
    signature = _b64decode(parts[1], "signature")
    if len(signature) != _SIGNATURE_BYTES:
        raise LicenseTokenError("license signature MUST be 64 bytes")
    return _claims_from_document(document), document, signature


def _claims_from_document(document: bytes) -> LicenseClaims:
    try:
        payload = json.loads(document)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LicenseTokenError("license document is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise LicenseTokenError("license document MUST be a JSON object")
    unknown = set(payload) - _FIELDS
    if unknown:
        raise LicenseTokenError(f"license document has unknown fields: {sorted(unknown)}")
    if payload.get("schema_version") != LICENSE_SCHEMA:
        raise LicenseTokenError("license document schema_version does not match")
    capability_ids = payload.get("capability_ids")
    if not isinstance(capability_ids, list) or not all(
        isinstance(value, str) for value in capability_ids
    ):
        raise LicenseTokenError("capability_ids MUST be a list of strings")
    return LicenseClaims(
        license_id=_text(payload, "license_id"),
        distribution_id=_text(payload, "distribution_id"),
        capability_ids=tuple(capability_ids),
        not_before=_moment(payload, "not_before"),
        not_after=_moment(payload, "not_after"),
        image_digest=_optional_text(payload, "image_digest"),
        tenant_binding=_optional_text(payload, "tenant_binding"),
    )


def _text(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str):
        raise LicenseTokenError(f"license document field {field!r} MUST be a string")
    return value


def _optional_text(payload: dict[str, Any], field: str) -> str | None:
    value = payload.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise LicenseTokenError(f"license document field {field!r} MUST be a string or null")
    return value


def _moment(payload: dict[str, Any], field: str) -> datetime:
    raw = _text(payload, field)
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise LicenseTokenError(f"license document field {field!r} MUST be RFC 3339") from exc
    if parsed.tzinfo is None:
        raise LicenseTokenError(f"license document field {field!r} MUST carry an offset")
    return parsed.astimezone(UTC)


def _format_moment(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _b64encode(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _b64decode(segment: str, label: str) -> bytes:
    """Decode one segment, accepting only its canonical unpadded encoding.

    Base64 decoding in the standard library silently drops characters outside
    the alphabet, so a whitespace run inserted into a segment decodes to the
    same bytes and keeps the signature valid. That would make one license
    presentable as unlimited distinct token strings, and anything that
    identifies a license by its token - a revocation list, a reuse check, an
    audit correlation - would be trivially evaded. Re-encoding the decoded
    bytes and demanding the original segment back rejects every such variant,
    including a final group whose unused bits are not zero.
    """
    if _B64URL_PATTERN.fullmatch(segment) is None:
        raise LicenseTokenError(f"license {label} is not unpadded base64url")
    padding = "=" * (-len(segment) % 4)
    try:
        decoded = base64.urlsafe_b64decode(segment + padding)
    except (binascii.Error, ValueError) as exc:
        raise LicenseTokenError(f"license {label} is not valid base64url") from exc
    if _b64encode(decoded) != segment:
        raise LicenseTokenError(f"license {label} is not canonically encoded")
    return decoded


__all__ = [
    "LICENSE_SCHEMA",
    "LicenseClaims",
    "LicenseTokenError",
    "encode_license_token",
    "parse_license_token",
]
