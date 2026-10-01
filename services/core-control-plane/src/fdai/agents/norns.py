"""Norns - Learner (Wave 2 behavior).

Norns turns operational signals into inert RuleCandidate proposals for Mimir. It never mutates
the catalog or thresholds: every proposal must pass the quality gate (see
`docs/roadmap/rules-and-detection/rule-governance.md` and the discovery loop in
`architecture.instructions.md`).

Every candidate passes the internal Urd, Verdandi, and Skuld perspectives. These are not agents or
principals. Norns publishes one aggregate only on unanimous agreement and bounds held records.

Deterministic learners run here; T1 clustering and T2 summary remain off-path:

1. **Fingerprint aggregator** - repeated handoff fingerprints propose a
   *new* rule (Wave 2 baseline).
2. **Outcome-threshold learner** - a high measured rollback rate on an
   action proposes a *threshold_adjustment* (raise the confidence bar so
   the action escalates to HIL more often). Measurement-based, in the
   safer direction, never a silent auto-relax.
3. **Override learner** - recurring operator overrides on the same rule
   propose a *revision* (or *retirement* when the overrides disable it),
   matching the "recurring overrides are a signal to revise/retire"
   feedback rule in the architecture.
4. **Approval-pattern learner** - recurring HIL *rejections* of the same
   action type propose a *revision* candidate (humans consistently refuse
   it, so the action or its risk classification is a poor fit). Same safe,
   autonomy-lowering direction as the override learner; approvals are
   counted for evidence only, never a proposal to auto-promote.

5. **Scenario-coverage aggregator** (optional, active when a composition
    root supplies it) - repeated live incidents whose symptom the compiled
   chaos-scenarios index cannot match propose a `scenario-coverage-gap`
   candidate. Same discipline: never mutates the catalog. See
   :class:`fdai.core.chaos.coverage.ScenarioCoverageAggregator` and
   `docs/internals/sre-scenario-library-scaling.md`.

6. **Preflight toggle-gap learner** - repeated manual deployment blockers
    across distinct scopes propose an inert candidate for a reviewed alternate
    rendering. It never creates a toggle or changes deployment authority.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from fdai.agents._framework.base import Agent
from fdai.agents._framework.bounded import BoundedLruDict, BoundedLruSet
from fdai.agents._framework.handover_knowledge import HandoverKnowledgeMixin
from fdai.agents._framework.introspection import (
    IntrospectionResult,
    agent_state_evidence_ref,
    capability_facts,
    capped_list,
)
from fdai.agents._framework.norns_candidate_delivery import NornsCandidateDeliveryMixin
from fdai.agents._framework.norns_consensus import NornsConsensus
from fdai.agents._framework.norns_deployment_learning import NornsDeploymentLearning
from fdai.agents._framework.norns_event_learning import NornsEventLearningMixin
from fdai.agents._framework.norns_issue_dedup import NornsIssueDeduplicator
from fdai.agents._framework.norns_learning import (
    NornsCapacityError as NornsCapacityError,
)
from fdai.agents._framework.norns_learning import (
    NornsLearningStateMixin,
)
from fdai.agents._framework.norns_learning import observe_approval as _learn_approval
from fdai.agents._framework.norns_learning import observe_outcome as _learn_outcome
from fdai.agents._framework.norns_learning import observe_override as _learn_override
from fdai.agents._framework.norns_learning import (
    retain_shadow_dwell as _learn_shadow_dwell,
)
from fdai.agents._framework.norns_learning import (
    shadow_dwell_evidence as _learning_shadow_dwell_evidence,
)
from fdai.agents._framework.norns_semantic_feedback import NornsSemanticFeedbackLearning
from fdai.agents._framework.pantheon import _NORNS
from fdai.agents._framework.role_answers import norns_role_answer
from fdai.core.case_history import CaseHistoryAnalyzer, CaseHistoryMaterializer
from fdai.core.chaos.coverage import ScenarioCoverageAggregator
from fdai.core.learning import (
    PostTurnReviewCoordinator,
    RuleCandidateHint,
)
from fdai.core.operational_learning import (
    InvestigationStrategyCandidateCompiler,
    OperatingPatternCompiler,
    ShadowDwellEvidence,
    ShadowDwellLedger,
)
from fdai.core.trajectory import ReviewedTrajectoryDataset
from fdai.rule_catalog.schema.rule_semantic_feedback import SemanticFeedbackCandidateSink
from fdai.shared.providers.state_store import StateStore

# LRU cap on the per-event / per-fingerprint maps a long-lived learner keeps,
# so they cannot grow without bound over the process lifetime.
_MAX_TRACKED = 50_000
_MAX_PENDING_CANDIDATES = 5_000
_DEFAULT_PROVIDER_TIMEOUT_SECONDS = 5.0
_MAX_POST_TURN_BODY_BYTES = 64 * 1024
_CANDIDATE_TERMINAL_OUTCOMES = (
    "published",
    "held",
    "invalidated",
    "disabled",
    "rate_limited",
)


class Norns(
    NornsEventLearningMixin,
    NornsLearningStateMixin,
    Agent,
    HandoverKnowledgeMixin,
    NornsCandidateDeliveryMixin,
):
    """Wave-2 Norns: fingerprint aggregator + outcome / override / approval learner."""

    def __init__(
        self,
        *,
        promotion_threshold: int = 3,
        rollback_alarm_rate: float = 0.2,
        min_outcome_samples: int = 20,
        override_retire_threshold: int = 5,
        rejection_revise_threshold: int = 5,
        preflight_blocker_threshold: int = 3,
        coverage_aggregator: ScenarioCoverageAggregator | None = None,
        post_turn_review: PostTurnReviewCoordinator | None = None,
        forecast_error_threshold: int = 3,
        case_history_analyzer: CaseHistoryAnalyzer | None = None,
        case_history_materializer: CaseHistoryMaterializer | None = None,
        operating_pattern_compiler: OperatingPatternCompiler | None = None,
        investigation_strategy_compiler: InvestigationStrategyCandidateCompiler | None = None,
        semantic_feedback_store: SemanticFeedbackCandidateSink | None = None,
        shadow_dwell_ledger: ShadowDwellLedger | None = None,
        issue_state_store: StateStore | None = None,
        operational_state_store: StateStore | None = None,
        max_pending_candidates: int = _MAX_PENDING_CANDIDATES,
        operational_case_max_age: timedelta = timedelta(days=90),
        issue_close_quiet_window: timedelta = timedelta(hours=24),
        clock: Callable[[], datetime] | None = None,
        provider_timeout_seconds: float = _DEFAULT_PROVIDER_TIMEOUT_SECONDS,
    ) -> None:  # Fail fast on misconfiguration: a non-positive threshold or a
        # rate outside [0, 1] would make the learner propose on thin or
        # impossible evidence (e.g. min_outcome_samples=0 fires on a single
        # sample), the opposite of measurement-based learning.
        if promotion_threshold < 1:
            raise ValueError("promotion_threshold MUST be >= 1")
        if not 0.0 <= rollback_alarm_rate <= 1.0:
            raise ValueError("rollback_alarm_rate MUST be in [0, 1]")
        if min_outcome_samples < 1:
            raise ValueError("min_outcome_samples MUST be >= 1")
        if override_retire_threshold < 1:
            raise ValueError("override_retire_threshold MUST be >= 1")
        if rejection_revise_threshold < 1:
            raise ValueError("rejection_revise_threshold MUST be >= 1")
        if forecast_error_threshold < 1:
            raise ValueError("forecast_error_threshold MUST be >= 1")
        if max_pending_candidates < 1:
            raise ValueError("max_pending_candidates MUST be >= 1")
        if operational_case_max_age <= timedelta(0):
            raise ValueError("operational_case_max_age MUST be positive")
        if issue_close_quiet_window <= timedelta(0):
            raise ValueError("issue_close_quiet_window MUST be positive")
        if provider_timeout_seconds <= 0:
            raise ValueError("Norns provider timeout MUST be positive")
        super().__init__(spec=_NORNS)
        self._proposal_queue_managed_externally = True
        self._fingerprint_counter: BoundedLruDict[str, int] = BoundedLruDict(_MAX_TRACKED)
        self._issue_deduplicator = NornsIssueDeduplicator(issue_state_store, _MAX_TRACKED)
        # Fingerprints already proposed - same content-hash keyspace as the
        # counter above, so it is bounded too (a long-lived learner that saw
        # many distinct incidents would otherwise leak one entry per proposal).
        self._proposed: BoundedLruSet[str] = BoundedLruSet(_MAX_TRACKED)
        self._promotion_threshold = promotion_threshold
        self._max_pending_candidates = max_pending_candidates
        self._init_candidate_delivery(
            store=operational_state_store,
            max_pending_candidates=max_pending_candidates,
        )
        self._learning_state_store = operational_state_store
        self._learning_state_recovered = operational_state_store is None
        self._learning_dirty: dict[str, set[str]] = {}
        self._investigation_strategy_compiler = (
            investigation_strategy_compiler or InvestigationStrategyCandidateCompiler()
        )
        self._investigation_strategy_candidate_ids: BoundedLruSet[str] = BoundedLruSet(_MAX_TRACKED)
        self._learning_lock = asyncio.Lock()
        self._forecast_analysis_lock = asyncio.Lock()
        self._provider_timeout_seconds = provider_timeout_seconds
        self._consensus = NornsConsensus()
        self._consensus_holds: deque[dict[str, object]] = deque(maxlen=1_000)
        # Outcome-threshold learner state.
        self._rollback_alarm_rate = rollback_alarm_rate
        self._min_outcome_samples = min_outcome_samples
        self._outcomes: BoundedLruDict[str, dict[str, int]] = BoundedLruDict(_MAX_TRACKED)
        self._outcome_proposed: BoundedLruSet[str] = BoundedLruSet(_MAX_TRACKED)
        # Correlation ids whose outcome has already been counted, so a single
        # action that emits multiple adverse terminal audits (Thor emits
        # FAILED then ROLLED_BACK for a failed action) is scored once, not
        # twice. Only applied when a correlation_id is present; audit-entries
        # without one fall back to per-event counting. Bounded (LRU): one
        # entry per action forever would leak on a long-lived learner.
        self._counted_correlations: BoundedLruSet[str] = BoundedLruSet(_MAX_TRACKED)
        # Shadow audits are at-least-once too, so one shadow observation is
        # retained once; a replay must not inflate the dwell sample.
        self._counted_shadow_outcomes: BoundedLruSet[str] = BoundedLruSet(_MAX_TRACKED)
        # Override learner state.
        self._override_retire_threshold = override_retire_threshold
        self._override_counter: BoundedLruDict[str, int] = BoundedLruDict(_MAX_TRACKED)
        self._override_proposed: BoundedLruSet[str] = BoundedLruSet(_MAX_TRACKED)
        # Approval-pattern learner state. Repeated HIL rejections of the same
        # action type mean humans consistently refuse it - a signal the action
        # is a poor fit; it proposes an inert `revision` candidate (the safe,
        # autonomy-lowering direction, symmetric with the override learner).
        # Approvals are counted for evidence only; the learner never proposes
        # auto-promotion (the risky direction), which stays an explicit,
        # quality-gated decision. Dedup per correlation id (LRU) so a
        # re-delivered approval is scored once.
        self._rejection_revise_threshold = rejection_revise_threshold
        self._approval_counts: BoundedLruDict[str, dict[str, int]] = BoundedLruDict(_MAX_TRACKED)
        self._approval_proposed: BoundedLruSet[str] = BoundedLruSet(_MAX_TRACKED)
        self._counted_approvals: BoundedLruSet[str] = BoundedLruSet(_MAX_TRACKED)
        self._deployment_learning = NornsDeploymentLearning(
            coverage_aggregator=coverage_aggregator,
            preflight_blocker_threshold=preflight_blocker_threshold,
            max_tracked=_MAX_TRACKED,
        )
        self._post_turn_hint_proposed: BoundedLruSet[str] = BoundedLruSet(_MAX_TRACKED)
        self._reviewed_trajectory_manifests: BoundedLruSet[str] = BoundedLruSet(_MAX_TRACKED)
        self._reviewed_post_turn_reviews: BoundedLruSet[str] = BoundedLruSet(_MAX_TRACKED)
        self._post_turn_review = post_turn_review
        self._forecast_error_threshold = forecast_error_threshold
        self._forecast_error_counts: BoundedLruDict[str, int] = BoundedLruDict(_MAX_TRACKED)
        self._forecast_error_proposed: BoundedLruSet[str] = BoundedLruSet(_MAX_TRACKED)
        self._counted_case_revisions: BoundedLruSet[str] = BoundedLruSet(_MAX_TRACKED)
        self._case_history_analyzer = case_history_analyzer
        self._case_history_materializer = case_history_materializer
        self._operating_pattern_compiler = operating_pattern_compiler or OperatingPatternCompiler()
        self._operational_case_max_age = operational_case_max_age
        self._clock = clock or (lambda: datetime.now(UTC))
        self._issue_close_quiet_window = issue_close_quiet_window
        self._fingerprint_last_seen: BoundedLruDict[str, datetime] = BoundedLruDict(_MAX_TRACKED)
        self._issue_close_quiet_episodes: BoundedLruSet[str] = BoundedLruSet(_MAX_TRACKED)
        self._operating_pattern_ids: BoundedLruSet[str] = BoundedLruSet(_MAX_TRACKED)
        self._pattern_publications: dict[str, dict[str, Any]] = {}
        self._candidate_terminal_ids: BoundedLruSet[str] = BoundedLruSet(_MAX_TRACKED)
        self._candidate_terminal_counts = {outcome: 0 for outcome in _CANDIDATE_TERMINAL_OUTCOMES}
        self._pattern_validation_counts = {"valid": 0, "false": 0}
        self._semantic_feedback = NornsSemanticFeedbackLearning(semantic_feedback_store)
        # Shadow outcomes never feed the rollback-rate learner (a judged-and-logged
        # 'success' says nothing about real safety), but they are the only evidence
        # the discovery loop's shadow-dwell gate can ever have, so they are retained
        # here instead of discarded.
        self._shadow_dwell = shadow_dwell_ledger or ShadowDwellLedger()

    def observe_reviewed_trajectory_dataset(self, dataset: ReviewedTrajectoryDataset) -> bool:
        """Consume one reviewed aggregate without training or promoting anything.

        The type carries only counts and a human review receipt. Raw trajectory
        records are not accepted, and this method emits no candidate by itself.
        """

        if not isinstance(dataset, ReviewedTrajectoryDataset):
            raise TypeError("Norns trajectory input MUST be a ReviewedTrajectoryDataset")
        if dataset.manifest_checksum in self._reviewed_trajectory_manifests:
            return False
        self._reviewed_trajectory_manifests.add(dataset.manifest_checksum)
        self.record_behavior("reviewed_trajectory_dataset_consumed")
        return True

    # ---- 1. fingerprint aggregator ------------------------------------

    # ---- 2. outcome-threshold learner ---------------------------------

    def _observe_outcome(self, payload: dict[str, Any]) -> None:
        """Learn from an action's audit outcome.

        A measured rollback rate above the alarm rate (over a minimum
        sample) proposes raising the action's confidence threshold so it
        escalates to HIL more often - the safe direction. The proposal is
        inert until the quality gate promotes it.
        """
        _learn_outcome(self, payload)

    # ---- 2a. shadow-dwell evidence ------------------------------------

    def _retain_shadow_dwell(self, target: str, payload: dict[str, Any]) -> None:
        """Retain one judge-and-log-only observation as dwell evidence.

        Anything the payload cannot prove is dropped rather than guessed. A
        dropped observation only ever makes a candidate *less* eligible, so a
        malformed or replayed shadow audit can neither manufacture dwell nor
        veto an otherwise clean record.
        """

        _learn_shadow_dwell(self, target, payload)

    def shadow_dwell_evidence(self, target: str) -> ShadowDwellEvidence | None:
        """Retained dwell evidence for ``target``, or ``None`` when unobserved."""

        return _learning_shadow_dwell_evidence(self, target)

    # ---- 2b. approval-pattern learner ---------------------------------

    def _observe_approval(self, payload: dict[str, Any]) -> None:
        """Learn from a HIL approval decision.

        Recurring rejections propose an inert revision. Approvals contribute
        evidence only and never trigger automatic promotion.
        """
        _learn_approval(self, payload)

    # ---- 3. override learner ------------------------------------------

    def observe_override(self, payload: dict[str, Any]) -> None:
        """Learn from recurring operator overrides on a rule.

        The exemption machinery calls this directly because ``object.override``
        is not a Pantheon topic. Disabled rules propose retirement; other
        recurring overrides propose revision.
        """
        _learn_override(self, payload)

    # ---- 4. scenario-coverage learner (optional) ---------------------

    def observe_incident_symptom(
        self,
        *,
        incident_id: str,
        signal: str,
        target_type: str,
        severity: str,
    ) -> None:
        """Aggregate one incident symptom into an optional inert scenario-gap candidate."""
        self._ensure_pending_capacity()
        candidates = self._deployment_learning.observe_incident_symptom(
            incident_id=incident_id,
            signal=signal,
            target_type=target_type,
            severity=severity,
        )
        for candidate in candidates:
            self._append_candidate(candidate)

    def observe_preflight_manual_blocker(
        self,
        *,
        finding_id: str,
        category: str,
        evidence_source: str,
        scope: str,
    ) -> None:
        """Propose an inert toggle-gap candidate after distinct scopes repeat a blocker."""

        self._ensure_pending_capacity()
        candidate = self._deployment_learning.observe_preflight_manual_blocker(
            finding_id=finding_id,
            category=category,
            evidence_source=evidence_source,
            scope=scope,
        )
        if candidate is not None:
            self._append_candidate(candidate)

    async def submit_rule_hint(
        self,
        hint: RuleCandidateHint,
        *,
        proposed_by: str,
        at: datetime,
    ) -> str:
        async with self._learning_lock:
            await self._ensure_learning_state()
            return await self._submit_rule_hint_unlocked(
                hint,
                proposed_by=proposed_by,
                at=at,
            )

    async def _submit_rule_hint_unlocked(
        self,
        hint: RuleCandidateHint,
        *,
        proposed_by: str,
        at: datetime,
    ) -> str:
        """Convert one verified post-turn hint into an inert RuleCandidate.

        Norns remains the sole writer. The caller supplies a verified hint,
        but this method still derives a deterministic reference, deduplicates
        it, and publishes only through Norns' existing rate-limited topic.
        """
        self._ensure_pending_capacity()
        if proposed_by != self.spec.name:
            raise ValueError("post-turn rule hints MUST be proposed by Norns")
        if at.tzinfo is None:
            raise ValueError("post-turn rule hint timestamp MUST be timezone-aware")
        material = "\0".join(
            (
                hint.proposal_kind,
                hint.target_ref,
                hint.pattern,
                *sorted(hint.evidence_refs),
            )
        )
        digest = hashlib.sha256(material.encode()).hexdigest()
        proposal_ref = f"rule-candidate-hint:{digest[:32]}"
        if digest in self._post_turn_hint_proposed:
            return proposal_ref
        self._post_turn_hint_proposed.add(digest)
        self._mark_learning_dirty("post_turn_hint_proposed", digest)
        self._append_candidate(
            {
                "source_signal": "post_turn_review",
                "evidence": {
                    "evidence_refs": list(hint.evidence_refs),
                    "pattern_digest": hashlib.sha256(hint.pattern.encode()).hexdigest(),
                    "confidence": hint.confidence,
                },
                "provenance": {
                    "proposal_ref": proposal_ref,
                    "observed_at": at.isoformat(),
                },
                "proposed_by": self.spec.name,
                "proposal_kind": hint.proposal_kind,
                "target_rule_id": hint.target_ref,
                "suggested_pattern": hint.pattern,
            }
        )
        await self._persist_learning_state()
        await self._flush_candidates_unlocked()
        return proposal_ref

    def health(self) -> dict[str, Any]:
        durable_learning = self._learning_state_store is not None
        pending_count = len(self.pending_candidates)
        terminal_total = sum(self._candidate_terminal_counts.values())
        pattern_total = sum(self._pattern_validation_counts.values())
        status = "ok" if durable_learning else "degraded"
        post_turn_status = "enabled" if self._post_turn_review is not None else "unavailable"
        if self._post_turn_review is None and self.behavior_snapshot().get(
            "post_turn_review_unavailable", 0
        ):
            status = "degraded"
        return {
            "agent": self.spec.name,
            "status": status,
            "learning": {
                "mode": "off_path",
                "status": "enabled",
                "durability": "durable" if durable_learning else "process_local",
                "warning": None if durable_learning else "learning_state_process_local",
                "recovered": self._learning_state_recovered,
                "post_turn_review": {
                    "status": post_turn_status,
                    "warning": None
                    if post_turn_status == "enabled"
                    else "post_turn_review_coordinator_unbound",
                },
            },
            "candidate_delivery": {
                "journal_durability": (
                    "durable" if self._operational_journal.durable else "process_local"
                ),
                "pending_candidates": pending_count,
                "durable_pending_count": self._operational_journal.last_pending_total,
                "terminal_counts": dict(self._candidate_terminal_counts),
                "oldest_pending_age_seconds": None,
            },
            "discovery_velocity": {
                "pending_candidates": pending_count,
                "terminal_candidates": terminal_total,
            },
            "kpis": {
                "rule_candidate_adoption_rate": _ratio_kpi(
                    self._candidate_terminal_counts["published"],
                    terminal_total,
                ),
                "pattern_validity_rate": _ratio_kpi(
                    self._pattern_validation_counts["valid"],
                    pattern_total,
                ),
                "false_pattern_rate": _ratio_kpi(
                    self._pattern_validation_counts["false"],
                    pattern_total,
                ),
            },
        }

    # ---- observers -----------------------------------------------------

    def occurrences(self, fingerprint: str) -> int:
        return self._fingerprint_counter.get(fingerprint) or 0

    def outcome_rate(self, target: str) -> float | None:
        """Measured rollback rate for a target, or None if unseen."""
        counts = self._outcomes.get(target)
        if not counts:
            return None
        total = counts["success"] + counts["rollback"]
        return counts["rollback"] / total if total else None

    def override_count(self, rule_id: str) -> int:
        return self._override_counter.get(rule_id) or 0

    def rejection_count(self, action_type: str) -> int:
        """Measured HIL rejection count for an action type (0 if unseen)."""
        counts = self._approval_counts.get(action_type)
        return counts["rejected"] if counts else 0

    def consensus_holds(self) -> tuple[dict[str, object], ...]:
        """Return bounded aggregate hold records for operator inspection."""
        return tuple(self._consensus_holds)

    def conversation_evidence_available(self, context: dict[str, Any]) -> bool:
        """Discovery answers rest on observed patterns and proposed candidates."""
        return bool(
            self._fingerprint_counter
            or self.pending_candidates
            or self._outcomes
            or self._approval_counts
            or self._forecast_error_counts
        )

    async def introspect(self, question: str, context: dict[str, Any]) -> IntrospectionResult:
        facts = {
            **capability_facts(self.spec),
            "fingerprints_tracked": len(self._fingerprint_counter),
            "pending_candidates": len(self.pending_candidates),
            "consensus_holds": len(self._consensus_holds),
            "outcomes_tracked": capped_list(sorted(self._outcomes)),
            "outcomes_tracked_count": len(self._outcomes),
        }
        evidence_ref = agent_state_evidence_ref(self.spec.name, facts)
        facts["evidence_refs"] = [evidence_ref]
        answer = norns_role_answer(str(context.get("locale")), facts, evidence_ref)
        return IntrospectionResult(answer=answer, facts=facts)


def _forecast_case_behavior_key(label: str) -> str:
    keys = {
        "false_positive": "forecast_case:false_positive",
        "false_negative": "forecast_case:false_negative",
        "late_breach": "forecast_case:late_breach",
        "magnitude_error": "forecast_case:magnitude_error",
    }
    return keys.get(label, "forecast_case:invalid_label")


def _ratio_kpi(numerator: int, denominator: int) -> dict[str, Any]:
    if denominator <= 0:
        return {
            "value": None,
            "evidence_state": "not_observed",
            "numerator": numerator,
            "denominator": denominator,
            "unit": "ratio",
        }
    return {
        "value": numerator / denominator,
        "evidence_state": "measured",
        "numerator": numerator,
        "denominator": denominator,
        "unit": "ratio",
    }


__all__ = ["Norns", "NornsCapacityError"]
