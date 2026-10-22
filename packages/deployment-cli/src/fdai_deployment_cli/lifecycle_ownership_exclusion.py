"""Foundation ownership verification and operations-loop target exclusion."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal

from fdai_deployment_cli.contracts import canonical_bytes

_PREFIXED_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z", re.ASCII)


@dataclass(frozen=True, slots=True, kw_only=True)
class SignedFoundationOwnershipReceipt:
    """Signed Foundation creation receipt paired with Terraform state identity."""

    resource_ref: str
    foundation_receipt_digest: str
    terraform_state_digest: str
    signature: bytes

    def __post_init__(self) -> None:
        if not self.resource_ref.strip():
            raise ValueError("resource_ref MUST NOT be empty")
        if _PREFIXED_SHA256.fullmatch(self.foundation_receipt_digest) is None:
            raise ValueError("foundation_receipt_digest MUST be sha256:<64 hex>")
        if _PREFIXED_SHA256.fullmatch(self.terraform_state_digest) is None:
            raise ValueError("terraform_state_digest MUST be sha256:<64 hex>")

    def canonical_payload(self) -> bytes:
        return canonical_bytes(
            {
                "schema_version": "fdai.foundation-ownership-receipt.v1",
                "resource_ref": self.resource_ref,
                "foundation_receipt_digest": self.foundation_receipt_digest,
                "terraform_state_digest": self.terraform_state_digest,
            }
        )


@dataclass(frozen=True, slots=True)
class ProvenFoundationOwnershipRegistry:
    """Registry of resources with verified signed Foundation ownership receipts.

    A manual ``fdai:managed=true`` tag without a verified signed Foundation receipt and
    matching Terraform state digest is never admitted into this registry.
    """

    receipts_by_resource: Mapping[str, SignedFoundationOwnershipReceipt] = field(
        default_factory=dict
    )

    def register_verified(
        self,
        receipt: SignedFoundationOwnershipReceipt,
        *,
        verify_signature: Callable[[bytes, bytes], bool],
    ) -> ProvenFoundationOwnershipRegistry:
        if not receipt.signature or not bool(
            verify_signature(receipt.canonical_payload(), receipt.signature)
        ):
            raise ValueError("foundation_ownership_signature_invalid")
        updated = dict(self.receipts_by_resource)
        updated[receipt.resource_ref] = receipt
        return ProvenFoundationOwnershipRegistry(receipts_by_resource=updated)

    def is_proven_fdai_owned(self, resource_ref: str) -> bool:
        return resource_ref in self.receipts_by_resource

    def upstream_risk_gate_signal(self, target_resource_ref: str) -> Literal["deny"] | None:
        """Return ``"deny"`` for RiskGate.evaluate when an operations-loop action targets a
        proven FDAI-owned resource."""

        if self.is_proven_fdai_owned(target_resource_ref):
            return "deny"
        return None
