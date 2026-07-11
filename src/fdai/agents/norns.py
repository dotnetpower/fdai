"""Norns - Learner (Wave 2 behavior).

Norns watches the audit stream and turns operational signals into
inert RuleCandidate proposals for Mimir. It never mutates the catalog
or any threshold directly: every proposal is data that must pass the
quality gate before it can take effect (see
`docs/roadmap/rules-and-detection/rule-governance.md` and the discovery loop in
`architecture.instructions.md`).

Three deterministic (T0) learners run here; T1 clustering and T2 batch
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
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from fdai.agents._framework.action_semantics import outcome_result
from fdai.agents._framework.base import Agent
from fdai.agents._framework.bounded import BoundedLruDict, BoundedLruSet
from fdai.agents._framework.introspection import IntrospectionResult, capability_facts, capped_list
from fdai.agents._framework.pantheon import _NORNS

# Adverse outcomes that count against an action's success record.
_ADVERSE_RESULTS: frozenset[str] = frozenset({"rollback", "failure", "reverted"})
_SUCCESS_RESULTS: frozenset[str] = frozenset({"success", "applied", "ok"})

# LRU cap on the per-event / per-fingerprint maps a long-lived learner keeps,
# so they cannot grow without bound over the process lifetime.
_MAX_TRACKED = 50_000


class Norns(Agent):
    """Wave-2 Norns: fingerprint aggregator + outcome / override learner."""

    def __init__(
        self,
        *,
        promotion_threshold: int = 3,
        rollback_alarm_rate: float = 0.2,
        min_outcome_samples: int = 20,
        override_retire_threshold: int = 5,
    ) -> None:
        # Fail fast on misconfiguration: a non-positive threshold or a
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

    async def on_typed_message(self, topic: str, payload: dict[str, Any]) -> None:
        if topic == "object.issue":
            self._observe_fingerprint(payload)
        elif topic == "object.audit-entry":
            # Saga audits every terminal state and republishes it as an
            # audit-entry; the outcome learner scores rollback rates from it.
            self._observe_outcome(payload)
        # object.override is deliberately NOT handled here: it is not a pantheon
        # bus topic (agent-pantheon.md 2 - overrides flow through the exemption
        # / rule-catalog machinery). That machinery calls observe_override()
        # directly. object.approval is subscribed but has no learner yet
        # (follow-up: an approval-pattern learner).

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

    async def introspect(self, question: str, context: dict[str, Any]) -> IntrospectionResult:
        facts = {
            **capability_facts(self.spec),
            "fingerprints_tracked": len(self._fingerprint_counter),
            "pending_candidates": len(self.pending_candidates),
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
