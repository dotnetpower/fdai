"""Norns - Learner (Wave 2 behavior).

Norns watches the audit stream and turns operational signals into
inert RuleCandidate proposals for Mimir. It never mutates the catalog
or any threshold directly: every proposal is data that must pass the
quality gate before it can take effect (see
`docs/roadmap/rules-and-detection/rule-governance.md` and the discovery loop in
`architecture.instructions.md`).

Every candidate passes the internal Urd (past evidence), Verdandi (current
contract), and Skuld (future safety) perspectives before publication. These
perspectives are not agents or principals. Norns publishes one aggregate
consensus result only when all three agree and retains disagreements as
bounded hold records.

Four deterministic (T0) learners run here; T1 clustering and T2 batch
summary land in later waves:

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

Optional scenario-coverage learner:

5. **Scenario-coverage aggregator** (optional, active when a composition
    root supplies it) - repeated live incidents whose symptom the compiled
   chaos-scenarios index cannot match propose a `scenario-coverage-gap`
   candidate. Same discipline: never mutates the catalog. See
   :class:`fdai.core.chaos.coverage.ScenarioCoverageAggregator` and
   `docs/internals/sre-scenario-library-scaling.md`.
"""

from __future__ import annotations

import hashlib
from collections import Counter, deque
from datetime import datetime
from typing import Any

from fdai.agents._framework.action_semantics import outcome_result
from fdai.agents._framework.base import Agent
from fdai.agents._framework.bounded import BoundedLruDict, BoundedLruSet
from fdai.agents._framework.introspection import (
    IntrospectionResult,
    capability_facts,
    capped_list,
)
from fdai.agents._framework.norns_consensus import NornsConsensus
from fdai.agents._framework.pantheon import _NORNS
from fdai.core.chaos.coverage import ScenarioCoverageAggregator
from fdai.core.learning import (
    PostTurnReviewCoordinator,
    RuleCandidateHint,
    review_input_from_mapping,
)
from fdai.core.trajectory import ReviewedTrajectoryDataset

# Adverse outcomes that count against an action's success record.
_ADVERSE_RESULTS: frozenset[str] = frozenset({"rollback", "failure", "reverted"})
_SUCCESS_RESULTS: frozenset[str] = frozenset({"success", "applied", "ok"})

# LRU cap on the per-event / per-fingerprint maps a long-lived learner keeps,
# so they cannot grow without bound over the process lifetime.
_MAX_TRACKED = 50_000


