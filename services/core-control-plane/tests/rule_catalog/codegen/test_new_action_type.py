"""Tests for the ActionType codegen (module + CLI)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fdai.rule_catalog.codegen.new_action_type import (
    ActionTypeSpec,
    render_action_type_yaml,
)
from fdai.rule_catalog.codegen.new_action_type_cli import main as cli_main
from fdai.rule_catalog.schema.action_type import load_action_type_from_mapping
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry


def test_render_produces_loader_valid_yaml() -> None:
    spec = ActionTypeSpec(
        name="governance.assign-reviewers",
        operation="update",
        interfaces=("ControlPlane",),
        rollback_contract="state_forward_only",
        category="ops",
        description="Assign reviewers deterministically.",
    )
    text = render_action_type_yaml(spec)
    doc = yaml.safe_load(text)
    model = load_action_type_from_mapping(doc, schema_registry=PackageResourceSchemaRegistry())
    assert model.name == "governance.assign-reviewers"
    assert model.default_mode.value == "shadow"


def test_spec_rejects_enforce_default_mode() -> None:
    with pytest.raises(ValueError, match="default_mode='enforce' is forbidden"):
        ActionTypeSpec(
            name="ops.bad",
            operation="create",
            interfaces=("ControlPlane",),
            rollback_contract="pr_revert",
            category="ops",
            description="d",
            default_mode="enforce",
        )


def test_spec_rejects_name_with_trailing_newline() -> None:
    # The name anchor is \Z (not $), so a trailing newline cannot slip a
    # malformed identifier past validation ($ would match before a \n).
    with pytest.raises(ValueError, match="MUST match"):
        ActionTypeSpec(
            name="ops.scale\n",
            operation="create",
            interfaces=("ControlPlane",),
            rollback_contract="pr_revert",
            category="ops",
            description="d",
        )


def test_spec_rejects_missing_argument_schema_for_operator_request() -> None:
    with pytest.raises(ValueError, match="argument_schema"):
        ActionTypeSpec(
            name="ops.operator-only",
            operation="create",
            interfaces=("ControlPlane",),
            rollback_contract="pr_revert",
            category="ops",
            description="d",
            trigger_kind="operator_request",
            argument_schema=None,
        )


def test_spec_accepts_operator_request_with_argument_schema() -> None:
    spec = ActionTypeSpec(
        name="ops.operator-ok",
        operation="create",
        interfaces=("ControlPlane",),
        rollback_contract="pr_revert",
        category="ops",
        description="d",
        trigger_kind="operator_request",
        argument_schema={"type": "object", "additionalProperties": False, "properties": {}},
    )
    doc = yaml.safe_load(render_action_type_yaml(spec))
    assert doc["argument_schema"]["type"] == "object"


def test_spec_rejects_unknown_operation() -> None:
    with pytest.raises(ValueError, match="operation"):
        ActionTypeSpec(
            name="ops.bogus",
            operation="floofify",
            interfaces=("ControlPlane",),
            rollback_contract="pr_revert",
            category="ops",
            description="d",
        )


def test_spec_rejects_unknown_rollback() -> None:
    with pytest.raises(ValueError, match="rollback_contract"):
        ActionTypeSpec(
            name="ops.bogus",
            operation="create",
            interfaces=("ControlPlane",),
            rollback_contract="magic",
            category="ops",
            description="d",
        )


def test_spec_rejects_none_rollback_contract() -> None:
    with pytest.raises(ValueError, match="rollback_contract"):
        ActionTypeSpec(
            name="ops.bogus",
            operation="create",
            interfaces=("ControlPlane",),
            rollback_contract="none",  # legacy value, removed
            category="ops",
            description="d",
        )


def test_spec_rejects_unknown_interface() -> None:
    with pytest.raises(ValueError, match="interface"):
        ActionTypeSpec(
            name="ops.bogus",
            operation="create",
            interfaces=("MadeUp",),
            rollback_contract="pr_revert",
            category="ops",
            description="d",
        )


def test_cli_writes_to_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli_main(
        [
            "--name",
            "ops.example-action",
            "--operation",
            "create",
            "--interface",
            "ControlPlane",
            "--rollback",
            "pr_revert",
            "--category",
            "ops",
            "--description",
            "Example action.",
        ]
    )
    assert rc == 0
    text = capsys.readouterr().out
    doc = yaml.safe_load(text)
    assert doc["name"] == "ops.example-action"
    assert doc["default_mode"] == "shadow"


def test_cli_writes_to_file_and_argument_schema_json(tmp_path: Path) -> None:
    out = tmp_path / "action.yaml"
    cli_main(
        [
            "--name",
            "ops.request-thing",
            "--operation",
            "create",
            "--interface",
            "ControlPlane",
            "--rollback",
            "pr_revert",
            "--category",
            "ops",
            "--description",
            "Operator-request action.",
            "--trigger",
            "operator_request",
            "--argument-schema",
            '{"type":"object","additionalProperties":false,"required":["reason"],"properties":{"reason":{"type":"string","minLength":10}}}',
            "--out",
            str(out),
        ]
    )
    doc = yaml.safe_load(out.read_text())
    assert doc["trigger_kind"]["kind"] == "operator_request"
    assert doc["argument_schema"]["required"] == ["reason"]


def test_cli_bad_json_argument_schema(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="argument-schema"):
        cli_main(
            [
                "--name",
                "ops.bad-schema",
                "--operation",
                "create",
                "--interface",
                "ControlPlane",
                "--rollback",
                "pr_revert",
                "--category",
                "ops",
                "--description",
                "d",
                "--trigger",
                "operator_request",
                "--argument-schema",
                "{not-json}",
            ]
        )


def test_cli_refuses_to_overwrite_without_flag(tmp_path: Path) -> None:
    out = tmp_path / "action.yaml"
    out.write_text("existing")
    with pytest.raises(SystemExit, match="already exists"):
        cli_main(
            [
                "--name",
                "ops.example",
                "--operation",
                "create",
                "--interface",
                "ControlPlane",
                "--rollback",
                "pr_revert",
                "--category",
                "ops",
                "--description",
                "d",
                "--out",
                str(out),
            ]
        )
