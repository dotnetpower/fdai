"""Focused integrity and artifact-boundary tests for the local shadow cohort."""

from __future__ import annotations

from pathlib import Path

import pytest
from fdai.core.standing_authority.promotion_candidate import DenialReason
from fdai.core.standing_authority.shadow_cohort_runner import (
    CohortArtifactWriter,
    CohortCaseInput,
    run_cohort,
)
from tests.core.standing_authority.test_shadow_cohort_runner import (
    _external_denial,
    _make_full_corpus,
)


def test_corpus_digest_binds_review_and_external_denial_inputs() -> None:
    manifest, corpus, elapsed = _make_full_corpus()
    original = run_cohort(manifest, corpus, elapsed)
    first = corpus[0]
    changed_first = CohortCaseInput(
        case_id=first.case_id,
        record=first.record,
        review_steps=(),
        external_denial=_external_denial(DenialReason.EXPIRED),
    )
    changed = run_cohort(manifest, (changed_first,) + corpus[1:], elapsed)

    assert changed.corpus_digest != original.corpus_digest


def test_write_receipt_rejects_predictable_symlink_target(tmp_path: Path) -> None:
    manifest, corpus, elapsed = _make_full_corpus()
    receipt = run_cohort(manifest, corpus, elapsed)
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    outside = tmp_path / "outside.json"
    filename = f"cohort-receipt-{receipt.receipt_id[7:15]}.json"
    (artifact_dir / filename).symlink_to(outside)
    writer = CohortArtifactWriter(artifact_dir)

    with pytest.raises(OSError):
        writer.write_receipt(receipt)

    assert not outside.exists()
