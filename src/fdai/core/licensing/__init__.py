"""Capability licensing: signed entitlement for a downstream distribution.

The mechanism is upstream and shared by every distribution; the public key and
the token itself are deployment configuration. A license moves the `available`
axis only - promotion, RBAC, risk, and approval stay authoritative.

See `docs/roadmap/fork-and-sequencing/capability-licensing.md`.
"""

from __future__ import annotations

from fdai.core.licensing.entitlement import (
    DeploymentBinding,
    Entitlement,
    LicenseStatus,
    LicenseVerifier,
    resolve_entitlement,
)
from fdai.core.licensing.token import (
    LICENSE_SCHEMA,
    LicenseClaims,
    LicenseTokenError,
    encode_license_token,
    parse_license_token,
)

__all__ = [
    "LICENSE_SCHEMA",
    "DeploymentBinding",
    "Entitlement",
    "LicenseClaims",
    "LicenseStatus",
    "LicenseTokenError",
    "LicenseVerifier",
    "encode_license_token",
    "parse_license_token",
    "resolve_entitlement",
]
