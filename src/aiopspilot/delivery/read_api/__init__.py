"""Read-only console API.

Public surface:

- :mod:`.auth` — extract a :class:`~aiopspilot.core.rbac.resolver.Principal`
  from an HTTP ``Authorization`` header and glue in
  :class:`~aiopspilot.core.rbac.enforcer.RoleEnforcer`. Framework-neutral;
  no ASGI framework is imported at module load.
- :mod:`.read_model` — projection Protocol + in-memory fake the console
  handlers read through.
- :mod:`.main` — Starlette app factory. This is the ONLY place Starlette
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
from .read_model import (
    AuditItem,
    AuditPage,
    ConsoleReadModel,
    DashboardKpi,
    HilQueueItem,
    HilQueuePage,
    InMemoryConsoleReadModel,
)

__all__ = [
    "AuditItem",
    "AuditPage",
    "AuthenticationError",
    "Authenticator",
    "ClaimsVerifier",
    "ConsoleReadModel",
    "DashboardKpi",
    "HilQueueItem",
    "HilQueuePage",
    "InMemoryConsoleReadModel",
    "UnsafeClaimsExtractor",
    "build_authenticator",
]
