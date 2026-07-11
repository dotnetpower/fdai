"""LLM quality gate - guards T2 output before it reaches the risk-gate.

Phase 2 quality gate (see
[`docs/roadmap/phases/phase-2-quality-and-t1.md § LLM Quality Gate`]).

T2 inputs are **untrusted**; the verifier + policy re-check are the
authority, not model text. The gate composes three independent checks -
**mixed-model cross-check**, **deterministic verifier**, and
**grounding (RAG citation) validator** - plus a **confidence threshold**
derived from verifier / cross-check signals (not the model's self-report).

Outcomes are typed and audited:

- ``eligible`` - verifier passed, cross-check agreed, grounding validated,
  confidence above threshold. The risk-gate MAY consider auto-execution.
- ``abstain`` - grounding unavailable, verifier abstained, or confidence
  below threshold. Route to HIL, no auto-action.
- ``disagree`` - cross-check disagreement. Escalate to HIL, do NOT
  auto-resolve.
- ``deny`` - verifier explicitly rejected the candidate. No execution.

Public shape
------------

The gate itself is a small orchestrator built from three Protocols so a
fork can swap any leg (real LLM cross-check, remote verifier, custom
grounding source) without editing ``core/``. The upstream default
in-memory implementations under
:mod:`~fdai.core.quality_gate.testing` produce a deterministic
outcome from the injected candidate and are used by every test in this
suite plus the P1 e2e replay when a T2 stage is exercised.

Wave 4.5 delta-2b: the gate accepts an optional
:class:`~fdai.core.quality_gate.debate.DebateOrchestrator` and a
:class:`~fdai.core.quality_gate.debate_router.DebateRouterConfig`.
When cross-check quorum disagrees AND both are wired AND the router
returns :attr:`DebateRoute.DEBATE`, the gate runs the debate and:

- treats ``DebateOutcome(verdict=PROCEED)`` as resolving the
  disagreement (outcome flips from ``DISAGREE`` to ``ELIGIBLE`` provided
  no other reasons stand);
- keeps the disagreement on ``DebateOutcome(verdict=ABORT)`` and adds
  the orchestrator's ``reason`` string to the audit trail.

The router / orchestrator MUST be provided together (both, or neither);
half-wiring raises :class:`ValueError` at construction so a fork bug is
caught at build time.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from fdai.shared.contracts.models import Rule

if TYPE_CHECKING:
    # Broken circular import: debate + debate_router + rubric all import
    # ``QualityCandidate`` from this module, so we defer the type
    # references here and runtime imports to the ``evaluate`` method.
    from fdai.core.quality_gate.debate import DebateOrchestrator
    from fdai.core.quality_gate.debate_router import DebateRouterConfig
    from fdai.core.quality_gate.rubric import RubricEvaluator, RubricScore


class QualityOutcome(StrEnum):
    """Terminal outcome for one :meth:`QualityGate.evaluate` call."""

    ELIGIBLE = "eligible"
    ABSTAIN = "abstain"
    DISAGREE = "disagree"
    DENY = "deny"


@dataclass(frozen=True, slots=True)
class QualityCandidate:
    """A T2-generated action candidate handed to the quality gate.

    ``action_type`` is the ActionType id the T2 model proposed;
    ``params`` are the free-form parameters the risk-gate would forward.
    ``cited_rule_ids`` MUST be citations from the rule catalog - the
    grounding validator checks each against the loaded catalog and the
    resource context.

    ``confidence_signals`` is a dict of derived confidences (retrieval
    coverage, verifier margin, precondition-check pass rate). The gate's
    ``confidence_threshold`` is compared against a single aggregate
    :attr:`aggregate_confidence`; the model's own self-report is NEVER
    passed here - that's the anti-pattern the gate closes.

    ``reasoning_trace`` is the T2 model's natural-language justification
    for the proposed action. It is the **scoring target** for the
    optional rubric evaluator (:mod:`~fdai.core.quality_gate.rubric`):
    faithfulness / evidence-action alignment cannot be scored without
    the reasoning text. It is untrusted data like every other model
    output - the rubric only ever *lowers* confidence from it, never
    raises eligibility. Empty string when a proposer does not emit one
    (older adapters); the rubric then abstains for lack of a target.
    """

    action_type: str
    target_resource_ref: str
    params: dict[str, Any]
    cited_rule_ids: tuple[str, ...]
    confidence_signals: Mapping[str, float] = field(default_factory=dict)
    reasoning_trace: str = ""

    @property
    def aggregate_confidence(self) -> float:
        """Mean of the derived signals; 0.0 when none are supplied.

        ``bool`` values are excluded even though they subtype ``int``:
        confidence signals are numeric floats, and letting ``True`` pass
        as ``1.0`` would silently inflate the aggregate. Values outside
        ``[0.0, 1.0]`` are likewise excluded - a confidence is a
        probability, so an out-of-range signal is corrupt and MUST NOT be
        allowed to push the aggregate past the gate threshold.
        """
        if not self.confidence_signals:
            return 0.0
        values = [
            float(v)
            for v in self.confidence_signals.values()
            if isinstance(v, (int, float)) and not isinstance(v, bool) and 0.0 <= float(v) <= 1.0
        ]
        if not values:
            return 0.0
        return sum(values) / len(values)


@dataclass(frozen=True, slots=True)
class ModelVote:
    """One cross-check model's vote, recorded for reproducible audit.

    Capturing the per-model proposal (not just the agreement count) makes
    a T2 judgment reconstructable from the audit trail - the
    reproducibility property the append-only log promises.
    """

    model_id: str
    proposed_action_type: str
    agreed: bool


@dataclass(frozen=True, slots=True)
class QualityDecision:
    """Frozen record produced by :meth:`QualityGate.evaluate`."""

    outcome: QualityOutcome
    candidate: QualityCandidate
    reasons: tuple[str, ...] = field(default_factory=tuple)
    grounded_rule_ids: tuple[str, ...] = field(default_factory=tuple)
    aggregate_confidence: float = 0.0
    model_votes: tuple[ModelVote, ...] = field(default_factory=tuple)
    """Per-model cross-check votes (empty when the gate aborted before the
    cross-check ran). Provenance for reproducible replay of a T2 judgment."""

    rubric_scores: tuple[RubricScore, ...] = field(default_factory=tuple)
    """Per-criterion rubric scores recorded for audit (empty when no
    rubric evaluator is wired). Provenance for a hallucination-filter
    decision, regardless of shadow / enforce mode."""

    rubric_min_score: float | None = None
    """The minimum rubric criterion score - the value folded into the
    aggregate confidence via ``min()`` when the rubric runs in enforce
    mode. ``None`` when no rubric evaluator is wired."""

    rubric_verdict: str | None = None
    """The reduced rubric verdict (``pass`` / ``fail`` / ``abstain``) or
    ``None`` when no rubric evaluator ran. Recorded even in shadow mode
    so the promotion gate can measure catch / false-positive rates."""

    rubric_shadow: bool = False
    """Whether the rubric ran judge-and-log only (shadow) for this
    decision. ``True`` means the rubric verdict did NOT influence the
    outcome or confidence - it was recorded for measurement only."""


# ---------------------------------------------------------------------------
# DI seams (Protocols) - a fork implements these with real LLM clients
# ---------------------------------------------------------------------------


@runtime_checkable
class CrossCheckModel(Protocol):
    """One frontier model used for a cross-check vote.

    ``propose`` returns the ActionType id + parameter subset the model
    would emit for the given candidate context. Real implementations
    call a remote LLM under a bounded timeout; the fake in
    :mod:`~fdai.core.quality_gate.testing` returns a deterministic
    payload seeded by the input, so tests are reproducible.
    """

    async def propose(self, candidate: QualityCandidate) -> tuple[str, Mapping[str, Any]]: ...


@runtime_checkable
class VerifierPolicy(Protocol):
    """Deterministic re-check of the candidate action.

    Implementations MUST run without any LLM call: policy-as-code (OPA/Rego),
    what-if simulation, or an authored Python check. Returns ``True`` when
    the candidate is verifier-eligible (no explicit rejection), ``None`` to
    abstain (grounding unavailable, verifier cannot decide), and ``False``
    to explicitly deny.
    """

    def verify(self, candidate: QualityCandidate) -> bool | None: ...


@runtime_checkable
class GroundingSource(Protocol):
    """Provides the rule ids the candidate is allowed to cite."""

    def known_rule_ids(self) -> set[str]: ...

    def get(self, rule_id: str) -> Rule | None: ...


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class QualityGateConfig:
    """Thresholds the gate enforces.

    ``confidence_threshold`` is the aggregate cutoff derived from
    :class:`QualityCandidate.confidence_signals` (not the model self-
    report). Below → abstain.
    """

    confidence_threshold: float = 0.7
    require_grounding: bool = True
    require_cross_check_quorum: int = 2
    """Minimum number of cross-check models that MUST agree with the
    candidate's ``action_type``. Independent models (distinct
    vendors/weights) - see phase-2 § Quality Gate."""

    rubric_shadow: bool = True
    """When ``True`` (the default), a wired rubric evaluator runs
    judge-and-log only: its scores are recorded on the
    :class:`QualityDecision` but do NOT change the outcome or the
    aggregate confidence. Shadow-before-enforce, per
    ``docs/roadmap/hallucination-rubric-gate.md``. A fork flips this to
    ``False`` only after the promotion gate is met on a labeled
    scenario set."""

    rubric_required_criteria: tuple[str, ...] = ()
    """Criteria a :class:`~fdai.core.quality_gate.rubric.RubricOutput`
    MUST cover for the rubric to render a ``pass`` / ``fail`` verdict.
    A missing required criterion collapses the rubric to ``abstain``
    (route to HIL) so a truncated evaluator response cannot silently
    skip a hallucination dimension. Empty tuple = no coverage
    requirement (any returned scores are honored as-is)."""


class QualityGate:
    """Compose verifier + cross-check + grounding + threshold checks."""

    def __init__(
        self,
        *,
        verifier: VerifierPolicy,
        cross_check_models: tuple[CrossCheckModel, ...],
        grounding: GroundingSource,
        config: QualityGateConfig | None = None,
        debate_orchestrator: DebateOrchestrator | None = None,
        debate_router_config: DebateRouterConfig | None = None,
        rubric_evaluator: RubricEvaluator | None = None,
    ) -> None:
        cfg = config or QualityGateConfig()
        if not 0.0 <= cfg.confidence_threshold <= 1.0:
            raise ValueError("confidence_threshold MUST be in [0.0, 1.0]")
        if cfg.require_cross_check_quorum < 1:
            raise ValueError("require_cross_check_quorum MUST be >= 1")
        if len(cross_check_models) < cfg.require_cross_check_quorum:
            raise ValueError("not enough cross-check models registered for the configured quorum")
        # Wave 4.5 delta-2b: debate wire is opt-in. Half-wiring
        # (orchestrator without router or vice versa) is a fork bug
        # that would only surface on the first disagreement - refuse
        # at construction so the failure is loud and immediate.
        if (debate_orchestrator is None) != (debate_router_config is None):
            raise ValueError(
                "debate_orchestrator and debate_router_config MUST be provided "
                "together (both, or neither)"
            )
        self._verifier = verifier
        self._models = cross_check_models
        self._grounding = grounding
        self._config = cfg
        self._debate_orchestrator = debate_orchestrator
        self._debate_router_config = debate_router_config
        self._rubric_evaluator = rubric_evaluator

    async def evaluate(self, candidate: QualityCandidate) -> QualityDecision:
        """Return the gate outcome for one candidate action.

        Ordering: verifier → grounding → cross-check → threshold. A hard
        deny short-circuits (verifier ``False``); every other failure
        falls through to :attr:`QualityOutcome.ABSTAIN` or
        :attr:`QualityOutcome.DISAGREE` so a caller sees the whole
        picture in :attr:`QualityDecision.reasons`.
        """
        reasons: list[str] = []

        # 1. Deterministic verifier
        verify = self._verifier.verify(candidate)
        if verify is False:
            return QualityDecision(
                outcome=QualityOutcome.DENY,
                candidate=candidate,
                reasons=("verifier_rejected",),
                aggregate_confidence=candidate.aggregate_confidence,
            )
        if verify is None:
            reasons.append("verifier_abstained")

        # 2. Grounding (RAG citation validity)
        known = self._grounding.known_rule_ids()
        grounded: list[str] = []
        # Duck-typed hook: a richer :class:`GroundingSource` (e.g.
        # :class:`~fdai.core.quality_gate.rag_grounding.RagGroundingSource`)
        # MAY expose ``supports(candidate, rule_id) -> bool`` to validate
        # that a citation is topically relevant to the candidate, not
        # only that its id exists in the catalog. The base Protocol
        # stays unchanged so older grounding sources fall back to the
        # ID-exists-only behavior.
        supports_fn = getattr(self._grounding, "supports", None)
        for rule_id in candidate.cited_rule_ids:
            if rule_id not in known:
                reasons.append(f"unknown_cited_rule:{rule_id}")
                continue
            if supports_fn is not None and not supports_fn(candidate, rule_id):
                reasons.append(f"ungrounded_citation:{rule_id}")
                continue
            grounded.append(rule_id)
        if self._config.require_grounding and not grounded:
            reasons.append("no_grounded_citation")

        # 3. Mixed-model cross-check (agreement on action_type)
        agree = 0
        votes: list[ModelVote] = []
        first_proposer_output: tuple[str, Mapping[str, Any]] | None = None
        # Models are independent read-only calls; run them concurrently so
        # the cross-check adds one model's latency, not the sum, to the T2
        # budget. Results are gathered in registration order, so votes and
        # the first-proposer selection stay deterministic.
        proposals = await asyncio.gather(*(model.propose(candidate) for model in self._models))
        for i, (model, (proposed_type, proposed_params)) in enumerate(
            zip(self._models, proposals, strict=True)
        ):
            if i == 0:
                first_proposer_output = (proposed_type, proposed_params)
            agreed = proposed_type == candidate.action_type
            if agreed:
                agree += 1
            votes.append(
                ModelVote(
                    model_id=str(getattr(model, "model_id", f"model-{i}")),
                    proposed_action_type=proposed_type,
                    agreed=agreed,
                )
            )
        cross_check_below_quorum = agree < self._config.require_cross_check_quorum
        if cross_check_below_quorum:
            reasons.append(
                f"cross_check_below_quorum:agree={agree}<"
                f"quorum={self._config.require_cross_check_quorum}"
            )

        # 3b. Wave 4.5 delta-2b: escalate to the debate orchestrator
        # when both are wired AND the router says DEBATE. On PROCEED
        # we drop the disagreement reason; on ABORT we keep it and
        # thread the orchestrator's reason into the audit trail.
        debate_resolved_disagreement = False
        if (
            cross_check_below_quorum
            and self._debate_orchestrator is not None
            and self._debate_router_config is not None
            and first_proposer_output is not None
        ):
            # Deferred imports break the circular chain:
            # ``debate`` + ``debate_router`` both import ``QualityCandidate``
            # from this module, so importing them at module scope loops.
            from fdai.core.quality_gate.debate import DebateVerdict
            from fdai.core.quality_gate.debate_router import (
                DebateRoute,
                decide_debate_route,
            )

            router_decision = decide_debate_route(
                candidate=candidate,
                cross_check_disagreed=True,
                orchestrator_available=True,
                config=self._debate_router_config,
            )
            reasons.append(f"debate_route:{router_decision.route.value}:{router_decision.reason}")
            if router_decision.route is DebateRoute.DEBATE:
                debate_outcome = await self._debate_orchestrator.run(
                    candidate=candidate,
                    proposer_output=first_proposer_output,
                    known_rule_ids=known,
                    retry_proposer=self._debate_retry_proposer,
                )
                reasons.append(
                    f"debate_outcome:{debate_outcome.verdict.value}:{debate_outcome.reason}"
                )
                if debate_outcome.verdict is DebateVerdict.PROCEED:
                    debate_resolved_disagreement = True

        # 3c. Rubric evaluation (hallucination filter). Runs after the
        # cross-check so it only spends judge tokens on candidates the
        # structural checks did not already reject. The rubric is a
        # *subtractive* filter: it can only lower confidence (via
        # ``min()`` below) or add an abstain reason - it can NEVER raise
        # eligibility above what the deterministic verifier allows. In
        # shadow mode it is judge-and-log only (scores recorded, outcome
        # untouched). See docs/roadmap/hallucination-rubric-gate.md.
        rubric_scores: tuple[RubricScore, ...] = ()
        rubric_min_score: float | None = None
        rubric_verdict_value: str | None = None
        rubric_shadow = self._config.rubric_shadow
        if self._rubric_evaluator is not None:
            from fdai.core.quality_gate.rubric import (
                RubricCriterion,
                RubricVerdict,
                evaluate_rubric_output,
            )

            if not candidate.reasoning_trace.strip():
                # No reasoning to score - faithfulness / coherence cannot
                # be judged, so a "pass" here would be unfounded. Abstain
                # (route to HIL) in enforce mode without spending a judge
                # call; record it in shadow without changing the outcome.
                rubric_verdict_value = RubricVerdict.ABSTAIN.value
                rubric_min_score = 0.0
                if not rubric_shadow:
                    reasons.append("rubric_no_reasoning_trace")
            else:
                try:
                    rubric_output = await self._rubric_evaluator.score(candidate)
                except Exception as exc:  # noqa: BLE001 - fail-closed to HIL
                    # A transport failure / malformed evaluator response MUST
                    # NOT fail open into an eligible outcome. Record the error
                    # and treat it as an abstain signal in enforce mode; in
                    # shadow mode it is recorded but does not change the
                    # outcome (judge-and-log only).
                    rubric_verdict_value = RubricVerdict.ABSTAIN.value
                    rubric_min_score = 0.0
                    if not rubric_shadow:
                        reasons.append(f"rubric_evaluator_error:{type(exc).__name__}")
                else:
                    # Reuse the grounding leg's entailment check (if the
                    # source provides one) so a rubric citation must both
                    # exist AND topically support the candidate - closing
                    # the id-existence-vs-entailment gap.
                    grounding_supports = getattr(self._grounding, "supports", None)
                    rubric_supports = (
                        (lambda rid: grounding_supports(candidate, rid))
                        if grounding_supports is not None
                        else None
                    )
                    # Wiring a rubric requires FULL criterion coverage by
                    # default (the shipped catalog scores all four); a fork
                    # narrows it explicitly via rubric_required_criteria.
                    effective_required = self._config.rubric_required_criteria or tuple(
                        c.value for c in RubricCriterion
                    )
                    rubric_decision = evaluate_rubric_output(
                        rubric_output,
                        known_rule_ids=known,
                        required_criteria=effective_required,
                        known_criteria=tuple(c.value for c in RubricCriterion),
                        supports=rubric_supports,
                    )
                    rubric_scores = rubric_decision.scores
                    rubric_min_score = rubric_decision.min_score
                    rubric_verdict_value = rubric_decision.verdict.value
                    if not rubric_shadow:
                        if rubric_decision.verdict is RubricVerdict.FAIL:
                            reasons.append(
                                f"rubric_failed:{','.join(rubric_decision.failed_criteria)}"
                            )
                        elif rubric_decision.verdict is RubricVerdict.ABSTAIN:
                            reasons.append(f"rubric_abstained:{','.join(rubric_decision.reasons)}")

        # 4. Confidence threshold on the aggregate of verifier / cross-check
        # signals (not model self-report). The rubric min score is folded
        # in via ``min()`` in enforce mode only - subtractive, never
        # additive.
        confidence = candidate.aggregate_confidence
        if rubric_min_score is not None and not rubric_shadow:
            confidence = min(confidence, rubric_min_score)
        if confidence < self._config.confidence_threshold:
            reasons.append(
                f"confidence={confidence:.2f}<threshold={self._config.confidence_threshold:.2f}"
            )

        # Decide outcome
        outcome: QualityOutcome
        if (
            any(r.startswith("cross_check_below_quorum") for r in reasons)
            and not debate_resolved_disagreement
        ):
            outcome = QualityOutcome.DISAGREE
        elif debate_resolved_disagreement and not any(
            r.startswith(
                (
                    "verifier_abstained",
                    "unknown_cited_rule",
                    "ungrounded_citation",
                    "no_grounded_citation",
                    "confidence=",
                    # Any rubric-originated reason (failed / abstained /
                    # no_reasoning_trace / evaluator_error) is a subtractive
                    # signal the debate resolution MUST NOT override.
                    "rubric_",
                )
            )
            for r in reasons
        ):
            outcome = QualityOutcome.ELIGIBLE
        elif reasons and not debate_resolved_disagreement:
            outcome = QualityOutcome.ABSTAIN
        elif reasons:
            # Debate resolved the disagreement but other soft issues
            # remain (e.g. verifier abstained, low confidence). Abstain
            # so the caller routes to HIL rather than auto-executing.
            outcome = QualityOutcome.ABSTAIN
        else:
            outcome = QualityOutcome.ELIGIBLE

        return QualityDecision(
            outcome=outcome,
            candidate=candidate,
            reasons=tuple(reasons),
            grounded_rule_ids=tuple(grounded),
            aggregate_confidence=confidence,
            model_votes=tuple(votes),
            rubric_scores=rubric_scores,
            rubric_min_score=rubric_min_score,
            rubric_verdict=rubric_verdict_value,
            rubric_shadow=rubric_shadow if self._rubric_evaluator is not None else False,
        )

    async def _debate_retry_proposer(
        self,
        candidate: QualityCandidate,
        directive: str,
    ) -> tuple[str, Mapping[str, Any]]:
        """No-directive retry: re-run the first cross-check model.

        Wave 4.5 delta-2b threads the debate orchestrator through the
        QualityGate; the ``CrossCheckModel`` Protocol does not accept a
        directive so the ``retry_proposer`` re-invokes the primary model
        with the same candidate. The directive lives in the debate
        transcript for audit but does not alter the retry call itself.
        The Judge's retry decision therefore acts as a "give the
        Proposer one more chance under the same conditions" gate rather
        than "steer the Proposer toward a specific change". A future
        wave that broadens the Protocol MAY forward the directive; the
        upstream contract stays minimal.
        """

        if not self._models:  # pragma: no cover - constructor enforces >= 1
            raise RuntimeError("no cross-check model available for retry")
        return await self._models[0].propose(candidate)


def quality_decision_audit_fields(decision: QualityDecision) -> dict[str, Any]:
    """Flatten a :class:`QualityDecision` into JSON-safe audit fields.

    The append-only audit log is the source of truth for shadow-mode
    measurement: without the ``rubric_*`` provenance here, a shadow rubric
    records nothing to compute catch / false-positive rates on. A fork's
    control-loop audit writer calls this and merges the result into its
    per-decision audit entry. Contains no secrets or customer values -
    only ids, scores, and enum values.
    """
    return {
        "outcome": decision.outcome.value,
        "aggregate_confidence": decision.aggregate_confidence,
        "reasons": list(decision.reasons),
        "grounded_rule_ids": list(decision.grounded_rule_ids),
        "model_votes": [
            {
                "model_id": v.model_id,
                "proposed_action_type": v.proposed_action_type,
                "agreed": v.agreed,
            }
            for v in decision.model_votes
        ],
        "rubric_verdict": decision.rubric_verdict,
        "rubric_min_score": decision.rubric_min_score,
        "rubric_shadow": decision.rubric_shadow,
        "rubric_scores": [
            {
                "criterion": s.criterion,
                "score": s.score,
                "threshold": s.threshold,
                "passed": s.passed,
                "supporting_rule_ids": list(s.supporting_rule_ids),
            }
            for s in decision.rubric_scores
        ],
    }


__all__ = [
    "CrossCheckModel",
    "GroundingSource",
    "ModelVote",
    "QualityCandidate",
    "QualityDecision",
    "QualityGate",
    "QualityGateConfig",
    "QualityOutcome",
    "VerifierPolicy",
    "quality_decision_audit_fields",
]
