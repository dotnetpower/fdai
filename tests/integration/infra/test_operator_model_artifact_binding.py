from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_operator_prefers_the_protected_inline_model_artifact() -> None:
    root = " ".join((ROOT / "infra/main.tf").read_text(encoding="utf-8").split())

    assert (
        'resolved_models_path = var.resolved_models_json != "" ? '
        "var.resolved_models_json : var.operator_api_resolved_models_path" in root
    )
