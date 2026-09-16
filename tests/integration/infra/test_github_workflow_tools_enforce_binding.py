"""Tests for the protected GitHub workflow tool enforcement binding."""

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_SERVICE_VARIABLES = (_ROOT / "infra/services/core-control-plane/variables.tf").read_text()
_SERVICE_MODULE = (
    _ROOT / "infra/services/core-control-plane/modules/core-control-plane/main.tf"
).read_text()


def test_workflow_tool_enforcement_is_an_explicit_disabled_by_default_input() -> None:
    assert "workflow_tools_enforce    = optional(bool, false)" in _SERVICE_VARIABLES
    assert (
        "!var.stewardship_gitops.workflow_tools_enforce || var.stewardship_gitops.enabled"
    ) in _SERVICE_VARIABLES


def test_enabled_gitops_materializes_the_runtime_enforcement_switch() -> None:
    assert "github_workflow_tools_enforce" in _SERVICE_MODULE
    assert (
        "local.stewardship_gitops_enabled && var.stewardship_gitops.workflow_tools_enforce"
        in _SERVICE_MODULE
    )
    assert (
        '{ name = "FDAI_GITHUB_WORKFLOW_TOOLS_ENFORCE", '
        'value = local.github_workflow_tools_enforce ? "1" : "0" }'
    ) in _SERVICE_MODULE
