"""Precise temporal causal-chain reconstruction for T1 RCA.

The deterministic engine behind T1 correlation cause
([observability-and-detection.md](../../../../docs/roadmap/observability-and-detection.md)
section 4, path b): reconstruct the **multi-hop causal chain** from a
root change to an observed failure - the "a config change went out on the
database, then replica lag rose, then the app error rate rose" chain an
on-call engineer rebuilds by hand.

What makes it *precise* (beyond a single "closest antecedent" lookup):

- **Multi-hop**: a chain is ``root_change -> symptom -> ... -> failure``,
  each hop a temporal antecedent within a bounded window. The **root MUST
  be a change** (a mutation can cause; a symptom only propagates), so a
  storm of pure symptoms with no antecedent change **abstains** to T2.
- **Dependency-aware**: when a resource-dependency graph is supplied, a
  change on a resource the failing resource *depends on* (directly or
  transitively, bounded depth) outranks an unrelated resource's change,
  and an unrelated resource cannot link at all. With no graph the engine
  stays permissive (any correlated resource may link) - preserving the
  cross-resource default.
- **Ambiguity-discounted**: when several distinct roots explain the
  failure about equally well, confidence is *reduced* (we are less sure
  which is the true trigger) and the count is recorded - a single clean
  antecedent scores high, a confounded window scores low.
- **Deterministic**: strict temporal precedence makes the event set a
  DAG; every tie is broken by a total order, so the same events always
  yield the same chain (deterministic replay).

No model call. Confidence is bounded to the T1 band ``[0.35, 0.85]`` - a
temporal antecedent is a strong hint, never T0-style certainty - and the
engine returns ``None`` (abstain, defer to T2) when no change-rooted
chain exists.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from fdai.core.rca.contract import (
    Citation,
    CitationKind,
    RcaTier,
    RootCauseHypothesis,
)

# Correlation confidence is deliberately capped: a temporal antecedent is
# a strong hint, not a proof, so T1 never claims T0-style certainty. The
# floor keeps a weak (far-apart) correlation from looking authoritative.
_MAX_CONFIDENCE = 0.85
_MIN_CONFIDENCE = 0.35


class Relationship(StrEnum):
    """How a cause event's resource relates to an effect event's resource."""

    SAME_RESOURCE = "same-resource"
    """Cause and effect touch the same resource - the most direct link."""

    DEPENDENCY = "dependency"
    """Cause is on a resource the effect directly depends on."""

    TRANSITIVE_DEPENDENCY = "transitive-dependency"
    """Cause is on a resource the effect depends on indirectly (>= 2 hops
    in the dependency graph, within the configured depth)."""

    UNSCOPED = "unscoped"
    """No dependency graph configured - a permissive cross-resource link
    (the correlation window is the only evidence they belong together)."""


@dataclass(frozen=True, slots=True)
class CorrelatedEvent:
    """One member event of an incident, trimmed to what T1 RCA needs.

    ``is_change`` marks a mutation/deploy/config-change event - the class
    of antecedent that can *cause* a downstream failure (a symptom only
    propagates one). ``resource_ref`` is an opaque, generic reference
    (never a raw payload or secret). ``change_kind`` is an optional,
    generic label (e.g. ``deploy``, ``config``, ``scale``) a fork may use
    to weight some change classes as more causal than others; ``None``
    means unweighted.
    """

    event_id: str
    at: datetime
    resource_ref: str
    is_change: bool
    change_kind: str | None = None


@dataclass(frozen=True, slots=True)
class CausalHop:
    """One link in a reconstructed causal chain: cause -> effect."""

    cause_event_id: str
    effect_event_id: str
    cause_resource_ref: str
    effect_resource_ref: str
    lead: timedelta
    relationship: Relationship
    confidence: float


@dataclass(frozen=True, slots=True)
class CausalChain:
    """A reconstructed causal chain from a root change to the failure.

    ``hops`` are ordered root -> ... -> failure. ``confidence`` is the
    banded T1 confidence for the whole chain (weakest-link aggregate,
    ambiguity-discounted). ``ambiguity`` is the number of distinct roots
    that explained the failure about equally well (1 == a single clean
    antecedent).
    """

    root_event_id: str
    failure_event_id: str
    hops: tuple[CausalHop, ...]
    confidence: float
    ambiguity: int

    @property
    def event_ids(self) -> tuple[str, ...]:
        """Every event in the chain, root -> ... -> failure, deduplicated
        while preserving order."""
        ordered: list[str] = [self.root_event_id]
        for hop in self.hops:
            if hop.effect_event_id not in ordered:
                ordered.append(hop.effect_event_id)
        return tuple(ordered)

    @property
    def resource_path(self) -> tuple[str, ...]:
        """The resource each event in the chain touched, root -> failure."""
        if not self.hops:
            return ()
        path = [self.hops[0].cause_resource_ref]
        for hop in self.hops:
            path.append(hop.effect_resource_ref)
        return tuple(path)


@dataclass(frozen=True, slots=True)
class CausalChainConfig:
    """Configuration for :class:`CausalChainAnalyzer`.

    Every knob is data, never hard-coded in the traversal, so a fork
    tunes precision via config (never by editing core). ``depends_on``
    maps a resource ref to the set of resource refs it *depends on*; an
    empty map means "no topology" and the analyzer stays permissive
    (cross-resource links allowed, scored ``UNSCOPED``).
    """

    window: timedelta
    depends_on: Mapping[str, frozenset[str]] = field(default_factory=dict)
    max_hops: int = 4
    transitive_depth: int = 3
    relationship_weights: Mapping[Relationship, float] = field(
        default_factory=lambda: {
            Relationship.SAME_RESOURCE: 1.0,
            Relationship.DEPENDENCY: 0.9,
            Relationship.TRANSITIVE_DEPENDENCY: 0.7,
            Relationship.UNSCOPED: 0.85,
        }
    )
    change_kind_weights: Mapping[str, float] = field(default_factory=dict)
    default_change_weight: float = 1.0
    symptom_propagation_weight: float = 0.9
    ambiguity_epsilon: float = 0.05
    ambiguity_discount: float = 0.85

    def __post_init__(self) -> None:
        if self.window <= timedelta(0):
            raise ValueError("CausalChainConfig.window MUST be positive")
        if self.max_hops < 1:
            raise ValueError("CausalChainConfig.max_hops MUST be >= 1")
        if self.transitive_depth < 1:
            raise ValueError("CausalChainConfig.transitive_depth MUST be >= 1")
        if not 0.0 <= self.ambiguity_epsilon <= 1.0:
            raise ValueError("CausalChainConfig.ambiguity_epsilon MUST be in [0, 1]")
        if not 0.0 < self.ambiguity_discount <= 1.0:
            raise ValueError("CausalChainConfig.ambiguity_discount MUST be in (0, 1]")
        for name, weight in (
            ("default_change_weight", self.default_change_weight),
            ("symptom_propagation_weight", self.symptom_propagation_weight),
        ):
            if not 0.0 <= weight <= 1.0:
                raise ValueError(f"CausalChainConfig.{name} MUST be in [0, 1]")


@dataclass(frozen=True, slots=True)
class _PartialChain:
    """An internal, unbanded chain candidate during traversal.

    ``score`` is the raw weakest-link aggregate in ``[0, 1]`` (banding and
    the ambiguity discount are applied once, at the top level).
    """

    hops: tuple[CausalHop, ...]
    score: float
    root_event_id: str
    root_same_resource: bool


class CausalChainAnalyzer:
    """Reconstruct the most probable causal chain ending at a failure."""

    def __init__(self, config: CausalChainConfig) -> None:
        self._config = config

    # -- public API --------------------------------------------------------

    def reconstruct(
        self,
        *,
        failure_event_id: str,
        failure_at: datetime,
        failure_resource_ref: str,
        correlated_events: Sequence[CorrelatedEvent],
        same_resource_only: bool = False,
    ) -> CausalChain | None:
        """Return the best change-rooted chain, or ``None`` to abstain.

        Deterministic: the same events always yield the same chain,
        regardless of input order. Returns ``None`` when no antecedent
        **change** can be linked to the failure within the window - the
        case defers to T2 rather than guessing.
        """
        failure = CorrelatedEvent(
            event_id=failure_event_id,
            at=failure_at,
            resource_ref=failure_resource_ref,
            is_change=False,
        )
        # De-duplicate by event id (first occurrence wins for determinism)
        # and drop the failure's own self-event - it can never cause itself.
        pool: dict[str, CorrelatedEvent] = {}
        for event in correlated_events:
            if event.event_id == failure_event_id:
                continue
            pool.setdefault(event.event_id, event)
        events = tuple(pool.values())
        if not events:
            return None

        memo: dict[tuple[str, int], _PartialChain | None] = {}
        top_options = self._chains_into(
            target=failure,
            events=events,
            budget=self._config.max_hops,
            same_resource_only=same_resource_only,
            memo=memo,
        )
        if not top_options:
            return None

        best = self._pick_best(top_options)
        ambiguity = self._count_ambiguity(best, top_options)
        confidence = self._band(self._discount(best.score, ambiguity))
        return CausalChain(
            root_event_id=best.root_event_id,
            failure_event_id=failure_event_id,
            hops=best.hops,
            confidence=confidence,
            ambiguity=ambiguity,
        )

    # -- traversal ---------------------------------------------------------

    def _chains_into(
        self,
        *,
        target: CorrelatedEvent,
        events: tuple[CorrelatedEvent, ...],
        budget: int,
        same_resource_only: bool,
        memo: dict[tuple[str, int], _PartialChain | None],
    ) -> list[_PartialChain]:
        """Every valid change-rooted chain ending at ``target`` within
        ``budget`` hops. Only the *best* per distinct root is kept (that is
        all the caller needs for selection and ambiguity counting)."""
        if budget < 1:
            return []
        best_by_root: dict[str, _PartialChain] = {}
        for cand in self._antecedents(target, events, same_resource_only):
            rel = self._relationship(cand.resource_ref, target.resource_ref, same_resource_only)
            if rel is None:
                continue
            hop = self._hop(cause=cand, effect=target, relationship=rel)
            # Option A: the candidate is itself the root (only a change may
            # root a chain).
            if cand.is_change:
                self._offer(
                    best_by_root,
                    _PartialChain(
                        hops=(hop,),
                        score=hop.confidence,
                        root_event_id=cand.event_id,
                        root_same_resource=cand.resource_ref == target.resource_ref,
                    ),
                )
            # Option B: extend a chain that already reaches the candidate
            # (the candidate is an intermediate change or symptom).
            for sub in self._memoized_chains_into(
                target=cand,
                events=events,
                budget=budget - 1,
                same_resource_only=same_resource_only,
                memo=memo,
            ):
                self._offer(
                    best_by_root,
                    _PartialChain(
                        hops=(*sub.hops, hop),
                        score=min(sub.score, hop.confidence),
                        root_event_id=sub.root_event_id,
                        root_same_resource=sub.root_same_resource,
                    ),
                )
        return list(best_by_root.values())

    def _memoized_chains_into(
        self,
        *,
        target: CorrelatedEvent,
        events: tuple[CorrelatedEvent, ...],
        budget: int,
        same_resource_only: bool,
        memo: dict[tuple[str, int], _PartialChain | None],
    ) -> list[_PartialChain]:
        """The single best change-rooted chain into ``target`` (memoized).

        Extension only needs the best sub-chain per target/budget, not
        every root, so this collapses to one entry - bounding traversal
        while staying deterministic."""
        key = (target.event_id, budget)
        if key in memo:
            cached = memo[key]
            return [cached] if cached is not None else []
        options = self._chains_into(
            target=target,
            events=events,
            budget=budget,
            same_resource_only=same_resource_only,
            memo=memo,
        )
        best = self._pick_best(options) if options else None
        memo[key] = best
        return [best] if best is not None else []

    def _antecedents(
        self,
        target: CorrelatedEvent,
        events: tuple[CorrelatedEvent, ...],
        same_resource_only: bool,  # noqa: ARG002 - relationship filter applies it
    ) -> list[CorrelatedEvent]:
        """Events strictly before ``target`` and within the window, in a
        deterministic order (latest first, same-resource first, id)."""
        window = self._config.window
        out = [
            e
            for e in events
            if e.event_id != target.event_id
            and e.at < target.at
            and target.at - e.at <= window
        ]
        out.sort(
            key=lambda e: (e.at, e.resource_ref == target.resource_ref, e.event_id),
            reverse=True,
        )
        return out

    # -- scoring -----------------------------------------------------------

    def _hop(
        self,
        *,
        cause: CorrelatedEvent,
        effect: CorrelatedEvent,
        relationship: Relationship,
    ) -> CausalHop:
        lead = effect.at - cause.at
        prox = self._proximity(lead)
        rel_w = self._config.relationship_weights.get(relationship, 0.0)
        if cause.is_change:
            kind_w = self._config.change_kind_weights.get(
                cause.change_kind, self._config.default_change_weight
            ) if cause.change_kind is not None else self._config.default_change_weight
        else:
            kind_w = self._config.symptom_propagation_weight
        confidence = _clamp01(prox * rel_w * kind_w)
        return CausalHop(
            cause_event_id=cause.event_id,
            effect_event_id=effect.event_id,
            cause_resource_ref=cause.resource_ref,
            effect_resource_ref=effect.resource_ref,
            lead=lead,
            relationship=relationship,
            confidence=confidence,
        )

    def _proximity(self, lead: timedelta) -> float:
        """1.0 at zero lead, 0.0 at the window edge, linear between."""
        fraction = _clamp01(lead.total_seconds() / self._config.window.total_seconds())
        return 1.0 - fraction

    def _relationship(
        self,
        cause_resource: str,
        effect_resource: str,
        same_resource_only: bool,
    ) -> Relationship | None:
        """Classify the cause->effect resource relationship, or ``None``
        when the pair cannot be causally linked under the config."""
        if cause_resource == effect_resource:
            return Relationship.SAME_RESOURCE
        if same_resource_only:
            return None
        deps = self._config.depends_on
        if not deps:
            return Relationship.UNSCOPED
        # Bounded, cycle-safe BFS over the dependency graph from the effect.
        visited: set[str] = {effect_resource}
        frontier: list[str] = [effect_resource]
        depth = 0
        while frontier and depth < self._config.transitive_depth:
            depth += 1
            nxt: list[str] = []
            for node in frontier:
                for dep in deps.get(node, ()):
                    if dep in visited:
                        continue
                    if dep == cause_resource:
                        return (
                            Relationship.DEPENDENCY
                            if depth == 1
                            else Relationship.TRANSITIVE_DEPENDENCY
                        )
                    visited.add(dep)
                    nxt.append(dep)
            frontier = nxt
        return None

    # -- selection ---------------------------------------------------------

    @staticmethod
    def _offer(best_by_root: dict[str, _PartialChain], chain: _PartialChain) -> None:
        """Keep only the best chain per distinct root (deterministic)."""
        incumbent = best_by_root.get(chain.root_event_id)
        if incumbent is None or CausalChainAnalyzer._prefer(chain, incumbent):
            best_by_root[chain.root_event_id] = chain

    @staticmethod
    def _prefer(a: _PartialChain, b: _PartialChain) -> bool:
        """True iff chain ``a`` should be preferred over ``b``.

        Higher score wins; ties prefer fewer hops (a simpler cause), then a
        same-resource root (more direct), then a stable root-id order."""
        return CausalChainAnalyzer._rank(a) > CausalChainAnalyzer._rank(b)

    @staticmethod
    def _rank(chain: _PartialChain) -> tuple[float, int, bool, str]:
        # Negative hop count so *fewer* hops rank higher under max().
        return (
            round(chain.score, 6),
            -len(chain.hops),
            chain.root_same_resource,
            chain.root_event_id,
        )

    def _pick_best(self, options: list[_PartialChain]) -> _PartialChain:
        return max(options, key=self._rank)

    def _count_ambiguity(self, best: _PartialChain, options: list[_PartialChain]) -> int:
        """How many distinct roots explain the failure within epsilon of
        the best score (>= 1; 1 means a single clean antecedent)."""
        threshold = best.score - self._config.ambiguity_epsilon
        roots = {
            opt.root_event_id for opt in options if round(opt.score, 6) >= round(threshold, 6)
        }
        return max(1, len(roots))

    def _discount(self, score: float, ambiguity: int) -> float:
        if ambiguity <= 1:
            return score
        return _clamp01(score * self._config.ambiguity_discount ** (ambiguity - 1))

    @staticmethod
    def _band(score: float) -> float:
        """Map a raw ``[0, 1]`` score into the bounded T1 confidence band."""
        span = _MAX_CONFIDENCE - _MIN_CONFIDENCE
        return round(_MIN_CONFIDENCE + _clamp01(score) * span, 4)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def chain_to_hypothesis(
    chain: CausalChain,
    *,
    failure_resource_ref: str,
) -> RootCauseHypothesis:
    """Convert a reconstructed :class:`CausalChain` into a grounded
    :class:`RootCauseHypothesis` (tier T1).

    Every event in the chain is cited (root -> intermediates -> failure)
    so the hypothesis is grounded on the full temporal evidence. The prose
    keeps the single-hop wording an operator already reads, and describes
    the arrow path for a genuine multi-hop chain.
    """
    root_hop = chain.hops[0]
    failure_hop = chain.hops[-1]
    if len(chain.hops) == 1:
        scope = (
            "same-resource"
            if root_hop.cause_resource_ref == failure_resource_ref
            else "upstream-resource"
        )
        cause = (
            f"correlation cause ({scope}): change event '{root_hop.cause_event_id}' on "
            f"'{root_hop.cause_resource_ref}' at {root_hop.cause_event_id and _iso(chain)} "
        )
        cause = (
            f"correlation cause ({scope}): change event '{root_hop.cause_event_id}' on "
            f"'{root_hop.cause_resource_ref}' preceded the failure on "
            f"'{failure_resource_ref}' by {_format_lead(failure_hop.lead)}"
        )
    else:
        arrows = " -> ".join(
            f"'{eid}'" for eid in chain.event_ids
        )
        total_lead = failure_hop.effect_at_minus_root(chain)
        cause = (
            f"correlation cause (causal chain, {len(chain.hops)} hops): {arrows}; "
            f"root change '{chain.root_event_id}' on '{root_hop.cause_resource_ref}' "
            f"preceded the failure on '{failure_resource_ref}' by {_format_lead(total_lead)}"
        )
    citations = tuple(Citation(kind=CitationKind.EVENT, ref=eid) for eid in chain.event_ids)
    return RootCauseHypothesis(
        tier=RcaTier.T1,
        cause=cause,
        confidence=chain.confidence,
        citations=citations,
        evidence_refs=chain.event_ids,
        remediation_ref=None,
    )


def _iso(chain: CausalChain) -> str:  # pragma: no cover - retained for symmetry
    return chain.root_event_id


def _format_lead(lead: timedelta) -> str:
    seconds = int(lead.total_seconds())
    if seconds < 60:
        return f"{seconds}s"
    minutes, rem = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m{rem}s"
    hours, rem_min = divmod(minutes, 60)
    return f"{hours}h{rem_min}m"


__all__ = [
    "CausalChain",
    "CausalChainAnalyzer",
    "CausalChainConfig",
    "CausalHop",
    "CorrelatedEvent",
    "Relationship",
    "chain_to_hypothesis",
]
