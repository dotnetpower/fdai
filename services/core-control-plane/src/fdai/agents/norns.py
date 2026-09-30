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
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from fdai_service_contracts.ontology_query import content_digest

from fdai.agents._framework.adapters import canonical_json_digest
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
from fdai.agents._framework.norns_case_history import (
    operational_case_cohort_is_current,
)
from fdai.agents._framework.norns_consensus import NornsConsensus
from fdai.agents._framework.norns_deployment_learning import NornsDeploymentLearning
from fdai.agents._framework.norns_issue_dedup import NornsIssueDeduplicator
from fdai.agents._framework.norns_learning import observe_approval as _learn_approval
from fdai.agents._framework.norns_learning import observe_operational_case_cohort
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
from fdai.agents._framework.producer_auth import require_topic_owner
from fdai.agents._framework.role_answers import norns_role_answer
from fdai.core.case_history import CaseHistoryAnalyzer, CaseHistoryMaterializer
from fdai.core.chaos.coverage import ScenarioCoverageAggregator
from fdai.core.learning import (
    PostTurnReviewCoordinator,
    RuleCandidateHint,
    review_input_from_mapping,
)
from fdai.core.operational_learning import (
    InvestigationStrategyCandidateCompiler,
    InvestigationStrategyComparisonEvidence,
    InvestigationStrategyCompilationDisposition,
    OperatingPatternCompiler,
    ShadowDwellEvidence,
    ShadowDwellLedger,
)
from fdai.core.trajectory import ReviewedTrajectoryDataset
from fdai.rule_catalog.pipeline.distill.sensitivity import scan_text
from fdai.rule_catalog.schema.rule_semantic_feedback import SemanticFeedbackCandidateSink
from fdai.shared.providers.state_store import StateStore

# LRU cap on the per-event / per-fingerprint maps a long-lived learner keeps,
# so they cannot grow without bound over the process lifetime.
_MAX_TRACKED = 50_000
_MAX_PENDING_CANDIDATES = 5_000
_LEARNING_STATE_KEY = "pantheon/norns/learning-state"
_LEARNING_STATE_PREFIX = "pantheon/norns/learning-state-deltas"
_LEARNING_STATE_PAGE = 128
_DEFAULT_PROVIDER_TIMEOUT_SECONDS = 5.0
_MAX_POST_TURN_BODY_BYTES = 64 * 1024
_CANDIDATE_TERMINAL_OUTCOMES = (
    "published",
    "held",
    "invalidated",
    "disabled",
    "rate_limited",
)
_LEARNING_BUCKETS = (
    "outcomes",
    "outcome_proposed",
    "counted_correlations",
    "approval_counts",
    "approval_proposed",
    "counted_approvals",
    "forecast_error_counts",
    "forecast_error_proposed",
    "counted_case_revisions",
    "post_turn_hint_proposed",
)


class NornsCapacityError(RuntimeError):
    """Pending proposals are saturated; the caller must retry or dead-letter."""


