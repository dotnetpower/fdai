"""Exercise the real planning hook with local artifacts and synthetic provider boundaries."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/deployment/azure"))

import genesis_runner_image as command  # noqa: E402
from genesis_checks import CheckError  # noqa: E402
from genesis_runner_image_contract import PLAN_JSON_NAME  # noqa: E402
from tests.integration.scripts.test_genesis_runner_image import (  # noqa: E402
    _inputs,
    _plan_projection,
)
from tests.integration.scripts.test_genesis_runner_image_sku_choice import (  # noqa: E402
    POLICY_PATH,
    restricted,
    sku_rows,
    usage_rows,
)


@pytest.mark.parametrize("availability", ["clear", "b2s-restricted", "all-restricted"])
def test_image_review_is_published_only_after_both_planned_skus_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    availability: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inputs, _ = _inputs(tmp_path)
    work = tmp_path / "new-image-plan"
    order: list[str] = []
    monkeypatch.setenv("FDAI_SIGNED_SOURCE_EVIDENCE", "synthetic-test-boundary")
    monkeypatch.setattr(command, "load_runner_image_inputs", lambda **kw: inputs)
    monkeypatch.setattr(command, "_terraform_environment", lambda *_a, **_kw: {})
    monkeypatch.setattr(
        command,
        "GenesisChecks",
        lambda *_a, **_kw: SimpleNamespace(verify_target=lambda **_kw: None),
    )
    monkeypatch.setattr(command, "_trusted_azure_cli", lambda: Path("/usr/bin/az"))
    monkeypatch.setattr(command, "_trusted_terraform", lambda path: path)

    def snapshot(_source: Path, destination: Path, **_kwargs: object) -> str:
        destination.mkdir(mode=0o700)
        path = destination / "sku-policy.json"
        path.write_bytes(POLICY_PATH.read_bytes())
        path.chmod(0o600)
        return "d" * 64

    monkeypatch.setattr(command, "snapshot_terraform_root", snapshot)
    monkeypatch.setattr(
        command, "_file_digest", lambda _path: inputs.terraform_values["terraform_binary_sha256"]
    )
    monkeypatch.setattr(command, "_execution_tree_digest", lambda _path: "f" * 64)

    def required(cmd: list[str], **_kwargs: object) -> None:
        assert cmd[1] in {"init", "plan"}
        order.append(cmd[1])

    def capture(cmd: list[str], **_kwargs: object) -> str:
        if cmd[1:4] == ["vm", "image", "show"]:
            return "24.04.202608270"
        if cmd[1:3] == ["show", "-json"]:
            order.append("saved-plan-projection")
            values = json.loads((work / "runner-image.auto.tfvars.json").read_bytes())
            return json.dumps(_plan_projection(values))
        assert cmd[:4] == ["/usr/bin/az", "rest", "--method", "get"]
        if "/usages?" in cmd[cmd.index("--url") + 1]:
            order.append("quota-read")
            return json.dumps({"value": usage_rows()})
        order.append("plan-sku-check" if (work / PLAN_JSON_NAME).exists() else "sku-selection")
        evidence = sku_rows()
        for row in evidence:
            row["locations"] = [inputs.region]
            if availability == "all-restricted" or (
                availability == "b2s-restricted" and row["name"] == "Standard_B2s"
            ):
                restricted(row)
                row["restrictions"][0]["values"] = [inputs.region]
        query = cmd[cmd.index("--query") + 1]
        evidence = [row for row in evidence if f"'{row['name']}'" in query]
        return json.dumps({"value": evidence})

    def publish_review(**kwargs: object) -> dict[str, object]:
        order.append("review")
        selected = kwargs["inputs"]
        assert selected.terraform_values["verify_vm_size"] == (
            "Standard_B2s" if availability == "clear" else "Standard_D2ds_v5"
        )
        assert selected.sku_selection["capacity_reserved"] is False
        return {
            "review_digest": "a" * 64,
            "plan_digest": "b" * 64,
            "expires_at": "2030-01-01T00:00:00Z",
            "create_count": 30,
            "retained_resource_count": 26,
            "lifecycle_actions": [],
            "effect_summary": {},
        }

    monkeypatch.setattr(command, "_required", required)
    monkeypatch.setattr(command, "_capture", capture)
    monkeypatch.setattr(command, "create_review", publish_review)
    args = argparse.Namespace(
        work_dir=work,
        profile=tmp_path / "profile.json",
        foundation_variables=tmp_path / "foundation.json",
        terraform=tmp_path / "terraform",
        timeout_seconds=900,
        output="json",
    )
    if availability == "all-restricted":
        with pytest.raises(CheckError, match="runner_image_no_compatible_sku_in_selected_region"):
            command._plan(args)
        assert order == ["sku-selection", "quota-read"]
        assert capsys.readouterr().out == ""
    else:
        assert command._plan(args) == 0
        assert order == [
            "sku-selection",
            "quota-read",
            "init",
            "plan",
            "saved-plan-projection",
            "plan-sku-check",
            "review",
        ]
        assert json.loads(capsys.readouterr().out)["apply_authorized"] is False
