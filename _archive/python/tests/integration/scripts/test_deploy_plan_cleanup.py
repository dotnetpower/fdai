"""Regression tests for protected platform plan cleanup."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOW = (_ROOT / ".github" / "workflows" / "deploy-dev.yml").read_text(encoding="utf-8")


def test_plan_review_cleanup_precedes_sensitive_rendering() -> None:
    step = _WORKFLOW.split("- name: Reject destructive protected plan", maxsplit=1)[1].split(
        "- name: Run complete Azure live preflight", maxsplit=1
    )[0]

    assert step.index("trap 'rm -f dev.plan.review.json' EXIT") < step.index(
        "terraform show -json dev.plan > dev.plan.review.json"
    )
