"""Decision-start admission policy pinning for operator policy revisions."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from fdai_service_contracts.policy_administration import (
    AdmissionPolicyContent,
    PolicyKind,
    PolicyRevisionRecord,
)

from fdai.core.risk_gate.approval_profile import OperatorPolicyInput, OperatorPolicyOutcome

if TYPE_CHECKING:
    from fdai.shared.providers.state_store import StateStore

_LOGGER = logging.getLogger(__name__)


class OperatorPolicyRevisionReader(Protocol):
    """Read the active admission policy and immutable revision content."""

    async def active_revision_id(self, policy_kind: PolicyKind) -> str | None: ...

    async def revision(
        self,
        *,
        policy_kind: PolicyKind,
        revision_id: str,
    ) -> PolicyRevisionRecord | None: ...


class AdmissionPolicyEvaluator(Protocol):
    """Evaluate one pinned admission Rego revision against bounded action input."""

    async def evaluate(
        self,
        *,
        revision: PolicyRevisionRecord,
        action_input: Mapping[str, Any],
    ) -> OperatorPolicyOutcome: ...


@dataclass(frozen=True, slots=True)
class StateStoreOperatorPolicyRevisionReader:
    """Read active policy revisions from Mimir's StateStore projection."""

    store: StateStore

    async def active_revision_id(self, policy_kind: PolicyKind) -> str | None:
        stored = await self.store.read_state(_activation_key(policy_kind))
        revision_id = stored.get("revision_id") if stored is not None else None
        return revision_id if isinstance(revision_id, str) and revision_id else None

    async def revision(
        self,
        *,
        policy_kind: PolicyKind,
        revision_id: str,
    ) -> PolicyRevisionRecord | None:
        stored = await self.store.read_state(_revision_key(policy_kind, revision_id))
        if stored is None:
            return None
        return PolicyRevisionRecord.model_validate(stored)


@dataclass(frozen=True, slots=True)
class OperatorPolicyDecisionBinder:
    """Bind the active admission revision once at decision start.

    The returned :class:`OperatorPolicyInput` carries the immutable revision id
    and digest that replay and HIL resume reuse. Missing policy keeps existing
    behavior. Unreadable or unevaluable policy fails closed to HIL.
    """

    reader: OperatorPolicyRevisionReader
    evaluator: AdmissionPolicyEvaluator
    timeout_seconds: float = 6.0

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0 or self.timeout_seconds > 30:
            raise ValueError("operator policy timeout MUST be in (0, 30]")

    async def bind(self, *, action_input: Mapping[str, Any]) -> OperatorPolicyInput | None:
        try:
            revision_id = await asyncio.wait_for(
                self.reader.active_revision_id(PolicyKind.ADMISSION),
                timeout=self.timeout_seconds,
            )
            if revision_id is None:
                return None
            revision = await asyncio.wait_for(
                self.reader.revision(policy_kind=PolicyKind.ADMISSION, revision_id=revision_id),
                timeout=self.timeout_seconds,
            )
            if revision is None or not isinstance(revision.content, AdmissionPolicyContent):
                return OperatorPolicyInput(
                    revision_id=revision_id,
                    policy_digest="sha256:" + "0" * 64,
                    outcome=OperatorPolicyOutcome.REQUIRE_APPROVAL,
                )
            outcome = await asyncio.wait_for(
                self.evaluator.evaluate(revision=revision, action_input=action_input),
                timeout=self.timeout_seconds,
            )
            return OperatorPolicyInput(
                revision_id=revision.revision_id,
                policy_digest=revision.content_digest,
                outcome=outcome,
            )
        except Exception as exc:  # noqa: BLE001 - unreadable policy fails closed with evidence
            _LOGGER.warning(
                "operator_policy_binding_failed",
                extra={"error_type": type(exc).__name__},
                exc_info=True,
            )
            return OperatorPolicyInput(
                revision_id="evaluation-error",
                policy_digest="sha256:" + "0" * 64,
                outcome=OperatorPolicyOutcome.REQUIRE_APPROVAL,
            )


def bounded_action_policy_input(
    *,
    action_type: str,
    resource_id: str,
    environment: str,
    mode: str,
    policy_violation: bool,
    irreversible: bool,
    operation: str,
) -> dict[str, Any]:
    """Return the bounded admission input supplied to operator Rego."""

    return {
        "action_type": action_type,
        "resource_id": resource_id,
        "environment": environment,
        "mode": mode,
        "policy_violation": policy_violation,
        "irreversible": irreversible,
        "operation": operation,
    }


def _revision_key(policy_kind: PolicyKind, revision_id: str) -> str:
    return f"policy_revision:{policy_kind.value}:{revision_id}"


def _activation_key(policy_kind: PolicyKind) -> str:
    return f"policy_activation:{policy_kind.value}"


__all__ = [
    "AdmissionPolicyEvaluator",
    "OperatorPolicyDecisionBinder",
    "OperatorPolicyRevisionReader",
    "StateStoreOperatorPolicyRevisionReader",
    "bounded_action_policy_input",
]
