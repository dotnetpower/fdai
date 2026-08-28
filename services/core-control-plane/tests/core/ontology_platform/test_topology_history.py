"""Bitemporal topology graph and diff tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from fdai.core.ontology_platform import (
    QueryNodeResult,
    TopologyAtNodeHandler,
    TopologyDiff,
    TopologyDiffNodeHandler,
    TopologyLinkRevision,
    TopologyObjectRevision,
    TopologyRevisionBatch,
    graph_at,
    topology_diff,
)
from fdai.core.ontology_platform.topology_history import _digest
from fdai.shared.providers.ontology_instance import OntologyObjectRecord
from fdai_service_contracts.ontology_query import OntologyQueryNode, QueryNodeKind, canonical_json

T0 = datetime(2026, 8, 10, 0, tzinfo=UTC)
T1 = datetime(2026, 8, 10, 1, tzinfo=UTC)
T2 = datetime(2026, 8, 10, 2, tzinfo=UTC)
T3 = datetime(2026, 8, 10, 3, tzinfo=UTC)
RELEASE_DIGEST = "sha256:" + ("a" * 64)


class _Reader:
    def __init__(self, batches: tuple[TopologyRevisionBatch, ...]) -> None:
        self._batches = batches

    async def read(
        self,
        *,
        as_of: datetime,
        known_at: datetime,
    ) -> tuple[TopologyRevisionBatch, ...]:
        assert as_of <= known_at
        return self._batches


def _object(
    identifier: str,
    *,
    effective_at: datetime,
    recorded_at: datetime,
    name: str | None = None,
) -> TopologyObjectRevision:
    return TopologyObjectRevision.upsert(
        OntologyObjectRecord(
            id=identifier,
            object_type="Resource",
            properties={"id": identifier, "name": name or identifier},
        ),
        effective_at=effective_at,
        recorded_at=recorded_at,
        evidence_ref=f"evidence:{identifier}:{recorded_at.hour}",
    )


def _peering(
    *,
    effective_at: datetime,
    recorded_at: datetime,
    deleted: bool = False,
) -> TopologyLinkRevision:
    return TopologyLinkRevision(
        from_id="vnet-a",
        from_type="Resource",
        link_type="peered_with",
        to_id="vnet-b",
        to_type="Resource",
        properties_json="{}",
        effective_at=effective_at,
        recorded_at=recorded_at,
        deleted=deleted,
        evidence_ref=f"evidence:peering:{recorded_at.hour}",
    )


def test_graph_at_reconstructs_tombstone_and_topology_diff() -> None:
    baseline = TopologyRevisionBatch(
        revision_id="revision-1",
        provider_generation_ref="provider-generation-1",
        effective_at=T0,
        recorded_at=T0,
        complete_snapshot=True,
        ontology_release_digest=RELEASE_DIGEST,
        source_receipt_digest=RELEASE_DIGEST,
        object_revisions=(
            _object("vnet-a", effective_at=T0, recorded_at=T0),
            _object("vnet-b", effective_at=T0, recorded_at=T0),
        ),
        link_revisions=(_peering(effective_at=T0, recorded_at=T0),),
    )
    removal = TopologyRevisionBatch(
        revision_id="revision-2",
        provider_generation_ref="provider-generation-2",
        effective_at=T1,
        recorded_at=T1,
        complete_snapshot=False,
        ontology_release_digest=RELEASE_DIGEST,
        source_receipt_digest=RELEASE_DIGEST,
        link_revisions=(_peering(effective_at=T1, recorded_at=T1, deleted=True),),
    )

    before = graph_at((baseline, removal), as_of=T0, known_at=T2)
    after = graph_at((baseline, removal), as_of=T1, known_at=T2)
    change = topology_diff(before, after)

    assert before.complete is True
    assert len(before.graph.links) == 1
    assert after.complete is True
    assert after.graph.links == ()
    assert change.removed_link_keys == ("vnet-a|peered_with|vnet-b",)
    assert change.complete is True
    assert change.digest.startswith("sha256:")


def test_known_at_replay_excludes_late_evidence_without_rewriting_prior_view() -> None:
    baseline = TopologyRevisionBatch(
        revision_id="revision-1",
        provider_generation_ref="provider-generation-1",
        effective_at=T0,
        recorded_at=T0,
        complete_snapshot=True,
        ontology_release_digest=RELEASE_DIGEST,
        source_receipt_digest=RELEASE_DIGEST,
        object_revisions=(_object("vnet-a", effective_at=T0, recorded_at=T0),),
    )
    late_correction = TopologyRevisionBatch(
        revision_id="revision-3",
        provider_generation_ref="provider-generation-late",
        effective_at=T0,
        recorded_at=T3,
        complete_snapshot=False,
        ontology_release_digest=RELEASE_DIGEST,
        source_receipt_digest=RELEASE_DIGEST,
        object_revisions=(_object("vnet-a", effective_at=T0, recorded_at=T3, name="corrected"),),
    )

    original = graph_at((baseline, late_correction), as_of=T0, known_at=T2)
    revised = graph_at((baseline, late_correction), as_of=T0, known_at=T3)
    replay = graph_at((baseline, late_correction), as_of=T0, known_at=T2)

    assert original.graph.objects[0].properties["name"] == "vnet-a"
    assert revised.graph.objects[0].properties["name"] == "corrected"
    assert replay.digest == original.digest
    assert revised.digest != original.digest


def test_history_without_complete_baseline_cannot_prove_absence() -> None:
    delta = TopologyRevisionBatch(
        revision_id="revision-delta",
        provider_generation_ref="provider-generation-delta",
        effective_at=T1,
        recorded_at=T1,
        complete_snapshot=False,
        ontology_release_digest=RELEASE_DIGEST,
        source_receipt_digest=RELEASE_DIGEST,
        object_revisions=(_object("vnet-a", effective_at=T1, recorded_at=T1),),
    )

    result = graph_at((delta,), as_of=T1, known_at=T2)

    assert result.complete is False
    assert len(result.graph.objects) == 1


def test_dangling_active_link_lowers_replay_completeness() -> None:
    baseline = TopologyRevisionBatch(
        revision_id="revision-dangling",
        provider_generation_ref="provider-generation-dangling",
        effective_at=T0,
        recorded_at=T0,
        complete_snapshot=True,
        ontology_release_digest=RELEASE_DIGEST,
        source_receipt_digest=RELEASE_DIGEST,
        object_revisions=(_object("vnet-a", effective_at=T0, recorded_at=T0),),
        link_revisions=(_peering(effective_at=T0, recorded_at=T0),),
    )

    result = graph_at((baseline,), as_of=T0, known_at=T0)

    assert result.graph.links == ()
    assert result.complete is False


def test_missing_or_mixed_release_bindings_lower_replay_completeness() -> None:
    baseline = TopologyRevisionBatch(
        revision_id="revision-release",
        provider_generation_ref="provider-generation-release",
        effective_at=T0,
        recorded_at=T0,
        complete_snapshot=True,
        ontology_release_digest=RELEASE_DIGEST,
        source_receipt_digest=RELEASE_DIGEST,
        object_revisions=(_object("vnet-a", effective_at=T0, recorded_at=T0),),
    )
    missing = replace(baseline, revision_id="revision-missing", ontology_release_digest=None)
    mixed = replace(
        baseline,
        revision_id="revision-mixed",
        complete_snapshot=False,
        effective_at=T1,
        recorded_at=T1,
        object_revisions=(),
        ontology_release_digest="sha256:" + ("b" * 64),
    )

    assert graph_at((missing,), as_of=T0, known_at=T0).complete is False
    assert graph_at((baseline, mixed), as_of=T1, known_at=T1).complete is False


def test_missing_source_receipt_lowers_replay_completeness() -> None:
    baseline = TopologyRevisionBatch(
        revision_id="revision-source-receipt",
        provider_generation_ref="provider-generation-source-receipt",
        effective_at=T0,
        recorded_at=T0,
        complete_snapshot=True,
        ontology_release_digest=RELEASE_DIGEST,
        source_receipt_digest=RELEASE_DIGEST,
        object_revisions=(_object("vnet-a", effective_at=T0, recorded_at=T0),),
    )
    missing = replace(baseline, revision_id="revision-source-missing", source_receipt_digest=None)

    assert graph_at((missing,), as_of=T0, known_at=T0).complete is False
    assert graph_at((baseline,), as_of=T0, known_at=T0).complete is True


def test_graph_digest_binds_to_canonical_source_receipt_field() -> None:
    baseline = TopologyRevisionBatch(
        revision_id="revision-digest-a",
        provider_generation_ref="provider-generation-digest-a",
        effective_at=T0,
        recorded_at=T0,
        complete_snapshot=True,
        ontology_release_digest=RELEASE_DIGEST,
        source_receipt_digest=RELEASE_DIGEST,
        object_revisions=(_object("vnet-a", effective_at=T0, recorded_at=T0),),
    )
    duplicate_receipt = replace(
        baseline,
        revision_id="revision-digest-b",
        complete_snapshot=False,
        effective_at=T1,
        recorded_at=T1,
        object_revisions=(_object("vnet-b", effective_at=T1, recorded_at=T1),),
    )

    result = graph_at((baseline, duplicate_receipt), as_of=T1, known_at=T1)

    assert result.source_receipt_digests == (RELEASE_DIGEST,)
    recomputed_body = {
        "as_of": T1.astimezone(UTC).isoformat(),
        "known_at": T1.astimezone(UTC).isoformat(),
        "objects": [
            {
                "id": item.id,
                "object_type": item.object_type,
                "properties": item.properties,
                "revision": item.revision,
            }
            for item in result.graph.objects
        ],
        "links": [],
        "complete": result.complete,
        "revision_ids": list(result.revision_ids),
        "provider_generation_refs": list(result.provider_generation_refs),
        "evidence_refs": result.evidence_refs,
        "ontology_release_digests": result.ontology_release_digests,
        "source_receipt_digests": result.source_receipt_digests,
    }
    assert _digest(recomputed_body) == result.digest


async def test_topology_query_handlers_materialize_and_diff_retained_views() -> None:
    baseline = TopologyRevisionBatch(
        revision_id="revision-1",
        provider_generation_ref="provider-generation-1",
        effective_at=T0,
        recorded_at=T0,
        complete_snapshot=True,
        ontology_release_digest=RELEASE_DIGEST,
        source_receipt_digest=RELEASE_DIGEST,
        object_revisions=(
            _object("vnet-a", effective_at=T0, recorded_at=T0),
            _object("vnet-b", effective_at=T0, recorded_at=T0),
        ),
        link_revisions=(_peering(effective_at=T0, recorded_at=T0),),
    )
    removal = TopologyRevisionBatch(
        revision_id="revision-2",
        provider_generation_ref="provider-generation-2",
        effective_at=T1,
        recorded_at=T1,
        complete_snapshot=False,
        ontology_release_digest=RELEASE_DIGEST,
        source_receipt_digest=RELEASE_DIGEST,
        link_revisions=(_peering(effective_at=T1, recorded_at=T1, deleted=True),),
    )
    at_handler = TopologyAtNodeHandler(_Reader((baseline, removal)))

    async def materialize(node_id: str, at: datetime) -> QueryNodeResult:
        return await at_handler(
            OntologyQueryNode(
                node_id=node_id,
                kind=QueryNodeKind.TOPOLOGY_AT,
                arguments_json=canonical_json(
                    {"as_of": at.isoformat(), "known_at": T2.isoformat()}
                ),
                output_kind="topology.graph",
            ),
            {},
        )

    before = await materialize("before", T0)
    after = await materialize("after", T1)
    result = await TopologyDiffNodeHandler()(
        OntologyQueryNode(
            node_id="change",
            kind=QueryNodeKind.TOPOLOGY_DIFF,
            depends_on=("before", "after"),
            output_kind="topology.diff",
        ),
        {"before": before, "after": after},
    )

    assert isinstance(result.value, TopologyDiff)
    assert result.value.removed_link_keys == ("vnet-a|peered_with|vnet-b",)
    assert result.evidence_refs[-1].startswith("topology-diff:sha256:")
