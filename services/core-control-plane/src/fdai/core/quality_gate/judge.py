"""Judge role types + Protocol + pure evaluator (Wave 4.5 alpha).

The Judge is the third and final LLM role in the debate orchestrator.
It receives the Proposer's candidate action **and** the Critic's
:class:`CriticOutput` (from :mod:`fdai.core.quality_gate.critic`)
and issues one of three verdicts: ``accept`` (send the candidate on to
the deterministic verifier), ``revise_and_retry`` (Wave 4.5 caps this
at one retry per event; the orchestrator re-runs the Proposer with the
Critic's objections in the transcript), or ``escalate_hil`` (abort to
HIL, no auto-action).

Like the Critic (Wave 4 alpha), the Judge is shipped **shadow-first**:
the catalog seed at ``rule-catalog/prompts/base/t2-judge.v1.yaml`` is
``default_mode: shadow``. Wave 4.5 beta ships the Azure adapter and
Wave 4.5 gamma wires the :class:`DebateOrchestrator` around it. The
deterministic verifier remains the sole execution authority: a Judge
``accept`` does NOT grant eligibility; only the verifier does.

Design boundaries
-----------------
- **Structured only**: the shipped catalog prompt narrates the JSON
  contract the evaluator enforces (`decision`, `justification`,
  optional `retry_directive`, optional `citations`). Free-form model
  prose in the decision slot is refused.
- **`revise_and_retry` requires a `retry_directive`**. A Judge that
  asks for a retry without saying what to change is a defect - the
  evaluator collapses it to `ESCALATE`.
- **Grounding**: any `citations` entry the Judge references MUST match
  the same rule catalog the Proposer and Critic could have cited. An
  ungrounded citation collapses to `ESCALATE` for the same reason as
  in the Critic evaluator.
- **``core/``-safe**: imports only from ``fdai.core.quality_gate``
  and stdlib. No LLM SDK, no ``delivery.*`` import.

See also
--------
- ``docs/roadmap/decisioning/prompt-composition.md`` § Wave 4.5 - what shipped
- ``docs/roadmap/decisioning/prompt-composition.md`` § Debate orchestrator
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from fdai.core.quality_gate.critic import CriticOutput
from fdai.core.quality_gate.gate import QualityCandidate


class JudgeDecision(StrEnum):
    """Top-level decision the Judge emits after reading the debate transcript."""

    ACCEPT = "accept"
    """Send the Proposer's candidate on to the deterministic verifier
    unchanged. The verifier still has final say - a Judge accept does
    NOT bypass any downstream check."""

    REVISE_AND_RETRY = "revise_and_retry"
    """Ask the Proposer to retry with the Critic's objections in the
    transcript. Wave 4.5 caps this at one retry per event; the
    orchestrator returns :attr:`JudgeVerdict.RETRY` and the second
    Proposer turn is the last."""

    ESCALATE_HIL = "escalate_hil"
    """Abort to human-in-the-loop. No auto-action, no verifier call."""


@dataclass(frozen=True, slots=True)
class JudgeOutput:
    """Structured Judge response for one debate transcript."""

    decision: JudgeDecision
    justification: str
    retry_directive: str | None = None
    """Free-form guidance for the Proposer's retry attempt.
    REQUIRED when ``decision`` is ``REVISE_AND_RETRY`` (the evaluator
    collapses a missing / blank directive to ``ESCALATE``). Ignored
    for ``ACCEPT`` / ``ESCALATE_HIL``."""

    citations: tuple[str, ...] = ()
    """Rule ids the Judge consulted while reading the transcript.
    Grounded against the same catalog the Proposer and Critic used;
    any unknown id collapses the verdict to ``ESCALATE`` in the
    evaluator."""

    confidence_signals: Mapping[str, float] = field(default_factory=dict)
    """Optional derived signals (transcript coherence, citation
    coverage). Follows the "no model self-report" contract."""

    def __post_init__(self) -> None:
        if not self.justification or not self.justification.strip():
            raise ValueError(
                "JudgeOutput.justification MUST be non-empty - the debate "
                "audit trail requires a rendered reason"
            )


class JudgeVerdict(StrEnum):
    """Evaluator's reduction of :class:`JudgeOutput` to one action.

    Consumed by the Wave 4.5 gamma :class:`DebateOrchestrator`. The
    deterministic verifier is still the sole execution authority; a
    ``PROCEED`` verdict tells the orchestrator to hand the candidate
    to the verifier, not to skip it.
    """

    PROCEED = "proceed"
    """Judge accepted; hand the Proposer's candidate to the
    deterministic verifier."""

    RETRY = "retry"
    """Judge asked for a retry AND supplied a directive. Orchestrator
    re-runs the Proposer once with the transcript."""

    ESCALATE = "escalate"
    """Route to HIL. Also returned for a `revise_and_retry` with no
    directive, an unknown citation, or an evaluator-detected
    self-contradiction."""


@runtime_checkable
class JudgeModel(Protocol):
    """DI seam for a Judge implementation.

    Receives the Proposer's ``(action_type, params)`` and the Critic's
    :class:`CriticOutput`, returns a :class:`JudgeOutput`. Kept async
    so a remote model call slots in without changing callers. Wave
    4.5 beta ships the Azure adapter under
    :mod:`fdai.delivery.azure.llm.judge`.
    """

    async def judge(
        self,
        candidate: QualityCandidate,
        proposer_output: tuple[str, Mapping[str, Any]],
        critic_output: CriticOutput,
    ) -> JudgeOutput: ...


# ---------------------------------------------------------------------------
# Pure evaluator
# ---------------------------------------------------------------------------


def evaluate_judge_output(
    output: JudgeOutput,
    *,
    known_rule_ids: Iterable[str],
) -> JudgeVerdict:
    """Reduce a :class:`JudgeOutput` to one of three verdicts.

    Rules:
    - ``ACCEPT`` -> ``PROCEED``, unless any citation is unknown
      (``ESCALATE``);
    - ``REVISE_AND_RETRY`` with a non-blank ``retry_directive`` and
      only known citations -> ``RETRY``;
    - ``REVISE_AND_RETRY`` without a directive -> ``ESCALATE`` (the
      Proposer would not know what to change);
    - ``ESCALATE_HIL`` -> ``ESCALATE``;
    - any citation not in ``known_rule_ids`` collapses the verdict
      to ``ESCALATE`` regardless of decision.
    """

    known = frozenset(known_rule_ids)
    if any(cit not in known for cit in output.citations):
        return JudgeVerdict.ESCALATE
    if output.decision is JudgeDecision.ACCEPT:
        return JudgeVerdict.PROCEED
    if output.decision is JudgeDecision.REVISE_AND_RETRY:
        if output.retry_directive is None or not output.retry_directive.strip():
            return JudgeVerdict.ESCALATE
        return JudgeVerdict.RETRY
    return JudgeVerdict.ESCALATE


__all__ = [
    "JudgeDecision",
    "JudgeModel",
    "JudgeOutput",
    "JudgeVerdict",
    "evaluate_judge_output",
]
