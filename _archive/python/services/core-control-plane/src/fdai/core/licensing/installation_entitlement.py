"""Signed installation entitlement: a key holder's installation-bound full grant.

The v1 token keeps a 30-day ceiling because it travels to other operators. A key
holder's own installation needs full availability that survives upgrades and
restarts without that ceiling, so this separately versioned document grants the
complete shipped catalog, binds exact installation and deployment digests, and
carries no image digest and no expiry. It is useless outside the installation it
binds.

The integrity key signs this document, the v1 token, and the framework-surface
manifest. ``schema_version`` and the exact field set keep the three domains apart:
neither strict parser accepts another domain's document. Parsing establishes no
trust; the caller verifies the signature over the returned document bytes.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from fdai.core.licensing.token import LicenseTokenError, decode_signed_envelope

INSTALLATION_ENTITLEMENT_SCHEMA: Final = "fdai.installation-entitlement.v1"
_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{2,127}$")
_SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_FIELDS: Final = frozenset(
    {
        "schema_version",
        "entitlement_id",
        "distribution_id",
        "installation_binding",
        "deployment_binding",
        "issued_at",
    }
)


@dataclass(frozen=True, slots=True)
class InstallationEntitlementClaims:
    """Inert claims; holding them grants nothing until the signature verifies."""

    entitlement_id: str
    distribution_id: str
    installation_binding: str
    deployment_binding: str
    issued_at: datetime

    def __post_init__(self) -> None:
        for label, value in (
            ("entitlement_id", self.entitlement_id),
            ("distribution_id", self.distribution_id),
        ):
            if not isinstance(value, str) or _ID_PATTERN.fullmatch(value) is None:
                raise LicenseTokenError(f"{label} MUST be lowercase ASCII")
        for label, digest in (
            ("installation_binding", self.installation_binding),
            ("deployment_binding", self.deployment_binding),
        ):
            if not isinstance(digest, str) or _SHA256_PATTERN.fullmatch(digest) is None:
                raise LicenseTokenError(f"{label} MUST be a lowercase SHA-256 digest")
        if not isinstance(self.issued_at, datetime) or self.issued_at.tzinfo is None:
            raise LicenseTokenError("issued_at MUST be timezone aware")

    def canonical_document(self) -> bytes:
        """Return the exact bytes an issuer signs and a verifier checks."""
        document: dict[str, Any] = {
            "schema_version": INSTALLATION_ENTITLEMENT_SCHEMA,
            "entitlement_id": self.entitlement_id,
            "distribution_id": self.distribution_id,
            "installation_binding": self.installation_binding,
            "deployment_binding": self.deployment_binding,
            "issued_at": self.issued_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        }
        return json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")


def signed_document_schema(token: str) -> str | None:
    """Return the schema a signed token declares, or ``None`` when it declares none.

    This only routes a token to its own strict parser. It establishes no trust.
    """
    try:
        document, _signature = decode_signed_envelope(token)
        payload = json.loads(document)
    except (LicenseTokenError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    schema = payload.get("schema_version")
    return schema if isinstance(schema, str) else None


def parse_installation_entitlement(
    token: str,
) -> tuple[InstallationEntitlementClaims, bytes, bytes]:
    """Return claims, the signed document bytes, and the detached signature."""
    document, signature = decode_signed_envelope(token)
    try:
        payload = json.loads(document)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LicenseTokenError("entitlement document is not valid JSON") from exc
    if not isinstance(payload, dict) or set(payload) != _FIELDS:
        raise LicenseTokenError("entitlement document fields do not match its schema")
    if payload["schema_version"] != INSTALLATION_ENTITLEMENT_SCHEMA:
        raise LicenseTokenError("entitlement document schema_version does not match")
    values = {name: payload[name] for name in _FIELDS - {"schema_version"}}
    if not all(isinstance(value, str) for value in values.values()):
        raise LicenseTokenError("entitlement document fields MUST be strings")
    try:
        issued_at = datetime.fromisoformat(values["issued_at"])
    except ValueError as exc:
        raise LicenseTokenError("entitlement issued_at MUST be RFC 3339") from exc
    if issued_at.tzinfo is None:
        raise LicenseTokenError("entitlement issued_at MUST carry an offset")
    claims = InstallationEntitlementClaims(
        entitlement_id=values["entitlement_id"],
        distribution_id=values["distribution_id"],
        installation_binding=values["installation_binding"],
        deployment_binding=values["deployment_binding"],
        issued_at=issued_at,
    )
    if claims.canonical_document() != document:
        raise LicenseTokenError("entitlement document is not canonically encoded")
    return claims, document, signature


__all__ = [
    "INSTALLATION_ENTITLEMENT_SCHEMA",
    "InstallationEntitlementClaims",
    "parse_installation_entitlement",
    "signed_document_schema",
]
