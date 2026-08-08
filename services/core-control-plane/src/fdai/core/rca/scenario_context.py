"""Chaos-scenario context for RCA candidate citations.

Given a live incident's symptom `(signal_id, target_type, severity)`,
this module returns the catalog scenarios that would produce the same
symptom - projected as :class:`~fdai.core.rca.contract.Citation`
values with :attr:`~fdai.core.rca.contract.CitationKind.SCENARIO` so the
T2 reasoner can consider them as candidate causes.

Design intent (see docs/internals/sre-scenario-library-scaling.md
"Symptom index for O(1) lookup"):

- Runtime call site is
  :meth:`fdai.core.rca.coordinator.RcaCoordinator.analyze_t2`; the
  caller assembles the ``candidate_citations`` tuple, and the reasoner
  cannot cite anything outside that set.
- Scenario citations are *hypotheses*, not authorization. The reasoner
  proposes a cause; the pipeline (verifier + risk gate) still decides
  whether an action can execute - a scenario id in a citation is a
  pointer to why the loop believes X, not a permission to do X.
- The lookup uses the widening path (exact -> drop severity -> drop
  target) so a router matches a live incident whose target is a
  fork-only name the catalog does not know about; the caller can cap
  the widened set with ``max_candidates``.

This module deliberately never imports from `fdai.delivery.*` and
never calls anything remote - it is a pure fan-out from the compiled
symptom index into RCA citations.
"""

from __future__ import annotations

from collections.abc import Iterable

from fdai.core.chaos.symptom_index import ScenarioRef, SymptomIndex
from fdai.core.rca.contract import Citation, CitationKind


def candidate_scenarios(
    index: SymptomIndex,
    *,
    signal: str,
    target_type: str,
    severity: str,
    max_candidates: int = 8,
    include_needs_injector: bool = True,
) -> tuple[Citation, ...]:
    """Return `Citation(SCENARIO, scenario_id)` for matching scenarios.

    Uses :meth:`SymptomIndex.lookup_widening` (exact -> drop severity ->
    drop target), preserving the index's stable sort by scenario id so
    the citation set is deterministic across process restarts.

    ``max_candidates`` caps the fan-out so a router does not turn one
    incident into hundreds of citations (which would waste the T2
    context window and dilute grounding).

    ``include_needs_injector`` controls whether scenarios awaiting an
    injector implementation (``injector: needs-injector``) are surfaced.
    They are legitimate reasoning candidates - the loop can still say
    "this looks like an AWS FIS `ec2-stop-instances` pattern" without
    being able to inject it - but a caller that only wants
    directly-actionable candidates can set this False.
    """
    if not signal:
        raise ValueError("signal MUST be non-empty")
    if max_candidates <= 0:
        raise ValueError("max_candidates MUST be positive")
    refs: Iterable[ScenarioRef] = index.lookup_widening(
        signal=signal, target_type=target_type, severity=severity
    )
    if not include_needs_injector:
        refs = (r for r in refs if r.injector != "needs-injector")
    picked: list[Citation] = []
    for ref in refs:
        picked.append(Citation(kind=CitationKind.SCENARIO, ref=ref.id))
        if len(picked) >= max_candidates:
            break
    return tuple(picked)


def scenario_summary(
    index: SymptomIndex,
    *,
    signal: str,
    target_type: str,
    severity: str,
    max_candidates: int = 8,
) -> str:
    """Compact prose summary of the candidate scenarios for a symptom.

    Consumers pass this to the T2 reasoner alongside the
    :func:`candidate_scenarios` citation set: the reasoner sees
    "here are the scenarios the catalog says produce this symptom;
    the citations you may reference are their ids". No scenario body
    is leaked - only ``(id, category, injector-family, gpu?)`` per
    line so the reasoner cannot cite anything invented.
    """
    refs = index.lookup_widening(signal=signal, target_type=target_type, severity=severity)
    if not refs:
        return (
            f"no catalog scenario matches signal={signal} target={target_type} severity={severity}"
        )
    lines: list[str] = [
        f"candidate scenarios for signal={signal} target={target_type} severity={severity}:"
    ]
    for ref in refs[:max_candidates]:
        family = (
            ref.injector.split(":", 1)[0] if ref.injector != "needs-injector" else "needs-injector"
        )
        gpu = f" gpu={ref.gpu_domain}" if ref.gpu_domain else ""
        hw = " requires_hardware" if ref.requires_hardware else ""
        lines.append(f"- {ref.id} category={ref.category} injector_family={family}{gpu}{hw}")
    if len(refs) > max_candidates:
        lines.append(f"- ... and {len(refs) - max_candidates} more (capped by max_candidates)")
    return "\n".join(lines)


__all__ = [
    "candidate_scenarios",
    "scenario_summary",
]
