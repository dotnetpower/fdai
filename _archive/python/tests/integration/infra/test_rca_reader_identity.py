"""RCA reader identity handoff across legacy and split deployment shapes."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_platform_exports_dedicated_rca_reader_for_split_core() -> None:
    outputs = (ROOT / "infra/outputs.tf").read_text(encoding="utf-8")
    split_variables = (ROOT / "infra/services/core-control-plane/variables.tf").read_text(
        encoding="utf-8"
    )
    split_root = (ROOT / "infra/services/core-control-plane/main.tf").read_text(encoding="utf-8")

    assert 'output "rca_reader_identity"' in outputs
    assert "module.rca_reader_identity.resource_id" in outputs
    assert "module.rca_reader_identity.client_id" in outputs
    assert "module.rca_reader_identity.principal_id" in outputs
    assert 'variable "rca_reader_identity"' in split_variables
    assert "rca_reader_identity = var.rca_reader_identity" in " ".join(split_root.split())
