"""DebateOrchestrator - Proposer / Critic / Judge loop (Wave 4.5 gamma).

Orchestrates a two-role debate around one :class:`QualityCandidate`:

1. The Proposer produced the candidate (upstream of this module - the
   T2 :class:`CrossCheckModel.propose` output is what we consume).
2. The :class:`~fdai.core.quality_gate.critic.CriticModel`
   reviews the candidate and emits a
   :class:`~fdai.core.quality_gate.critic.CriticOutput`.
3. The :class:`~fdai.core.quality_gate.judge.JudgeModel` reads
   the transcript and emits a
   :class:`~fdai.core.quality_gate.judge.JudgeOutput`.
4. This orchestrator reduces both role outputs to a single
   :class:`DebateVerdict` the caller consumes.

Wave 4.5 caps ``max_rounds`` at ``1`` - the Judge's
``REVISE_AND_RETRY`` triggers exactly one Proposer re-run (via the
caller-supplied ``retry_proposer`` callback) and the second Judge
turn is terminal. Anything beyond that aborts to HIL.

Design invariants
-----------------
- **Verifier is still the sole execution authority.** A
  :attr:`DebateVerdict.PROCEED` tells the caller to hand the candidate
  to the deterministic verifier next; the orchestrator never grants
  eligibility itself.
- **Fail-closed.** Any exception raised by a role adapter (transport
  failure, malformed JSON, evaluator collapse) surfaces as
  :attr:`DebateVerdict.ABORT` with the reason preserved in the
  :class:`DebateOutcome` audit fields; the caller routes to HIL.
- **Grounding preserved.** The Critic and Judge evaluators both
  refuse ungrounded citations; the orchestrator threads the same
  ``known_rule_ids`` iterable into both.
- **``core/``-safe.** Imports only from ``fdai.core.quality_gate``
  and stdlib. No ``delivery.*`` import, no LLM SDK.

See also
--------
- ``docs/roadmap/decisioning/prompt-composition.md`` § Debate orchestrator
- ``docs/roadmap/decisioning/prompt-composition.md`` § Wave 4.5 - what shipped
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final

from fdai.core.quality_gate.critic import (
    CriticModel,
    CriticOutput,
    CriticVerdict,
    evaluate_critic_output,
)
from fdai.core.quality_gate.gate import QualityCandidate
from fdai.core.quality_gate.judge import (
    JudgeModel,
    JudgeOutput,
    JudgeVerdict,
    evaluate_judge_output,
)

ProposerRetry = Callable[[QualityCandidate, str], Awaitable[tuple[str, Mapping[str, Any]]]]
"""Caller-supplied callback: re-run the Proposer with a Judge
``retry_directive`` in the transcript, and return the new
``(action_type, params)`` tuple. Kept as a plain callable so the
orchestrator does not import the delivery-layer
:class:`AzureOpenAICrossCheckModel` and stays ``core/``-safe."""


class DebateVerdict(StrEnum):
    """Terminal decision the orchestrator emits per event."""

    PROCEED = "proceed"
    """Hand the final Proposer output to the deterministic verifier.
    Carries the outputs of the last accepted turn."""

    ABORT = "abort"
    """Route to HIL. No verifier call. Also emitted when the Critic
    already ABORTs on the first round - no reason to spend Judge
    tokens once the Critic has raised a high-severity objection."""


@dataclass(frozen=True, slots=True)
class DebateOutcome:
    """Structured record of one debate for the caller and audit log.

    ``final_proposer_output`` reflects the Proposer's last accepted
    turn - the original for a first-round proceed, or the retried
    output when the Judge asked for a revision. ``rounds`` counts the
    Proposer turns actually consumed (1 or 2 in Wave 4.5).
    """

    verdict: DebateVerdict
    reason: str
    final_proposer_output: tuple[str, Mapping[str, Any]]
    critic_output: CriticOutput | None = None
    judge_output: JudgeOutput | None = None
    critic_verdict: CriticVerdict | None = None
    judge_verdict: JudgeVerdict | None = None
    rounds: int = 1
    error_class: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DebateOrchestratorConfig:
    """Bounded debate limits per event.

    Wave 4.5 caps ``max_rounds`` at exactly 1 (one Proposer retry
    permitted). Any value > 1 raises at construction so a future
    change to the roadmap is an explicit, reviewable edit.
    """

    max_rounds: int = 1

    def __post_init__(self) -> None:
        if self.max_rounds < 0 or self.max_rounds > 1:
            raise ValueError(f"max_rounds MUST be in [0, 1] for Wave 4.5, got {self.max_rounds}")


class DebateOrchestrator:
    """Coordinate Critic + Judge around a Proposer candidate."""

    def __init__(
        self,
        *,
        critic: CriticModel,
        judge: JudgeModel,
        config: DebateOrchestratorConfig | None = None,
    ) -> None:
        self._critic: Final[CriticModel] = critic
        self._judge: Final[JudgeModel] = judge
        self._config: Final[DebateOrchestratorConfig] = config or DebateOrchestratorConfig()

    async def run(
        self,
        *,
        candidate: QualityCandidate,
        proposer_output: tuple[str, Mapping[str, Any]],
        known_rule_ids: Iterable[str],
        retry_proposer: ProposerRetry | None = None,
    ) -> DebateOutcome:
        """Run one debate around ``proposer_output`` and return the outcome.

        ``retry_proposer`` is required when ``max_rounds >= 1`` - the
        orchestrator refuses to run without it because a Judge
        ``REVISE_AND_RETRY`` could not be honored, which would collapse
        the wire to ABORT for every retry. Passing ``None`` when the
        config allows retries raises :class:`ValueError` at call time.
        """

        if self._config.max_rounds >= 1 and retry_proposer is None:
            raise ValueError(
                "retry_proposer MUST be supplied when max_rounds >= 1 - "
                "the orchestrator cannot honor a Judge revise_and_retry without it"
            )
        known_snapshot = frozenset(known_rule_ids)

        # ---- Round 1 --------------------------------------------------
        try:
            critic_output = await self._critic.critique(candidate, proposer_output)
        except Exception as exc:  # noqa: BLE001 - fail-closed to HIL
            return _outcome_from_error(
                proposer_output=proposer_output,
                reason=f"critic model error: {exc}",
                exc=exc,
            )
        critic_verdict = evaluate_critic_output(critic_output, known_rule_ids=known_snapshot)
        if critic_verdict is CriticVerdict.ABORT:
            return DebateOutcome(
                verdict=DebateVerdict.ABORT,
                reason="critic aborted on high-severity objection",
                final_proposer_output=proposer_output,
                critic_output=critic_output,
                critic_verdict=critic_verdict,
                rounds=1,
            )
        if critic_verdict is CriticVerdict.ABSTAIN:
            return DebateOutcome(
                verdict=DebateVerdict.ABORT,
                reason="critic abstained (ungrounded / empty challenge / abstain stance)",
                final_proposer_output=proposer_output,
                critic_output=critic_output,
                critic_verdict=critic_verdict,
                rounds=1,
            )

        try:
            judge_output = await self._judge.judge(candidate, proposer_output, critic_output)
        except Exception as exc:  # noqa: BLE001 - fail-closed to HIL
            return _outcome_from_error(
                proposer_output=proposer_output,
                reason=f"judge model error: {exc}",
                exc=exc,
                critic_output=critic_output,
                critic_verdict=critic_verdict,
            )
        judge_verdict = evaluate_judge_output(judge_output, known_rule_ids=known_snapshot)

        if judge_verdict is JudgeVerdict.PROCEED:
            return DebateOutcome(
                verdict=DebateVerdict.PROCEED,
                reason="judge accepted",
                final_proposer_output=proposer_output,
                critic_output=critic_output,
                judge_output=judge_output,
                critic_verdict=critic_verdict,
                judge_verdict=judge_verdict,
                rounds=1,
            )
        if judge_verdict is JudgeVerdict.ESCALATE:
            return DebateOutcome(
                verdict=DebateVerdict.ABORT,
                reason="judge escalated to HIL",
                final_proposer_output=proposer_output,
                critic_output=critic_output,
                judge_output=judge_output,
                critic_verdict=critic_verdict,
                judge_verdict=judge_verdict,
                rounds=1,
            )

        # judge_verdict is RETRY here.
        if self._config.max_rounds < 1 or retry_proposer is None:
            return DebateOutcome(
                verdict=DebateVerdict.ABORT,
                reason="judge asked for retry but max_rounds=0 forbids it",
                final_proposer_output=proposer_output,
                critic_output=critic_output,
                judge_output=judge_output,
                critic_verdict=critic_verdict,
                judge_verdict=judge_verdict,
                rounds=1,
            )
        # retry_directive is guaranteed non-blank by evaluate_judge_output
        # returning RETRY.
        directive = judge_output.retry_directive
        assert directive is not None  # noqa: S101 - narrows for mypy

        # ---- Round 2 --------------------------------------------------
        try:
            retried_output = await retry_proposer(candidate, directive)
        except Exception as exc:  # noqa: BLE001 - fail-closed to HIL
            return _outcome_from_error(
                proposer_output=proposer_output,
                reason=f"proposer retry error: {exc}",
                exc=exc,
                critic_output=critic_output,
                critic_verdict=critic_verdict,
                judge_output=judge_output,
                judge_verdict=judge_verdict,
                rounds=1,
            )
        try:
            critic_output_2 = await self._critic.critique(candidate, retried_output)
        except Exception as exc:  # noqa: BLE001 - fail-closed to HIL
            return _outcome_from_error(
                proposer_output=retried_output,
                reason=f"critic model error on retry: {exc}",
                exc=exc,
                judge_output=judge_output,
                judge_verdict=judge_verdict,
                rounds=2,
            )
        critic_verdict_2 = evaluate_critic_output(critic_output_2, known_rule_ids=known_snapshot)
        if critic_verdict_2 in (CriticVerdict.ABORT, CriticVerdict.ABSTAIN):
            return DebateOutcome(
                verdict=DebateVerdict.ABORT,
                reason=f"critic {critic_verdict_2.value} on retry",
                final_proposer_output=retried_output,
                critic_output=critic_output_2,
                judge_output=judge_output,
                critic_verdict=critic_verdict_2,
                judge_verdict=judge_verdict,
                rounds=2,
            )
        try:
            judge_output_2 = await self._judge.judge(candidate, retried_output, critic_output_2)
        except Exception as exc:  # noqa: BLE001 - fail-closed to HIL
            return _outcome_from_error(
                proposer_output=retried_output,
                reason=f"judge model error on retry: {exc}",
                exc=exc,
                critic_output=critic_output_2,
                critic_verdict=critic_verdict_2,
                rounds=2,
            )
        judge_verdict_2 = evaluate_judge_output(judge_output_2, known_rule_ids=known_snapshot)
        if judge_verdict_2 is JudgeVerdict.PROCEED:
            return DebateOutcome(
                verdict=DebateVerdict.PROCEED,
                reason="judge accepted on retry",
                final_proposer_output=retried_output,
                critic_output=critic_output_2,
                judge_output=judge_output_2,
                critic_verdict=critic_verdict_2,
                judge_verdict=judge_verdict_2,
                rounds=2,
            )
        # Any non-PROCEED after round 2 aborts (RETRY on round 2 exceeds
        # max_rounds=1 by construction).
        return DebateOutcome(
            verdict=DebateVerdict.ABORT,
            reason=f"judge {judge_verdict_2.value} after retry (max_rounds exhausted)",
            final_proposer_output=retried_output,
            critic_output=critic_output_2,
            judge_output=judge_output_2,
            critic_verdict=critic_verdict_2,
            judge_verdict=judge_verdict_2,
            rounds=2,
        )


def _outcome_from_error(
    *,
    proposer_output: tuple[str, Mapping[str, Any]],
    reason: str,
    exc: BaseException,
    critic_output: CriticOutput | None = None,
    critic_verdict: CriticVerdict | None = None,
    judge_output: JudgeOutput | None = None,
    judge_verdict: JudgeVerdict | None = None,
    rounds: int = 1,
) -> DebateOutcome:
    return DebateOutcome(
        verdict=DebateVerdict.ABORT,
        reason=reason,
        final_proposer_output=proposer_output,
        critic_output=critic_output,
        judge_output=judge_output,
        critic_verdict=critic_verdict,
        judge_verdict=judge_verdict,
        rounds=rounds,
        error_class=type(exc).__name__,
    )


__all__ = [
    "DebateOrchestrator",
    "DebateOrchestratorConfig",
    "DebateOutcome",
    "DebateVerdict",
    "ProposerRetry",
]
