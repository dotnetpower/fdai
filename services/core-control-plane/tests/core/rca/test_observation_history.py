"""Bounded actual-observation contracts preserve canonical legacy and new receipts."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fdai.core.rca.discrimination import (
    build_hypothesis_discrimination_frame,
    select_discriminating_observation,
)
from fdai.core.rca.observation_history import (
    HypothesisObservation,
    ObservationOutcome,
    history_from_mapping,
    history_material,
    validate_history,
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
