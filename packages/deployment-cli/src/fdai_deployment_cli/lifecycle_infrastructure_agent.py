"""Infrastructure agent envelope guard, destructive-change confirmation hold, and coordinator seam."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

from fdai_deployment_cli.lifecycle_authorization import (
    LifecycleAuthorizationReceipt,
    LifecyclePhaseCompletionReceipt,
    evaluate_phase_authorization,
    exact_plan_digest_for,
)
from fdai_deployment_cli.lifecycle_plan import LifecyclePlan
from fdai_deployment_cli.private_output import write_private_output

ResourceAction = Literal["create", "update", "delete", "replace"]
InfraAgentOutcome = Literal["applied", "held-for-confirmation", "rejected"]

INSTALLATION_BINDING_FORMAT = "fdai.installation-binding.v1"
_PREFIXED_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z", re.ASCII)
_DESTRUCTIVE_ACTIONS = frozenset({"delete", "replace"})
_BINDING_KEY = re.compile(r"[a-z][a-z0-9_.-]{0,62}\Z", re.ASCII)
_MAX_BINDING_VALUES = 128
_MAX_BINDING_VALUE_LENGTH = 1024
_CREDENTIAL_VALUE = re.compile(
    r"(?i)([a-z][a-z0-9+.-]*://[^/\s]*@|\*{6}|accountkey=|sharedaccesskey=|-----BEGIN )"
)


def validate_installation_binding_values(
    values: Mapping[str, object],
    *,
    allowed_keys: frozenset[str],
) -> dict[str, str]:
    """Validate exact reviewed Terraform outputs without exposing rejected values."""

    if len(values) > _MAX_BINDING_VALUES:
        raise ValueError("installation binding has too many values")
    if set(values) - allowed_keys:
        raise ValueError("installation binding names a key the bundle does not reference")
    if allowed_keys - set(values):
        raise ValueError("installation binding lacks a key the bundle references")
    validated: dict[str, str] = {}
    for key, value in values.items():
        if not isinstance(key, str) or _BINDING_KEY.fullmatch(key) is None:
            raise ValueError("installation binding key is invalid")
        if (
            not isinstance(value, str)
            or not 1 <= len(value) <= _MAX_BINDING_VALUE_LENGTH
            or any(ord(character) < 32 or ord(character) == 127 for character in value)
            or _CREDENTIAL_VALUE.search(value)
        ):
            raise ValueError("installation binding value is invalid")
        validated[key] = value
    return validated


def write_installation_binding(
    path: Path,
    values: Mapping[str, object],
    *,
    allowed_keys: frozenset[str],
) -> None:
    """Persist exact reviewed Terraform outputs as one private installation binding."""

    validated = validate_installation_binding_values(values, allowed_keys=allowed_keys)
    document = {
        "format": INSTALLATION_BINDING_FORMAT,
        "values": validated,
    }
    write_private_output(
        path,
        json.dumps(document, sort_keys=True, separators=(",", ":")),
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class PlannedResourceChange:
    """One resource change rendered in an exact Terraform plan."""

    address: str
    resource_id: str
    entity_id: str
    region: str
    actions: tuple[ResourceAction, ...]

    def __post_init__(self) -> None:
        if not self.address.strip() or not self.resource_id.strip():
            raise ValueError("address and resource_id MUST NOT be empty")
        if not self.entity_id.strip() or not self.region.strip():
            raise ValueError("entity_id and region MUST NOT be empty")
        if not self.actions:
            raise ValueError("actions MUST NOT be empty")

    @property
    def is_destructive(self) -> bool:
        action_set = set(self.actions)
        return bool(action_set & _DESTRUCTIVE_ACTIONS)


@dataclass(frozen=True, slots=True, kw_only=True)
class DestructiveChangeConfirmation:
    """Operator confirmation bound to the exact Plan digest and destructive resource addresses."""

    exact_plan_digest: str
    confirmed_addresses: frozenset[str]
    operator: str
    reason: str
    confirmed_at: datetime

    def __post_init__(self) -> None:
        if _PREFIXED_SHA256.fullmatch(self.exact_plan_digest) is None:
            raise ValueError("exact_plan_digest MUST be sha256:<64 hex>")
        if not self.confirmed_addresses or any(
            not addr.strip() for addr in self.confirmed_addresses
        ):
            raise ValueError("confirmed_addresses MUST NOT be empty")
        if not self.operator.strip() or not self.reason.strip():
            raise ValueError("operator and reason MUST NOT be empty")
        if self.confirmed_at.tzinfo is None or self.confirmed_at.utcoffset() is None:
            raise ValueError("confirmed_at MUST include timezone information")


class ExactPlanCoordinator(Protocol):
    """Existing exact-plan claim, apply, and verification-only recovery coordinator seam."""

    def claim_apply_and_verify(
        self,
        *,
        plan_id: str,
        exact_plan_digest: str,
        authorization_receipt_digest: str,
        changes: tuple[PlannedResourceChange, ...],
    ) -> bool: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class InfrastructurePhaseResult:
    """Outcome of one infrastructure agent phase execution."""

    outcome: InfraAgentOutcome
    reason_code: str
    held_addresses: tuple[str, ...] = ()
    completion_receipt: LifecyclePhaseCompletionReceipt | None = None


class InfrastructureAgent:
    """Execute in-envelope infrastructure changes and hold deletions/replacements for confirmation."""

    def __init__(self, coordinator: ExactPlanCoordinator) -> None:
        self._coordinator = coordinator

    def execute_phase(
        self,
        plan: LifecyclePlan,
        *,
        authorization_receipt: LifecycleAuthorizationReceipt | None,
        planned_changes: Sequence[PlannedResourceChange],
        trusted_now: datetime,
        confirmation: DestructiveChangeConfirmation | None = None,
    ) -> InfrastructurePhaseResult:
        auth_decision = evaluate_phase_authorization(
            plan,
            phase="infrastructure",
            authorization_receipt=authorization_receipt,
            trusted_now=trusted_now,
        )
        if not auth_decision.allowed or authorization_receipt is None:
            return InfrastructurePhaseResult(
                outcome="rejected",
                reason_code=auth_decision.reason_code,
            )

        changes = tuple(planned_changes)
        for change in changes:
            if (
                change.entity_id not in plan.envelope.entity_ids
                or change.region not in plan.envelope.regions
            ):
                return InfrastructurePhaseResult(
                    outcome="rejected",
                    reason_code="change_exceeds_envelope",
                )

        destructive_addresses = frozenset(
            change.address for change in changes if change.is_destructive
        )
        expected_plan_digest = exact_plan_digest_for(plan)
        if destructive_addresses:
            if (
                confirmation is None
                or confirmation.exact_plan_digest != expected_plan_digest
                or not destructive_addresses <= confirmation.confirmed_addresses
            ):
                return InfrastructurePhaseResult(
                    outcome="held-for-confirmation",
                    reason_code="destructive_change_confirmation_required",
                    held_addresses=tuple(sorted(destructive_addresses)),
                )

        applied = self._coordinator.claim_apply_and_verify(
            plan_id=plan.plan_id,
            exact_plan_digest=expected_plan_digest,
            authorization_receipt_digest=authorization_receipt.digest,
            changes=changes,
        )
        if not applied:
            return InfrastructurePhaseResult(
                outcome="rejected",
                reason_code="exact_plan_coordinator_failed",
            )

        receipt = LifecyclePhaseCompletionReceipt(
            plan_id=plan.plan_id,
            exact_plan_digest=expected_plan_digest,
            fencing_generation=plan.fencing_generation,
            phase="infrastructure",
            authorization_receipt_digest=authorization_receipt.digest,
            completed_at=trusted_now,
        )
        return InfrastructurePhaseResult(
            outcome="applied",
            reason_code="applied",
            completion_receipt=receipt,
        )
