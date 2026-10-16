"""Historical incident graphs use event and knowledge time without current-state fallback."""

from __future__ import annotations

import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.ontology_platform.topology_history import (
    TopologyLinkRevision,
    TopologyObjectRevision,
    TopologyRevisionBatch,
)
from fdai.core.rca.historical_graph import HistoricalCausalIncidentGraphMaterializer
from fdai.core.rca.incident_graph import IncidentGraphBounds
from fdai.shared.providers.ontology_instance import OntologyObjectRecord
from fdai.shared.providers.state_evidence import (
    LINK_OBSERVATION_METADATA_PROPERTY,
    LinkObservationMetadata,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)
from fdai_service_contracts.ontology_query import canonical_json

AT = datetime(2026, 10, 16, tzinfo=UTC)
RELEASE = "sha256:" + "a" * 64


class History:
    def __init__(self, batches):
        self.batches = batches

    async def read(self, *, as_of, known_at):
        return self.batches


def batch(*, recorded=AT, generation="generation:one", deleted=False):
    fact = StateFactMetadata(
        lane=StateFactLane.OBSERVED,
        authority=StateFactAuthority.PROVIDER,
        source_identity="provider:one",
        source_revision="schema:one",
        effective_at=AT,
        recorded_at=recorded,
        evidence_cutoff=AT,
        freshness_ceiling_seconds=3600,
        completeness=1.0,
        synthetic=False,
        evidence_refs=("evidence:link",),
    )
    metadata = LinkObservationMetadata(
        state_fact=fact,
        verified=True,
        verification_method="provider-readback",
        verifier_identity="verifier:one",
        verifier_revision="1",
        verification_receipt_ref="receipt:one",
    )
    return TopologyRevisionBatch(
        revision_id=f"revision:{generation}",
        provider_generation_ref=generation,
        effective_at=AT,
        recorded_at=recorded,
        complete_snapshot=True,
        ontology_release_digest=RELEASE,
        source_receipt_digest="sha256:" + "b" * 64,
        object_revisions=tuple(
            TopologyObjectRevision.upsert(
                OntologyObjectRecord(key, "Resource", {"id": key}),
                effective_at=AT,
                recorded_at=recorded,
                evidence_ref=f"evidence:{key}",
            )
            for key in ("app", "db")
        ),
        link_revisions=(
            TopologyLinkRevision(
                from_id="app",
                from_type="Resource",
                link_type="depends_on",
                to_id="db",
                to_type="Resource",
                properties_json="{}"
                if deleted
                else canonical_json(
                    {
                        LINK_OBSERVATION_METADATA_PROPERTY: metadata.to_mapping(),
                    }
                ),
                effective_at=AT,
                recorded_at=recorded,
                deleted=deleted,
                evidence_ref="evidence:link",
            ),
        ),
    )


async def materialize(batches, **changes):
    options = dict(
        incident_id="incident:one",
        root_ids=("app",),
        evidence_cutoff=AT,
        known_at=AT,
    )
    options.update(changes)
    return await HistoricalCausalIncidentGraphMaterializer(
        history=History(batches),
        release_digest=RELEASE,
    ).materialize(**options)


async def test_complete_retained_generation_is_historical_and_replay_stable():
    one = await materialize((batch(),))
    two = await materialize((batch(),))
    assert one.complete and one == two
    assert one.known_at == AT
    assert one.provider_generation_refs == ("generation:one",)
    assert one.active_provider_generation == "generation:one"
    assert len(one.snapshot.links) == 1
    assert "historical_topology_unavailable" not in one.incomplete_reasons
    assert one.source_evidence_refs


async def test_late_recorded_evidence_requires_explicit_later_knowledge():
    late = batch(recorded=AT + timedelta(minutes=1))
    unknown = await materialize((late,))
    known = await materialize((late,), known_at=late.recorded_at)
    assert not unknown.complete
    assert known.complete and len(known.snapshot.links) == 1
    assert unknown.graph_revision != known.graph_revision


async def test_historical_deletion_never_uses_current_or_future_relationship():
    baseline = batch()
    removal = replace(
        batch(generation="generation:two", deleted=True, recorded=AT + timedelta(minutes=1)),
        effective_at=AT + timedelta(minutes=1),
        complete_snapshot=False,
        object_revisions=(),
        link_revisions=tuple(
            replace(
                link,
                effective_at=AT + timedelta(minutes=1),
                recorded_at=AT + timedelta(minutes=1),
            )
            for link in batch(deleted=True).link_revisions
        ),
    )
    before = await materialize((baseline, removal), known_at=AT + timedelta(minutes=2))
    after = await materialize(
        (baseline, removal),
        evidence_cutoff=AT + timedelta(minutes=1),
        known_at=AT + timedelta(minutes=2),
    )
    assert before.complete and len(before.snapshot.links) == 1
    assert after.complete and not after.snapshot.links


@pytest.mark.parametrize("field", ["ontology_release_digest", "source_receipt_digest"])
async def test_missing_release_or_source_receipt_never_claims_completeness(field):
    result = await materialize((replace(batch(), **{field: None}),))
    assert not result.complete


async def test_changed_release_invalid_link_and_missing_root_hold():
    wrong_release = await materialize(
        (replace(batch(), ontology_release_digest="sha256:" + "c" * 64),)
    )
    assert "historical_release_mismatch" in wrong_release.incomplete_reasons
    original = batch()
    invalid = replace(original.link_revisions[0], properties_json="{}")
    result = await materialize((replace(original, link_revisions=(invalid,)),))
    assert not result.complete and result.snapshot.links == ()
    assert "link_metadata_missing" in result.incomplete_reasons
    missing = await materialize((original,), root_ids=("unknown",))
    assert not missing.complete and missing.snapshot.objects == ()


