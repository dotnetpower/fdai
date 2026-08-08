"""Workload identity - OIDC token issuer; user-assigned MI by default.

Realizes the wire-level contract in
``docs/roadmap/architecture/csp-neutrality.md § Workload Identity Contract``.

Core modules hold a :class:`WorkloadIdentity` reference (obtained via
:class:`fdai.composition.Container`) and never a
``DefaultAzureCredential`` or similar SDK entry point. Concrete
implementations translate an audience string into a short-lived token
retrieved from the runtime substrate (IMDS on Azure, IRSA on AWS, Workload
Identity Federation on GCP, SPIFFE/SPIRE on any K8s).

Security rules:

- Tokens are **short-lived**. Consumers MUST NOT persist them.
- Approval identities and execution identities are distinct principals;
  a token issued to the executor MUST NOT be reused by a read-only surface
  (see ``security-and-identity.md``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class IdentityToken:
    """A short-lived OIDC token.

    ``expires_at`` is timezone-aware UTC. The dataclass is frozen so a caller
    cannot mutate the expiry to extend the token's window in-process.
    """

    token: str
    expires_at: datetime
    audience: str


@runtime_checkable
class WorkloadIdentity(Protocol):
    """Get a short-lived, audience-scoped OIDC token.

    Async by contract - the token exchange is an HTTP round trip (IMDS on
    Azure; the AWS STS / GCP token endpoint elsewhere).
    """

    async def get_token(self, audience: str) -> IdentityToken:
        """Return a token valid for the given ``audience``.

        Implementations MUST NOT return a token issued for a different
        audience even if one is cached; cross-audience reuse is denied by
        the workload-identity contract.
        """
        ...


__all__ = ["IdentityToken", "WorkloadIdentity"]
