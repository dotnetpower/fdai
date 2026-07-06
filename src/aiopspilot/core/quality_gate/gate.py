"""LLM quality gate — guards T2 output before it reaches the risk-gate.

Phase 2 quality gate (see
[`docs/roadmap/phases/phase-2-quality-and-t1.md § LLM Quality Gate`]).

T2 inputs are **untrusted**; the verifier + policy re-check are the
authority, not model text. The gate composes three independent checks —
**mixed-model cross-check**, **deterministic verifier**, and
**grounding (RAG citation) validator** — plus a **confidence threshold**
derived from verifier / cross-check signals (not the model's self-report).

Outcomes are typed and audited:

- ``eligible`` — verifier passed, cross-check agreed, grounding validated,
  confidence above threshold. The risk-gate MAY consider auto-execution.
- ``abstain`` — grounding unavailable, verifier abstained, or confidence
  below threshold. Route to HIL, no auto-action.
- ``disagree`` — cross-check disagreement. Escalate to HIL, do NOT
  auto-resolve.
- ``deny`` — verifier explicitly rejected the candidate. No execution.

Public shape
------------

The gate itself is a small orchestrator built from three Protocols so a
fork can swap any leg (real LLM cross-check, remote verifier, custom
grounding source) without editing ``core/``. The upstream default
in-memory implementations under
:mod:`~aiopspilot.core.quality_gate.testing` produce a deterministic
outcome from the injected candidate and are used by every test in this
suite plus the P1 e2e replay when a T2 stage is exercised.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from aiopspilot.shared.contracts.models import Rule


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
    ``cited_rule_ids`` MUST be citations from the rule catalog — the
    grounding validator checks each against the loaded catalog and the
    resource context.

    ``confidence_signals`` is a dict of derived confidences (retrieval
    coverage, verifier margin, precondition-check pass rate). The gate's
    ``confidence_threshold`` is compared against a single aggregate
    :attr:`aggregate_confidence`; the model's own self-report is NEVER
    passed here — that's the anti-pattern the gate closes.
    """

    action_type: str
    target_resource_ref: str
    params: dict[str, Any]
    cited_rule_ids: tuple[str, ...]
    confidence_signals: Mapping[str, float] = field(default_factory=dict)

    @property
    def aggregate_confidence(self) -> float:
        """Mean of the derived signals; 0.0 when none are supplied.

        ``bool`` values are excluded even though they subtype ``int``:
        confidence signals are numeric floats, and letting ``True`` pass
        as ``1.0`` would silently inflate the aggregate.
        """
        if not self.confidence_signals:
            return 0.0
        values = [
            float(v)
            for v in self.confidence_signals.values()
            if isinstance(v, (int, float)) and not isinstance(v, bool)
        ]
        if not values:
            return 0.0
        return sum(values) / len(values)


@dataclass(frozen=True, slots=True)
class QualityDecision:
    """Frozen record produced by :meth:`QualityGate.evaluate`."""

    outcome: QualityOutcome
    candidate: QualityCandidate
    reasons: tuple[str, ...] = field(default_factory=tuple)
    grounded_rule_ids: tuple[str, ...] = field(default_factory=tuple)
    aggregate_confidence: float = 0.0


# ---------------------------------------------------------------------------
# DI seams (Protocols) — a fork implements these with real LLM clients
# ---------------------------------------------------------------------------


@runtime_checkable
class CrossCheckModel(Protocol):
    """One frontier model used for a cross-check vote.

    ``propose`` returns the ActionType id + parameter subset the model
    would emit for the given candidate context. Real implementations
    call a remote LLM under a bounded timeout; the fake in
    :mod:`~aiopspilot.core.quality_gate.testing` returns a deterministic
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
    vendors/weights) — see phase-2 § Quality Gate."""


class QualityGate:
    """Compose verifier + cross-check + grounding + threshold checks."""

    def __init__(
        self,
        *,
        verifier: VerifierPolicy,
        cross_check_models: tuple[CrossCheckModel, ...],
        grounding: GroundingSource,
        config: QualityGateConfig | None = None,
    ) -> None:
        cfg = config or QualityGateConfig()
        if not 0.0 <= cfg.confidence_threshold <= 1.0:
            raise ValueError("confidence_threshold MUST be in [0.0, 1.0]")
        if cfg.require_cross_check_quorum < 1:
            raise ValueError("require_cross_check_quorum MUST be >= 1")
        if len(cross_check_models) < cfg.require_cross_check_quorum:
            raise ValueError("not enough cross-check models registered for the configured quorum")
        self._verifier = verifier
        self._models = cross_check_models
        self._grounding = grounding
        self._config = cfg

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
        # :class:`~aiopspilot.core.quality_gate.rag_grounding.RagGroundingSource`)
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
        for model in self._models:
            proposed_type, _params = await model.propose(candidate)
            if proposed_type == candidate.action_type:
                agree += 1
        if agree < self._config.require_cross_check_quorum:
            reasons.append(
                f"cross_check_below_quorum:agree={agree}<"
                f"quorum={self._config.require_cross_check_quorum}"
            )

        # 4. Confidence threshold on the aggregate of verifier / cross-check
        # signals (not model self-report).
        confidence = candidate.aggregate_confidence
        if confidence < self._config.confidence_threshold:
            reasons.append(
                f"confidence={confidence:.2f}<threshold={self._config.confidence_threshold:.2f}"
            )

        # Decide outcome
        outcome: QualityOutcome
        if any(r.startswith("cross_check_below_quorum") for r in reasons):
            outcome = QualityOutcome.DISAGREE
        elif reasons:
            outcome = QualityOutcome.ABSTAIN
        else:
            outcome = QualityOutcome.ELIGIBLE

        return QualityDecision(
            outcome=outcome,
            candidate=candidate,
            reasons=tuple(reasons),
            grounded_rule_ids=tuple(grounded),
            aggregate_confidence=confidence,
        )


__all__ = [
    "CrossCheckModel",
    "GroundingSource",
    "QualityCandidate",
    "QualityDecision",
    "QualityGate",
    "QualityGateConfig",
    "QualityOutcome",
    "VerifierPolicy",
]
