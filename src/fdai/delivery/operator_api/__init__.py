"""Public facade for the FDAI Console Operator API.

Responsibility:
Expose stable authentication, read-model, and busy-input application symbols.

Boundary:
HTTP adapters may submit governed requests, but managed-resource effects must
re-enter typed agent, risk, approval, execution, recovery, and audit paths.

Authority and state:
No executor authority. Durable state remains in injected providers; this
package does not make browser claims or package imports authoritative.

Dependencies:
Core RBAC contracts, shared provider contracts, and delivery implementations
selected by app, development, or production composition roots.

Deployment:
Imported by the non-privileged Operator API process and by clients that need
its stable Python facade; it is not a second service or executor.
"""

from __future__ import annotations

from .auth import (
    AuthenticationError,
    Authenticator,
    ClaimsVerifier,
    UnsafeClaimsExtractor,
    build_authenticator,
)
from .entra_verifier import (
    EntraJwtVerifier,
    EntraVerifierConfigError,
)
from .read_model import (
    AuditItem,
    AuditPage,
    AuditSample,
    ConsoleReadModel,
    DashboardKpi,
    HilQueueItem,
    HilQueuePage,
    InMemoryConsoleReadModel,
)
from .routes.busy_input_runtime import (
    BusyInputRuntime,
    BusyInputRuntimeMetrics,
    build_postgres_busy_input_runtime,
)

__all__ = [
    "AuditItem",
    "AuditPage",
    "AuditSample",
    "AuthenticationError",
    "Authenticator",
    "BusyInputRuntime",
    "BusyInputRuntimeMetrics",
    "ClaimsVerifier",
    "ConsoleReadModel",
    "DashboardKpi",
    "EntraJwtVerifier",
    "EntraVerifierConfigError",
    "HilQueueItem",
    "HilQueuePage",
    "InMemoryConsoleReadModel",
    "UnsafeClaimsExtractor",
    "build_authenticator",
    "build_postgres_busy_input_runtime",
]
