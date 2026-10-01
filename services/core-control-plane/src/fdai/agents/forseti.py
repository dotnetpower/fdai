"""Forseti owns typed judgment, cross-domain arbitration and bounded planning.

Evidence, current policy and RBAC govern verdicts; planning never grants execution authority.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from weakref import WeakValueDictionary

from fdai.agents._framework.action_semantics import (
    ActionSemanticsCatalog,
)
from fdai.agents._framework.alert_noise_callbacks import ForsetiAlertNoiseMixin
from fdai.agents._framework.anomaly_action import AnomalyActionSource
from fdai.agents._framework.assignment_workflow import AssignmentJudgmentMixin
from fdai.agents._framework.base import Agent
from fdai.agents._framework.bounded import BoundedLruDict, BoundedLruSet
from fdai.agents._framework.bus import PantheonBus
from fdai.agents._framework.cross_vertical_candidates import (
    CrossVerticalCandidateAccumulator,
)
from fdai.agents._framework.forseti_arbitration import (
    _MAX_RESOURCES,
    ForsetiArbitrationMixin,
    _DecisionProjection,
)
from fdai.agents._framework.forseti_decision_helpers import (
    ChangeAssessor,
)
from fdai.agents._framework.forseti_development_authority import (
    ForsetiDevelopmentAuthorityMixin,
)
from fdai.agents._framework.forseti_judgment import (
    DEFAULT_JUDGMENT_TABLE,
    ForsetiJudgmentMixin,
    JudgmentTable,
)
from fdai.agents._framework.forseti_quality_runtime import (
    ForsetiQualityRuntimeMixin,
)
from fdai.agents._framework.forseti_quality_runtime import (
    _ratio_kpi as _ratio_kpi,
)
from fdai.agents._framework.forseti_runtime_events import (
    ForsetiRuntimeEventsMixin,
)
from fdai.agents._framework.forseti_runtime_events import (
    _rule_revision as _rule_revision,
)
from fdai.agents._framework.forseti_runtime_events import (
    _rule_state_is_newer as _rule_state_is_newer,
)
from fdai.agents._framework.forseti_runtime_events import (
    _rule_updated_at as _rule_updated_at,
)
from fdai.agents._framework.handover_knowledge import HandoverKnowledgeMixin
from fdai.agents._framework.pantheon import _FORSETI
from fdai.core.architecture_review import (
    OntologyArchitectureReviewLoop,
)
from fdai.core.decision_case import (
    DomainDecisionCoordinator,
)
from fdai.core.operational_context import OperationalContextMaterializer, SourceFreshness
from fdai.core.operational_context.test_context import TestContextSource
from fdai.core.operational_planning import (
    KineticActionProposalSource,
    SpecialistPlanningCoordinator,
)
from fdai.core.operational_planning.prospective_lineage import (
    ProspectiveLineageFinalizer,
)
from fdai.shared.contracts.models import (
    FullAuthorityDevelopmentProfile,
    RegisteredDevelopmentAction,
)
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmissionProvider
from fdai.shared.providers.development_authority import DevelopmentAuthorityBindingSource
from fdai.shared.providers.state_store import StateStore

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Deterministic tables (wave 3 defaults)
# ---------------------------------------------------------------------------

# ``event_type -> proposed ActionType id`` (rule match). Wave 3 uses a
# tiny in-memory table; real T0 loader consumes rule catalog YAML.
# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------

# An absent deployment policy grants no operator authority. Tests and composition
# roots that need an allowed principal inject an explicit mapping.
_DEFAULT_RBAC: dict[str, frozenset[str]] = {}
_DEFAULT_RULE_STALENESS_WINDOW = timedelta(hours=1)
_QUALITY_SAMPLE_LIMIT = 512

# LRU cap on the per-resource domain-advice maps, so a long-lived judge that
# sees advice for many resources without a conflict cannot leak memory.


# The topic whose single owner is the pantheon's arbitration authority.
# Resolved from the registry so the fail-closed path can never name a
# second arbiter or drift from the fixed pantheon.


class Forseti(
    ForsetiRuntimeEventsMixin,
    ForsetiQualityRuntimeMixin,
    Agent,
    ForsetiDevelopmentAuthorityMixin,
    ForsetiJudgmentMixin,
    ForsetiArbitrationMixin,
    HandoverKnowledgeMixin,
    AssignmentJudgmentMixin,
    ForsetiAlertNoiseMixin,
):
    """Wave-3 Forseti: rule match + risk verdict + RBAC + SecurityEvent.

    ``governed_execution_selected`` is the explicit add-on selection. Its default keeps
    forecasts and prediction-fed capacity arbitration advisory: they publish ActionType-free
    Verdicts, and only the selected add-on lets them reach the existing action gates.
    """

    def __init__(
        self,
        *,
        bus: PantheonBus | None = None,
        rbac: dict[str, frozenset[str]] | None = None,
        action_semantics: ActionSemanticsCatalog | None = None,
        judgment_table: JudgmentTable | None = None,
        operational_context: OperationalContextMaterializer | None = None,
        test_context_source: TestContextSource | None = None,
        test_context_admission: DecisionEvidenceAdmissionProvider | None = None,
        test_context_clock: Callable[[], datetime] | None = None,
        decision_coordinator: DomainDecisionCoordinator | None = None,
        operational_planner: SpecialistPlanningCoordinator | None = None,
        kinetic_proposal_source: KineticActionProposalSource | None = None,
        prospective_lineage_finalizer: ProspectiveLineageFinalizer | None = None,
        change_assessor: ChangeAssessor | None = None,
        architecture_review_loop: OntologyArchitectureReviewLoop | None = None,
        agent_availability: Callable[[], Iterable[str]] | None = None,
        cross_vertical_timeout_seconds: float = 30.0,
        architecture_review_timeout_seconds: float = 30.0,
        change_assessment_timeout_seconds: float = 30.0,
        anomaly_action_sources: Mapping[str, AnomalyActionSource] | None = None,
        development_profile: FullAuthorityDevelopmentProfile | None = None,
        development_binding_source: DevelopmentAuthorityBindingSource | None = None,
        development_executor_principal: str | None = None,
        development_action_types: Mapping[str, RegisteredDevelopmentAction] | None = None,
        governed_execution_selected: bool = False,
        rule_staleness_window: timedelta = _DEFAULT_RULE_STALENESS_WINDOW,
        state_store: StateStore | None = None,
    ) -> None:
        if cross_vertical_timeout_seconds <= 0.0 or cross_vertical_timeout_seconds > 300.0:
            raise ValueError("cross_vertical_timeout_seconds MUST be in (0, 300]")
        if architecture_review_timeout_seconds <= 0.0:
            raise ValueError("architecture_review_timeout_seconds MUST be positive")
        if change_assessment_timeout_seconds <= 0.0:
            raise ValueError("change_assessment_timeout_seconds MUST be positive")
        if rule_staleness_window <= timedelta(0):
            raise ValueError("rule_staleness_window MUST be positive")
        super().__init__(spec=_FORSETI)
        self.bus = bus
        # Observation-first by default: learned and predicted input stays advisory (#1541).
        self._governed_execution_selected = governed_execution_selected is True
        self._advisory_arbitrations: BoundedLruDict[str, dict[str, Any]] = BoundedLruDict(
            _MAX_RESOURCES
        )
        self.initialize_assignment_checks()
        self._rbac = rbac if rbac is not None else _DEFAULT_RBAC
        self._action_semantics = action_semantics
        self._judgment_table = judgment_table or DEFAULT_JUDGMENT_TABLE
        self._forseti_state_store = state_store
        self._operational_context = operational_context
        self._test_context_source = test_context_source
        self._test_context_admission = test_context_admission
        self._test_context_clock = test_context_clock or (lambda: datetime.now(tz=UTC))
        self._rule_staleness_window = rule_staleness_window
        self._rule_staleness_started_at = self._now()
        self._last_owner_rule_update_at: datetime | None = None
        self._rule_cache_stale = False
        self._decision_coordinator = decision_coordinator or DomainDecisionCoordinator()
        self._operational_planner = operational_planner
        self._kinetic_proposal_source = kinetic_proposal_source
        self._prospective_lineage_finalizer = prospective_lineage_finalizer
        self._change_assessor = change_assessor
        self._anomaly_action_sources = dict(anomaly_action_sources or {})
        self.initialize_development_authority(
            profile=development_profile,
            binding_source=development_binding_source,
            executor_principal=development_executor_principal,
            action_types=development_action_types,
            clock=self._test_context_clock,
        )
        if len(self._anomaly_action_sources) > 32 or any(
            not key or key != key.strip() or len(key) > 128 for key in self._anomaly_action_sources
        ):
            raise ValueError("anomaly action bindings must contain bounded exact signal names")
        self._architecture_review_loop = architecture_review_loop
        self._architecture_review_timeout_seconds = architecture_review_timeout_seconds
        self._change_assessment_timeout_seconds = change_assessment_timeout_seconds
        # Optional runtime probe; an absent probe never invents agent unavailability.
        self._agent_availability = agent_availability
        self._cross_vertical_timeout_seconds = cross_vertical_timeout_seconds
        self._cross_vertical_candidates = CrossVerticalCandidateAccumulator(
            max_pending=_MAX_RESOURCES
        )
        self._cross_vertical_timeout_tasks: dict[str, asyncio.Task[None]] = {}
        self._cross_vertical_timeout_deadlines: dict[str, float] = {}
        self._cross_vertical_timeout_heap: list[tuple[float, str]] = []
        self._cross_vertical_timeout_max = _MAX_RESOURCES
        self._cross_vertical_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()
        self._pending_arbitration_principals: BoundedLruDict[str, dict[str, str]] = BoundedLruDict(
            _MAX_RESOURCES
        )
        # Latest arbitration winner per correlation id (populated when Odin
        # resolves a cross-vertical conflict Forseti raised).
        self.arbitrations: dict[str, str] = {}
        # Correlations whose arbitration Odin flagged as too close to settle
        # (near-tie, unknown domain, non-finite impact). They gate the
        # verdict to HIL; cleared once a human-visible verdict is issued.
        self._unresolved_arbitrations: BoundedLruDict[str, dict[str, Any]] = BoundedLruDict(
            _MAX_RESOURCES
        )
        # Resource id per arbitration request, so the escalation verdict can
        # name the resource a human must look at. Odin's decision carries the
        # correlation but not the resource.
        self._arbitration_resources: BoundedLruDict[str, str] = BoundedLruDict(_MAX_RESOURCES)
        # Bounded advice joins cost/capacity signals per resource for conflict arbitration.
        self._domain_advice: BoundedLruDict[str, dict[str, str]] = BoundedLruDict(_MAX_RESOURCES)
        # Measured [0,1] domain impacts let Odin weigh magnitude instead of priority alone.
        self._domain_impact: BoundedLruDict[str, dict[str, float]] = BoundedLruDict(_MAX_RESOURCES)
        self._domain_observed_at: BoundedLruDict[str, dict[str, str]] = BoundedLruDict(
            _MAX_RESOURCES
        )
        self._domain_correlation_ids: BoundedLruDict[str, dict[str, str]] = BoundedLruDict(
            _MAX_RESOURCES
        )
        self._domain_source_freshness: BoundedLruDict[
            str, dict[str, tuple[SourceFreshness, ...]]
        ] = BoundedLruDict(_MAX_RESOURCES)
        self._domain_arguments: BoundedLruDict[str, dict[str, dict[str, object]]] = BoundedLruDict(
            _MAX_RESOURCES
        )
        self._domain_cost_annotations: BoundedLruDict[str, dict[str, Any]] = BoundedLruDict(
            _MAX_RESOURCES
        )
        self._pending_decision_cases: BoundedLruDict[str, _DecisionProjection] = BoundedLruDict(
            _MAX_RESOURCES
        )
        self._pending_change_assessments: BoundedLruDict[str, dict[str, Any]] = BoundedLruDict(
            _MAX_RESOURCES
        )
        self._detection_readiness: BoundedLruDict[str, dict[str, str]] = BoundedLruDict(
            _MAX_RESOURCES
        )
        self._rule_state: BoundedLruDict[str, dict[str, str]] = BoundedLruDict(_MAX_RESOURCES)
        self._no_rule_folds: BoundedLruDict[str, int] = BoundedLruDict(_MAX_RESOURCES)
        self._verdict_quality_samples: BoundedLruDict[str, dict[str, str]] = BoundedLruDict(
            _QUALITY_SAMPLE_LIMIT
        )
        self._last_verdict_coherence: dict[str, object] = {
            "evidence_state": "not_observed",
            "sample_size": 0,
            "disagreements": 0,
            "unit": "count",
        }
        self._last_novelty_drift: dict[str, object] = {
            "evidence_state": "not_observed",
            "sample_size": 0,
            "tier_mix": {"T0": 0, "T1": 0, "T2": 0},
            "t2_ratio": None,
            "unit": "ratio",
        }
        self._published_what_if_inputs: BoundedLruSet[str] = BoundedLruSet(_QUALITY_SAMPLE_LIMIT)
        self._last_retrospective_what_if: dict[str, object] = {
            "evidence_state": "not_requested",
            "sample_size": 0,
            "disagreements": 0,
            "unit": "count",
        }

    def bind_bus(self, bus: PantheonBus) -> None:
        self.bus = bus

    def bind_agent_availability(self, probe: Callable[[], Iterable[str]]) -> None:
        """Bind the runtime health probe that reports unreachable agents."""
        self._agent_availability = probe

    # ---- typed port ----------------------------------------------------

    # ---- cross-vertical arbitration -----------------------------------

    def _now(self) -> datetime:
        current = self._test_context_clock()
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("Forseti clock MUST return a timezone-aware datetime")
        return current


__all__ = ["Forseti"]
