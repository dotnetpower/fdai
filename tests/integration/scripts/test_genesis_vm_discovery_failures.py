"""Failed provider reads preserve bounded partial evidence without claiming completeness."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/deployment/azure"))

from genesis_checks import CheckError  # noqa: E402
from genesis_vm_sku_preflight import discover_foundation_vm_size  # noqa: E402
from tests.integration.scripts.test_genesis_vm_sku_choice import rows  # noqa: E402


@pytest.mark.parametrize("failed_stage", ["catalog", "quota"])
def test_provider_failure_retains_completed_inputs_and_unknown_counters(
    tmp_path, monkeypatch, failed_stage
):
    config = tmp_path / "azure"
    config.mkdir(mode=0o700)
    monkeypatch.setenv("AZURE_CONFIG_DIR", str(config))
    calls = []

    def capture(command, **_kwargs):
        stage = "quota" if "/usages?" in command[command.index("--url") + 1] else "catalog"
        calls.append(stage)
        if stage == failed_stage:
            raise CheckError("runner_image_sku_evidence_incomplete", 3)
        return json.dumps({"value": rows()})

    with pytest.raises(CheckError, match="evidence_incomplete"):
        discover_foundation_vm_size(
            repository_root=ROOT,
            subscription_id="00000000-0000-0000-0000-000000000001",
            region="eastus",
            evidence_directory=tmp_path,
            source_commit="a" * 40,
            target_binding="b" * 64,
            capture=capture,
        )
    folders = list(tmp_path.glob("vm-discovery-*"))
    assert len(folders) == 1
    result = json.loads((folders[0] / "result.json").read_bytes())
    assert result["state"] == "blocked"
    assert result["failed_stage"] == failed_stage
    assert result["quota_evidence_digest"] is None
    assert result["catalog_count"] == (None if failed_stage == "catalog" else 2)
    assert (folders[0] / "skus.json").exists() is (failed_stage == "quota")
    assert not (folders[0] / "quota.json").exists()
    assert calls == (["catalog"] if failed_stage == "catalog" else ["catalog", "quota"])
