"""Shared delivery authentication for human bearer-token APIs.

Responsibility: expose framework-neutral token verification and RBAC glue.
Authority: verified claims and core RBAC remain authoritative; this package
grants no execution or route authority. State: process-local verifier caches
only. Dependencies: core RBAC plus provider crypto libraries. Deployment role:
shared by independently hosted human-facing API processes.
"""

from fdai.delivery.auth.bearer import (
    AuthenticationError,
    Authenticator,
    ClaimsVerifier,
    UnsafeClaimsExtractor,
    build_authenticator,
)
from fdai.delivery.auth.entra import EntraJwtVerifier, EntraVerifierConfigError

__all__ = [
    "AuthenticationError",
    "Authenticator",
    "ClaimsVerifier",
    "EntraJwtVerifier",
    "EntraVerifierConfigError",
    "UnsafeClaimsExtractor",
    "build_authenticator",
]