class Norns(Agent):
    """Wave-2 Norns: fingerprint aggregator + outcome / override / approval learner."""

    def __init__(
        self,
        *,
        promotion_threshold: int = 3,
        rollback_alarm_rate: float = 0.2,
        min_outcome_samples: int = 20,
        override_retire_threshold: int = 5,
        rejection_revise_threshold: int = 5,
        coverage_aggregator: ScenarioCoverageAggregator | None = None,
        post_turn_review: PostTurnReviewCoordinator | None = None,
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
        super().__init__(spec=_NORNS)
        # Fingerprints are content hashes (one per distinct incident), so the
        # counter is bounded by an LRU cap - a long-lived learner would leak
        # otherwise.
        self._fingerprint_counter: BoundedLruDict[str, int] = BoundedLruDict(_MAX_TRACKED)
        # Fingerprints already proposed - same content-hash keyspace as the
        # counter above, so it is bounded too (a long-lived learner that saw
        # many distinct incidents would otherwise leak one entry per proposal).
        self._proposed: BoundedLruSet[str] = BoundedLruSet(_MAX_TRACKED)
        self._promotion_threshold = promotion_threshold
        self.pending_candidates: list[dict[str, Any]] = []
        # Cursor into ``pending_candidates`` marking how many have already been
        # published onto ``object.rule-candidate``. Publishing is idempotent:
        # a re-flush only sends candidates past the cursor, so a candidate is
        # never republished (which would trip Mimir's flood guard).
        self._flush_cursor = 0
        self._consensus = NornsConsensus()
        self._consensus_holds: deque[dict[str, object]] = deque(maxlen=1_000)
        # Outcome-threshold learner state.
        self._rollback_alarm_rate = rollback_alarm_rate
        self._min_outcome_samples = min_outcome_samples
        self._outcomes: dict[str, dict[str, int]] = {}
        self._outcome_proposed: set[str] = set()
        # Correlation ids whose outcome has already been counted, so a single
        # action that emits multiple adverse terminal audits (Thor emits
        # FAILED then ROLLED_BACK for a failed action) is scored once, not
        # twice. Only applied when a correlation_id is present; audit-entries
        # without one fall back to per-event counting. Bounded (LRU): one
        # entry per action forever would leak on a long-lived learner.
        self._counted_correlations: BoundedLruSet[str] = BoundedLruSet(_MAX_TRACKED)
        # Override learner state.
        self._override_retire_threshold = override_retire_threshold
        self._override_counter: Counter[str] = Counter()
        self._override_proposed: set[str] = set()
        # Approval-pattern learner state. Repeated HIL rejections of the same
        # action type mean humans consistently refuse it - a signal the action
        # is a poor fit; it proposes an inert `revision` candidate (the safe,
        # autonomy-lowering direction, symmetric with the override learner).
        # Approvals are counted for evidence only; the learner never proposes
        # auto-promotion (the risky direction), which stays an explicit,
        # quality-gated decision. Dedup per correlation id (LRU) so a
        # re-delivered approval is scored once.
        self._rejection_revise_threshold = rejection_revise_threshold
        self._approval_counts: dict[str, dict[str, int]] = {}
        self._approval_proposed: set[str] = set()
        self._counted_approvals: BoundedLruSet[str] = BoundedLruSet(_MAX_TRACKED)
        self._post_turn_hint_proposed: BoundedLruSet[str] = BoundedLruSet(_MAX_TRACKED)
        self._reviewed_trajectory_manifests: BoundedLruSet[str] = BoundedLruSet(_MAX_TRACKED)
        # Scenario-coverage learner (optional; composition root wires it).
        # When bound, live incident symptoms that the compiled
        # chaos-scenarios symptom index cannot match accumulate here and
        # emit `scenario-coverage-gap` candidates onto pending_candidates
        # once the aggregator's gap_threshold is crossed. When None, the
        # public `observe_incident_symptom` method is a no-op - the same
        # discipline as the other learners: never mutate the catalog.
        self._coverage_aggregator = coverage_aggregator
        self._post_turn_review = post_turn_review

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
        if topic == "object.issue":
            self._observe_fingerprint(payload)
        elif topic == "object.audit-entry":
            # Saga audits every terminal state and republishes it as an
            # audit-entry; the outcome learner scores rollback rates from it.
            self._observe_outcome(payload)
        elif topic == "object.approval":
            # Var publishes the final HIL decision (approved / rejected); the
            # approval-pattern learner scores recurring rejections from it.
            self._observe_approval(payload)
        elif topic == "object.turn":
            await self._observe_post_turn_review(payload)
        # object.override is deliberately NOT handled here: it is not a pantheon
        # bus topic (agent-pantheon.md 2 - overrides flow through the exemption
        # / rule-catalog machinery). That machinery calls observe_override()
        # directly.
        # Off-path batch: forward any newly-formed inert candidates to Mimir.
        await self.flush_candidates()

    async def _observe_post_turn_review(self, payload: dict[str, Any]) -> None:
        if payload.get("kind") != "post_turn_review":
            return
        if payload.get("producer_principal") != "Bragi":
            raise ValueError("post-turn review turn MUST be published by Bragi")
        if self._post_turn_review is None:
            self.record_behavior("post_turn_review_unavailable")
            return
        raw = payload.get("review")
        if not isinstance(raw, dict):
            raise ValueError("post-turn review payload MUST contain a review object")
        await self._post_turn_review.review(review_input_from_mapping(raw))
        self.record_behavior("post_turn_review_completed")

    # ---- candidate publication (Norns -> Mimir discovery loop) ---------

    async def flush_candidates(self) -> int:
        """Publish newly-accumulated inert RuleCandidates onto the bus.

        Norns is the single writer of ``object.rule-candidate`` (it owns the
        ``RuleCandidate`` object type), so it publishes each candidate its
        learners produced for Mimir's ``CandidateGuard`` + the quality gate to
        inspect. Publishing does NOT promote anything - candidates stay inert
        data until the quality gate acts (architecture discovery loop). This
        is off-path batch work: ``on_typed_message`` flushes after each
        learner pass, and a batch tick / the sync learners' caller MAY call it
        directly to drain override / coverage candidates.

        Before publication, the internal Urd, Verdandi, and Skuld perspectives
        must agree. A disagreement is removed from ``pending_candidates`` and
        retained as a bounded aggregate hold record. A published candidate is
        also removed once sent, so the buffer holds only proposals awaiting a
        decision or bus capacity. Publication is rate-limited per the agent's
        declared ``rate_limits`` (agent-pantheon.md 7.9): when the budget is
        exhausted the flush stops and leaves the not-yet-sent candidates
        queued, so a burst is throttled, never dropped. Returns the number of
        candidates published on this call.
        """
        published = 0
        while self._flush_cursor < len(self.pending_candidates):
            candidate = self.pending_candidates[self._flush_cursor]
            consensus = self._consensus.evaluate(candidate)
            if not consensus.unanimous:
                self._consensus_holds.append(
                    {
                        "decision": "hold",
                        "source_signal": str(candidate.get("source_signal", "")),
                        "proposal_kind": str(candidate.get("proposal_kind", "")),
                        "holding_perspectives": consensus.holding_perspectives(),
                        "reason_codes": consensus.reason_codes(),
                    }
                )
                self._flush_cursor += 1
                self.record_behavior("rule_candidate_consensus_held")
                continue
            payload = {
                "producer_principal": "Norns",
                **candidate,
                "norns_consensus": consensus.summary(),
            }
            if not await self._publish_proposal("object.rule-candidate", payload):
                # Bus-less (unit) or rate-limited: stop and leave the queued
                # candidates for a later pass. No learning signal is dropped -
                # only throttled.
                break
            self._flush_cursor += 1
            self.record_behavior("rule_candidate_published")
            published += 1
        # Drop the consumed (published or held) prefix so pending_candidates
        # stays a bounded buffer of only unresolved proposals. The cursor
        # counts consumed entries; slicing them off resets it to 0.
        if self._flush_cursor:
            del self.pending_candidates[: self._flush_cursor]
            self._flush_cursor = 0
        return published

    # ---- 1. fingerprint aggregator ------------------------------------

    def _observe_fingerprint(self, payload: dict[str, Any]) -> None:
        fp = str(payload.get("fingerprint", ""))
        if not fp:
            return
        count = (self._fingerprint_counter.get(fp) or 0) + 1
        self._fingerprint_counter.set(fp, count)
        if count >= self._promotion_threshold and fp not in self._proposed:
            self._proposed.add(fp)
            self.pending_candidates.append(
                {
                    "source_signal": "handoff_fingerprint",
                    "evidence": {
                        "fingerprint": fp,
                        "occurrence_count": count,
                    },
                    "proposed_by": "Norns",
                    "proposal_kind": "new",
                }
            )

    # ---- 2. outcome-threshold learner ---------------------------------

    def _observe_outcome(self, payload: dict[str, Any]) -> None:
        """Learn from an action's audit outcome.

        A measured rollback rate above the alarm rate (over a minimum
        sample) proposes raising the action's confidence threshold so it
        escalates to HIL more often - the safe direction. The proposal is
        inert until the quality gate promotes it.
        """
        target = str(payload.get("action_type") or payload.get("rule_id") or "")
        # Shadow outcomes are judged-and-logged, not real executions - a shadow
        # 'success' says nothing about the action's real safety, so it MUST NOT
        # dilute the measured rollback rate. Learn from real executions only.
        if payload.get("shadow_mode"):
            return
        result = str(payload.get("result", "")).lower()
        if not result:
            # An audit-entry that reports the raw ActionRun ``state`` (Thor's
            # vocabulary) instead of a normalized ``result`` still learns.
            result = outcome_result(str(payload.get("state", ""))) or ""
        if not target:
            return
        if result in _ADVERSE_RESULTS:
            bucket = "rollback"
        elif result in _SUCCESS_RESULTS:
            bucket = "success"
        else:
            return
        # Dedup one action's outcome across its multiple terminal audits.
        correlation_id = str(payload.get("correlation_id", ""))
        if correlation_id:
            if correlation_id in self._counted_correlations:
                return
            self._counted_correlations.add(correlation_id)
        counts = self._outcomes.setdefault(target, {"success": 0, "rollback": 0})
        counts[bucket] += 1
        total = counts["success"] + counts["rollback"]
        if total < self._min_outcome_samples or target in self._outcome_proposed:
            return
        rollback_rate = counts["rollback"] / total
        if rollback_rate <= self._rollback_alarm_rate:
            return
        self._outcome_proposed.add(target)
        self.pending_candidates.append(
            {
                "source_signal": "audit_outcome",
                "evidence": {
                    "target": target,
                    "sample_size": total,
                    "rollback_rate": round(rollback_rate, 4),
                    "alarm_rate": self._rollback_alarm_rate,
                },
                "proposed_by": "Norns",
                "proposal_kind": "threshold_adjustment",
                "suggested_change": "raise_confidence_threshold",
                "target_rule_id": target,
            }
        )

    # ---- 2b. approval-pattern learner ---------------------------------

    def _observe_approval(self, payload: dict[str, Any]) -> None:
        """Learn from a HIL approval decision.

        Var emits one ``object.approval`` per final decision with a ``state``
        of ``approved`` or ``rejected``. Recurring rejections of the same
        action type mean humans consistently refuse it - a signal the action
        (or its risk classification) is a poor fit - so once the rejection
        count crosses the threshold the learner proposes an inert ``revision``
        candidate. Approvals are counted for evidence (the sample the
        rejection rate is measured against); the learner never proposes
        auto-promotion, which stays an explicit, quality-gated decision.
        """
        action_type = str(payload.get("action_type") or "")
        state = str(payload.get("state", "")).strip().lower()
        if not action_type or state not in ("approved", "rejected"):
            return
        # Dedup one decision across a possible re-delivery (at-least-once).
        correlation_id = str(payload.get("correlation_id", ""))
        if correlation_id:
            if correlation_id in self._counted_approvals:
                return
            self._counted_approvals.add(correlation_id)
        counts = self._approval_counts.setdefault(action_type, {"approved": 0, "rejected": 0})
        counts[state] += 1
        if state != "rejected" or action_type in self._approval_proposed:
            return
        if counts["rejected"] < self._rejection_revise_threshold:
            return
        self._approval_proposed.add(action_type)
        self.pending_candidates.append(
            {
                "source_signal": "recurring_hil_rejection",
                "evidence": {
                    "action_type": action_type,
                    "rejection_count": counts["rejected"],
                    "sample_size": counts["approved"] + counts["rejected"],
                },
                "proposed_by": "Norns",
                "proposal_kind": "revision",
                "target_rule_id": action_type,
            }
        )

    # ---- 3. override learner ------------------------------------------

    def observe_override(self, payload: dict[str, Any]) -> None:
        """Learn from recurring operator overrides on a rule.

        Public entry point: ``object.override`` is not a pantheon bus topic
        (overrides flow through the exemption / rule-catalog machinery), so
        that machinery calls this method directly rather than publishing a
        topic Norns subscribes to. Repeated overrides mean the rule is a poor
        fit for the scope; a `disabled` mode proposes retirement, anything
        else a revision.
        """
        rule_id = str(payload.get("rule_id") or payload.get("target_rule_id") or "")
        event = str(payload.get("event", "create")).lower()
        if not rule_id or event not in ("create", "modify"):
            return
        self._override_counter[rule_id] += 1
        if (
            self._override_counter[rule_id] < self._override_retire_threshold
            or rule_id in self._override_proposed
        ):
            return
        self._override_proposed.add(rule_id)
        mode = str(payload.get("mode", ""))
        kind = "retirement" if mode == "disabled" else "revision"
        self.pending_candidates.append(
            {
                "source_signal": "recurring_override",
                "evidence": {
                    "rule_id": rule_id,
                    "override_count": self._override_counter[rule_id],
                    "latest_mode": mode,
                },
                "proposed_by": "Norns",
                "proposal_kind": kind,
                "target_rule_id": rule_id,
            }
        )

    # ---- 4. scenario-coverage learner (optional) ---------------------

    def observe_incident_symptom(
        self,
        *,
        incident_id: str,
        signal: str,
        target_type: str,
        severity: str,
    ) -> None:
        """Feed one live incident's symptom to the scenario-coverage learner.

        Public entry point: the sensing layer (`Huginn` / `Heimdall`
        analyzers) calls this per-incident so uncovered symptoms
        accumulate. No-op when `coverage_aggregator` was not injected
        at construction (`None`).

        Any threshold-crossing proposals are appended to
        ``pending_candidates`` as `candidate_type: scenario-coverage-gap`,
        alongside the fingerprint / outcome / override candidates. Mimir's
        `CandidateGuard` treats them identically - grounded provenance,
        same quality gate.
        """
        if self._coverage_aggregator is None:
            return
        self._coverage_aggregator.observe(
            incident_id=incident_id,
            signal=signal,
            target_type=target_type,
            severity=severity,
        )
        for candidate in self._coverage_aggregator.drain_proposals():
            self.pending_candidates.append(
                {
                    "source_signal": "scenario_coverage_gap",
                    "evidence": candidate["target_symptom"],
                    "provenance": candidate["provenance"],
                    "proposed_by": "Norns",
                    "proposal_kind": "new-scenario",
                    "candidate_type": candidate["candidate_type"],
                    "proposed_scenario_id": candidate["proposed_scenario_id"],
                    "notes": candidate["notes"],
                }
            )

    async def submit_rule_hint(
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
        self.pending_candidates.append(
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
        await self.flush_candidates()
        return proposal_ref

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
        return self._override_counter[rule_id]

    def rejection_count(self, action_type: str) -> int:
        """Measured HIL rejection count for an action type (0 if unseen)."""
        counts = self._approval_counts.get(action_type)
        return counts["rejected"] if counts else 0

    def consensus_holds(self) -> tuple[dict[str, object], ...]:
        """Return bounded aggregate hold records for operator inspection."""
        return tuple(self._consensus_holds)

    async def introspect(self, question: str, context: dict[str, Any]) -> IntrospectionResult:
        facts = {
            **capability_facts(self.spec),
            "fingerprints_tracked": len(self._fingerprint_counter),
            "pending_candidates": len(self.pending_candidates),
            "consensus_holds": len(self._consensus_holds),
            "outcomes_tracked": capped_list(sorted(self._outcomes)),
            "outcomes_tracked_count": len(self._outcomes),
        }
        if not self._fingerprint_counter and not self.pending_candidates:
            answer = (
                "No patterns observed yet; I turn operational signals into inert "
                "rule candidates for the quality gate."
            )
        else:
            answer = (
                f"Observed {len(self._fingerprint_counter)} fingerprint pattern(s); "
                f"{len(self.pending_candidates)} candidate(s) proposed."
            )
        return IntrospectionResult(answer=answer, facts=facts)


__all__ = ["Norns"]
