"""Offline inspection of a capability license token.

An operator - upstream or in a fork - can check a license without a network
call, a revocation lookup, or a certificate chain: the public key ships with
the distribution and the token is a single ASCII string. The result is a stable
JSON contract that reports status and non-secret metadata only. It never echoes
the token, the document, or the signature.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from fdai.core.capability_catalog import default_capability_catalog
from fdai.core.licensing import (
    DeploymentBinding,
    Entitlement,
    LicenseStatus,
    resolve_entitlement,
)
from fdai.delivery.trust.ed25519 import Ed25519LicenseVerifier

LICENSE_INSPECTION_SCHEMA: Final = "fdai.deployment-cli.license-inspection.v1"
_MAX_TOKEN_BYTES: Final = 16 * 1024
_MAX_KEY_BYTES: Final = 4 * 1024


class LicenseInspectionError(ValueError):
    """The license inspection inputs could not be read safely."""


@dataclass(frozen=True, slots=True)
class LicenseInspection:
    """Non-secret projection of one entitlement decision."""

    entitlement: Entitlement
    available_count: int
    catalog_count: int

    def to_dict(self) -> dict[str, object]:
        entitlement = self.entitlement
        return {
            "schema_version": LICENSE_INSPECTION_SCHEMA,
            "status": entitlement.status.value,
            "active": entitlement.is_active,
            "license_id": entitlement.license_id,
            "not_after": None
            if entitlement.not_after is None
            else entitlement.not_after.isoformat(),
            "available_capability_count": self.available_count,
            "catalog_capability_count": self.catalog_count,
            "reason": entitlement.reason,
            "mutation_performed": False,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


def inspect_license(
    *,
    token_path: Path,
    public_key_path: Path,
    now: datetime | None = None,
    image_digest: str | None = None,
    tenant_binding: str | None = None,
    require_license: bool = True,
) -> LicenseInspection:
    """Verify one license token against one packaged public key."""
    token = _read_text(token_path, "license token", _MAX_TOKEN_BYTES)
    public_key = _read_bytes(public_key_path, "public key", _MAX_KEY_BYTES)
    catalog = default_capability_catalog()
    entitlement = resolve_entitlement(
        catalog=catalog,
        token=token,
        verifier=Ed25519LicenseVerifier(public_key_pem=public_key),
        now=now or datetime.now(UTC),
        binding=DeploymentBinding(image_digest=image_digest, tenant_binding=tenant_binding),
        require_license=require_license,
    )
    return LicenseInspection(
        entitlement=entitlement,
        available_count=len(entitlement.available_capability_ids),
        catalog_count=len(catalog.list()),
    )


def inspection_exit_code(inspection: LicenseInspection) -> int:
    """Return 0 for an active license and 2 for any degraded status."""
    return 0 if inspection.entitlement.status is LicenseStatus.ACTIVE else 2


def _read_bytes(path: Path, label: str, limit: int) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise LicenseInspectionError(f"{label} MUST be a regular file")
    if path.stat().st_size > limit:
        raise LicenseInspectionError(f"{label} exceeds the size limit")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise LicenseInspectionError(f"{label} could not be read") from exc


def _read_text(path: Path, label: str, limit: int) -> str:
    try:
        return _read_bytes(path, label, limit).decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise LicenseInspectionError(f"{label} MUST be ASCII") from exc


__all__ = [
    "LICENSE_INSPECTION_SCHEMA",
    "LicenseInspection",
    "LicenseInspectionError",
    "inspect_license",
    "inspection_exit_code",
]