async def test_depth_byte_and_time_bounds_are_not_silent():
    with pytest.raises(ValueError, match="max_bytes"):
        await materialize((batch(),), bounds=IncidentGraphBounds(max_bytes=1))
    with pytest.raises(ValueError, match="MUST NOT exceed known_at"):
        await materialize((batch(),), known_at=AT - timedelta(seconds=1))
    with pytest.raises(ValueError, match="release digest"):
        HistoricalCausalIncidentGraphMaterializer(history=History(()), release_digest="latest")


async def test_equal_time_conflicting_revisions_hold_instead_of_choosing_lexical_winner():
    baseline = batch()
    changed = replace(baseline.object_revisions[0], properties_json='{"id":"app","name":"changed"}')
    delta = replace(
        baseline,
        revision_id="revision:zzzz-delta",
        complete_snapshot=False,
        object_revisions=(changed,),
        link_revisions=(),
    )
    result = await materialize((baseline, delta))
    assert not result.complete
    assert "historical_equal_time_conflict" in result.incomplete_reasons


async def test_unrelated_invalid_properties_do_not_poison_selected_neighborhood():
    baseline = batch()
    unrelated = TopologyObjectRevision.upsert(
        OntologyObjectRecord(
            "unrelated",
            "Resource",
            {"id": "unrelated", "observed_at": "not-a-time"},
        ),
        effective_at=AT,
        recorded_at=AT,
        evidence_ref="evidence:unrelated",
    )
    result = await materialize(
        (
            replace(
                baseline,
                object_revisions=(*baseline.object_revisions, unrelated),
            ),
        )
    )
    assert result.complete
    assert {record.id for record in result.snapshot.objects} == {"app", "db"}


async def test_retained_link_endpoint_types_must_match_selected_objects():
    original = batch()
    changed = replace(original.link_revisions[0], from_type="Change")
    result = await materialize((replace(original, link_revisions=(changed,)),))
    assert not result.complete
    assert "historical_endpoint_type_mismatch" in result.incomplete_reasons


@pytest.mark.parametrize("complete_snapshot", [False, True])
async def test_competing_same_time_snapshots_or_tombstones_cannot_hide_conflicts(complete_snapshot):
    original = batch()
    alternate = replace(
        original,
        revision_id="revision:zzzz-conflict",
        complete_snapshot=complete_snapshot,
        link_revisions=(
            ()
            if complete_snapshot
            else (replace(original.link_revisions[0], deleted=True, properties_json="{}"),)
        ),
    )
    result = await materialize((original, alternate))
    assert not result.complete
    assert "historical_equal_time_conflict" in result.incomplete_reasons


async def test_synchronous_history_rebuild_cannot_succeed_after_deadline(
    monkeypatch,
):
    from fdai.core.rca import historical_graph

    original = historical_graph.graph_at

    def slow(*args, **kwargs):
        time.sleep(0.01)
        return original(*args, **kwargs)

    monkeypatch.setattr(historical_graph, "graph_at", slow)
    with pytest.raises(TimeoutError, match="exceeded its deadline"):
        await materialize((batch(),), bounds=IncidentGraphBounds(timeout_seconds=0.001))


async def test_deleted_endpoint_does_not_invalidate_surviving_dependency():
    baseline = batch()
    cache = replace(
        baseline.object_revisions[1],
        object_id="cache",
        properties_json='{"id":"cache"}',
    )
    baseline = replace(
        baseline,
        object_revisions=(*baseline.object_revisions, cache),
        link_revisions=(
            *baseline.link_revisions,
            replace(baseline.link_revisions[0], to_id="cache"),
        ),
    )
    later = AT + timedelta(minutes=1)
    delta = replace(
        baseline,
        revision_id="revision:deleted",
        provider_generation_ref="generation:two",
        effective_at=later,
        recorded_at=later,
        complete_snapshot=False,
        object_revisions=(
            replace(
                baseline.object_revisions[1],
                effective_at=later,
                recorded_at=later,
                deleted=True,
                properties_json="{}",
            ),
        ),
        link_revisions=(
            replace(
                baseline.link_revisions[0],
                effective_at=later,
                recorded_at=later,
                deleted=True,
                properties_json="{}",
            ),
        ),
    )
    result = await materialize((baseline, delta), evidence_cutoff=later, known_at=later)
    assert result.complete
    assert [(link.from_id, link.to_id) for link in result.snapshot.links] == [("app", "cache")]


async def test_active_generation_follows_effective_time_not_late_record_order():
    baseline = batch()
    later = AT + timedelta(minutes=1)
    newer = replace(
        baseline,
        revision_id="revision:new",
        provider_generation_ref="generation:new",
        complete_snapshot=False,
        effective_at=later,
        recorded_at=later,
        link_revisions=(),
        object_revisions=(
            replace(
                baseline.object_revisions[1],
                effective_at=later,
                recorded_at=later,
                properties_json='{"id":"db","name":"new"}',
            ),
        ),
    )
    late = replace(
        baseline,
        revision_id="revision:late-old",
        provider_generation_ref="generation:old",
        complete_snapshot=False,
        recorded_at=later + timedelta(minutes=1),
        link_revisions=(),
        object_revisions=(
            replace(
                baseline.object_revisions[1],
                recorded_at=later + timedelta(minutes=1),
            ),
        ),
    )
    result = await materialize(
        (baseline, late, newer),
        evidence_cutoff=later,
        known_at=later + timedelta(minutes=2),
    )
    assert result.complete
    assert result.provider_generation_refs[-1] == "generation:old"
    assert result.active_provider_generation == "generation:new"
