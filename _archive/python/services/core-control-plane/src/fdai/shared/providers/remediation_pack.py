"""Seams for remediation-pack signing and the authoritative pack registry.

A remediation pack leaves FDAI and runs on developer machines with third-party coding agents.
These Protocols keep key material and durable state out of ``core/``:

- :class:`PackSigner` signs the exact manifest bytes (Ed25519 in the upstream adapter);
- :class:`PackSignatureVerifier` verifies a signature for a key id;
- :class:`RemediationPackRegistry` stores FDAI's own record of every exported pack, including
  revocation, so result import never trusts data carried inside the pack.

Adapters live under ``delivery/`` and are bound at the composition root or the operator CLI.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from fdai.core.security.code_findings.result_import import PackRecord


class PackRegistryError(RuntimeError):
    """Raised when the registry cannot read or write a record; callers fail closed."""


@runtime_checkable
class PackSigner(Protocol):
    """Sign remediation-pack manifests with one private key."""

    @property
    def key_id(self) -> str:
        """Stable identifier of the public key that verifies this signer's signatures."""
        ...

    def sign(self, message: bytes) -> bytes:
        """Return the raw signature over ``message``."""
        ...


@runtime_checkable
class PackSignatureVerifier(Protocol):
    """Verify remediation-pack manifest signatures."""

    def verify(self, message: bytes, signature: bytes, key_id: str) -> bool:
        """Return ``True`` only for a valid signature by a trusted key with ``key_id``."""
        ...


@runtime_checkable
class RemediationPackRegistry(Protocol):
    """Durable, FDAI-owned record of exported remediation packs."""

    async def record(self, pack: PackRecord) -> None:
        """Store a newly exported pack. Recording an existing pack id raises."""
        ...

    async def get(self, pack_id: str) -> PackRecord | None:
        """Return the pack record, or ``None`` when FDAI never exported that pack."""
        ...

    async def revoke(self, pack_id: str, reason: str) -> PackRecord:
        """Mark a pack revoked so its results are rejected. Unknown ids raise."""
        ...

    async def list_active(self) -> Sequence[PackRecord]:
        """Return packs that are neither revoked nor expired at the registry's clock."""
        ...

    async def record_baseline(self, pack_id: str, document: Mapping[str, Any]) -> None:
        """Store the baseline coverage receipt and issue snapshot taken at export."""
        ...

    async def get_baseline(self, pack_id: str) -> Mapping[str, Any] | None:
        """Return the stored baseline, or ``None`` when absent."""
        ...

    async def append_review(self, pack_id: str, document: Mapping[str, Any]) -> None:
        """Append one immutable review record (fix verification or adjudication)."""
        ...

    async def list_reviews(self, pack_id: str) -> Sequence[Mapping[str, Any]]:
        """Return review records in append order."""
        ...


__all__ = [
    "PackRegistryError",
    "PackSignatureVerifier",
    "PackSigner",
    "RemediationPackRegistry",
]
