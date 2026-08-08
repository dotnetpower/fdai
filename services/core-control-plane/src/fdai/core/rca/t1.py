"""T1 correlation root-cause analysis.

The middle tier of RCA (observability-and-detection.md section 4),
between T0 (a matched rule names the direct cause) and T2 (grounded LLM
reasoning for a novel case). T1 is **deterministic correlation**: given
the events correlated into one incident, it reconstructs the most
probable **causal chain** from an antecedent change / mutation to the
observed failure - the "a deploy went out, then the error rate rose"
chain an on-call engineer rebuilds by hand.

The reconstruction itself lives in
:mod:`fdai.core.rca.causal_chain` (multi-hop, dependency-aware,
ambiguity-discounted). This module is the thin T1 entry point: it drives
the analyzer with a per-call config and converts the resulting chain into
a grounded :class:`RootCauseHypothesis`.

No model call. The hypothesis is grounded on the chain's events and is
deterministic (the same event set always yields the same cause). Because
correlation is not proof, confidence is bounded below ``1.0`` and the tier
**abstains** (returns ``None``) when no change-rooted chain exists in the
window - handing the case to T2 rather than guessing.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta

from fdai.core.rca.causal_chain import (
    CausalChainAnalyzer,
    CausalChainConfig,
    CorrelatedEvent,
    Relationship,
    chain_to_hypothesis,
)
from fdai.core.rca.contract import RootCauseHypothesis


def t1_causal_chain(
    *,
    failure_event_id: str,
    failure_at: datetime,
    failure_resource_ref: str,
    correlated_events: Sequence[CorrelatedEvent],
    window: timedelta,
    same_resource_only: bool = False,
    depends_on: Mapping[str, Iterable[str]] | None = None,
    max_hops: int = 4,
) -> RootCauseHypothesis | None:
    """Return a T1 correlation hypothesis, or ``None`` when none is plausible.

    Reconstructs the most probable **causal chain** ending at the failure:
    the closest antecedent change is the primary trigger, and when a
    dependency graph and intermediate symptoms are supplied the chain
    extends backward through them (``root change -> symptom -> failure``).
    The root MUST be a change; a window of pure symptoms with no antecedent
    change abstains to T2.

    When ``same_resource_only`` is set, only changes on the failing
    resource itself are considered; otherwise a correlated resource's
    change qualifies (cross-resource causation, e.g. a shared dependency
    deploy). Supplying ``depends_on`` (resource ref -> the refs it depends
    on) makes cross-resource links dependency-aware: a change on a resource
    the failure depends on outranks an unrelated one, and - once a graph is
    given - an unrelated resource cannot link at all.

    Confidence scales with temporal proximity, relationship strength, and
    the absence of competing antecedents, bounded to the T1 band. Ties are
    broken deterministically so the result is reproducible.
    """
    if window <= timedelta(0):
        return None
    if max_hops < 1:
        return None

    config = CausalChainConfig(
        window=window,
        depends_on=_freeze_graph(depends_on),
        max_hops=max_hops,
    )
    chain = CausalChainAnalyzer(config).reconstruct(
        failure_event_id=failure_event_id,
        failure_at=failure_at,
        failure_resource_ref=failure_resource_ref,
        correlated_events=correlated_events,
        same_resource_only=same_resource_only,
    )
    if chain is None:
        return None
    return chain_to_hypothesis(chain, failure_resource_ref=failure_resource_ref)


def _freeze_graph(
    depends_on: Mapping[str, Iterable[str]] | None,
) -> dict[str, frozenset[str]]:
    """Normalize a caller-supplied dependency graph into the frozen shape
    the analyzer config expects (empty when ``None``)."""
    if not depends_on:
        return {}
    return {resource: frozenset(deps) for resource, deps in depends_on.items()}


__all__ = ["CorrelatedEvent", "Relationship", "t1_causal_chain"]
