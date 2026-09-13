"""VM metadata reads must fail safely when the selected Azure CLI context is unavailable."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/deployment/azure"))

import genesis_vm_sku_preflight as preflight  # noqa: E402
from genesis_checks import CheckError  # noqa: E402


@pytest.mark.parametrize("fault", ["missing", "file", "writable"])
def test_bad_azure_context_is_value_safe_and_precedes_provider_reads(tmp_path, monkeypatch, fault):
    context = tmp_path / "private-context-marker"
    if fault == "file":
        context.write_text("not a directory")
    elif fault == "writable":
        context.mkdir(mode=0o777)
        context.chmod(0o777)
    monkeypatch.setenv("AZURE_CONFIG_DIR", str(context))
    with pytest.raises(CheckError, match="evidence_incomplete") as failure:
        preflight.discover_foundation_vm_size(
            repository_root=ROOT,
            subscription_id="00000000-0000-0000-0000-000000000001",
            region="eastus",
            evidence_directory=tmp_path,
            source_commit="a" * 40,
            target_binding="b" * 64,
            capture=lambda *_a, **_k: pytest.fail("No provider request with invalid context"),
        )
    assert "private-context-marker" not in str(failure.value)
    assert str(tmp_path) not in str(failure.value)
