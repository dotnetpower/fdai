"""Precise temporal causal-chain reconstruction (core/rca/causal_chain).

Covers the T1 upgrade beyond a single closest-antecedent lookup:
multi-hop chain reconstruction, dependency-aware linking (direct +
bounded transitive), ambiguity discounting, deterministic tie-breaks,
config validation, and the chain -> grounded-hypothesis conversion.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fdai.core.rca.causal_chain import (
    CausalChainAnalyzer,
    CausalChainConfig,
    CorrelatedEvent,
    Relationship,
    chain_to_hypothesis,
)
from fdai.core.rca.contract import CitationKind, RcaTier

FAIL_AT = datetime(2026, 7, 7, 12, 0, 0, tzinfo=UTC)
WINDOW = timedelta(minutes=10)


def _ev(
    event_id: str,
    *,
    before: timedelta,
    resource: str,
    is_change: bool,
    change_kind: str | None = None,
) -> CorrelatedEvent:
    return CorrelatedEvent(
        event_id=event_id,
        at=FAIL_AT - before,
        resource_ref=resource,
        is_change=is_change,
        change_kind=change_kind,
    )


def _analyzer(**overrides: object) -> CausalChainAnalyzer:
    return CausalChainAnalyzer(CausalChainConfig(window=WINDOW, **overrides))  # type: ignore[arg-type]


def _reconstruct(events: list[CorrelatedEvent], **overrides: object):
    analyzer = _analyzer(**overrides)
    return analyzer.reconstruct(
        failure_event_id="fail",
        failure_at=FAIL_AT,
        failure_resource_ref="app",
        correlated_events=events,
    )


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"window": timedelta(0)},
        {"window": timedelta(minutes=-1)},
        {"window": WINDOW, "max_hops": 0},
        {"window": WINDOW, "transitive_depth": 0},
        {"window": WINDOW, "ambiguity_epsilon": 1.5},
        {"window": WINDOW, "ambiguity_epsilon": -0.1},
        {"window": WINDOW, "ambiguity_discount": 0.0},
        {"window": WINDOW, "ambiguity_discount": 1.5},
        {"window": WINDOW, "default_change_weight": 1.5},
        {"window": WINDOW, "symptom_propagation_weight": -0.1},
    ],
)
def test_config_rejects_invalid_values(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        CausalChainConfig(**kwargs)  # type: ignore[arg-type]


def test_config_rejects_incomplete_relationship_weights() -> None:
    with pytest.raises(ValueError, match="relationship_weights MUST cover"):
        CausalChainConfig(
            window=WINDOW,
            relationship_weights={Relationship.SAME_RESOURCE: 1.0},  # missing three
        )


def test_config_rejects_out_of_range_relationship_weight() -> None:
    with pytest.raises(ValueError, match="relationship_weights"):
        CausalChainConfig(
            window=WINDOW,
            relationship_weights={
                Relationship.SAME_RESOURCE: 1.5,
                Relationship.DEPENDENCY: 0.9,
                Relationship.TRANSITIVE_DEPENDENCY: 0.7,
                Relationship.UNSCOPED: 0.85,
            },
        )


def test_config_rejects_out_of_range_change_kind_weight() -> None:
    with pytest.raises(ValueError, match="change_kind_weights"):
        CausalChainConfig(window=WINDOW, change_kind_weights={"deploy": 2.0})


def test_chain_to_hypothesis_rejects_empty_hops() -> None:
    from fdai.core.rca.causal_chain import CausalChain

    empty = CausalChain(
        root_event_id="r", failure_event_id="f", hops=(), confidence=0.5, ambiguity=1
    )
    with pytest.raises(ValueError, match="at least one hop"):
        chain_to_hypothesis(empty, failure_resource_ref="app")


def test_engine_is_total_over_naive_and_aware_timestamps() -> None:
    # A naive failure time + naive event times must not raise TypeError;
    # the engine coerces to UTC and reconstructs deterministically.
    naive_fail = datetime(2026, 7, 7, 12, 0, 0)  # noqa: DTZ001 - deliberately naive
    events = [
        CorrelatedEvent(
            event_id="cfg",
            at=datetime(2026, 7, 7, 11, 58, 0),  # noqa: DTZ001 - deliberately naive
            resource_ref="app",
            is_change=True,
        ),
    ]
    analyzer = _analyzer()
    chain = analyzer.reconstruct(
        failure_event_id="fail",
        failure_at=naive_fail,
        failure_resource_ref="app",
        correlated_events=events,
    )
    assert chain is not None
    assert chain.root_event_id == "cfg"


def test_engine_handles_mixed_naive_and_aware() -> None:
    # Aware failure time + naive event time (the realistic mismatch).
    events = [
        CorrelatedEvent(
            event_id="cfg",
            at=datetime(2026, 7, 7, 11, 59, 0),  # noqa: DTZ001 - deliberately naive
            resource_ref="app",
            is_change=True,
        ),
    ]
    chain = _reconstruct(events)  # _reconstruct uses aware FAIL_AT
    assert chain is not None
    assert chain.root_event_id == "cfg"


# ---------------------------------------------------------------------------
# Multi-hop reconstruction
# ---------------------------------------------------------------------------


def test_reconstructs_multi_hop_chain_through_intermediate_symptom() -> None:
    # root change on db -> symptom on db -> failure on app (app depends on db).
    events = [
        _ev("cfg", before=timedelta(minutes=4), resource="db", is_change=True),
        _ev("dbslow", before=timedelta(minutes=1), resource="db", is_change=False),
    ]
    chain = _reconstruct(events, depends_on={"app": frozenset({"db"})})
    assert chain is not None
    # The chain routes through the intermediate symptom, not a direct link.
    assert chain.root_event_id == "cfg"
    assert chain.failure_event_id == "fail"
    assert chain.event_ids == ("cfg", "dbslow", "fail")
    assert len(chain.hops) == 2
    assert chain.resource_path == ("db", "db", "app")
    assert chain.ambiguity == 1
    assert 0.35 <= chain.confidence <= 0.85
    # The last hop crosses the dependency edge db -> app.
    assert chain.hops[-1].relationship is Relationship.DEPENDENCY


def test_multi_hop_chain_outscores_weaker_direct_link() -> None:
    # A direct db-change -> app-failure link exists but is farther away than
    # the two-hop path through the closer intermediate symptom.
    events = [
        _ev("cfg", before=timedelta(minutes=6), resource="db", is_change=True),
        _ev("dbslow", before=timedelta(minutes=1), resource="db", is_change=False),
    ]
    chain = _reconstruct(events, depends_on={"app": frozenset({"db"})})
    assert chain is not None
    assert len(chain.hops) == 2  # the multi-hop path won


# ---------------------------------------------------------------------------
# Dependency awareness
# ---------------------------------------------------------------------------


def test_unrelated_resource_cannot_link_once_graph_supplied() -> None:
    events = [_ev("noise", before=timedelta(minutes=1), resource="unrelated", is_change=True)]
    # With a graph, an unrelated resource's change is not causally linkable.
    assert _reconstruct(events, depends_on={"app": frozenset({"db"})}) is None
    # Without a graph, the permissive cross-resource link still applies.
    permissive = _reconstruct(events)
    assert permissive is not None
    assert permissive.hops[0].relationship is Relationship.UNSCOPED


def test_direct_vs_transitive_dependency_classification() -> None:
    analyzer = _analyzer(depends_on={"app": frozenset({"mid"}), "mid": frozenset({"db"})})
    assert analyzer._relationship("mid", "app", False) is Relationship.DEPENDENCY
    assert analyzer._relationship("db", "app", False) is Relationship.TRANSITIVE_DEPENDENCY


def test_transitive_depth_bound_blocks_far_dependency() -> None:
    # db is two graph hops from app; a depth of 1 must not reach it.
    analyzer = _analyzer(
        depends_on={"app": frozenset({"mid"}), "mid": frozenset({"db"})},
        transitive_depth=1,
    )
    assert analyzer._relationship("db", "app", False) is None


def test_dependency_graph_cycle_is_safe() -> None:
    # a -> b -> a cycle must not loop forever; an unreachable cause returns None.
    analyzer = _analyzer(
        depends_on={"a": frozenset({"b"}), "b": frozenset({"a"})},
        transitive_depth=5,
    )
    assert analyzer._relationship("z", "a", False) is None
    assert analyzer._relationship("b", "a", False) is Relationship.DEPENDENCY


# ---------------------------------------------------------------------------
# Ambiguity discounting
# ---------------------------------------------------------------------------


def test_competing_antecedents_discount_confidence() -> None:
    two_changes = [
        _ev("chg-a", before=timedelta(minutes=2), resource="app", is_change=True),
        _ev("chg-b", before=timedelta(minutes=2), resource="app", is_change=True),
    ]
    ambiguous = _reconstruct(two_changes)
    single = _reconstruct([two_changes[0]])
    assert ambiguous is not None
    assert single is not None
    assert ambiguous.ambiguity == 2
    assert single.ambiguity == 1
    # Less certain which change is the trigger -> lower confidence.
    assert ambiguous.confidence < single.confidence


def test_far_second_candidate_does_not_count_as_ambiguous() -> None:
    events = [
        _ev("near", before=timedelta(seconds=5), resource="app", is_change=True),
        _ev("far", before=timedelta(minutes=9), resource="app", is_change=True),
    ]
    chain = _reconstruct(events)
    assert chain is not None
    assert chain.root_event_id == "near"
    assert chain.ambiguity == 1  # the far candidate is not within epsilon


# ---------------------------------------------------------------------------
# Root-must-be-change + abstain
# ---------------------------------------------------------------------------


def test_pure_symptom_storm_abstains() -> None:
    # No change anywhere -> no change-rooted chain -> abstain (defer to T2).
    events = [
        _ev("s1", before=timedelta(minutes=3), resource="app", is_change=False),
        _ev("s2", before=timedelta(minutes=1), resource="app", is_change=False),
    ]
    assert _reconstruct(events) is None


def test_empty_events_abstain() -> None:
    assert _reconstruct([]) is None


def test_self_event_is_ignored() -> None:
    events = [
        CorrelatedEvent(
            event_id="fail", at=FAIL_AT - timedelta(minutes=1), resource_ref="app", is_change=True
        ),
    ]
    assert _reconstruct(events) is None


# ---------------------------------------------------------------------------
# Determinism + bounds
# ---------------------------------------------------------------------------


def test_reconstruction_is_order_independent() -> None:
    events = [
        _ev("cfg", before=timedelta(minutes=4), resource="db", is_change=True),
        _ev("dbslow", before=timedelta(minutes=1), resource="db", is_change=False),
    ]
    graph = {"app": frozenset({"db"})}
    forward = _reconstruct(events, depends_on=graph)
    backward = _reconstruct(list(reversed(events)), depends_on=graph)
    assert forward is not None
    assert backward is not None
    assert forward.event_ids == backward.event_ids
    assert forward.confidence == backward.confidence
    assert forward.root_event_id == backward.root_event_id


def test_max_hops_caps_chain_length() -> None:
    # A 3-link path exists; max_hops=2 must still return a bounded chain.
    events = [
        _ev("c0", before=timedelta(minutes=6), resource="app", is_change=True),
        _ev("s1", before=timedelta(minutes=4), resource="app", is_change=False),
        _ev("s2", before=timedelta(minutes=2), resource="app", is_change=False),
    ]
    chain = _reconstruct(events, max_hops=2)
    assert chain is not None
    assert len(chain.hops) <= 2


def test_duplicate_event_ids_are_deduplicated() -> None:
    dup = _ev("cfg", before=timedelta(minutes=2), resource="app", is_change=True)
    dup2 = _ev("cfg", before=timedelta(minutes=3), resource="app", is_change=True)
    chain = _reconstruct([dup, dup2])
    assert chain is not None
    # First occurrence wins; only one root remains.
    assert chain.root_event_id == "cfg"


# ---------------------------------------------------------------------------
# change-kind weighting
# ---------------------------------------------------------------------------


def test_change_kind_weight_biases_root_selection() -> None:
    # Two equidistant changes; a heavier change-kind wins the tie.
    events = [
        _ev(
            "deploy",
            before=timedelta(minutes=2),
            resource="app",
            is_change=True,
            change_kind="deploy",
        ),
        _ev(
            "tweak",
            before=timedelta(minutes=2),
            resource="app",
            is_change=True,
            change_kind="config",
        ),
    ]
    chain = _reconstruct(
        events,
        change_kind_weights={"deploy": 1.0, "config": 0.5},
    )
    assert chain is not None
    assert chain.root_event_id == "deploy"


# ---------------------------------------------------------------------------
# chain -> hypothesis conversion
# ---------------------------------------------------------------------------


def test_single_hop_hypothesis_wording_and_citations() -> None:
    events = [_ev("cfg", before=timedelta(minutes=1), resource="app", is_change=True)]
    chain = _reconstruct(events)
    assert chain is not None
    hyp = chain_to_hypothesis(chain, failure_resource_ref="app")
    assert hyp.tier is RcaTier.T1
    assert "same-resource" in hyp.cause
    assert "cfg" in hyp.cause
    assert {c.ref for c in hyp.citations} == {"cfg", "fail"}
    assert all(c.kind is CitationKind.EVENT for c in hyp.citations)


def test_multi_hop_hypothesis_cites_every_chain_event() -> None:
    events = [
        _ev("cfg", before=timedelta(minutes=4), resource="db", is_change=True),
        _ev("dbslow", before=timedelta(minutes=1), resource="db", is_change=False),
    ]
    chain = _reconstruct(events, depends_on={"app": frozenset({"db"})})
    assert chain is not None
    hyp = chain_to_hypothesis(chain, failure_resource_ref="app")
    assert "causal chain" in hyp.cause
    assert {c.ref for c in hyp.citations} == {"cfg", "dbslow", "fail"}
    assert hyp.evidence_refs == ("cfg", "dbslow", "fail")


def test_same_resource_only_excludes_dependency_link() -> None:
    events = [_ev("cfg", before=timedelta(minutes=1), resource="db", is_change=True)]
    analyzer = _analyzer(depends_on={"app": frozenset({"db"})})
    chain = analyzer.reconstruct(
        failure_event_id="fail",
        failure_at=FAIL_AT,
        failure_resource_ref="app",
        correlated_events=events,
        same_resource_only=True,
    )
    assert chain is None


# ---------------------------------------------------------------------------
# Defensive edges (bug-zero)
# ---------------------------------------------------------------------------


def test_format_lead_renders_hours_for_wide_window() -> None:
    wide = CausalChainAnalyzer(CausalChainConfig(window=timedelta(hours=2)))
    events = [
        CorrelatedEvent(
            event_id="cfg",
            at=FAIL_AT - timedelta(minutes=90),
            resource_ref="app",
            is_change=True,
        ),
    ]
    chain = wide.reconstruct(
        failure_event_id="fail",
        failure_at=FAIL_AT,
        failure_resource_ref="app",
        correlated_events=events,
    )
    assert chain is not None
    hyp = chain_to_hypothesis(chain, failure_resource_ref="app")
    assert "1h30m" in hyp.cause  # hours branch of the lead formatter


def test_empty_chain_resource_path_is_empty() -> None:
    from fdai.core.rca.causal_chain import CausalChain

    empty = CausalChain(
        root_event_id="root",
        failure_event_id="fail",
        hops=(),
        confidence=0.5,
        ambiguity=1,
    )
    assert empty.resource_path == ()
    assert empty.event_ids == ("root",)


@pytest.mark.asyncio
async def test_noop_member_source_returns_empty() -> None:
    from fdai.core.rca.member_source import NoopIncidentMemberSource

    source = NoopIncidentMemberSource()
    assert await source.members(incident_id="inc-1") == ()
