"""Isolated-service safeguard proof bundle revalidation.

The isolated Executor revalidates proof bundles with its own validators,
importing no Core implementation. Validation runs before provider dispatch.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Protocol

from fdai_service_contracts.execution_safeguards import (
    SafeguardProofBundle,
    SafeguardProofKind,
)
from fdai_service_contracts.executor_models import (
    AnyExecutorCommand,
    ExecutorCommand,
    SafeguardBoundExecutorCommand,
)

_DIGEST_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
_REQUIRED_PROOF_KINDS = tuple(SafeguardProofKind)
_BUNDLE_MAX_AGE_SECONDS = 86_400  # 24 hours


class SafeguardBundleStore(Protocol):
    """Read-only port for retrieving a proof bundle by its digest."""

    async def resolve_bundle(self, bundle_digest: str) -> SafeguardProofBundle | None: ...


class BundleValidationRefusal:
    """Structured refusal with a machine-readable category."""

    __slots__ = ("category", "reason")

    def __init__(self, category: str, reason: str) -> None:
        self.category = category
        self.reason = reason

    def __repr__(self) -> str:
        return f"BundleValidationRefusal({self.category!r}, {self.reason!r})"


def validate_bundle_binding_sync(
    command: AnyExecutorCommand,
    bundle: SafeguardProofBundle | None,
    *,
    now: datetime,
) -> BundleValidationRefusal | None:
    """Revalidate the safeguard proof bundle against the command envelope.

    Returns ``None`` when the bundle is valid, or a refusal otherwise.
    Only v1.1.0 commands carry a bundle digest; v1.0.0 commands skip this
    validation for backward compatibility.
    """

    if isinstance(command, ExecutorCommand):
        return None

    if not isinstance(command, SafeguardBoundExecutorCommand):
        return BundleValidationRefusal("malformed", "command type is not recognized")

    digest = command.safeguard_proof_bundle_digest
    if not digest or not _DIGEST_PATTERN.match(digest):
        return BundleValidationRefusal(
            "malformed",
            "safeguard_proof_bundle_digest is missing or malformed",
        )

    if bundle is None:
        return BundleValidationRefusal(
            "missing",
            "safeguard proof bundle not found for the command digest",
        )

    if bundle.bundle_digest != digest:
        return BundleValidationRefusal(
            "mismatched",
            "resolved bundle digest does not match the command binding",
        )

    if str(bundle.action_id) != str(command.action_id):
        return BundleValidationRefusal(
            "substituted",
            "bundle action_id does not match command action_id",
        )

    if bundle.execution_path.value != command.execution_path.value:
        return BundleValidationRefusal(
            "wrong-path",
            "bundle execution_path does not match command execution_path",
        )

    payload_target = command.action_payload.get("target_resource_ref", "")
    if payload_target != command.target_resource_ref:
        return BundleValidationRefusal(
            "wrong-target",
            "action payload target_resource_ref does not match envelope",
        )

    if command.source_revision and bundle.source_revision != command.source_revision:
        return BundleValidationRefusal(
            "mismatched",
            "bundle source_revision does not match command source_revision",
        )

    age_seconds = (now - bundle.recorded_at).total_seconds()
    if age_seconds > _BUNDLE_MAX_AGE_SECONDS:
        return BundleValidationRefusal(
            "stale",
            f"bundle recorded_at is {age_seconds:.0f}s old, "
            f"exceeds {_BUNDLE_MAX_AGE_SECONDS}s limit",
        )

    if age_seconds < 0:
        return BundleValidationRefusal(
            "stale",
            "bundle recorded_at is in the future",
        )

    proof_kinds = tuple(proof.kind for proof in bundle.proofs)
    if proof_kinds != _REQUIRED_PROOF_KINDS:
        return BundleValidationRefusal(
            "malformed",
            "bundle proofs are incomplete or out of canonical order",
        )

    if bundle.execution_authority is not False:
        return BundleValidationRefusal(
            "substituted",
            "bundle claims execution_authority which is not permitted",
        )

    if bundle.effect_verified is not False:
        return BundleValidationRefusal(
            "substituted",
            "bundle claims effect_verified which is not permitted before observation",
        )

    return None


__all__ = [
    "BundleValidationRefusal",
    "SafeguardBundleStore",
    "validate_bundle_binding_sync",
]
