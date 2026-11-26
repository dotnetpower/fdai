"""Build and reconcile the deployment-local Rule activation generation."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from fdai_service_contracts.rule_activation import (
    RuleActivationApproval,
    RuleActivationCommand,
    RuleActivationDelta,
    RuleActivationGeneration,
    RuleActivationProposal,
    RuleActivationSource,
    RuleActivationStatus,
    rule_activation_proposal_digest,
)

from fdai.core.rule_activation import (
    RuleActivationCoordinator,
    StateStoreRuleActivationLedger,
    build_rule_activation_generation,
    resolve_rule_activation_generation,
)
from fdai.shared.contracts.models import Rule

BOOTSTRAP_REQUESTER_ENV = "FDAI_RULE_ACTIVATION_BOOTSTRAP_REQUESTER"
BOOTSTRAP_APPROVER_ENV = "FDAI_RULE_ACTIVATION_BOOTSTRAP_APPROVER"
PACKAGE_DIGEST_ENV = "FDAI_RULE_ACTIVATION_PACKAGE_DIGEST"
SOURCE_ENV = "FDAI_RULE_ACTIVATION_SOURCE"
SOURCE_REF_ENV = "FDAI_RULE_ACTIVATION_SOURCE_REF"
SOURCE_RECORDED_AT_ENV = "FDAI_RULE_ACTIVATION_SOURCE_RECORDED_AT"


@dataclass(frozen=True, slots=True)
class RuleActivationRuntimeReconciler:
    """Keep one Core replica aligned with the deployment-local current generation."""

    coordinator: RuleActivationCoordinator
    interval_seconds: float = 1.0

    def __post_init__(self) -> None:
        if not 0 < self.interval_seconds <= 60:
            raise ValueError("Rule activation reconciliation interval MUST be in (0, 60]")

    async def run_once(self) -> bool:
        return await self.coordinator.synchronize_runtime()

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            await self.run_once()
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.interval_seconds)
            except TimeoutError:
                continue


async def reconcile_rule_activation(
    *,
    ledger: StateStoreRuleActivationLedger,
    available_rules: Sequence[Rule],
    profile_id: str,
    profile_version: str,
    source_ref: str,
    source_digest: str,
    requested_by: str,
    approved_by: str,
    source: RuleActivationSource = RuleActivationSource.INSTALLATION,
    desired_rules: Sequence[Rule] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> tuple[tuple[Rule, ...], RuleActivationGeneration]:
    """Seed an empty store or resolve its exact current generation against local artifacts."""

    rules_by_id = {rule.id: rule for rule in available_rules}
    if not rules_by_id or len(rules_by_id) != len(available_rules):
        raise ValueError("Available Rule catalog MUST contain unique non-empty membership")
    now = (clock or (lambda: datetime.now(UTC)))()
    desired = tuple(desired_rules or available_rules)
    desired_ids = {rule.id for rule in desired}
    if not desired_ids or len(desired_ids) != len(desired):
        raise ValueError("Desired Rule activation MUST contain unique non-empty membership")
    if not desired_ids.issubset(rules_by_id):
        raise ValueError("Desired Rule activation references an unavailable Rule")
    catalog_generation = build_rule_activation_generation(
        available_rules,
        profile_id=profile_id,
        profile_version=profile_version,
        created_at=now,
    )
    generation = build_rule_activation_generation(
        desired,
        profile_id=profile_id,
        profile_version=profile_version,
        created_at=now,
        catalog_digest=catalog_generation.catalog_digest,
    )
    current = await ledger.current_generation()
    if current is not None and current.generation_digest == generation.generation_digest:
        return resolve_rule_activation_generation(current, rules_by_id), current
    if current is not None and source is RuleActivationSource.INSTALLATION:
        return resolve_rule_activation_generation(current, rules_by_id), current
    current_ids = {member.rule_id for member in current.members} if current is not None else set()
    changes = tuple(
        RuleActivationDelta(rule_id=rule_id, enabled=rule_id in desired_ids)
        for rule_id in sorted(current_ids ^ desired_ids)
    )
    if current is None and source not in {
        RuleActivationSource.INSTALLATION,
        RuleActivationSource.OFFLINE_PACKAGE,
    }:
        raise ValueError("Rule activation genesis source is invalid")
    idempotency_key = f"{source.value}:{source_digest}:{generation.generation_digest}"
    reason = (
        "Install the signed offline default Rule activation profile."
        if source is RuleActivationSource.OFFLINE_PACKAGE
        else "Install the reviewed default Rule activation profile."
    )
    proposal_digest = rule_activation_proposal_digest(
        idempotency_key=idempotency_key,
        expected_generation_digest=(current.generation_digest if current is not None else None),
        source=source,
        source_ref=source_ref,
        source_digest=source_digest,
        requested_by=requested_by,
        requested_at=now,
        reason=reason,
        changes=changes,
    )
    proposal = RuleActivationProposal(
        request_id=f"rule-activation-request-{proposal_digest[:32]}",
        idempotency_key=idempotency_key,
        expected_generation_digest=(current.generation_digest if current is not None else None),
        source=source,
        source_ref=source_ref,
        source_digest=source_digest,
        requested_by=requested_by,
        requested_at=now,
        reason=reason,
        changes=changes,
    )
    approval = RuleActivationApproval(
        proposal_digest=proposal.proposal_digest,
        approver_ids=(approved_by,),
        approved_at=now,
        approval_ref=f"{source.value}-approval:{source_digest}",
    )
    result = await ledger.apply(
        RuleActivationCommand(
            proposal=proposal,
            approval=approval,
            generation=generation,
            commanded_at=now,
        )
    )
    if result.status not in {
        RuleActivationStatus.APPLIED,
        RuleActivationStatus.ALREADY_APPLIED,
    }:
        raise RuntimeError(f"default Rule activation failed: {result.failure_reason}")
    return resolve_rule_activation_generation(generation, rules_by_id), generation


__all__ = [
    "BOOTSTRAP_APPROVER_ENV",
    "BOOTSTRAP_REQUESTER_ENV",
    "PACKAGE_DIGEST_ENV",
    "SOURCE_ENV",
    "SOURCE_RECORDED_AT_ENV",
    "SOURCE_REF_ENV",
    "RuleActivationRuntimeReconciler",
    "build_rule_activation_generation",
    "reconcile_rule_activation",
]
