"""Focused tests for Terraform inventory-to-cost-model SKU and quantity reconciliation."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = (
    REPO_ROOT / "scripts" / "quality" / "architecture" / "check-cost-model-reconciliation.py"
)


def _load_module():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("check_cost_model", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_cost_model_reconciliation_artifact_passes_gate() -> None:
    mod = _load_module()
    assert mod.validate_reconciliation_artifact(REPO_ROOT) == []


def test_cost_model_reconciliation_detects_digest_drift_and_placeholder_rows(
    tmp_path: Path,
) -> None:
    mod = _load_module()
    for rel in mod.TERRAFORM_SOURCES:
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes((REPO_ROOT / rel).read_bytes())

    artifact = mod.build_reconciliation_artifact(tmp_path)
    cfg = tmp_path / "config" / "cost-model-sku-reconciliation.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    assert mod.validate_reconciliation_artifact(tmp_path) == []

    # Mutate digest and introduce placeholder
    artifact["terraform_inventory_digest"] = "sha256:" + "0" * 64
    artifact["rows"][0]["reconciled_baseline_usd"] = "recalculate from current plan"
    cfg.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    errs = mod.validate_reconciliation_artifact(tmp_path)
    assert any("terraform_inventory_digest" in e for e in errs)
    assert any("unreconciled placeholder" in e for e in errs)
