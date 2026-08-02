"""Tests for the manual-distillation seam (contracts + abstaining default)."""

from __future__ import annotations

import pytest

from fdai.shared.providers.distiller import (
    AbstainingDistiller,
    CandidateKind,
    CoverageGap,
    CoverageReport,
    DistillationResult,
    DistilledCandidate,
    Distiller,
    ManualDocument,
)


def _candidate(**over: object) -> DistilledCandidate:
    base: dict[str, object] = {
        "kind": CandidateKind.RULE,
        "candidate_id": "cand-1",
        "source_ref": "manual://runbook#storage",
        "source_section": "Storage",
        "source_lines": (3, 5),
    }
    base.update(over)
    return DistilledCandidate(**base)  # type: ignore[arg-type]


async def test_abstaining_distiller_returns_empty_result() -> None:
    doc = ManualDocument(doc_id="d1", text="anything", source_ref="manual://d1")
    result = await AbstainingDistiller().distill(doc)
    assert result.candidates == ()
    assert result.coverage.total == 0
    assert result.coverage.coverage_ratio == 1.0


def test_abstaining_distiller_satisfies_protocol() -> None:
    assert isinstance(AbstainingDistiller(), Distiller)


def test_candidate_rejects_zero_based_or_inverted_lines() -> None:
    with pytest.raises(ValueError, match="1-based inclusive"):
        _candidate(source_lines=(0, 2))
    with pytest.raises(ValueError, match="1-based inclusive"):
        _candidate(source_lines=(5, 3))


def test_candidate_accepts_single_line_range() -> None:
    cand = _candidate(source_lines=(7, 7))
    assert cand.source_lines == (7, 7)


def test_coverage_ratio_empty_manual_is_full() -> None:
    assert CoverageReport(total=0, covered=0).coverage_ratio == 1.0


def test_coverage_ratio_partial() -> None:
    report = CoverageReport(
        total=4,
        covered=1,
        gaps=(CoverageGap(line=2, text="must not expose", kind="imperative"),),
    )
    assert report.coverage_ratio == pytest.approx(0.25)


def test_distillation_result_defaults() -> None:
    result = DistillationResult()
    assert result.candidates == ()
    assert isinstance(result.coverage, CoverageReport)


def test_candidate_kind_values() -> None:
    assert {k.value for k in CandidateKind} == {
        "rule",
        "workflow",
        "action_type",
        "policy",
        "ontology_object",
        "ontology_link",
    }
