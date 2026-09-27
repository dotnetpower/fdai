"""Deployment-owned collaborators for governed chaos enforce runs.

:class:`GovernedChaosBindings` names every authority and evidence source the
governed adapter needs. The adapter never grants authority itself:

- the durable state store records Saga-audited run transitions;
- the ActionType mode source and the append-only scenario ledger prove
  promotion;
- the approval verifier proves current Var approval, with a separate closure
  intent that can never reuse the approval that authorized an injection;
- the planner supplies Vidar's compiled recovery plan, Heimdall's continuous
  impact guard, and the remaining readiness evidence;
- the recovery dispatcher executes pre-authorized Thor recovery actions;
- the evidence collector independently observes recovery; and
- the distributed target lock serializes each logical target across replicas,
  matching the enforce-mode lock requirement for Thor's execution bindings.

A deployment binds exactly one provider through the ``fdai.governed_chaos``
entry-point group under the ``catalog-scenario`` name. Upstream ships no
provider, so an unbound checkout refuses every enforce request.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
from importlib.metadata import entry_points
from typing import Protocol

from fdai.core.chaos.contract import FaultScenario
from fdai.core.chaos.guard import ImpactGuard
from fdai.core.chaos.promotion_evidence import ScenarioPromotionLedger
from fdai.core.quality_gate.promotion import ActionModeSource
from fdai.core.recovery import (
    RecoveryActionDispatcher,
    RecoveryEvidenceCollector,
    RecoveryPlanRecord,
)
from fdai.shared.providers.resource_lock import ResourceLock
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.tool import ToolCallRequest

GOVERNED_CHAOS_ENTRY_POINT_GROUP = "fdai.governed_chaos"
GOVERNED_CHAOS_ENTRY_POINT_NAME = "catalog-scenario"


CHAOS_ENFORCE_INTENT = "enforce"
CHAOS_CLOSURE_INTENT = "closure"


@dataclass(frozen=True, slots=True)
class ChaosApprovalEvidence:
    """Current human approval verified against the authoritative approval state.

    ``intent`` names the decision the approval records. An ``enforce`` approval
    authorizes one run; a ``closure`` approval releases the targets of one exact
    run and must also name that ``run_id`` and the ``target_digests`` it covers.
    Neither intent can stand in for the other.
    """

    approval_ref: str
    approval_principal: str
    approver_ids: tuple[str, ...]
    initiator_id: str
    intent: str = CHAOS_ENFORCE_INTENT
    run_id: str | None = None
    target_digests: tuple[str, ...] = ()


class ChaosApprovalVerifier(Protocol):
    """Verify current human approvals for governed chaos decisions.

    A reference carried by a request is a claim only. Each method returns
    ``None`` when no current approval with its intent covers the request.
    """

    async def verify(
        self,
        request: ToolCallRequest,
        *,
        run_id: str,
    ) -> ChaosApprovalEvidence | None:
        """Verify the ``enforce`` approval that covers one exact governed run."""
        ...

    async def verify_closure(
        self,
        request: ToolCallRequest,
        *,
        run_id: str,
    ) -> ChaosApprovalEvidence | None:
        """Verify a separate ``closure`` decision for a run that still holds its targets.

        Closure is a new human decision that manual recovery of ``run_id`` on the
        request's exact targets was verified. It is never the approval that
        authorized the run's injection. Return evidence with ``intent="closure"``,
        this ``run_id``, and the digests of exactly those targets.
        """
        ...


@dataclass(frozen=True, slots=True)
class ChaosRunPlan:
    """Planner-owned impact, recovery, and readiness evidence for one run.

    The plan cannot express promotion, approval, lock, idempotency, or audit
    readiness. The adapter derives those gates from their authoritative
    sources, so a planner cannot approve or promote its own run.
    """

    recovery_plan: RecoveryPlanRecord
    impact_guard: ImpactGuard
    causal_hypothesis_ref: str
    refutation_query_ref: str
    owner_ref: str
    dry_run_receipt: str
    supported_environment: bool
    maintenance_window_active: bool
    graph_complete: bool
    objective_headroom: bool
    recovery_ready: bool
    telemetry_ready: bool
    no_conflicting_work: bool
    kill_switch_clear: bool
    stop_conditions_ready: bool
    production_or_stateful: bool


class ChaosRunPlanner(Protocol):
    """Compile the typed run plan, or return ``None`` when it is unavailable."""

    async def plan(
        self,
        *,
        run_id: str,
        scenario: FaultScenario,
        targets: tuple[str, ...],
    ) -> ChaosRunPlan | None: ...


@dataclass(frozen=True, slots=True)
class GovernedChaosBindings:
    """Every collaborator is required, and the target lock must be distributed."""

    state_store: StateStore
    action_registry: ActionModeSource
    scenario_ledger: ScenarioPromotionLedger
    approval_verifier: ChaosApprovalVerifier
    planner: ChaosRunPlanner
    recovery_dispatcher: RecoveryActionDispatcher
    evidence_collector: RecoveryEvidenceCollector
    target_lock: ResourceLock

    def __post_init__(self) -> None:
        missing = sorted(item.name for item in fields(self) if getattr(self, item.name) is None)
        if missing:
            raise ValueError("governed chaos bindings are missing: " + ", ".join(missing))
        if getattr(self.target_lock, "distributed", False) is not True:
            raise ValueError("governed chaos bindings require a distributed target lock")


def load_governed_chaos_bindings(environment: Mapping[str, str]) -> GovernedChaosBindings | None:
    """Load the single installed deployment provider, or return ``None`` when unbound.

    Raises:
        RuntimeError: several providers are installed, the provider is not
            callable, or it returns anything other than
            :class:`GovernedChaosBindings`.
    """

    matches = tuple(
        item
        for item in entry_points(group=GOVERNED_CHAOS_ENTRY_POINT_GROUP)
        if item.name == GOVERNED_CHAOS_ENTRY_POINT_NAME
    )
    if not matches:
        return None
    if len(matches) != 1:
        raise RuntimeError("governed chaos execution requires exactly one installed provider")
    factory: object = matches[0].load()
    if not callable(factory):
        raise RuntimeError("governed chaos provider is not callable")
    bindings: object = factory(environment=environment)
    if not isinstance(bindings, GovernedChaosBindings):
        raise RuntimeError("governed chaos provider returned invalid bindings")
    return bindings


__all__ = [
    "CHAOS_CLOSURE_INTENT",
    "CHAOS_ENFORCE_INTENT",
    "GOVERNED_CHAOS_ENTRY_POINT_GROUP",
    "GOVERNED_CHAOS_ENTRY_POINT_NAME",
    "ChaosApprovalEvidence",
    "ChaosApprovalVerifier",
    "ChaosRunPlan",
    "ChaosRunPlanner",
    "GovernedChaosBindings",
    "load_governed_chaos_bindings",
]
