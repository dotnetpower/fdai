"""Capability licensing: signed entitlement for an FDAI distribution.

The public verification key is a distribution artifact and the token is
deployment configuration. A license moves the `available` axis only -
promotion, RBAC, risk, and approval stay authoritative.

See `docs/roadmap/fork-and-sequencing/capability-licensing.md`.
"""

from __future__ import annotations

from fdai.core.licensing.entitlement import (
    DeploymentBinding,
    Entitlement,
    LicenseEntitlementAuthority,
    LicenseStatus,
    LicenseVerifier,
    resolve_entitlement,
)
from fdai.core.licensing.installation_entitlement import (
    INSTALLATION_ENTITLEMENT_SCHEMA,
    InstallationEntitlementClaims,
    parse_installation_entitlement,
)
from fdai.core.licensing.token import (
    LICENSE_SCHEMA,
    LicenseClaims,
    LicenseTokenError,
    encode_license_token,
    parse_license_token,
)

__all__ = [
    "INSTALLATION_ENTITLEMENT_SCHEMA",
    "LICENSE_SCHEMA",
    "DeploymentBinding",
    "Entitlement",
    "InstallationEntitlementClaims",
    "LicenseEntitlementAuthority",
    "LicenseClaims",
    "LicenseStatus",
    "LicenseTokenError",
    "LicenseVerifier",
    "encode_license_token",
    "parse_installation_entitlement",
    "parse_license_token",
    "resolve_entitlement",
]
