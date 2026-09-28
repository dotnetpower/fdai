"""The committed coverage baseline must equal the receipt the compiler produces now."""

from __future__ import annotations

import json

from fdai.core.conversation.semantic_reasoning_coverage import reasoning_coverage_receipt

from tests.conversation.semantic_reasoning_support import (
    DEFAULT_LOOKBACK_SECONDS,
    NOW,
    PURPOSE,
    ROOT,
    plan_verifier,
    production_manifest,
)

_BASELINE = ROOT / "scripts/quality/architecture/reasoning-coverage-baseline.json"


def test_compiled_cells_and_reasons_match_the_reviewed_baseline() -> None:
    receipt = reasoning_coverage_receipt(
        manifest=production_manifest(),
        verifier=plan_verifier(),
        purpose=PURPOSE,
        evaluation_time=NOW,
        default_lookback_seconds=DEFAULT_LOOKBACK_SECONDS,
    )
    baseline = json.loads(_BASELINE.read_text(encoding="utf-8"))

    assert len(receipt.cells) == baseline["cells"]
    assert len({cell.cell_id for cell in receipt.cells}) == len(receipt.cells)
    assert list(receipt.compiled_cells) == baseline["compiled_cells"]
    assert receipt.status_counts == baseline["status_counts"]
    assert receipt.reason_counts == baseline["reason_counts"]
