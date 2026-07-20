"""Shared ARB readiness and runtime gate evaluation."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import yaml

from fdai.core.architecture_review import (
    ArchitectureReviewProductionGateEvaluator,
    evaluate_readiness,
)

_ROOT = Path(__file__).resolve().parents[3]
_MANIFEST = _ROOT / "config" / "architecture-review.yaml"


def _manifest() -> dict[str, object]:
    raw = yaml.safe_load(_MANIFEST.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    return raw


def test_upstream_structure_is_valid_but_production_is_blocked() -> None:
    report = evaluate_readiness(_manifest(), repo_root=_ROOT)

    assert report.structure_valid is True
    assert report.production_ready is False
    assert any("missing owner bindings" in failure for failure in report.failures)


def test_malformed_manifest_is_structurally_unhealthy() -> None:
    raw = deepcopy(_manifest())
    review = raw["architecture_review"]
    assert isinstance(review, dict)
    review["design_review_status"] = "unknown"

    report = evaluate_readiness(raw, repo_root=_ROOT)

    assert report.structure_valid is False
    assert report.production_ready is False
    assert report.failures == ("design_review_status is invalid",)


async def test_runtime_gate_fails_closed_for_blocked_or_unknown_gate() -> None:
    evaluator = ArchitectureReviewProductionGateEvaluator(
        manifest_path=_MANIFEST,
        repo_root=_ROOT,
    )

    assert (
        await evaluator.evaluate(
            rule_id="architecture-review.production-ready",
            step_id="production_gate",
            process_id="process-1",
        )
        is False
    )
    assert (
        await evaluator.evaluate(
            rule_id="unknown",
            step_id="production_gate",
            process_id="process-1",
        )
        is False
    )