class Norns(Agent, HandoverKnowledgeMixin, NornsCandidateDeliveryMixin):
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

    async def on_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
        if topic == "object.post-turn-review":
            if require_topic_owner(
                self,
                topic,
                payload,
                behavior="post_turn_review:invalid_producer",
            ):
                return
            await self._observe_post_turn_review(payload)
            return
        if topic == "object.context-index" and payload.get("kind") == "forecast_case_history":
            if require_topic_owner(
                self,
                topic,
                payload,
                behavior="forecast_case:invalid_producer",
            ):
                return
            if await self._handover_message(topic, payload):
                return
            await self._ensure_learning_state()
            await self._observe_forecast_case(payload)
            async with self._learning_lock:
                await self._persist_learning_state()
                await self._flush_candidates_unlocked()
            return
        async with self._learning_lock:
            if await self._handover_message(topic, payload):
                return
            await self._handle_typed_message(topic, payload)

    async def _handle_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
        await self._ensure_learning_state()
        operational_pattern_id = None
        if len(self.pending_candidates) >= self._max_pending_candidates:
            await self._flush_candidates_unlocked()
        self._ensure_pending_capacity()
        if topic == "object.issue":
            if require_topic_owner(self, topic, payload, behavior="issue:invalid_producer"):
                return
            await self._issue_deduplicator.observe(self, payload)
        elif topic == "object.audit-entry":
            if require_topic_owner(
                self,
                topic,
                payload,
                behavior="audit_outcome:invalid_producer",
            ):
                return
            # Saga audits every terminal state and republishes it as an
            # audit-entry; the outcome learner scores rollback rates from it.
            self._observe_outcome(payload)
        elif topic == "object.approval":
            if require_topic_owner(self, topic, payload, behavior="approval:invalid_producer"):
                return
            # Var publishes the final HIL decision (approved / rejected); the
            # approval-pattern learner scores recurring rejections from it.
            self._observe_approval(payload)
        elif topic == "object.context-index":
            if require_topic_owner(
                self,
                topic,
                payload,
                behavior="context_index:invalid_producer",
            ):
                return
            if payload.get("kind") == "operational_case_fingerprint_cohort":
                try:
                    async with asyncio.timeout(self._provider_timeout_seconds):
                        cohort_current = await operational_case_cohort_is_current(self, payload)
                except TimeoutError:
                    cohort_current = False
                    self.record_behavior("operational_case_cohort_source_timeout")
                if cohort_current:
                    operational_pattern_id = observe_operational_case_cohort(self, payload)
                    if operational_pattern_id is not None:
                        await self.retain_operational_candidate(operational_pattern_id)
            elif payload.get("kind") == "investigation_strategy_comparison_cohort":
                self._observe_investigation_strategy_cohort(payload)
            elif payload.get("kind") == "semantic_retrieval_failure":
                candidate = await self._semantic_feedback.observe(payload)
                if candidate is None:
                    self.record_behavior("semantic_feedback_candidate_duplicate")
                else:
                    self._append_candidate(candidate)
                    self.record_behavior("semantic_feedback_candidate_created")
            elif payload.get("kind") == "forecast_case_history":
                await self._observe_forecast_case(payload)
            else:
                self.record_behavior("context_index:unsupported_kind")
        else:
            self.record_behavior("typed_message:ignored")
        # object.override is deliberately NOT handled here: it is not a pantheon
        # bus topic (agent-pantheon.md 2 - overrides flow through the exemption
        # / rule-catalog machinery). That machinery calls observe_override()
        # directly.
        # Off-path batch: forward any newly-formed inert candidates to Mimir.
        await self._persist_learning_state()
        await self._flush_candidates_unlocked()
        if (
            operational_pattern_id is not None
            and payload.get("cohort_snapshot_ref")
            and any(
                item.get("suggested_pattern") == operational_pattern_id
                for item in self.pending_candidates
            )
        ):
            raise NornsCapacityError("operational cohort publication pending; retain for replay")

    def _observe_investigation_strategy_cohort(self, payload: dict[str, Any]) -> None:
        if payload.get("producer_principal") != "Muninn":
            self.record_behavior("investigation_strategy_cohort_invalid_producer")
            return
        raw_comparisons = payload.get("comparisons")
        if not isinstance(raw_comparisons, list) or not 1 <= len(raw_comparisons) <= 100:
            self.record_behavior("investigation_strategy_cohort_invalid_payload")
            return
        try:
            comparisons = tuple(
                InvestigationStrategyComparisonEvidence.from_mapping(item)
                for item in raw_comparisons
                if isinstance(item, dict)
            )
        except ValueError:
            self.record_behavior("investigation_strategy_cohort_invalid_payload")
            return
        if len(comparisons) != len(raw_comparisons):
            self.record_behavior("investigation_strategy_cohort_invalid_payload")
            return
        pairs = {
            (item.active_strategy_digest, item.challenger_strategy_digest) for item in comparisons
        }
        if len(pairs) != 1:
            self.record_behavior("investigation_strategy_cohort_invalid_payload")
            return
        active_digest, challenger_digest = next(iter(pairs))
        pair_digest = content_digest(
            {
                "active_strategy_digest": active_digest,
                "challenger_strategy_digest": challenger_digest,
            }
        )
        cohort_digest = content_digest(
            {
                "pair_digest": pair_digest,
                "comparison_digests": sorted(item.comparison_digest for item in comparisons),
            }
        )
        if (
            payload.get("cohort_digest") != cohort_digest
            or payload.get("correlation_id") != pair_digest
            or payload.get("idempotency_key") != f"investigation-strategy:{cohort_digest}"
        ):
            self.record_behavior("investigation_strategy_cohort_invalid_seal")
            return
        result = self._investigation_strategy_compiler.compile_evidence(comparisons)
        if (
            result.disposition is not InvestigationStrategyCompilationDisposition.COMPILED
            or result.candidate is None
        ):
            self.record_behavior("investigation_strategy_cohort_held")
            return
        if result.candidate.candidate_id in self._investigation_strategy_candidate_ids:
            self.record_behavior("investigation_strategy_cohort_duplicate")
            return
        self._investigation_strategy_candidate_ids.add(result.candidate.candidate_id)
        self._append_candidate(result.candidate.to_rule_candidate_mapping())
        self.record_behavior("investigation_strategy_candidate_created")

    async def _observe_forecast_case(self, payload: dict[str, Any]) -> None:
        if payload.get("kind") != "forecast_case_history":
            self.record_behavior("forecast_case:unsupported_kind")
            return
        case_id = str(payload.get("case_id") or "")
        revision = str(payload.get("revision") or "")
        manifest_digest = str(payload.get("manifest_digest") or "")
        detector_id = str(payload.get("detector_id") or "")
        metric = str(payload.get("metric") or "")
        label = str(payload.get("outcome_label") or "")
        case_ref = str(payload.get("case_ref") or "")
        dedup_key = f"{case_id}:{revision}:{manifest_digest}"
        if not all((case_id, revision, manifest_digest, detector_id, metric, case_ref)):
            self.record_behavior("forecast_case:invalid")
            return
        if label not in {
            "false_positive",
            "false_negative",
            "late_breach",
            "magnitude_error",
        }:
            self.record_behavior("forecast_case:invalid_label")
            return
        fingerprint = hashlib.sha256(f"{detector_id}\0{metric}".encode()).hexdigest()
        count = (self._forecast_error_counts.get(fingerprint) or 0) + 1
        if count < self._forecast_error_threshold:
            async with self._learning_lock:
                if dedup_key in self._counted_case_revisions:
                    self.record_behavior("forecast_case:duplicate")
                    return
                self._counted_case_revisions.add(dedup_key)
                self._mark_learning_dirty("counted_case_revisions", dedup_key)
                self._forecast_error_counts.set(fingerprint, count)
                self._mark_learning_dirty("forecast_error_counts", fingerprint)
                self.record_behavior(_forecast_case_behavior_key(label))
            self.record_behavior("forecast_case:collecting")
            return
        if fingerprint in self._forecast_error_proposed:
            self.record_behavior("forecast_case:already_proposed")
            return
        if self._case_history_analyzer is not None:
            try:
                async with self._forecast_analysis_lock:
                    async with asyncio.timeout(self._provider_timeout_seconds):
                        hint = await self._case_history_analyzer.analyze(payload)
            except TimeoutError:
                hint = None
                self.record_behavior("forecast_case:analysis_timeout")
            except Exception:  # noqa: BLE001 - optional off-path analysis fails closed
                hint = None
                self.record_behavior("forecast_case:analysis_failed")
            if hint is not None and not isinstance(hint, RuleCandidateHint):
                self.record_behavior("forecast_case:analysis_invalid")
                hint = None
            if isinstance(hint, RuleCandidateHint):
                async with self._learning_lock:
                    if dedup_key in self._counted_case_revisions:
                        self.record_behavior("forecast_case:duplicate")
                        return
                    self._counted_case_revisions.add(dedup_key)
                    self._mark_learning_dirty("counted_case_revisions", dedup_key)
                    self._forecast_error_counts.set(fingerprint, count)
                    self._mark_learning_dirty("forecast_error_counts", fingerprint)
                    self._forecast_error_proposed.add(fingerprint)
                    self._mark_learning_dirty("forecast_error_proposed", fingerprint)
                    self.record_behavior(_forecast_case_behavior_key(label))
                    self._append_candidate(
                        {
                            "source_signal": "forecast_case_history_analysis",
                            "evidence": {
                                "evidence_refs": list(hint.evidence_refs),
                                "pattern_digest": hashlib.sha256(hint.pattern.encode()).hexdigest(),
                                "confidence": hint.confidence,
                                "occurrence_count": count,
                            },
                            "provenance": {
                                "source": "case-history-analysis",
                                "case_id": case_id,
                                "revision": revision,
                                "manifest_digest": manifest_digest,
                            },
                            "proposed_by": "Norns",
                            "proposal_kind": hint.proposal_kind,
                            "target_rule_id": hint.target_ref,
                            "suggested_pattern": hint.pattern,
                        }
                    )
                return
        async with self._learning_lock:
            if dedup_key in self._counted_case_revisions:
                self.record_behavior("forecast_case:duplicate")
                return
            self._counted_case_revisions.add(dedup_key)
            self._mark_learning_dirty("counted_case_revisions", dedup_key)
            self._forecast_error_counts.set(fingerprint, count)
            self._mark_learning_dirty("forecast_error_counts", fingerprint)
            self._forecast_error_proposed.add(fingerprint)
            self._mark_learning_dirty("forecast_error_proposed", fingerprint)
            self.record_behavior(_forecast_case_behavior_key(label))
            self._append_candidate(
                {
                    "source_signal": "forecast_case_history",
                    "evidence": {
                        "detector_id": detector_id,
                        "metric": metric,
                        "latest_label": label,
                        "occurrence_count": count,
                        "case_ref": case_ref,
                        "manifest_digest": manifest_digest,
                    },
                    "provenance": {
                        "source": "case-history",
                        "case_id": case_id,
                        "revision": revision,
                        "manifest_digest": manifest_digest,
                    },
                    "proposed_by": "Norns",
                    "proposal_kind": "threshold_adjustment",
                    "suggested_change": "review_forecast_detector",
                    "target_rule_id": detector_id,
                }
            )

    async def _observe_post_turn_review(self, payload: dict[str, Any]) -> None:
        if payload.get("kind") != "post_turn_review":
            return
        if self._post_turn_review is None:
            self.record_behavior("post_turn_review_unavailable")
            return
        raw = payload.get("review")
        if not isinstance(raw, dict):
            raise ValueError("post-turn review payload MUST contain a review object")
        review_id = str(raw.get("review_id") or "")
        idempotency_key = str(payload.get("idempotency_key") or "")
        fence = idempotency_key or (f"post-turn-review:{review_id}" if review_id else "")
        if not fence:
            raise ValueError("post-turn review payload MUST carry an idempotency key or review id")
        if fence in self._reviewed_post_turn_reviews:
            self.record_behavior("post_turn_review_duplicate")
            return
        try:
            review_input = review_input_from_mapping(raw)
        except ValueError:
            self.record_behavior("post_turn_review_invalid")
            return
        if not self._post_turn_review_body_admissible(payload, raw, review_input):
            return
        await self._post_turn_review.review(review_input)
        self._reviewed_post_turn_reviews.add(fence)
        self.record_behavior("post_turn_review_completed")

    def _post_turn_review_body_admissible(
        self,
        payload: Mapping[str, Any],
        raw: Mapping[str, Any],
        review_input: Any,
    ) -> bool:
        if not any(
            body is not None for body in (review_input.operator_body, review_input.assistant_body)
        ):
            return True
        if not review_input.body_shared:
            self.record_behavior("post_turn_review_raw_body_incomplete")
            return False
        consent = raw.get("body_consent")
        if not isinstance(consent, Mapping):
            consent = payload.get("body_consent")
        if not isinstance(consent, Mapping) or (
            consent.get("share_with_learner") is not True
            or consent.get("principal_scope") != review_input.principal_scope
            or not isinstance(consent.get("consent_ref"), str)
            or not consent.get("consent_ref")
        ):
            self.record_behavior("post_turn_review_raw_body_without_consent")
            return False
        text = "\n".join((review_input.operator_body or "", review_input.assistant_body or ""))
        if len(text.encode("utf-8")) > _MAX_POST_TURN_BODY_BYTES:
            self.record_behavior("post_turn_review_raw_body_too_large")
            return False
        if scan_text(text):
            self.record_behavior("post_turn_review_raw_body_sensitive")
            return False
        return True

    async def recover_issue_learning(self) -> int:
        """Restore durable handoff-learning work before consumers start."""
        return await self._issue_deduplicator.recover(self)

    async def maintenance_tick(self) -> None:
        await super().maintenance_tick()
        published = await self.flush_candidates()
        if published:
            self.record_behavior("maintenance_tick:candidates_flushed", published)

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

    async def recover_learning_state(self) -> int:
        """Restore durable learner counters and idempotency fences once."""
        if self._learning_state_recovered:
            return 0
        self._learning_state_recovered = True
        store = self._learning_state_store
        if store is None:
            return 0
        row = await store.read_state(_LEARNING_STATE_KEY)
        restored = 0
        if row is not None:
            self._load_learning_state(row)
            restored += 1
        for bucket in _LEARNING_BUCKETS:
            offset = 0
            while True:
                rows, _total = await store.read_state_page(
                    f"{_LEARNING_STATE_PREFIX}/{bucket}/",
                    limit=_LEARNING_STATE_PAGE,
                    offset=offset,
                )
                if not rows:
                    break
                for delta in rows:
                    self._load_learning_delta(delta)
                    restored += 1
                offset += len(rows)
        return 1 if restored else 0

    async def _ensure_learning_state(self) -> None:
        await self.recover_learning_state()

    async def _persist_learning_state(self) -> None:
        store = self._learning_state_store
        if store is None:
            return
        dirty = self._learning_dirty
        if not dirty:
            return
        self._learning_dirty = {}
        for bucket, keys in dirty.items():
            for item_key in keys:
                await self._persist_learning_delta(store, bucket, item_key)
            await store.delete_states_beyond(
                f"{_LEARNING_STATE_PREFIX}/{bucket}/",
                retain_newest=_MAX_TRACKED,
            )

    async def _persist_learning_delta(
        self,
        store: StateStore,
        bucket: str,
        item_key: str,
    ) -> None:
        value = self._learning_value(bucket, item_key)
        if value is None:
            return
        state_key = (
            f"{_LEARNING_STATE_PREFIX}/{bucket}/{hashlib.sha256(item_key.encode()).hexdigest()}"
        )
        current = await store.read_state(state_key)
        revision = int(current.get("revision", 0)) if current is not None else 0
        record = {
            "kind": "norns_learning_state_delta",
            "revision": revision + 1,
            "bucket": bucket,
            "item_key": item_key,
            "value": value,
        }
        audit = {
            "kind": "norns_learning_state_delta",
            "principal": "Norns",
            "bucket": bucket,
            "item_key_digest": hashlib.sha256(item_key.encode()).hexdigest(),
            "revision": revision + 1,
            "grants_authority": False,
        }
        if current is None:
            if await store.write_state_with_audit_if_absent(state_key, record, audit):
                return
            current = await store.read_state(state_key)
            revision = int(current.get("revision", 0)) if current is not None else 0
            record["revision"] = revision + 1
            audit["revision"] = revision + 1
        if not await store.compare_and_set_state_with_audit(
            state_key,
            record,
            expected_revision=revision,
            audit_entry=audit,
        ):
            self.record_behavior("learning_state:cas_conflict")
            raise RuntimeError("Norns learning state delta CAS did not converge")

    def _load_learning_state(self, row: Mapping[str, Any]) -> None:
        self._restore_counter_dict(self._outcomes, row.get("outcomes"), nested=True)
        self._restore_set(self._outcome_proposed, row.get("outcome_proposed"))
        self._restore_set(self._counted_correlations, row.get("counted_correlations"))
        self._restore_counter_dict(self._approval_counts, row.get("approval_counts"), nested=True)
        self._restore_set(self._approval_proposed, row.get("approval_proposed"))
        self._restore_set(self._counted_approvals, row.get("counted_approvals"))
        self._restore_counter_dict(
            self._forecast_error_counts,
            row.get("forecast_error_counts"),
            nested=False,
        )
        self._restore_set(self._forecast_error_proposed, row.get("forecast_error_proposed"))
        self._restore_set(self._counted_case_revisions, row.get("counted_case_revisions"))
        self._restore_set(self._post_turn_hint_proposed, row.get("post_turn_hint_proposed"))

    def _load_learning_delta(self, row: Mapping[str, Any]) -> None:
        if row.get("kind") != "norns_learning_state_delta":
            raise ValueError("Norns durable learner delta kind is invalid")
        bucket = str(row.get("bucket") or "")
        item_key = str(row.get("item_key") or "")
        if bucket not in _LEARNING_BUCKETS or not item_key:
            raise ValueError("Norns durable learner delta identity is invalid")
        value = row.get("value")
        if bucket == "outcomes":
            if not isinstance(value, Mapping):
                raise ValueError("Norns durable outcome delta is invalid")
            self._outcomes.set(item_key, {str(name): int(count) for name, count in value.items()})
        elif bucket == "approval_counts":
            if not isinstance(value, Mapping):
                raise ValueError("Norns durable approval delta is invalid")
            self._approval_counts.set(
                item_key, {str(name): int(count) for name, count in value.items()}
            )
        elif bucket == "forecast_error_counts":
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError("Norns durable forecast delta is invalid")
            self._forecast_error_counts.set(item_key, int(value))
        elif isinstance(value, bool) and value:
            self._learning_set(bucket).add(item_key)
        else:
            raise ValueError("Norns durable learner set delta is invalid")

    def _learning_value(self, bucket: str, item_key: str) -> object | None:
        if bucket == "outcomes":
            return self._outcomes.get(item_key)
        if bucket == "approval_counts":
            return self._approval_counts.get(item_key)
        if bucket == "forecast_error_counts":
            return self._forecast_error_counts.get(item_key)
        return True if item_key in self._learning_set(bucket) else None

    def _learning_set(self, bucket: str) -> BoundedLruSet[str]:
        return {
            "outcome_proposed": self._outcome_proposed,
            "counted_correlations": self._counted_correlations,
            "approval_proposed": self._approval_proposed,
            "counted_approvals": self._counted_approvals,
            "forecast_error_proposed": self._forecast_error_proposed,
            "counted_case_revisions": self._counted_case_revisions,
            "post_turn_hint_proposed": self._post_turn_hint_proposed,
        }[bucket]

    def _mark_learning_dirty(self, bucket: str, item_key: str) -> None:
        if bucket not in _LEARNING_BUCKETS or not item_key:
            return
        self._learning_dirty.setdefault(bucket, set()).add(item_key)

    @staticmethod
    def _restore_set(target: BoundedLruSet[str], values: object) -> None:
        if values is None:
            return
        if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
            raise ValueError("Norns durable learner set is invalid")
        for item in values:
            target.add(item)

    @staticmethod
    def _restore_counter_dict(
        target: BoundedLruDict[str, Any],
        values: object,
        *,
        nested: bool,
    ) -> None:
        if values is None:
            return
        if not isinstance(values, Mapping):
            raise ValueError("Norns durable learner counter is invalid")
        for key, value in values.items():
            if not isinstance(key, str):
                raise ValueError("Norns durable learner counter key is invalid")
            if nested:
                if not isinstance(value, Mapping):
                    raise ValueError("Norns durable nested learner counter is invalid")
                target.set(key, {str(name): int(count) for name, count in value.items()})
            else:
                target.set(key, int(value))

    def _append_candidate(self, candidate: dict[str, Any]) -> None:
        self._ensure_pending_capacity()
        self.pending_candidates.append(candidate)
        self._index_pending_candidate(candidate)

    def _ensure_pending_capacity(self) -> None:
        if len(self.pending_candidates) >= self._max_pending_candidates:
            raise NornsCapacityError("Norns pending candidate capacity exhausted")

    def _record_candidate_terminal(self, candidate: Mapping[str, Any], outcome: str) -> None:
        if outcome not in self._candidate_terminal_counts:
            return
        try:
            identity = canonical_json_digest(candidate)
        except (TypeError, ValueError):
            identity = content_digest({"candidate_identity": "non_json", "outcome": outcome})
        if identity in self._candidate_terminal_ids:
            return
        self._candidate_terminal_ids.add(identity)
        self._candidate_terminal_counts[outcome] += 1

    def observe_pattern_validation(self, *, valid: bool) -> None:
        """Record a bounded pattern validation outcome for KPI reporting."""

        key = "valid" if valid else "false"
        self._pattern_validation_counts[key] += 1
        self.record_behavior(f"pattern_validation:{key}")

    def health(self) -> dict[str, Any]:
        durable_learning = self._learning_state_store is not None
        pending_count = len(self.pending_candidates)
        terminal_total = sum(self._candidate_terminal_counts.values())
        pattern_total = sum(self._pattern_validation_counts.values())
        status = "ok" if durable_learning else "degraded"
        return {
            "agent": self.spec.name,
            "status": status,
            "learning": {
                "mode": "off_path",
                "status": "enabled",
                "durability": "durable" if durable_learning else "process_local",
                "warning": None if durable_learning else "learning_state_process_local",
                "recovered": self._learning_state_recovered,
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
