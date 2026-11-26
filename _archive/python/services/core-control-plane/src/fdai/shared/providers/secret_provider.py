"""Secret provider - Container Apps native secret + Key Vault reference by default.

Realizes the wire-level contract in
``docs/roadmap/architecture/csp-neutrality.md § Secret Contract``.

The application reads **environment variables** at runtime; the concrete
:class:`SecretProvider` implementation is a startup-time helper that resolves
secret references (Key Vault URI, K8s Secret mount, etc.) into env values.
Core modules NEVER call a CSP secret SDK directly - they call
:meth:`SecretProvider.get`.

Concrete implementations:

- **Upstream default** - Container Apps native secret (KV reference) resolved
  into env. Adapter lands in a later phase; today the env-only reader in
  :mod:`fdai.shared.config` is sufficient.
- **In-memory fake** - dict-backed, for unit tests (W6.2).
- **AKS / non-Azure** - External Secrets Operator with a ``SecretStore`` CRD.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


class SecretNotFoundError(LookupError):
    """Raised when a required secret is not resolvable.

    Fail-closed by contract: callers MUST propagate this (or map it to a
    startup error) - a missing secret is never silently defaulted.
    """


@runtime_checkable
class SecretProvider(Protocol):
    """Resolve a secret reference into its value.

    Async by contract - real backends (Key Vault SDK / K8s file-mount read /
    HashiCorp Vault HTTP) are I/O bound.

    Security rules:

    - The returned string MUST NEVER be logged, audited, or written to an
      error message. Implementations SHOULD zero the memory when possible.
    - A caller MUST NOT cache the value across process restarts; secrets
      may be rotated and stale caches are a compromise vector.
    """

    async def get(self, name: str) -> str:
        """Return the current value of the secret ``name``.

        Raises :class:`SecretNotFoundError` when the secret is unknown; never
        returns an empty string as a sentinel.
        """
        ...


__all__ = ["SecretNotFoundError", "SecretProvider"]
