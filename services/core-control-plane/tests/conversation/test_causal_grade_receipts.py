"""Causal-grade receipts keep temporal coincidence below cause claims."""

from __future__ import annotations

from pathlib import Path

import yaml
from fdai.core.conversation.causal_grade_receipts import (
    causal_grade_receipt,
    load_causal_mechanism_catalog,
    supports_causal_hypothesis,
)
from fdai.shared.contracts.models import CausalEvidenceGrade


def _mechanism():
    catalog_path = (
        Path(__file__).resolve().parents[4]
        / "rule-catalog"
        / "vocabulary"
        / "causal-mechanisms.yaml"
    )
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    return load_causal_mechanism_catalog(catalog)[0]


def test_predictive_precedence_requires_refutation_and_confounder_accounting() -> None:
    mechanism = _mechanism()
    single = causal_grade_receipt(
        mechanism=mechanism,
        repeated_sample_count=1,
        reverse_direction_checked=True,
        confounder_checked=True,
        complete_windows=True,
        mechanism_evidence_refs=("evidence:mechanism",),
        refutation_refs=("evidence:refutation",),
    )
    missing_refutation = causal_grade_receipt(
        mechanism=mechanism,
        repeated_sample_count=3,
        reverse_direction_checked=True,
        confounder_checked=True,
        complete_windows=True,
        mechanism_evidence_refs=("evidence:mechanism",),
        refutation_refs=(),
        missing_refutation_reads=("unchanged_peer_activity_window",),
    )
    predictive = causal_grade_receipt(
        mechanism=mechanism,
        repeated_sample_count=3,
        reverse_direction_checked=True,
        confounder_checked=True,
        complete_windows=True,
        mechanism_evidence_refs=("evidence:mechanism",),
        refutation_refs=("evidence:refutation",),
    )

    assert single.grade is CausalEvidenceGrade.ASSOCIATION
    assert missing_refutation.grade is CausalEvidenceGrade.ASSOCIATION
    assert predictive.grade is CausalEvidenceGrade.PREDICTIVE_PRECEDENCE
    assert not supports_causal_hypothesis(single)
    assert not supports_causal_hypothesis(missing_refutation)
    assert supports_causal_hypothesis(predictive)
