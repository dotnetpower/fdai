"""Bounded actual-observation contracts preserve canonical legacy and new receipts."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import cast

import pytest
from fdai.core.rca.discrimination import (
    build_hypothesis_discrimination_frame,
    select_discriminating_observation,
)
from fdai.core.rca.hypothesis import (
    CausalClosure,
    CausalEvidenceAssessment,
    CausalHypothesisRecord,
    build_causal_hypothesis,
    close_causal_hypothesis,
)
from fdai.core.rca.observation_history import (
    HypothesisObservation,
    ObservationOutcome,
    history_from_mapping,
    history_material,
    validate_history,
    validate_transition,
)
from fdai.core.rca.projection import (
    CausalHypothesisProjector,
    CausalProjectionConflictError,
)
from fdai.shared.contracts.models import CausalEvidenceGrade
from fdai.shared.providers.ontology_instance import (
    OntologyInstanceStore,
    OntologyLinkRecord,
    OntologyObjectRecord,
)


def observation(key="hypothesis:a", outcome=ObservationOutcome.SUPPORTED):
    return HypothesisObservation(
        key,
        outcome,
        "telemetry-receipt:sha256:" + "a" * 64,
        "sha256:" + "b" * 64,
    )


def frame(history=(), active=("hypothesis:a",)):
    return build_hypothesis_discrimination_frame(
        incident_id="incident:one",
        graph_revision="graph:one",
        evidence_cutoff=datetime(2026, 10, 16, tzinfo=UTC),
        active_hypothesis_ids=active,
        active_set_receipt_digest="sha256:" + "c" * 64,
        cost_model_digest="sha256:" + "d" * 64,
        observation_history=history,
    )


def test_history_roundtrip_is_exact_and_digest_bound():
    known = (observation(),)
    assert history_from_mapping(history_material(known)) == known
    assert frame().frame_digest != frame(known).frame_digest
    assert (
        frame(known).frame_digest
        != frame(
            (
                replace(
                    known[0],
                    evidence_ref="telemetry-receipt:sha256:" + "e" * 64,
                ),
            )
        ).frame_digest
    )
    assert (
        select_discriminating_observation(frame(), ()).hold_reason.value
        == "insufficient_hypotheses"
    )


@pytest.mark.parametrize("kind", ["duplicate", "order", "size", "shape", "unknown_fields"])
def test_invalid_history_shapes_fail_explicitly(kind):
    with pytest.raises(ValueError):
        if kind == "duplicate":
            validate_history((observation(), observation()))
        elif kind == "order":
            validate_history((observation("hypothesis:b"), observation("hypothesis:a")))
        elif kind == "size":
            validate_history(tuple(observation(f"hypothesis:{i:02}") for i in range(33)))
        elif kind == "shape":
            history_from_mapping("not-a-list")
        else:
            history_from_mapping([{**history_material((observation(),))[0], "extra": "forged"}])


@pytest.mark.parametrize("outcome", [ObservationOutcome.SUPPORTED, ObservationOutcome.UNKNOWN])
def test_observed_non_refuted_hypotheses_cannot_be_removed_from_frame(outcome):
    with pytest.raises(ValueError, match="active hypothesis set disagrees"):
        frame((observation("hypothesis:other", outcome),))


def test_refuted_hypothesis_cannot_remain_in_active_frame():
    with pytest.raises(ValueError, match="active hypothesis set disagrees"):
        frame((observation(outcome=ObservationOutcome.REFUTED),))


def test_history_from_mapping_accepts_tuple_and_resolve_citation_dedupes() -> None:
    from fdai.core.rca.citations import resolve_citation
    from fdai.core.rca.contract import Citation, CitationKind

    known = (observation(),)
    assert history_from_mapping(tuple(history_material(known))) == known
    c = Citation(kind=CitationKind.TELEMETRY, ref="log:1")
    assert resolve_citation("  telemetry:log:1  ", (c, c)) == c


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"hypothesis_id": "   "}, "hypothesis_id MUST be exact bounded text"),
        ({"hypothesis_id": " padded "}, "hypothesis_id MUST be exact bounded text"),
        ({"evidence_ref": ""}, "evidence_ref MUST be exact bounded text"),
        ({"outcome": "supported"}, "outcome MUST be typed"),
        ({"result_digest": "invalid"}, "result digest MUST be SHA-256"),
        ({"result_digest": "sha256:" + "G" * 64}, "result digest MUST be SHA-256"),
    ],
)
def test_hypothesis_observation_rejects_invalid_fields(
    kwargs: dict[str, object],
    match: str,
) -> None:
    base: dict[str, object] = {
        "hypothesis_id": "hypothesis:a",
        "outcome": ObservationOutcome.SUPPORTED,
        "evidence_ref": "telemetry-receipt:sha256:" + "a" * 64,
        "result_digest": "sha256:" + "b" * 64,
    }
    base.update(kwargs)
    with pytest.raises(ValueError, match=match):
        HypothesisObservation(**base)  # type: ignore[arg-type]


def test_history_from_mapping_rejects_non_text_field_and_transition_validates() -> None:
    raw = [{**history_material((observation(),))[0], "hypothesis_id": 123}]
    with pytest.raises(ValueError, match="fields MUST be text"):
        history_from_mapping(raw)

    assert (
        validate_transition(
            (),
            (),
            active_ids=("hypothesis:a",),
            result_digest="sha256:" + "b" * 64,
            evidence_refs=("telemetry-receipt:sha256:" + "a" * 64,),
        )
        is None
    )

    obs_a = observation("hypothesis:a")
    obs_b = observation("hypothesis:b")
    added = validate_transition(
        (obs_a,),
        (obs_a, obs_b),
        active_ids=("hypothesis:a", "hypothesis:b"),
        result_digest=obs_b.result_digest,
        evidence_refs=(obs_b.evidence_ref,),
    )
    assert added == obs_b

    with pytest.raises(ValueError, match="rewrote observation history"):
        validate_transition(
            (obs_a,),
            (observation("hypothesis:a", ObservationOutcome.REFUTED),),
            active_ids=("hypothesis:a",),
            result_digest=obs_a.result_digest,
            evidence_refs=(obs_a.evidence_ref,),
        )
    with pytest.raises(ValueError, match="exactly one new observation"):
        validate_transition(
            (obs_a,),
            (obs_a,),
            active_ids=("hypothesis:a",),
            result_digest=obs_a.result_digest,
            evidence_refs=(obs_a.evidence_ref,),
        )
    with pytest.raises(ValueError, match="does not match the current verified execution"):
        validate_transition(
            (),
            (obs_a,),
            active_ids=("hypothesis:other",),
            result_digest=obs_a.result_digest,
            evidence_refs=(obs_a.evidence_ref,),
        )


class _MemoryOntologyStore:
    def __init__(self, existing: OntologyObjectRecord | None = None) -> None:
        self.existing = existing
        self.calls: list[
            tuple[tuple[OntologyObjectRecord, ...], tuple[OntologyLinkRecord, ...]]
        ] = []

    async def get_object(self, _object_id: str) -> OntologyObjectRecord | None:
        return self.existing

    async def replace_subgraph(
        self,
        *,
        objects: tuple[OntologyObjectRecord, ...],
        links: tuple[OntologyLinkRecord, ...],
        **_kwargs: object,
    ) -> None:
        self.calls.append((objects, links))


def _causal_hypothesis() -> CausalHypothesisRecord:
    now = datetime(2026, 8, 12, tzinfo=UTC)
    return build_causal_hypothesis(
        incident_id="incident-1",
        cause_ref="run-1",
        effect_ref="effect-1",
        mechanism="scale_reduces_latency",
        graph_revision="graph-1",
        evidence_cutoff=now,
        method_version="causal-v1",
        evidence_grade=CausalEvidenceGrade.PREDICTIVE_PRECEDENCE,
        assessment=CausalEvidenceAssessment(
            temporal_precedence=1.0,
            topological_reachability=1.0,
            mechanism_fit=1.0,
            intervention_consistency=0.5,
            evidence_completeness=1.0,
            supporting_refs=("support-1",),
            refuting_refs=("refute-1",),
        ),
        created_at=now,
    )


async def test_causal_hypothesis_projector_covers_links_idempotence_and_errors() -> None:
    hyp = _causal_hypothesis()
    revised = close_causal_hypothesis(
        hyp,
        closure=CausalClosure.INCONCLUSIVE,
        outcome_ref="outcome-1",
        created_at=datetime(2026, 8, 12, 0, 5, tzinfo=UTC),
    )
    store = _MemoryOntologyStore()
    projector = CausalHypothesisProjector(store=cast(OntologyInstanceStore, store))

    await projector.project(
        hyp,
        finding_id="finding-1",
        change_ids=("change-1",),
        experiment_ids=("exp-1",),
        supporting_evidence_ids=("support-1",),
        refuting_evidence_ids=("refute-1",),
        outcome_ids=("outcome-1",),
        informed_expected_effect_ids=("effect-1",),
    )
    await projector.project(
        revised,
        finding_id="finding-1",
        previous_hypothesis_id=hyp.hypothesis_id,
    )
    assert len(store.calls) == 2

    record = hyp.to_ontology_object()
    idempotent_store = _MemoryOntologyStore(existing=record)
    await CausalHypothesisProjector(store=cast(OntologyInstanceStore, idempotent_store)).project(
        hyp, finding_id="finding-1"
    )
    assert idempotent_store.calls == []

    conflicting = OntologyObjectRecord(
        id=record.id,
        object_type="other_type",
        properties=record.properties,
    )
    conflict_store = _MemoryOntologyStore(existing=conflicting)
    with pytest.raises(CausalProjectionConflictError, match="content changed"):
        await CausalHypothesisProjector(store=cast(OntologyInstanceStore, conflict_store)).project(
            hyp, finding_id="finding-1"
        )

    with pytest.raises(ValueError, match="finding_id MUST be non-empty"):
        await projector.project(hyp, finding_id="  ")
    with pytest.raises(ValueError, match="previous_hypothesis_id MUST be non-empty"):
        await projector.project(hyp, finding_id="finding-1", previous_hypothesis_id="  ")
    with pytest.raises(ValueError, match="same hypothesis"):
        await projector.project(
            hyp,
            finding_id="finding-1",
            previous_hypothesis_id=hyp.hypothesis_id,
        )
    with pytest.raises(ValueError, match="change_ids MUST contain non-empty strings"):
        await projector.project(hyp, finding_id="finding-1", change_ids=("",))
