"""Causal-grade receipts keep temporal coincidence below cause claims."""

from __future__ import annotations

from pathlib import Path

import yaml
from fdai.core.conversation.causal_grade_receipts import (
    CausalMechanismSpec,
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
        refutation_reads_run=_mechanism().refutation_reads,
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
        refutation_reads_run=_mechanism().refutation_reads,
    )

    assert single.grade is CausalEvidenceGrade.ASSOCIATION
    assert missing_refutation.grade is CausalEvidenceGrade.ASSOCIATION
    assert predictive.grade is CausalEvidenceGrade.PREDICTIVE_PRECEDENCE
    assert not supports_causal_hypothesis(single)
    assert not supports_causal_hypothesis(missing_refutation)
    assert supports_causal_hypothesis(predictive)


def _predictive(**overrides: object) -> CausalEvidenceGrade:
    mechanism = _mechanism()
    arguments: dict[str, object] = {
        "mechanism": mechanism,
        "repeated_sample_count": 3,
        "reverse_direction_checked": True,
        "confounder_checked": True,
        "complete_windows": True,
        "mechanism_evidence_refs": ("evidence:mechanism",),
        "refutation_refs": ("evidence:refutation",),
        "refutation_reads_run": mechanism.refutation_reads,
    }
    arguments.update(overrides)
    return causal_grade_receipt(**arguments).grade  # type: ignore[arg-type]


def test_every_refutation_read_must_be_run_and_none_may_refute() -> None:
    reads = _mechanism().refutation_reads

    assert _predictive() is CausalEvidenceGrade.PREDICTIVE_PRECEDENCE
    # One refutation read silently left out keeps the grade at association.
    assert _predictive(refutation_reads_run=reads[:1]) is CausalEvidenceGrade.ASSOCIATION
    assert _predictive(refuted_reads=reads[:1]) is CausalEvidenceGrade.ASSOCIATION


def test_required_evidence_the_receipt_cannot_check_must_be_named_present() -> None:
    mechanism = CausalMechanismSpec(
        mechanism_id="extra_evidence",
        required_evidence=("deployment_record", "repeated_samples"),
        refutation_reads=("peer_window",),
    )
    base = {
        "mechanism": mechanism,
        "refutation_reads_run": ("peer_window",),
    }

    assert _predictive(**base) is CausalEvidenceGrade.ASSOCIATION
    assert (
        _predictive(**base, present_evidence=("deployment_record",))
        is CausalEvidenceGrade.PREDICTIVE_PRECEDENCE
    )
