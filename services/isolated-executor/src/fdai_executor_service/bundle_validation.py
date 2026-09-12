"""Isolated-service safeguard proof bundle revalidation.

The isolated Executor revalidates proof bundles with its own validators,
importing no Core implementation. Validation runs before provider dispatch.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from fdai_service_contracts.execution_safeguards import (
    SafeguardProofBundle,
    SafeguardProofKind,
)
from fdai_service_contracts.executor_models import (
    Action,
    AnyExecutorCommand,
    ExecutorCommand,
    Mode,
    SafeguardBoundExecutorCommand,
    executor_action_fingerprint,
)
from pydantic import ValidationError

_DIGEST_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
_REQUIRED_PROOF_KINDS = tuple(SafeguardProofKind)
_BUNDLE_MAX_AGE_SECONDS = 86_400  # 24 hours


@dataclass(frozen=True, slots=True)
class ResolvedSafeguardBundle:
    """A bundle plus its authoritative reservation attempt."""

    bundle: SafeguardProofBundle
    reservation_attempt: int

    def __post_init__(self) -> None:
        if type(self.bundle) is not SafeguardProofBundle:
            raise ValueError("resolved safeguard bundle requires an exact bundle")
        if type(self.reservation_attempt) is not int or self.reservation_attempt < 1:
            raise ValueError("resolved safeguard reservation attempt MUST be positive")


class SafeguardBundleStore(Protocol):
    """Read-only port for retrieving a proof bundle by its digest."""

    async def resolve_bundle(self, bundle_digest: str) -> SafeguardProofBundle | None: ...

    async def resolve_bundle_context(
        self,
        bundle_digest: str,
    ) -> ResolvedSafeguardBundle | None: ...


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
    reservation_attempt: int | None = None,
) -> BundleValidationRefusal | None:
    """Revalidate the safeguard proof bundle against the command envelope.

    Returns ``None`` when the bundle is valid, or a refusal otherwise.
    Only v1.1.0 commands carry a bundle digest. The effect service rejects
    v1.0.0 by default and may admit it only during the explicit bounded
    legacy-unbound rollout transition.
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
    if reservation_attempt is not None and reservation_attempt != command.attempt:
        return BundleValidationRefusal(
            "substituted",
            "bundle reservation attempt does not match command attempt",
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

    try:
        action = Action.model_validate(command.action_payload)
    except ValidationError:
        return BundleValidationRefusal(
            "malformed",
            "command action payload is invalid",
        )
    if action.target_resource_ref != command.target_resource_ref:
        return BundleValidationRefusal(
            "wrong-target",
            "action payload target_resource_ref does not match envelope",
        )
    expected_fingerprint = "sha256:" + executor_action_fingerprint(
        action_payload=action.model_dump(mode="json", exclude_none=False),
        execution_path=command.execution_path.value,
    )
    if bundle.execution_fingerprint != expected_fingerprint and not (
        command.requested_mode is Mode.SHADOW
        and bundle.execution_fingerprint == _legacy_execution_fingerprint(action, command)
    ):
        return BundleValidationRefusal(
            "substituted",
            "bundle execution fingerprint does not match command action payload",
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


def _legacy_execution_fingerprint(
    action: Action,
    command: SafeguardBoundExecutorCommand,
) -> str:
    payload = {
        "action_id": str(action.action_id),
        "event_id": str(action.event_id),
        "action_type": action.action_type,
        "target_resource_ref": action.target_resource_ref,
        "operation": action.operation.value,
        "params": dict(action.params),
        "stop_condition": action.stop_condition,
        "rollback": {
            "kind": action.rollback_ref.kind.value,
            "reference": action.rollback_ref.reference,
        },
        "blast_radius": {
            "scope": action.blast_radius.scope.value,
            "count": action.blast_radius.count,
            "rate_per_minute": action.blast_radius.rate_per_minute,
        },
        "mode": action.mode.value,
        "executor_identity_ref": action.executor_identity_ref,
        "citing_rules": sorted(action.citing_rules),
        "execution_path": command.execution_path.value,
    }
    canonical = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


__all__ = [
    "BundleValidationRefusal",
    "ResolvedSafeguardBundle",
    "SafeguardBundleStore",
    "validate_bundle_binding_sync",
]
