"""Health, retrospective quality, and introspection mixin for Forseti."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from fdai.agents._framework.action_semantics import ActionSemanticsCatalog
from fdai.agents._framework.bounded import BoundedLruDict, BoundedLruSet
from fdai.agents._framework.forseti_judgment import JudgmentTable
from fdai.agents._framework.forseti_telemetry_introspection import telemetry_recipe_facts
from fdai.agents._framework.forseti_what_if import (
    MAX_WHAT_IF_SAMPLES,
    build_what_if_batch,
    judgment_table_from_request,
)
from fdai.agents._framework.introspection import (
    IntrospectionResult,
    attach_agent_state_evidence,
    capability_facts,
    evidence_backed_result,
    mentioned,
    semantic_intents,
)
from fdai.agents._framework.role_answers import forseti_role_answer
from fdai.agents._framework.topics import stable_idempotency_key

if TYPE_CHECKING:
    from fdai.agents._framework.base import AgentSpec
    from fdai.agents._framework.bus import PantheonBus
    from fdai.core.architecture_review import OntologyArchitectureReviewLoop


def _ratio_kpi(numerator: int, denominator: int, *, unit: str = "ratio") -> dict[str, object]:
    if denominator <= 0:
        return {
            "value": None,
            "evidence_state": "insufficient_sample",
            "numerator": numerator,
            "denominator": denominator,
            "unit": unit,
        }
    return {
        "value": numerator / denominator,
        "evidence_state": "measured",
        "numerator": numerator,
        "denominator": denominator,
        "unit": unit,
    }


class ForsetiQualityRuntimeMixin:
    """Report Forseti health and run bounded retrospective checks."""

    arbitrations: dict[str, str]
    _detection_readiness: BoundedLruDict[str, dict[str, str]]
    _unresolved_arbitrations: BoundedLruDict[str, dict[str, Any]]
    _agent_availability: Callable[[], Iterable[str]] | None
    _no_rule_folds: BoundedLruDict[str, int]
    _rule_cache_stale: bool
    _judgment_table: JudgmentTable
    _action_semantics: ActionSemanticsCatalog | None
    _architecture_review_loop: OntologyArchitectureReviewLoop | None
    _rule_state: BoundedLruDict[str, dict[str, str]]
    _rule_staleness_window: timedelta
    _last_owner_rule_update_at: datetime | None
    _verdict_quality_samples: BoundedLruDict[str, dict[str, str]]
    _published_what_if_inputs: BoundedLruSet[str]
    bus: PantheonBus | None
    spec: AgentSpec

    if TYPE_CHECKING:

        def behavior_snapshot(self) -> dict[str, int]: ...

        def record_behavior(self, name: str, amount: int = 1) -> None: ...

    _last_verdict_coherence: dict[str, object]
    _last_novelty_drift: dict[str, object]

    def conversation_evidence_available(self, context: dict[str, Any]) -> bool:
        """Report whether any judged runtime state backs this turn.
        The risk table and rule matches are configuration. Answering "why
        was this denied" from them alone presents a default as if it were
        a decision, so the turn is grounded only once an arbitration, a
        readiness ceiling, or an unresolved conflict has been recorded.
        """
        return bool(self.arbitrations or self._detection_readiness or self._unresolved_arbitrations)

    def health(self) -> dict[str, Any]:
        behavior = self.behavior_snapshot()
        unavailable_peers: tuple[str, ...] = ()
        if self._agent_availability is not None:
            try:
                unavailable_peers = tuple(sorted(str(name) for name in self._agent_availability()))
            except Exception:  # noqa: BLE001 - health must stay bounded
                unavailable_peers = ("availability_probe_unavailable",)
        t2_escalations = int(behavior.get("t2:escalated", 0) or 0)
        verdicts = sum(
            int(count)
            for key, count in behavior.items()
            if isinstance(key, str) and key.startswith("verdict:") and isinstance(count, int)
        )
        grounding_missing = int(behavior.get("grounding:missing", 0) or 0) + len(
            self._no_rule_folds
        )
        model_disagreements = int(behavior.get("model:disagreement", 0) or 0)
        fallback_closures = int(behavior.get("arbitration:fallback_terminal_hil", 0) or 0)
        return {
            "agent": "Forseti",
            "status": "degraded" if self._rule_cache_stale else "ok",
            "judgment_table_digest": self._judgment_table.digest,
            "action_semantics_bound": self._action_semantics is not None,
            "architecture_review_bound": self._architecture_review_loop is not None,
            "rule_state_cached": len(self._rule_state),
            "rule_cache_fresh": not self._rule_cache_stale,
            "rule_staleness_window_seconds": self._rule_staleness_window.total_seconds(),
            "last_owner_rule_update_at": (
                self._last_owner_rule_update_at.isoformat()
                if self._last_owner_rule_update_at is not None
                else ""
            ),
            "unavailable_required_peers": list(unavailable_peers),
            "open_arbitrations": len(self._unresolved_arbitrations),
            "fallback_terminal_hil_closures": fallback_closures,
            "operator_alert": {
                "required": "Odin" in unavailable_peers,
                "status": "pending" if "Odin" in unavailable_peers else "not_required",
            },
            "no_verdict_fallback": "Forseti" in unavailable_peers,
            "judgment_counters": {
                "verdicts": verdicts,
                "t2_escalations": t2_escalations,
                "grounding_missing": grounding_missing,
                "model_disagreements": model_disagreements,
            },
            "verdict_coherence_self_test": dict(self._last_verdict_coherence),
            "novelty_drift_signal": dict(self._last_novelty_drift),
            "retrospective_what_if": dict(self._last_retrospective_what_if),
            "kpis": {
                "t2_escalation_rate": _ratio_kpi(t2_escalations, verdicts),
                "mixed_model_disagreement_rate": _ratio_kpi(model_disagreements, verdicts),
                "grounding_missing_rate": _ratio_kpi(
                    grounding_missing, verdicts + grounding_missing
                ),
            },
            "no_rule_folds": dict(self._no_rule_folds.items()),
            "behavior": behavior,
        }

    def _remember_verdict_for_quality(
        self,
        event: Mapping[str, Any],
        verdict: Mapping[str, Any],
    ) -> None:
        correlation_id = str(verdict.get("correlation_id") or event.get("correlation_id") or "")
        idempotency_key = str(verdict.get("idempotency_key") or "")
        key = correlation_id or idempotency_key
        if not key:
            return
        tier = str(event.get("judgment_tier") or event.get("source_tier") or "T0").upper()
        if tier not in {"T0", "T1", "T2"}:
            tier = "T0"
        self._verdict_quality_samples.set(
            key,
            {
                "event_type": str(event.get("event_type") or ""),
                "action_type": str(verdict.get("action_type") or ""),
                "risk_verdict": str(verdict.get("risk_verdict") or ""),
                "tier": tier,
            },
        )

    async def _run_retrospective_what_if(self, request: Mapping[str, Any]) -> None:
        what_if_table = judgment_table_from_request(request.get("judgment_table"))
        correlation_id = str(request.get("correlation_id") or "")
        if what_if_table is None or not correlation_id:
            self._last_retrospective_what_if = {
                "evidence_state": "invalid_request",
                "sample_size": 0,
                "disagreements": 0,
                "unit": "count",
            }
            self.record_behavior("retrospective_what_if:invalid")
            return
        raw_limit = request.get("sample_limit", MAX_WHAT_IF_SAMPLES)
        sample_limit = (
            raw_limit if isinstance(raw_limit, int) and not isinstance(raw_limit, bool) else 1
        )
        batch = build_what_if_batch(
            correlation_id=correlation_id,
            active_table=self._judgment_table,
            what_if_table=what_if_table,
            retained_samples=self._verdict_quality_samples.items(),
            sample_limit=sample_limit,
        )
        if batch is None:
            self._last_retrospective_what_if = {
                "evidence_state": "insufficient_sample",
                "sample_size": 0,
                "disagreements": 0,
                "unit": "count",
            }
            self.record_behavior("retrospective_what_if:no_samples")
            return
        new_keys = tuple(
            key for key in batch.idempotency_keys if key not in self._published_what_if_inputs
        )
        if not new_keys:
            self.record_behavior("retrospective_what_if:duplicate")
            return
        for key in new_keys:
            self._published_what_if_inputs.add(key)
        payload = {
            **batch.payload,
            "idempotency_key": stable_idempotency_key(
                "forseti-retrospective-what-if",
                correlation_id,
                self._judgment_table.digest,
                what_if_table.digest,
                new_keys,
            ),
        }
        outcomes = payload["outcomes"]
        disagreement_count = int(payload["disagreement_count"])
        self._last_retrospective_what_if = {
            "evidence_state": "measured",
            "sample_size": len(outcomes),
            "disagreements": disagreement_count,
            "contract_version": payload["what_if_contract"]["contract_version"],
            "what_if_judgment_table_digest": what_if_table.digest,
            "unit": "count",
        }
        self.record_behavior("retrospective_what_if:published")
        if disagreement_count:
            self.record_behavior("retrospective_what_if:disagreement", disagreement_count)
        if self.bus is not None:
            await self.bus.publish("Forseti", "object.verdict", payload)

    def _run_verdict_coherence_self_test(self) -> None:
        disagreements = 0
        sample_size = 0
        for _key, sample in self._verdict_quality_samples.items():
            sample_size += 1
            action_type = sample["action_type"] or self._judgment_table.rule_match.get(
                sample["event_type"],
                "",
            )
            expected = self._judgment_table.risk_verdict.get(action_type, "hil")
            if sample["risk_verdict"] != expected:
                disagreements += 1
        self._last_verdict_coherence = {
            "evidence_state": "measured" if sample_size else "insufficient_sample",
            "sample_size": sample_size,
            "disagreements": disagreements,
            "unit": "count",
        }
        if disagreements:
            self.record_behavior("verdict_coherence:disagreement", disagreements)
        else:
            self.record_behavior("verdict_coherence:checked")

    def _refresh_novelty_drift_signal(self) -> None:
        tier_mix = {"T0": 0, "T1": 0, "T2": 0}
        for _key, sample in self._verdict_quality_samples.items():
            tier = sample["tier"]
            tier_mix[tier] = tier_mix.get(tier, 0) + 1
        sample_size = sum(tier_mix.values())
        t2_ratio = (tier_mix["T2"] / sample_size) if sample_size else None
        self._last_novelty_drift = {
            "evidence_state": "measured" if sample_size else "insufficient_sample",
            "sample_size": sample_size,
            "tier_mix": tier_mix,
            "t2_ratio": t2_ratio,
            "unit": "ratio",
        }
        if t2_ratio is not None and t2_ratio > 0.1:
            self.record_behavior("novelty_drift:t2_ratio_high")
        else:
            self.record_behavior("novelty_drift:checked")

    async def introspect(self, question: str, context: dict[str, Any]) -> IntrospectionResult:
        facts = {
            **capability_facts(self.spec),
            **telemetry_recipe_facts(),
            "known_action_verdicts": dict(self._judgment_table.risk_verdict),
            "rule_matches": dict(self._judgment_table.rule_match),
            "judgment_table_digest": self._judgment_table.digest,
            "arbitrations_recorded": len(self.arbitrations),
            # Both gates that force an otherwise-auto verdict to human
            # review. The charter tells Forseti to report them as exactly
            # that, so they MUST be readable through the judgment tool.
            "unresolved_arbitrations": len(self._unresolved_arbitrations),
            "readiness_limited_resources": len(self._detection_readiness),
            "rca_evidence_available": False,
            "action_type": None,
            "risk_verdict": None,
        }
        if "rca_evidence" in semantic_intents(context):
            statement = "No grounded RCA record is retained by this conversational projection"
            return evidence_backed_result(self.spec.name, facts, statement)
        actions = mentioned(question, self._judgment_table.risk_verdict)
        if actions:
            action = actions[0]
            verdict = self._judgment_table.risk_verdict[action]
            facts.update({"action_type": action, "risk_verdict": verdict})
            statement = f"Action {action!r} has configured default risk verdict {verdict!r}"
            return evidence_backed_result(self.spec.name, facts, statement)
        evidence_ref = attach_agent_state_evidence(self.spec.name, facts)
        answer = forseti_role_answer(str(context.get("locale")), facts, evidence_ref)
        return IntrospectionResult(answer=answer, facts=facts)
