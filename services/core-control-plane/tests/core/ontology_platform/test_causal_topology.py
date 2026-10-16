"""Exact topology and competing-evidence boundaries for causal metric joins."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.detection.series import MetricSample
from fdai.core.ontology_platform.causal_topology import causal_topology_limitation
from fdai.core.ontology_platform.metric_semantics import (
    CausalJoinStatus,
    MetricWindow,
    join_causal_evidence,
)
from fdai.core.ontology_platform.topology_history import TopologyGraphAt, topology_diff
from fdai.core.rca.temporal_causality import TemporalCausalityConfig
from fdai.shared.providers.ontology_instance import (
    OntologyGraphSnapshot,
    OntologyLinkRecord,
    OntologyObjectRecord,
)
from fdai.shared.providers.state_evidence import (
    LINK_OBSERVATION_METADATA_PROPERTY,
    LinkObservationMetadata,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)
from fdai_service_contracts.ontology_query import content_digest

NOW = datetime(2026, 10, 16, tzinfo=UTC)
VALUES = (
    3.0,
    8.0,
    1.0,
    7.0,
    2.0,
    9.0,
    4.0,
    6.0,
    0.0,
    5.0,
    11.0,
    3.0,
    10.0,
    2.0,
    8.0,
    1.0,
    12.0,
    4.0,
    9.0,
    0.0,
)


def _edge(source: str, target: str, **changes: object) -> OntologyLinkRecord:
    fact = StateFactMetadata(
        lane=StateFactLane.OBSERVED,
        authority=StateFactAuthority.PROVIDER,
        source_identity="provider:one",
        source_revision="revision:one",
        effective_at=NOW - timedelta(minutes=30),
        recorded_at=NOW,
        evidence_cutoff=NOW,
        freshness_ceiling_seconds=3600,
        completeness=1.0,
        synthetic=False,
        evidence_refs=("evidence:edge",),
    )
    metadata = LinkObservationMetadata(
        state_fact=fact,
        verification_method="provider-readback",
        verified=True,
        verifier_identity="verifier:one",
        verifier_revision="1",
        verification_receipt_ref="receipt:edge",
    )
    properties = {LINK_OBSERVATION_METADATA_PROPERTY: metadata.to_mapping()}
    properties.update(changes)
    return OntologyLinkRecord("depends_on", source, target, properties)


def _view(
    links: tuple[OntologyLinkRecord, ...],
    *,
    ids: tuple[str, ...] = ("app", "db", "other", "bridge"),
) -> TopologyGraphAt:
    return TopologyGraphAt(
        as_of=NOW,
        known_at=NOW,
        graph=OntologyGraphSnapshot(
            objects=tuple(
                OntologyObjectRecord(id=key, object_type="Resource", properties={"id": key})
                for key in ids
            ),
            links=links,
        ),
        complete=True,
        revision_ids=("revision:one",),
        provider_generation_refs=("generation:one",),
        evidence_refs=("evidence:topology",),
        digest=content_digest([(link.from_id, link.link_type, link.to_id) for link in links]),
    )


def _limitation(before: TopologyGraphAt, after: TopologyGraphAt | None = None) -> str | None:
    return causal_topology_limitation(
        topology_diff(before, after or before),
        cause_id="db",
        effect_id="app",
        cutoff=NOW,
        window_start=NOW,
    )


def test_exact_dependency_direction_and_transitive_reachability() -> None:
    assert _limitation(_view((_edge("app", "db"),))) is None
    assert _limitation(_view((_edge("app", "bridge"), _edge("bridge", "db")))) is None
    assert _limitation(_view((_edge("db", "app"),))) == "causal_dependency_path_unproven"
    assert _limitation(_view((_edge("other", "db"),))) == "causal_dependency_path_unproven"
    assert _limitation(_view(())) == "causal_dependency_path_unproven"


def test_never_combine_edges_from_different_historical_views() -> None:
    assert (
        _limitation(_view((_edge("app", "bridge"),)), _view((_edge("bridge", "db"),)))
        == "causal_dependency_path_unproven"
    )


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "unverified",
        "malformed",
        "future",
        "recorded_late",
        "stale",
        "synthetic",
        "partial",
    ],
)
def test_invalid_relationship_evidence_cannot_support_a_path(change: str) -> None:
    edge = _edge("app", "db")
    raw = dict(edge.properties[LINK_OBSERVATION_METADATA_PROPERTY])
    fact = dict(raw["state_fact"])
    if change == "missing":
        edge = replace(edge, properties={})
    else:
        if change == "unverified":
            raw.update(
                verified=False,
                verifier_identity=None,
                verifier_revision=None,
                verification_receipt_ref=None,
            )
        elif change == "malformed":
            raw["unexpected"] = True
        elif change == "future":
            for name in ("effective_at", "evidence_cutoff", "recorded_at"):
                fact[name] = (NOW + timedelta(seconds=1)).isoformat()
        elif change == "recorded_late":
            fact["recorded_at"] = (NOW + timedelta(seconds=1)).isoformat()
        elif change == "stale":
            for name in ("effective_at", "evidence_cutoff"):
                fact[name] = (NOW - timedelta(hours=2)).isoformat()
        elif change == "synthetic":
            fact["synthetic"] = True
        else:
            fact["completeness"] = 0.5
        raw["state_fact"] = fact
        edge = replace(edge, properties={LINK_OBSERVATION_METADATA_PROPERTY: raw})
    assert _limitation(_view((edge,))) == "causal_dependency_path_unproven"


def test_incomplete_or_future_view_and_legacy_diff_remain_unresolved() -> None:
    view = _view((_edge("app", "db"),))
    assert _limitation(replace(view, complete=False)) == "causal_dependency_path_unproven"
    assert (
        _limitation(replace(view, as_of=NOW + timedelta(seconds=1)))
        == "causal_dependency_path_unproven"
    )
    diff = topology_diff(view, view)
    for changed, expected in (
        (replace(diff, before=None), "topology_path_evidence_unavailable"),
        (replace(diff, before_digest="sha256:" + "f" * 64), "topology_view_digest_mismatch"),
    ):
        assert (
            causal_topology_limitation(
                changed,
                cause_id="db",
                effect_id="app",
                cutoff=NOW,
                window_start=NOW,
            )
            == expected
        )


def _window(concept: str, resource: str, values: tuple[float, ...]) -> MetricWindow:
    return MetricWindow(
        concept_id=concept,
        resource_id=resource,
        unit="count",
        start=NOW - timedelta(minutes=len(values)),
        end=NOW,
        samples=tuple(
            MetricSample(timestamp=NOW - timedelta(minutes=len(values) - i), value=value)
            for i, value in enumerate(values)
        ),
        complete=True,
        evidence_refs=(f"evidence:{concept}",),
    )


@pytest.mark.parametrize("competitors", [(), ("unmeasured_common_driver",)])
def test_lagged_series_need_exact_topology_and_resolved_competitors(competitors) -> None:
    cause = _window("cpu", "db", VALUES)
    effect = _window("latency", "app", (0.0, *VALUES[:-1]))
    config = TemporalCausalityConfig(lag_seconds=(60,), min_samples=12)
    view = _view((_edge("app", "db"),))
    supported = join_causal_evidence(
        cause=cause,
        effect=effect,
        topology_change=topology_diff(view, view),
        feature_cutoff=NOW,
        config=config,
        competing_explanations=competitors,
    )
    assert supported.temporal_claim is not None
    assert supported.temporal_claim.evidence_grade.value == "predictive_precedence"
    assert supported.status is (
        CausalJoinStatus.UNRESOLVED if competitors else CausalJoinStatus.SUPPORTED
    )
    unrelated = _view((_edge("other", "db"),))
    held = join_causal_evidence(
        cause=cause,
        effect=effect,
        topology_change=topology_diff(unrelated, unrelated),
        feature_cutoff=NOW,
        config=config,
        competing_explanations=(),
    )
    assert held.status is CausalJoinStatus.UNRESOLVED
    assert held.temporal_claim is None
    assert held.evidence_refs[-1] == "evidence:topology"
    assert held.limitations == ("causal_dependency_path_unproven",)


def test_dependency_created_after_observations_cannot_explain_them() -> None:
    edge = _edge("app", "db")
    raw = dict(edge.properties[LINK_OBSERVATION_METADATA_PROPERTY])
    raw["state_fact"] = {**raw["state_fact"], "effective_at": NOW.isoformat()}
    edge = replace(edge, properties={LINK_OBSERVATION_METADATA_PROPERTY: raw})
    cause = _window("cpu", "db", VALUES)
    effect = _window("latency", "app", (0.0, *VALUES[:-1]))
    joined = join_causal_evidence(
        cause=cause,
        effect=effect,
        topology_change=topology_diff(_view(()), _view((edge,))),
        feature_cutoff=NOW,
        config=TemporalCausalityConfig(lag_seconds=(60,), min_samples=12),
        competing_explanations=(),
    )
    assert effect.samples[-1].timestamp < NOW
    assert joined.status is CausalJoinStatus.UNRESOLVED
    assert joined.limitations == ("causal_dependency_path_unproven",)
