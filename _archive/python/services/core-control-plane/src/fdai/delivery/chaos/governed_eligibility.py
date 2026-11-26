"""Deterministic eligibility inputs for one governed chaos enforce run.

The adapter derives every authority-bearing gate itself: promotion from the
ActionType mode source and the scenario ledger, approval from the verifier,
the tier ceiling from the ActionType, the mutation scope from the built
injector, lock ownership from the distributed target lock, the durable target
claim, and audit readiness from the audit chain. The planner supplies only
impact, recovery, and readiness evidence, so it cannot approve, promote, lock,
or widen its own run.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from fdai.core.chaos.governance import ChaosEligibilityContext
from fdai.core.chaos.injector import FaultInjector, SignalProbe
from fdai.core.chaos.promotion_evidence import ScenarioEvidenceKey
from fdai.core.chaos.scenario_catalog import CatalogEntry
from fdai.core.recovery import RecoveryPlanStatus
from fdai.delivery.chaos.governed_bindings import (
    ChaosApprovalEvidence,
    ChaosRunPlan,
    GovernedChaosBindings,
)
from fdai.delivery.chaos.governed_records import (
    CHAOS_ACTION_TYPE,
    autonomy_ceiling_enforce,
    time_box_seconds,
)
from fdai.delivery.chaos.mutation_scope import mutation_targets_approved
from fdai.shared.contracts.models import Mode, OntologyActionType
from fdai.shared.providers.tool import ToolCallRequest

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class EligibilityInputs:
    """Everything one run's eligibility context is derived from."""

    request: ToolCallRequest
    entry: CatalogEntry
    targets: tuple[str, ...]
    plan: ChaosRunPlan
    built: tuple[FaultInjector, SignalProbe] | None
    approval: ChaosApprovalEvidence | None
    targets_claimed: bool
    now: datetime


async def eligibility_context(
    inputs: EligibilityInputs,
    *,
    bindings: GovernedChaosBindings,
    action_type: OntologyActionType,
    promoted_ids: frozenset[str],
    catalog_fingerprint: str,
) -> ChaosEligibilityContext:
    plan = inputs.plan
    recovery_plan = plan.recovery_plan
    approval = inputs.approval
    return ChaosEligibilityContext(
        catalog_valid=inputs.built is not None,
        scenario_promoted=_scenario_promoted(
            inputs.entry,
            bindings=bindings,
            promoted_ids=promoted_ids,
            catalog_fingerprint=catalog_fingerprint,
        ),
        action_types_promoted=_action_types_promoted(plan, bindings=bindings),
        causal_hypothesis_ref=plan.causal_hypothesis_ref,
        refutation_query_ref=plan.refutation_query_ref,
        explicit_targets=inputs.targets,
        supported_environment=plan.supported_environment,
        owner_ref=plan.owner_ref,
        maintenance_window_active=plan.maintenance_window_active,
        graph_complete=plan.graph_complete,
        objective_headroom=plan.objective_headroom,
        recovery_ready=(
            plan.recovery_ready
            and recovery_plan.status is RecoveryPlanStatus.READY
            and inputs.now < recovery_plan.expires_at
        ),
        telemetry_ready=plan.telemetry_ready,
        no_conflicting_work=plan.no_conflicting_work and inputs.targets_claimed,
        dry_run_receipt=plan.dry_run_receipt,
        locks_acquired=bindings.target_lock.distributed is True,
        idempotency_key=inputs.request.idempotency_key,
        kill_switch_clear=plan.kill_switch_clear,
        stop_conditions_ready=(
            plan.stop_conditions_ready and time_box_seconds(inputs.request) is not None
        ),
        audit_ready=await _audit_ready(bindings),
        approval_principal=approval.approval_principal if approval is not None else "",
        approver_ids=approval.approver_ids if approval is not None else (),
        initiator_id=approval.initiator_id if approval is not None else "",
        autonomy_ceiling_enforce=autonomy_ceiling_enforce(action_type, inputs.request),
        mutation_targets_approved=mutation_targets_approved(
            inputs.built[0] if inputs.built is not None else None,
            inputs.targets,
        ),
        production_or_stateful=plan.production_or_stateful,
    )


def _scenario_promoted(
    entry: CatalogEntry,
    *,
    bindings: GovernedChaosBindings,
    promoted_ids: frozenset[str],
    catalog_fingerprint: str,
) -> bool:
    if entry.id not in promoted_ids:
        return False
    try:
        key = ScenarioEvidenceKey(
            scenario_id=entry.id,
            scenario_version=int(entry.spec["version"]),
            catalog_fingerprint=catalog_fingerprint,
        )
    except (KeyError, TypeError, ValueError):
        return False
    return bindings.scenario_ledger.is_enforce_eligible(key)


def _action_types_promoted(plan: ChaosRunPlan, *, bindings: GovernedChaosBindings) -> bool:
    names = {CHAOS_ACTION_TYPE}
    for item in plan.recovery_plan.actions:
        names.add(item.action_type_ref)
        if item.compensation_action_type_ref:
            names.add(item.compensation_action_type_ref)
    try:
        return all(bindings.action_registry.mode_of(name) is Mode.ENFORCE for name in sorted(names))
    except Exception:  # noqa: BLE001 - an unreadable registry keeps shadow authority
        _LOGGER.warning("governed_chaos_promotion_unreadable")
        return False


async def _audit_ready(bindings: GovernedChaosBindings) -> bool:
    try:
        return await bindings.state_store.verify_chain() is True
    except Exception:  # noqa: BLE001 - an unverifiable audit chain denies the run
        _LOGGER.warning("governed_chaos_audit_unverified")
        return False


__all__ = ["EligibilityInputs", "eligibility_context"]
