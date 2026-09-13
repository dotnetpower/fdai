"""Display only the selection from the exact expiring image review before human approval."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TextIO

from genesis_runner_image_contract import load_review
from genesis_runner_image_skus import selection_sizes


def show_image_vm_selection(
    *,
    status: dict[str, object],
    work_dir: Path,
    evidence: dict[str, str],
    output: TextIO,
) -> None:
    """Load the review rather than trusting a copied status summary; legacy reviews add no label."""

    report = status.get("foundation_report")
    plan = report.get("runner_image_plan") if isinstance(report, dict) else None
    ref = plan.get("plan_ref") if isinstance(plan, dict) else None
    if not isinstance(ref, str) or re.fullmatch(r"runner-image-attempt-[0-9]+", ref) is None:
        raise ValueError("runner image approval review reference is invalid")
    review = load_review(work_dir / ref, expected_review_digest=evidence["review_digest"])
    if (
        review["plan_digest"] != evidence["plan_digest"]
        or review["source_commit"] != status.get("source_commit")
        or review["run_digest"] != status.get("target_binding")
    ):
        raise ValueError("runner image approval review context is invalid")
    summary = review.get("effect_summary")
    if not isinstance(summary, dict) or "vm_skus" not in summary:
        return
    builder, verifier = selection_sizes(summary["vm_skus"])
    output.write(
        "Image VM selection (sealed in this plan):\n"
        f"  Builder: {builder}\n  Verifier: {verifier}\n"
        "  Eligibility and quota checked; allocation capacity is not reserved.\n"
    )
    selected = summary["vm_skus"]
    if (
        isinstance(selected, dict)
        and selected.get("schema_version") == "fdai.runner-image-sku-selection.v2"
    ):
        output.write(f"  Foundation host included in quota: {selected['foundation_vm_size']}\n")
    output.flush()
