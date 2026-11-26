from __future__ import annotations

from pathlib import Path


def test_governance_review_gate_covers_override_parameter_bounds() -> None:
    workflow = (Path(__file__).resolve().parents[3] / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )

    assert "rule-catalog/override-parameter-bounds\\.yaml$" in workflow
