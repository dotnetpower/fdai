"""Typed-message learning handlers for Norns."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

from fdai_service_contracts.ontology_query import content_digest

from fdai.agents._framework.bounded import BoundedLruDict, BoundedLruSet
from fdai.agents._framework.norns_candidate_delivery import _IssueDeduplicator
from fdai.agents._framework.norns_case_history import operational_case_cohort_is_current
from fdai.agents._framework.norns_constants import _MAX_POST_TURN_BODY_BYTES
from fdai.agents._framework.norns_learning import (
    NornsCapacityError,
    NornsLearningState,
    observe_operational_case_cohort,
)
from fdai.agents._framework.norns_semantic_feedback import NornsSemanticFeedbackLearning
from fdai.agents._framework.producer_auth import require_topic_owner
from fdai.agents._framework.topics import stable_idempotency_key
from fdai.core.case_history import CaseHistoryAnalyzer, CaseHistoryMaterializer
from fdai.core.learning import (
    PostTurnReviewCoordinator,
    PostTurnReviewInput,
    RuleCandidateHint,
    review_input_from_mapping,
)
from fdai.core.operational_learning import (
    InvestigationStrategyCandidateCompiler,
    InvestigationStrategyComparisonEvidence,
    InvestigationStrategyCompilationDisposition,
    OperatingPatternCompiler,
    ShadowDwellLedger,
)
from fdai.rule_catalog.pipeline.distill.sensitivity import scan_text

if TYPE_CHECKING:
    from fdai.agents._framework.bus import PantheonBus


def _forecast_case_behavior_key(label: str) -> str:
    keys = {
        "false_positive": "forecast_case:false_positive",
        "false_negative": "forecast_case:false_negative",
        "late_breach": "forecast_case:late_breach",
        "magnitude_error": "forecast_case:magnitude_error",
    }
    return keys.get(label, "forecast_case:invalid_label")


class NornsEventLearningMixin:
    """Handle Norns-owned typed learning events and inert candidate creation."""

    _learning_lock: asyncio.Lock
    pending_candidates: list[dict[str, Any]]
    _max_pending_candidates: int
    _issue_deduplicator: _IssueDeduplicator
    _fingerprint_last_seen: BoundedLruDict[str, datetime]
    _clock: Callable[[], datetime]
    _promotion_threshold: int
    _provider_timeout_seconds: float
    _semantic_feedback: NornsSemanticFeedbackLearning
    _investigation_strategy_compiler: InvestigationStrategyCandidateCompiler
    _investigation_strategy_candidate_ids: BoundedLruSet[str]
    _forecast_error_counts: BoundedLruDict[str, int]
    _forecast_error_threshold: int
    _counted_case_revisions: BoundedLruSet[str]
    _forecast_error_proposed: BoundedLruSet[str]
    _case_history_analyzer: CaseHistoryAnalyzer | None
    _forecast_analysis_lock: asyncio.Lock
    _post_turn_review: PostTurnReviewCoordinator | None
    _reviewed_post_turn_reviews: BoundedLruSet[str]
    bus: PantheonBus | None
    _issue_close_quiet_window: timedelta
    _issue_close_quiet_episodes: BoundedLruSet[str]
    _case_history_materializer: CaseHistoryMaterializer | None
    _operating_pattern_compiler: OperatingPatternCompiler
    _operational_case_max_age: timedelta
    _operating_pattern_ids: BoundedLruSet[str]
    _pattern_publications: dict[str, dict[str, Any]]
    _shadow_dwell: ShadowDwellLedger
    _min_outcome_samples: int
    _counted_shadow_outcomes: BoundedLruSet[str]
    _fingerprint_counter: BoundedLruDict[str, int]
    _override_counter: BoundedLruDict[str, int]
    _override_proposed: BoundedLruSet[str]
    _override_retire_threshold: int
    _proposed: BoundedLruSet[str]
    _rejection_revise_threshold: int
    _rollback_alarm_rate: float

    if TYPE_CHECKING:

        async def _handover_message(self, topic: str, payload: dict[str, Any]) -> bool: ...

        async def _ensure_learning_state(self) -> None: ...

        async def _persist_learning_state(self) -> None: ...

        async def _flush_candidates_unlocked(self) -> int: ...

        def _append_candidate(self, candidate: dict[str, Any]) -> None: ...

        def _ensure_pending_capacity(self) -> None: ...

        def _mark_learning_dirty(self, bucket: str, item_key: str) -> None: ...

        def record_behavior(self, name: str, amount: int = 1) -> None: ...

        def occurrences(self, fingerprint: str) -> int: ...

        def _observe_outcome(self, payload: dict[str, Any]) -> None: ...

        def _observe_approval(self, payload: dict[str, Any]) -> None: ...

        async def retain_operational_candidate(
            self,
            pattern_id: str,
        ) -> None: ...

        async def flush_candidates(self) -> int: ...

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
            fingerprint = str(payload.get("fingerprint") or "")
            await self._issue_deduplicator.observe(self, payload)
            if fingerprint:
                self._fingerprint_last_seen.set(fingerprint, self._clock())
                self.record_behavior("issue_learning:observed")
                if self.occurrences(fingerprint) < self._promotion_threshold:
                    self.record_behavior("issue_learning:collecting")
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
                    operational_pattern_id = observe_operational_case_cohort(
                        cast(NornsLearningState, self), payload
                    )
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
        kind = str(payload.get("kind") or "")
        if kind == "bragi_intent_training_evidence":
            self.record_behavior("post_turn_review:intent_training_evidence_observed")
            return
        if kind != "post_turn_review":
            self.record_behavior("post_turn_review:unsupported_kind")
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
        review_input: PostTurnReviewInput,
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
        maintenance_tick = getattr(super(), "maintenance_tick", None)
        if maintenance_tick is not None:
            await maintenance_tick()
        published = await self.flush_candidates()
        if published:
            self.record_behavior("maintenance_tick:candidates_flushed", published)
        quiet_published = await self._publish_issue_close_quiet_eligibility()
        if quiet_published:
            self.record_behavior(
                "maintenance_tick:issue_close_quiet_eligibility_published",
                quiet_published,
            )

    async def _publish_issue_close_quiet_eligibility(self) -> int:
        if self.bus is None:
            self.record_behavior("issue_close_quiet_eligibility:transport_unavailable")
            return 0
        now = self._clock()
        published = 0
        for fingerprint, last_seen in tuple(self._fingerprint_last_seen.items()):
            count = self.occurrences(fingerprint)
            if count <= 0 or now - last_seen < self._issue_close_quiet_window:
                continue
            episode_key = stable_idempotency_key(
                "norns-issue-close-quiet-episode",
                fingerprint,
                str(count),
                last_seen.isoformat(),
            )
            if episode_key in self._issue_close_quiet_episodes:
                continue
            await self.bus.publish(
                "Norns",
                "object.rule-candidate",
                {
                    "kind": "issue_close_eligibility_signal",
                    "source_signal": "issue_close_quiet_window",
                    "correlation_id": episode_key,
                    "idempotency_key": stable_idempotency_key(
                        "norns-issue-close-eligibility",
                        episode_key,
                    ),
                    "fingerprint": fingerprint,
                    "closure_eligibility": {
                        "fingerprint": fingerprint,
                        "occurrence_count": count,
                        "last_seen_at": last_seen.isoformat(),
                        "quiet_window_seconds": int(self._issue_close_quiet_window.total_seconds()),
                        "inert": True,
                        "grants_issue_authority": False,
                    },
                    "proposed_by": "Norns",
                    "proposal_kind": "inert_issue_close_support",
                },
            )
            # Mark the episode only after broker acceptance so a failed publish stays retryable.
            self._issue_close_quiet_episodes.add(episode_key)
            published += 1
        return published


__all__ = ["NornsEventLearningMixin"]
