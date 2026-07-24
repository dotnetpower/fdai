from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_JOB = _ROOT / "infra/modules/compute/container-apps/analyzer_tick_job.tf"


def test_analyzer_job_uses_inventory_identity_not_executor_identity() -> None:
    source = _JOB.read_text(encoding="utf-8")

    assert "identity_ids = [var.inventory_identity_id]" in source
    assert "identity = var.inventory_identity_id" in source
    assert "identity_ids = [var.executor_identity_id]" not in source
    assert "identity = var.executor_identity_id" not in source
