"""Read-only console API.

Public surface:

- :mod:`.auth` - extract a :class:`~fdai.core.rbac.resolver.Principal`
  from an HTTP ``Authorization`` header and glue in
  :class:`~fdai.core.rbac.enforcer.RoleEnforcer`. Framework-neutral;
  no ASGI framework is imported at module load.
- :mod:`.entra_verifier` - production :class:`~.auth.ClaimsVerifier`:
  JWKS signature + ``aud`` + ``iss`` + ``exp`` validation via PyJWT.
  Generic (tenant / audience / issuer from env); the fork only supplies
  values, not code.
- :mod:`.read_model` - projection Protocol + in-memory fake the console
  handlers read through.
- :mod:`.main` - Starlette app factory. This is the ONLY place Starlette
  is imported in the codebase; importing this sub-module pulls Starlette
  into the process, so tests that do not need the HTTP layer keep using
  the primitives in :mod:`.auth` / :mod:`.read_model` directly.

See ``app-shape.instructions.md § Operator console`` for the read-only
invariant enforced here.
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
