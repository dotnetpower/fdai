"""Tests for the manual classifier seam (contract + abstaining default)."""

from __future__ import annotations

import pytest

from fdai.shared.providers.manual_classifier import (
    AbstainingManualClassifier,
    ClassifiedManual,
    ManualClassifier,
    ProcedureVerdict,
)
from fdai.shared.providers.manual_source import ManualCandidate


def _cand(doc_id: str) -> ManualCandidate:
    return ManualCandidate(doc_id=doc_id, source_ref=f"drop://{doc_id}")


def test_abstaining_classifier_satisfies_protocol() -> None:
    assert isinstance(AbstainingManualClassifier(), ManualClassifier)


async def test_abstaining_classifier_marks_all_uncertain() -> None:
    cands = [_cand("a"), _cand("b")]
    result = await AbstainingManualClassifier().classify(cands)
    assert [r.candidate.doc_id for r in result] == ["a", "b"]
    assert all(r.verdict is ProcedureVerdict.UNCERTAIN for r in result)


async def test_abstaining_classifier_empty_input() -> None:
    assert await AbstainingManualClassifier().classify([]) == ()


def test_confidence_bounds_enforced() -> None:
    with pytest.raises(ValueError, match="within"):
        ClassifiedManual(_cand("a"), ProcedureVerdict.PROCEDURE, confidence=1.5)
    with pytest.raises(ValueError, match="within"):
        ClassifiedManual(_cand("a"), ProcedureVerdict.PROCEDURE, confidence=-0.1)
