"""Critic role types + Protocol + pure evaluator (Wave 4 alpha).

The Critic is a second LLM role that reviews the Proposer's candidate
action **before** the deterministic verifier runs. It emits structured
:class:`CriticObjection` records (severity, cited rule, alternate
action) - never free-form text - so the downstream
:class:`~fdai.core.quality_gate.gate.QualityGate` and the Wave
4.5 debate orchestrator can dispatch on the shape without parsing
model prose. The verifier remains the sole execution authority: a
Critic that says "AGREE" does NOT grant eligibility, and a Critic
that says "CHALLENGE" does NOT block a deterministic verify-pass on
its own - it only surfaces objections the orchestrator threads into
the audit trail and (in Wave 4.5) into a Proposer retry.

Design boundaries
-----------------
- **Shadow-first**: the shipped catalog seed
  (``rule-catalog/prompts/base/t2-critic.v1.yaml``) is
  ``default_mode: shadow``, so this module lives in ``core/`` without
  any live gate wiring. Wave 4.5 wires the debate orchestrator; Wave
  4 alpha just ships the types + evaluator so shadow-mode probes and
  a fork's early experimentation can consume them.
- **Structured only**: :class:`CriticOutput` refuses model prose in
  the ``objections`` slot; each objection carries a severity, a
  cited rule id (grounded against the same catalog the Proposer used),
  and an optional alternate ``action_type``. The evaluator rejects an
  ``AGREE`` that contains any high-severity objection - a
  self-contradictory Critic is not a signal we honor.
- **``core/``-safe**: imports only from ``fdai.core.quality_gate``
  and stdlib. No LLM SDK, no ``delivery.*`` import; the concrete
  Azure-OpenAI Critic adapter lands in Wave 4.5 in
  ``delivery/azure/llm/``.

See also
--------
- ``docs/roadmap/decisioning/prompt-composition.md`` § Wave 4 - what shipped
- ``docs/roadmap/decisioning/prompt-composition.md`` § Debate orchestrator
  (Proposer / Critic / Judge)
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final, Protocol, runtime_checkable

from fdai.core.quality_gate.gate import QualityCandidate


class CriticStance(StrEnum):
    """Top-level opinion the Critic emits about the Proposer's candidate.

    Kept intentionally coarse - fine-grained "why" lives on the
    :class:`CriticObjection` list. A stance without matching objections
    is a smell the evaluator flags (see :class:`CriticVerdict`).
    """

    AGREE = "agree"
    """The Critic endorses the candidate as-is. Objections list is
    expected to be empty; a non-empty list at ``AGREE`` triggers a
    self-contradiction abstain in the evaluator."""

    CHALLENGE = "challenge"
    """The Critic objects to the candidate. Objections list MUST be
    non-empty; the orchestrator threads them into either a Proposer
    retry (Wave 4.5) or an audit-log entry (Wave 4 alpha)."""

    ABSTAIN = "abstain"
    """The Critic could not form an opinion (unclear grounding,
    missing context). Routes to HIL in the future orchestrator;
    never auto-honored as approval."""


class CriticSeverity(StrEnum):
    """Per-objection severity - drives orchestrator retry vs abstain."""

    LOW = "low"
    """Non-blocking nit; the orchestrator may proceed but records the
    objection in the audit trail."""

    MEDIUM = "medium"
    """The orchestrator MUST address the objection (Wave 4.5: retry
    once with the objection in the transcript)."""

    HIGH = "high"
    """The orchestrator MUST NOT proceed to the verifier; the run
    aborts to HIL. Also the value that makes an ``AGREE`` self-
    contradictory in :func:`evaluate_critic_output`."""


@dataclass(frozen=True, slots=True)
class CriticObjection:
    """One structured objection the Critic raises.

    ``cited_rule_id`` MUST be a rule the Proposer or the Critic could
    have grounded against (the evaluator checks it against the
    grounded rule set the caller supplies). Free-form text without a
    citation is refused at construction time; the invariant matches
    the ``require_grounding`` rule in
    :class:`~fdai.core.quality_gate.gate.QualityGateConfig`.
    """

    severity: CriticSeverity
    cited_rule_id: str
    description: str
    alt_action_type: str | None = None
    """Optional replacement ActionType the Critic suggests the
    Proposer retry with. Never a params payload - the Critic never
    proposes concrete parameters, only names an alternate action."""

    def __post_init__(self) -> None:
        if not self.cited_rule_id or not self.cited_rule_id.strip():
            raise ValueError(
                "CriticObjection.cited_rule_id MUST be non-empty - ungrounded "
                "objections are refused per require_grounding"
            )
        if not self.description or not self.description.strip():
            raise ValueError("CriticObjection.description MUST be non-empty")


@dataclass(frozen=True, slots=True)
class CriticOutput:
    """Structured Critic response for one Proposer candidate."""

    stance: CriticStance
    objections: tuple[CriticObjection, ...] = ()
    citations: tuple[str, ...] = ()
    """Additional rule citations the Critic consulted (beyond the ones
    on individual objections). Threaded into the audit trail; the
    evaluator does NOT require this to be non-empty."""

    confidence_signals: Mapping[str, float] = field(default_factory=dict)
    """Optional Critic-side signals (retrieval coverage, verifier-margin
    estimates). Follows the same "no model self-report" contract as
    :attr:`~fdai.core.quality_gate.gate.QualityCandidate.confidence_signals`."""


class CriticVerdict(StrEnum):
    """Evaluator's opinion of the :class:`CriticOutput`.

    The verdict tells the orchestrator what to do; the deterministic
    verifier is still the sole execution authority regardless of
    verdict. In Wave 4 alpha this is consumed only by tests and
    fork-authored probes; Wave 4.5 threads it into the debate loop.
    """

    ENDORSE = "endorse"
    """AGREE with no high-severity contradictions - the orchestrator
    proceeds to the deterministic verifier."""

    RETRY = "retry"
    """CHALLENGE with medium-severity objections - Wave 4.5's
    orchestrator will retry the Proposer once with the transcript
    included."""

    ABORT = "abort"
    """CHALLENGE with a high-severity objection, OR an AGREE that
    contains high-severity objections (self-contradiction). The
    orchestrator MUST route to HIL; no auto-action."""

    ABSTAIN = "abstain"
    """ABSTAIN stance, or unresolvable evaluator error (unknown
    citation, empty CHALLENGE objection list). Routes to HIL."""


@runtime_checkable
class CriticModel(Protocol):
    """DI seam for a Critic implementation.

    A real Critic calls an LLM under a bounded timeout, receives the
    Proposer's ``(action_type, params)``, and returns a
    :class:`CriticOutput`. Test fakes under
    :mod:`~fdai.core.quality_gate.testing` (Wave 4.5) return
    deterministic outputs seeded by the candidate. Kept ``async`` so
    a remote model call slots in without changing callers.
    """

    async def critique(
        self,
        candidate: QualityCandidate,
        proposer_output: tuple[str, Mapping[str, Any]],
    ) -> CriticOutput: ...


# ---------------------------------------------------------------------------
# Pure evaluator
# ---------------------------------------------------------------------------


_HIGH_SEVERITY: Final[frozenset[CriticSeverity]] = frozenset({CriticSeverity.HIGH})


def evaluate_critic_output(
    output: CriticOutput,
    *,
    known_rule_ids: Iterable[str],
) -> CriticVerdict:
    """Reduce a :class:`CriticOutput` to one of four verdicts.

    ``known_rule_ids`` is the rule set the Proposer (and the Critic)
    could have cited - typically the return value of
    :meth:`GroundingSource.known_rule_ids`.
    Any objection carrying an unknown citation collapses the verdict
    to :attr:`CriticVerdict.ABSTAIN` because the orchestrator cannot
    thread an ungrounded objection into the audit trail without
    breaking the grounding invariant.

    Rules:
    - ``ABSTAIN`` stance -> ``ABSTAIN`` verdict (short-circuits, no
      objection checks).
    - ``AGREE`` with any high-severity objection -> ``ABORT`` (self-
      contradiction; a Critic that agrees but flags a high-severity
      issue is not honored).
    - ``AGREE`` with no high-severity objections -> ``ENDORSE``.
    - ``CHALLENGE`` with an empty objections list -> ``ABSTAIN`` (a
      challenge without evidence is a defect, not a signal).
    - ``CHALLENGE`` with any unknown-rule citation -> ``ABSTAIN``.
    - ``CHALLENGE`` with any high-severity objection -> ``ABORT``.
    - ``CHALLENGE`` otherwise -> ``RETRY``.
    """

    if output.stance is CriticStance.ABSTAIN:
        return CriticVerdict.ABSTAIN

    known = frozenset(known_rule_ids)
    has_high = any(obj.severity in _HIGH_SEVERITY for obj in output.objections)

    if output.stance is CriticStance.AGREE:
        return CriticVerdict.ABORT if has_high else CriticVerdict.ENDORSE

    # CHALLENGE from here on.
    if not output.objections:
        return CriticVerdict.ABSTAIN
    if any(obj.cited_rule_id not in known for obj in output.objections):
        return CriticVerdict.ABSTAIN
    if has_high:
        return CriticVerdict.ABORT
    return CriticVerdict.RETRY


__all__ = [
    "CriticModel",
    "CriticObjection",
    "CriticOutput",
    "CriticSeverity",
    "CriticStance",
    "CriticVerdict",
    "evaluate_critic_output",
]
