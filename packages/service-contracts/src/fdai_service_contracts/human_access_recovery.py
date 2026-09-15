"""Exact owned membership mutation evidence for separately approved, non-recursive recovery.

These records identify an inverse; they never authorize it. Current human review,
promotion, case/demand admission, target lineage and the shared safeguards remain
mandatory at dispatch. Pre-existing membership is never a recoverable owned change.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

Digest = Annotated[str, Field(strict=True, pattern=r"^[a-f0-9]{64}$")]
ActionDigest = Annotated[str, Field(strict=True, pattern=r"^sha256:[a-f0-9]{64}$")]
SafeRef = Annotated[str, Field(strict=True, pattern=r"^[A-Za-z0-9._:-]{1,256}$")]


def membership_attempt_key(idempotency_key: str) -> str:
    """Resolve the original Executor-owned intent/result key without changing legacy identity."""
    value = json.dumps({"idempotency_key": idempotency_key}, sort_keys=True, separators=(",", ":"))
    return "isolated-executor:human-access:" + hashlib.sha256(value.encode()).hexdigest()


def mutation_evidence_digest(intent: Mapping[str, Any], result: Mapping[str, Any]) -> str:
    """Address exact retained records; this digest is not proof of ownership by itself."""
    value = json.dumps(
        {"intent": dict(intent), "result": dict(result)},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(value.encode()).hexdigest()


def require_inverse_fence(
    binding: HumanAccessInverseBinding, fence: Mapping[str, Any], *, inverse_key: str
) -> None:
    """Accept only the pinned resolved predecessor or this inverse's next shared generation."""
    identity = fence.get("identity")
    if not isinstance(identity, Mapping):
        raise ValueError("human access recovery target fence is unavailable")
    prior = (
        fence.get("state") == "resolved"
        and fence.get("record_digest") == binding.target_fence_digest
        and identity.get("generation") == binding.target_fence_generation
        and identity.get("sink_idempotency_key") == binding.original_idempotency_key
    )
    current = (
        identity.get("generation") == binding.target_fence_generation + 1
        and identity.get("sink_idempotency_key") == inverse_key
        and fence.get("state")
        in {"preparing", "prepared", "in_flight", "release_pending", "quarantined"}
    )
    if not prior and not current:
        raise ValueError("human access recovery target has intervening execution lineage")


class HumanAccessInverseBinding(BaseModel):
    """Private exact inverse of one acknowledged owned mutation, frozen before fresh human review."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    original_action_id: UUID
    original_action_digest: ActionDigest
    original_material_digest: Digest
    original_idempotency_key: SafeRef
    original_target_digest: Digest
    original_attempt_digest: Digest
    original_before_membership: Annotated[bool, Field(strict=True)]
    original_receipt_ref: SafeRef
    original_completed_at: datetime
    target_fence_digest: ActionDigest
    target_fence_generation: Annotated[int, Field(strict=True, ge=1)]
    demand_digest: Digest
    source_case_state: Literal["degraded"] = "degraded"

    @model_validator(mode="after")
    def aware_original_time(self) -> HumanAccessInverseBinding:
        """A recorded original acknowledgement must retain an aware effective time."""
        if (
            self.original_completed_at.tzinfo is None
            or self.original_completed_at.utcoffset() is None
        ):
            raise ValueError("human access recovery original completion MUST be timezone-aware")
        return self

    def require_owned(self, intent: Mapping[str, Any], result: Mapping[str, Any]) -> None:
        """Refuse changed, uncertain, pre-existing or rebound original mutation evidence."""
        expected = {
            "action_digest": self.original_action_digest,
            "material_digest": self.original_material_digest,
            "target_digest": self.original_target_digest,
            "idempotency_key": self.original_idempotency_key,
        }
        if (
            any(
                intent.get(key) != value or result.get(key) != value
                for key, value in expected.items()
            )
            or intent.get("before_membership") is not self.original_before_membership
            or result.get("owned_mutation") is not True
            or result.get("outcome") != "succeeded"
            or result.get("receipt_ref") != self.original_receipt_ref
            or result.get("recorded_at") != self.original_completed_at.isoformat()
            or mutation_evidence_digest(intent, result) != self.original_attempt_digest
        ):
            raise ValueError("human access recovery lacks its exact acknowledged owned mutation")


__all__ = [
    "HumanAccessInverseBinding",
    "membership_attempt_key",
    "mutation_evidence_digest",
    "require_inverse_fence",
]
