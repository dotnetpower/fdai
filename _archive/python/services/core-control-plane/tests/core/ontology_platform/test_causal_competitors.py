"""Independent competitor accounting through the real metric join and node handler."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import FrozenInstanceError, dataclass, replace
from datetime import UTC, datetime, timedelta, timezone

import pytest
from fdai.composition.semantic_query_metric_bindings import build_metric_query_handlers
from fdai.core.detection.series import MetricSample
from fdai.core.ontology_platform.causal_competitors import (
    CausalCompetitorAssessment,
    CausalCompetitorFinding,
    CausalCompetitorRequest,
    CompetitorDisposition,
)
from fdai.core.ontology_platform.metric_semantics import (
    CausalEvidenceJoin,
    CausalJoinStatus,
    MetricAggregation,
    MetricSemanticDefinition,
    MetricSemanticRegistry,
    MetricWindow,
    causal_competitor_request,
    join_causal_evidence,
)
from fdai.core.ontology_platform.query_execution import QueryNodeResult
from fdai.core.ontology_platform.query_metric_handlers import EvidenceJoinNodeHandler
from fdai.core.ontology_platform.topology_history import (
    TopologyDiff,
    TopologyGraphAt,
    TopologyLinkRevision,
    TopologyObjectRevision,
    TopologyRevisionBatch,
    graph_at,
    topology_diff,
)
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
from fdai_service_contracts.ontology_query import (
    OntologyQueryNode,
    QueryNodeKind,
    canonical_json,
    content_digest,
)

START = datetime(2026, 10, 16, tzinfo=UTC)
END = START + timedelta(minutes=20)
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
COMPETITORS = ("credential_change", "deployment")
CONFIG = TemporalCausalityConfig(lag_seconds=(60,), min_samples=12)


def _changed_request(
    request: CausalCompetitorRequest, field: str, changed: object
) -> CausalCompetitorRequest:
    text_fields: dict[str, Callable[[str], CausalCompetitorRequest]] = {
        "cause_resource_id": lambda value: replace(request, cause_resource_id=value),
        "effect_resource_id": lambda value: replace(request, effect_resource_id=value),
        "cause_concept_id": lambda value: replace(request, cause_concept_id=value),
        "effect_concept_id": lambda value: replace(request, effect_concept_id=value),
        "topology_diff_digest": lambda value: replace(request, topology_diff_digest=value),
        "topology_before_digest": lambda value: replace(request, topology_before_digest=value),
        "topology_after_digest": lambda value: replace(request, topology_after_digest=value),
    }
    time_fields: dict[str, Callable[[datetime], CausalCompetitorRequest]] = {
        "cause_start": lambda value: replace(request, cause_start=value),
        "cause_end": lambda value: replace(request, cause_end=value),
        "effect_start": lambda value: replace(request, effect_start=value),
        "effect_end": lambda value: replace(request, effect_end=value),
        "feature_cutoff": lambda value: replace(request, feature_cutoff=value),
    }
    tuple_fields: dict[str, Callable[[tuple[str, ...]], CausalCompetitorRequest]] = {
        "topology_generation_refs": lambda value: replace(request, topology_generation_refs=value),
        "topology_source_receipt_digests": lambda value: replace(
            request, topology_source_receipt_digests=value
        ),
        "competing_explanations": lambda value: replace(request, competing_explanations=value),
    }
    if isinstance(changed, str):
        return text_fields[field](changed)
    if isinstance(changed, datetime):
        return time_fields[field](changed)
    assert isinstance(changed, tuple)
    assert all(isinstance(value, str) for value in changed)
    return tuple_fields[field](tuple(str(value) for value in changed))


def _window(concept: str, resource: str, values: tuple[float, ...]) -> MetricWindow:
    return MetricWindow(
        concept_id=concept,
        resource_id=resource,
        unit="count",
        start=START,
        end=END,
        samples=tuple(
            MetricSample(timestamp=START + timedelta(minutes=i), value=value)
            for i, value in enumerate(values)
        ),
        complete=True,
        evidence_refs=(f"evidence:{concept}",),
    )


def _topology(*, path: bool = True) -> TopologyDiff:
    fact = StateFactMetadata(
        lane=StateFactLane.OBSERVED,
        authority=StateFactAuthority.PROVIDER,
        source_identity="provider:example",
        source_revision="revision:one",
        effective_at=START - timedelta(minutes=30),
        recorded_at=START,
        evidence_cutoff=START,
        freshness_ceiling_seconds=3600,
        completeness=1.0,
        synthetic=False,
        evidence_refs=("evidence:edge",),
    )
    metadata = LinkObservationMetadata(
        state_fact=fact,
        verification_method="provider-readback",
        verified=True,
        verifier_identity="verifier:example",
        verifier_revision="1",
        verification_receipt_ref="receipt:edge",
    )
    links = (
        (
            OntologyLinkRecord(
                "depends_on",
                "app",
                "db",
                {LINK_OBSERVATION_METADATA_PROPERTY: metadata.to_mapping()},
            ),
        )
        if path
        else ()
    )
    graph = OntologyGraphSnapshot(
        objects=tuple(
            OntologyObjectRecord(id=key, object_type="Resource", properties={"id": key})
            for key in ("app", "db")
        ),
        links=links,
    )
    view = TopologyGraphAt(
        as_of=START,
        known_at=START,
        graph=graph,
        complete=True,
        revision_ids=("revision:one",),
        provider_generation_refs=("generation:one",),
        evidence_refs=("evidence:topology",),
        digest=content_digest({"path": path}),
        source_receipt_digests=(content_digest("generation:one"),),
    )
    return topology_diff(view, view)


@dataclass(frozen=True)
class _Inputs:
    cause: MetricWindow
    effect: MetricWindow
    topology: TopologyDiff

    def request(self) -> CausalCompetitorRequest:
        request = causal_competitor_request(
            cause=self.cause,
            effect=self.effect,
            topology_change=self.topology,
            feature_cutoff=END,
            competing_explanations=COMPETITORS,
        )
        assert request is not None
        return request

    def join(self, assessment: CausalCompetitorAssessment | None) -> CausalEvidenceJoin:
        return join_causal_evidence(
            cause=self.cause,
            effect=self.effect,
            topology_change=self.topology,
            feature_cutoff=END,
            config=CONFIG,
            competing_explanations=COMPETITORS,
            competitor_assessment=assessment,
        )

    def dependencies(self) -> dict[str, QueryNodeResult]:
        return {
            "cause": QueryNodeResult(value=self.cause, evidence_refs=self.cause.evidence_refs),
            "effect": QueryNodeResult(value=self.effect, evidence_refs=self.effect.evidence_refs),
            "topology": QueryNodeResult(
                value=self.topology, evidence_refs=self.topology.evidence_refs
            ),
        }


@pytest.fixture
def inputs() -> _Inputs:
    return _Inputs(
        _window("cpu", "db", VALUES),
        _window("latency", "app", (0.0, *VALUES[:-1])),
        _topology(),
    )


def _assessment(
    request: CausalCompetitorRequest,
    disposition: CompetitorDisposition = CompetitorDisposition.REFUTED,
) -> CausalCompetitorAssessment:
    return CausalCompetitorAssessment(
        request=request,
        complete=True,
        findings=tuple(
            CausalCompetitorFinding(
                competitor_id=competitor,
                disposition=disposition,
                request_digest=request.digest,
                source_receipt_digest=content_digest(["independent-source", competitor]),
                evidence_refs=(f"independent:{competitor}:mechanism-observation",),
            )
            for competitor in request.competing_explanations
        ),
    )


class _Source:
    def __init__(self, assessment: CausalCompetitorAssessment | None) -> None:
        self.assessment = assessment
        self.requests: list[CausalCompetitorRequest] = []

    async def resolve(
        self, *, request: CausalCompetitorRequest
    ) -> CausalCompetitorAssessment | None:
        self.requests.append(request)
        return self.assessment


def _node(**arguments: object) -> OntologyQueryNode:
    return OntologyQueryNode(
        node_id="join",
        kind=QueryNodeKind.EVIDENCE_JOIN,
        depends_on=("cause", "effect", "topology"),
        arguments_json=canonical_json(
            {
                "feature_cutoff": END.isoformat(),
                "lag_seconds": [60],
                "min_samples": 12,
                "competing_explanations": list(COMPETITORS),
                **arguments,
            }
        ),
        output_kind="causal.join",
    )


async def test_independent_refutations_support_real_handler_and_join(inputs: _Inputs) -> None:
    assessment = _assessment(inputs.request())
    source = _Source(assessment)
    result = await EvidenceJoinNodeHandler(competitor_source=source)(_node(), inputs.dependencies())
    assert source.requests == [inputs.request()]
    assert isinstance(result.value, CausalEvidenceJoin)
    assert result.value == inputs.join(assessment)
    assert result.value.status is CausalJoinStatus.SUPPORTED
    assert result.value.temporal_claim is not None
    assert result.value.temporal_claim.evidence_grade.value == "predictive_precedence"
    assert result.value.competitor_assessment_digest == assessment.digest
    assert set(assessment.evidence_refs) <= set(result.evidence_refs)
    assert result.value.execution_authority is False
    with pytest.raises(ValueError, match="MUST NOT grant execution authority"):
        replace(result.value, execution_authority=True)


@pytest.mark.parametrize("bind_source", [False, True])
async def test_composition_metric_bindings_preserve_optional_independent_source(
    inputs: _Inputs, bind_source: bool
) -> None:
    class _UnusedMetricProvider:
        async def read(
            self,
            *,
            definition: MetricSemanticDefinition,
            resource_id: str,
            start: datetime,
            end: datetime,
            query_labels: Mapping[str, str] | None = None,
        ) -> MetricWindow:
            raise AssertionError("binding existing evidence MUST NOT read metric providers")

    registry = MetricSemanticRegistry.build(
        (
            MetricSemanticDefinition(
                concept_id="cpu",
                provider_metric="cpu",
                canonical_unit="count",
                aggregation=MetricAggregation.AVERAGE,
                description="Synthetic CPU samples.",
            ),
        )
    )
    source = _Source(_assessment(inputs.request()))
    handlers = (
        build_metric_query_handlers(
            registry=registry,
            provider=_UnusedMetricProvider(),
            competitor_source=source,
        )
        if bind_source
        else build_metric_query_handlers(registry=registry, provider=_UnusedMetricProvider())
    )
    assert set(handlers) == {
        QueryNodeKind.METRIC_SERIES,
        QueryNodeKind.METRIC_SCOPE_SERIES,
        QueryNodeKind.METRIC_COMPARISON,
        QueryNodeKind.EVIDENCE_JOIN,
    }
    output = await handlers[QueryNodeKind.EVIDENCE_JOIN](_node(), inputs.dependencies())
    assert isinstance(output.value, CausalEvidenceJoin)
    assert output.value == inputs.join(source.assessment if bind_source else None)
    assert source.requests == ([inputs.request()] if bind_source else [])
    assert output.value.execution_authority is False


@pytest.mark.parametrize("disposition", list(CompetitorDisposition))
async def test_every_competitor_requires_independent_refutation(
    inputs: _Inputs, disposition: CompetitorDisposition
) -> None:
    assessment = _assessment(inputs.request())
    assessment = replace(
        assessment,
        findings=(replace(assessment.findings[0], disposition=disposition), assessment.findings[1]),
    )
    source = _Source(assessment)
    output = await EvidenceJoinNodeHandler(competitor_source=source)(_node(), inputs.dependencies())
    assert isinstance(output.value, CausalEvidenceJoin)
    assert output.value == inputs.join(assessment)
    assert output.value.status is (
        CausalJoinStatus.SUPPORTED
        if disposition is CompetitorDisposition.REFUTED
        else CausalJoinStatus.UNRESOLVED
    )
    assert set(assessment.evidence_refs) <= set(output.evidence_refs)


@pytest.mark.parametrize(
    ("field", "changed"),
    [
        ("cause_resource_id", "other-db"),
        ("effect_resource_id", "other-app"),
        ("cause_concept_id", "other-cpu"),
        ("effect_concept_id", "other-latency"),
        ("topology_diff_digest", content_digest("other-diff")),
        ("topology_before_digest", content_digest("other-before")),
        ("topology_after_digest", content_digest("other-after")),
        ("topology_generation_refs", ("generation:other",)),
        ("topology_source_receipt_digests", (content_digest("other-generation"),)),
        ("feature_cutoff", END + timedelta(seconds=1)),
        ("cause_start", START - timedelta(seconds=1)),
        ("cause_end", END - timedelta(seconds=1)),
        ("effect_start", START - timedelta(seconds=1)),
        ("effect_end", END - timedelta(seconds=1)),
        ("competing_explanations", ("deployment",)),
        ("competing_explanations", ("credential_change", "deployment", "dns")),
    ],
)
async def test_changed_assessment_scope_holds_without_citing_wrong_receipts(
    inputs: _Inputs, field: str, changed: object
) -> None:
    assessment = _assessment(_changed_request(inputs.request(), field, changed))
    output = await EvidenceJoinNodeHandler(competitor_source=_Source(assessment))(
        _node(), inputs.dependencies()
    )
    assert isinstance(output.value, CausalEvidenceJoin)
    assert output.value == inputs.join(assessment)
    assert output.value.status is CausalJoinStatus.UNRESOLVED
    assert "competing_assessment_scope_mismatch" in output.value.limitations
    assert output.value.competitor_assessment_digest is None
    assert not set(assessment.evidence_refs) & set(output.evidence_refs)


@pytest.mark.parametrize("missing", [True, False])
async def test_incomplete_or_missing_competitor_accounting_holds(
    inputs: _Inputs, missing: bool
) -> None:
    assessment = _assessment(inputs.request())
    assessment = (
        replace(assessment, findings=assessment.findings[:1])
        if missing
        else replace(assessment, complete=False)
    )
    output = await EvidenceJoinNodeHandler(competitor_source=_Source(assessment))(
        _node(), inputs.dependencies()
    )
    assert isinstance(output.value, CausalEvidenceJoin)
    assert output.value == inputs.join(assessment)
    assert output.value.status is CausalJoinStatus.UNRESOLVED
    assert (
        "competing_assessment_set_mismatch" if missing else "competing_assessment_incomplete"
    ) in output.value.limitations


async def test_absent_source_or_assessment_preserves_unresolved_behavior(inputs: _Inputs) -> None:
    for source in (None, _Source(None)):
        output = await EvidenceJoinNodeHandler(competitor_source=source)(
            _node(), inputs.dependencies()
        )
        assert isinstance(output.value, CausalEvidenceJoin)
        assert output.value == inputs.join(None)
        assert output.value.limitations == ("competing_explanations_unresolved",)


async def test_unnamed_competitors_never_trigger_source_io(inputs: _Inputs) -> None:
    source = _Source(_assessment(inputs.request()))
    output = await EvidenceJoinNodeHandler(competitor_source=source)(
        _node(competing_explanations=[]), inputs.dependencies()
    )
    assert isinstance(output.value, CausalEvidenceJoin)
    assert output.value.status is CausalJoinStatus.SUPPORTED
    assert output.value.competitor_assessment_digest is None
    assert source.requests == []


async def test_empty_historical_graph_holds_without_calling_competitor_source(
    inputs: _Inputs,
) -> None:
    empty = graph_at((), as_of=START, known_at=START)
    changed = replace(inputs, topology=topology_diff(empty, empty))
    source = _Source(_assessment(inputs.request()))
    output = await EvidenceJoinNodeHandler(competitor_source=source)(
        _node(), changed.dependencies()
    )
    assert isinstance(output.value, CausalEvidenceJoin)
    assert output.value.status is CausalJoinStatus.UNRESOLVED
    assert "topology_history_incomplete" in output.value.limitations
    assert "competing_assessment_scope_unavailable" in output.value.limitations
    assert set(
        (
            *changed.cause.evidence_refs,
            *changed.effect.evidence_refs,
            *changed.topology.evidence_refs,
        )
    ) <= set(output.evidence_refs)
    assert output.value.topology_diff_digest == changed.topology.digest
    assert output.value.competitor_assessment_digest is None
    assert source.requests == []


async def test_complete_65_generation_history_holds_without_truncation_or_source_io(
    inputs: _Inputs,
) -> None:
    original = inputs.topology.before
    assert original is not None
    edge = original.graph.links[0]
    effective_at = START - timedelta(minutes=30)
    objects = tuple(
        TopologyObjectRevision.upsert(
            record,
            effective_at=effective_at,
            recorded_at=START,
            evidence_ref=f"evidence:historical:{record.id}",
        )
        for record in original.graph.objects
    )
    link = TopologyLinkRevision(
        from_id=edge.from_id,
        from_type="Resource",
        link_type=edge.link_type,
        to_id=edge.to_id,
        to_type="Resource",
        properties_json=canonical_json(edge.properties),
        effective_at=effective_at,
        recorded_at=START,
        deleted=False,
        evidence_ref="evidence:historical:dependency",
    )
    generations = tuple(f"generation:{i:03d}" for i in range(65))
    batches = tuple(
        TopologyRevisionBatch(
            revision_id=f"revision:{i:03d}",
            provider_generation_ref=generation,
            effective_at=effective_at,
            recorded_at=START,
            complete_snapshot=i == 0,
            object_revisions=objects if i == 0 else (),
            link_revisions=(link,) if i == 0 else (),
            ontology_release_digest=content_digest("release:example"),
            source_receipt_digest=content_digest(generation),
        )
        for i, generation in enumerate(generations)
    )
    historical = graph_at(batches, as_of=START, known_at=START)
    assert historical.complete
    assert historical.provider_generation_refs == generations
    changed = replace(inputs, topology=topology_diff(historical, historical))
    baseline = changed.join(None)
    assert baseline.temporal_claim is not None
    assert baseline.temporal_claim.falsifiers == ()
    assert baseline.limitations == ("competing_explanations_unresolved",)
    source = _Source(_assessment(inputs.request()))
    output = await EvidenceJoinNodeHandler(competitor_source=source)(
        _node(), changed.dependencies()
    )
    assert isinstance(output.value, CausalEvidenceJoin)
    assert output.value.status is CausalJoinStatus.UNRESOLVED
    assert "competing_assessment_scope_unavailable" in output.value.limitations
    assert set(
        (
            *changed.cause.evidence_refs,
            *changed.effect.evidence_refs,
            *changed.topology.evidence_refs,
        )
    ) <= set(output.evidence_refs)
    assert output.value.topology_diff_digest == changed.topology.digest
    assert output.value.competitor_assessment_digest is None
    assert historical.provider_generation_refs == generations
    assert len(historical.source_receipt_digests) == 65
    assert source.requests == []


async def test_extra_finding_does_not_change_the_named_denominator(inputs: _Inputs) -> None:
    assessment = _assessment(inputs.request())
    assessment = replace(
        assessment,
        findings=(
            *assessment.findings,
            replace(assessment.findings[0], competitor_id="dns"),
        ),
    )
    output = await EvidenceJoinNodeHandler(competitor_source=_Source(assessment))(
        _node(), inputs.dependencies()
    )
    assert isinstance(output.value, CausalEvidenceJoin)
    assert output.value.status is CausalJoinStatus.UNRESOLVED
    assert output.value.competing_explanations == COMPETITORS
    assert "competing_assessment_set_mismatch" in output.value.limitations


async def test_source_failure_is_an_explicit_sanitized_hold(inputs: _Inputs) -> None:
    class _FailedSource:
        async def resolve(
            self, *, request: CausalCompetitorRequest
        ) -> CausalCompetitorAssessment | None:
            raise RuntimeError("private source details MUST NOT escape")

    output = await EvidenceJoinNodeHandler(competitor_source=_FailedSource())(
        _node(), inputs.dependencies()
    )
    assert isinstance(output.value, CausalEvidenceJoin)
    assert output.value.status is CausalJoinStatus.UNRESOLVED
    assert "competing_assessment_source_failed" in output.value.limitations
    assert "private source" not in repr(output)


async def test_source_json_is_not_an_independent_typed_assessment(inputs: _Inputs) -> None:
    source = _Source(None)
    source.__setattr__("assessment", {"complete": True, "disposition": "refuted"})
    output = await EvidenceJoinNodeHandler(competitor_source=source)(_node(), inputs.dependencies())
    assert isinstance(output.value, CausalEvidenceJoin)
    assert output.value.status is CausalJoinStatus.UNRESOLVED
    assert "competing_assessment_source_invalid" in output.value.limitations
    assert output.value.competitor_assessment_digest is None


async def test_source_cancellation_is_not_swallowed(inputs: _Inputs) -> None:
    class _CancelledSource:
        async def resolve(
            self, *, request: CausalCompetitorRequest
        ) -> CausalCompetitorAssessment | None:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await EvidenceJoinNodeHandler(competitor_source=_CancelledSource())(
            _node(), inputs.dependencies()
        )


@pytest.mark.parametrize(
    "key", ["competitor_assessment", "assessment", "findings", "assessment_digest"]
)
async def test_plan_arguments_cannot_inject_assessments(inputs: _Inputs, key: str) -> None:
    source = _Source(_assessment(inputs.request()))
    with pytest.raises(ValueError, match="closed schema"):
        await EvidenceJoinNodeHandler(competitor_source=source)(
            _node(**{key: {"complete": True, "disposition": "refuted"}}),
            inputs.dependencies(),
        )
    assert source.requests == []


@pytest.mark.parametrize(
    "competitors",
    [
        ["deployment", "deployment"],
        ["deployment"] * 17,
        ["x" * 257],
        [" "],
    ],
)
async def test_handler_rejects_duplicate_or_overbound_names(
    inputs: _Inputs, competitors: list[str]
) -> None:
    source = _Source(_assessment(inputs.request()))
    with pytest.raises(ValueError):
        await EvidenceJoinNodeHandler(competitor_source=source)(
            _node(competing_explanations=competitors), inputs.dependencies()
        )
    assert source.requests == []


def test_assessment_rejects_duplicates_uncited_or_unbound_receipts(inputs: _Inputs) -> None:
    assessment = _assessment(inputs.request())
    finding = assessment.findings[0]
    for findings in (
        (finding, finding),
        tuple(replace(finding, competitor_id=f"candidate-{i}") for i in range(17)),
    ):
        with pytest.raises(ValueError):
            replace(assessment, findings=findings)
    for changes in (
        {"evidence_refs": ()},
        {"evidence_refs": (" ",)},
        {"evidence_refs": ("same", "same")},
        {"evidence_refs": ("x" * 513,)},
        {"evidence_refs": tuple(f"evidence:{i}" for i in range(65))},
        {"source_receipt_digest": "sha256:" + "g" * 64},
        {"source_receipt_digest": "sha256:" + "a" * 65},
        {"disposition": "refuted"},
    ):
        with pytest.raises(ValueError):
            replace(finding, **changes)
    with pytest.raises(ValueError, match="exact request digest"):
        replace(
            assessment,
            findings=(replace(finding, request_digest=content_digest("other-request")),),
        )


@pytest.mark.parametrize(
    ("field", "changed"),
    [
        ("cause_resource_id", ""),
        ("effect_resource_id", "x" * 257),
        ("cause_concept_id", "x" * 129),
        ("cause_start", START.replace(tzinfo=None)),
        ("cause_start", END),
        ("cause_start", START - timedelta(days=8)),
        ("feature_cutoff", END - timedelta(seconds=1)),
        ("topology_diff_digest", "digest"),
        ("topology_before_digest", "sha256:" + "A" * 64),
        ("topology_generation_refs", ()),
        ("topology_generation_refs", tuple(f"generation:{i}" for i in range(65))),
        ("topology_source_receipt_digests", ("not-a-digest",)),
        ("competing_explanations", ()),
        ("competing_explanations", ("deployment", "deployment")),
        ("competing_explanations", tuple(f"competitor:{i}" for i in range(17))),
    ],
)
def test_request_rejects_invalid_identities_times_and_bounds(
    inputs: _Inputs, field: str, changed: object
) -> None:
    with pytest.raises(ValueError):
        _changed_request(inputs.request(), field, changed)


def test_request_and_assessment_are_immutable_canonical_and_content_bound(inputs: _Inputs) -> None:
    request = inputs.request()
    equivalent = replace(
        request,
        competing_explanations=tuple(reversed(request.competing_explanations)),
        feature_cutoff=END.astimezone(timezone(timedelta(hours=9))),
    )
    assert request == equivalent
    assert request.digest == equivalent.digest
    assessment = _assessment(request)
    assert assessment == replace(assessment, findings=tuple(reversed(assessment.findings)))
    assert (
        assessment.digest
        == replace(assessment, findings=tuple(reversed(assessment.findings))).digest
    )
    assert assessment.digest != replace(assessment, complete=False).digest
    changed_finding = replace(
        assessment.findings[0], evidence_refs=("independent:changed-observation",)
    )
    assert (
        assessment.digest
        != replace(assessment, findings=(changed_finding, assessment.findings[1])).digest
    )
    with pytest.raises(FrozenInstanceError):
        request.__setattr__("cause_resource_id", "other")


def test_assessment_cannot_suppress_a_changed_empty_competitor_set(inputs: _Inputs) -> None:
    output = join_causal_evidence(
        cause=inputs.cause,
        effect=inputs.effect,
        topology_change=inputs.topology,
        feature_cutoff=END,
        config=CONFIG,
        competing_explanations=(),
        competitor_assessment=_assessment(inputs.request()),
    )
    assert output.status is CausalJoinStatus.UNRESOLVED
    assert output.limitations == ("competing_assessment_set_mismatch",)


@pytest.mark.parametrize("boundary", ["path", "incomplete", "temporal", "topology_absent"])
async def test_refutations_never_replace_topology_or_temporal_evidence(
    inputs: _Inputs, boundary: str
) -> None:
    changed = inputs
    if boundary == "path":
        changed = replace(inputs, topology=_topology(path=False))
    elif boundary == "incomplete":
        changed = replace(
            inputs,
            cause=replace(inputs.cause, complete=False, missing_reason="source_gap"),
        )
    elif boundary == "temporal":
        changed = replace(inputs, cause=_window("cpu", "db", (1.0,) * len(VALUES)))
    assessment = _assessment(changed.request())
    dependencies = changed.dependencies()
    node = _node()
    if boundary == "topology_absent":
        dependencies.pop("topology")
        node = node.model_copy(update={"depends_on": ("cause", "effect")})
    output = await EvidenceJoinNodeHandler(competitor_source=_Source(assessment))(
        node, dependencies
    )
    assert isinstance(output.value, CausalEvidenceJoin)
    assert output.value.status is CausalJoinStatus.UNRESOLVED
    assert output.value.execution_authority is False
    expected = {
        "path": "causal_dependency_path_unproven",
        "incomplete": "metric_window_incomplete",
        "temporal": "association_below_threshold",
        "topology_absent": "topology_change_unavailable",
    }
    assert expected[boundary] in output.value.limitations
