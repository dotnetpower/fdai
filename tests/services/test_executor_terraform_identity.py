from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_ROOT = (
    REPO_ROOT / "infra" / "services" / "isolated-executor" / "modules" / "isolated-executor"
)


def test_authority_cutover_attaches_and_injects_all_vertical_identities() -> None:
    main = (MODULE_ROOT / "main.tf").read_text(encoding="utf-8")
    variables = (MODULE_ROOT / "variables.tf").read_text(encoding="utf-8")

    for vertical in ("change", "resilience", "finops"):
        assert f"var.identity.{vertical}_resource_id" in main
        assert f"var.identity.{vertical}_client_id" in main
        assert f"FDAI_{vertical.upper()}_MI_CLIENT_ID" in main
        assert f"{vertical}_resource_id" in variables
        assert f"{vertical}_client_id" in variables

    assert "action_resource_ids" not in main
    assert "all three vertical resource and client IDs" in variables
