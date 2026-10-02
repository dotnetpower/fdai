"""Source Foundation plans use real saved-plan validation and never invoke kit verification."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from fdai_deployment_cli import cli, cli_plan, source_foundation
from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.foundation_plan import verify_foundation_plan
from fdai_deployment_cli.private_output import write_private_bytes

pytest_plugins = ["test_foundation_plan"]


def test_source_plan_retains_distinct_provenance(foundation_command, monkeypatch, capsys) -> None:
    arguments, root, profile = foundation_command
    profile = replace(profile, connectivity="online")
    monkeypatch.setattr(cli_plan, "load_profile", lambda _: profile)
    monkeypatch.setattr(
        cli_plan, "verify_offline_kit", lambda *_, **__: pytest.fail("kit verification invoked")
    )
    snapshot = root.parents[1]
    monkeypatch.setattr(
        source_foundation, "verify_source_snapshot", lambda *_, **__: {"source_commit": "c" * 40}
    )
    infra = snapshot / "tree/infra/genesis-foundation"
    infra.mkdir(parents=True)
    (infra / ".terraform.lock.hcl").write_bytes(b"locked")
    tools = snapshot / "tree/infra/genesis-runner-image"
    tools.mkdir()
    tools.joinpath("toolchain.json").write_text(
        json.dumps({"terraform_binary_sha256": hashlib.sha256(b"synthetic terraform").hexdigest()})
    )
    executable = snapshot.parent / "terraform"
    executable.write_bytes(b"synthetic terraform")
    executable.chmod(0o700)
    variables_file = Path(arguments[arguments.index("--variables-file") + 1])
    variables = json.loads(variables_file.read_bytes())
    source_commit = variables["source_commit"]
    monkeypatch.setattr(
        source_foundation,
        "verify_source_snapshot",
        lambda *_, **__: {"source_commit": source_commit},
    )
    monkeypatch.setattr(
        source_foundation, "verify_foundation_runner_image", lambda *_, **__: "f" * 64
    )
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if command[1] == "plan":
            normalized = Path(next(item[10:] for item in command if item.startswith("-var-file=")))
            variables.clear()
            variables.update(json.loads(normalized.read_bytes()))
            write_private_bytes(
                Path(next(item[5:] for item in command if item.startswith("-out="))), b"plan"
            )
        if command[1] == "show":
            projection = {
                "format_version": "1.2",
                "terraform_version": "1.9.8",
                "complete": True,
                "errored": False,
                "applyable": True,
                "variables": {key: {"value": value} for key, value in variables.items()},
            }
            kwargs["stdout"].write(json.dumps(projection).encode())
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(source_foundation.subprocess, "run", run)
    for option in ("--offline-kit", "--release-root", "--bundle-public-key"):
        index = arguments.index(option)
        del arguments[index : index + 2]
    arguments += [
        "--source-snapshot",
        str(snapshot),
        "--source-snapshot-digest",
        "e" * 64,
        "--terraform",
        str(executable),
        "--save-plan",
    ]
    assert cli.main(arguments) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["state"] == "review"
    assert result["deployment_ready"] is False
    review = result["saved_plan"]
    assert review["schema_version"] == "fdai.foundation-saved-source-plan.v1"
    assert review["context"]["source_input_digest"] == canonical_digest(
        {"source_commit": source_commit}
    )
    assert "offline_manifest_digest" not in review["context"]
    assert [command[1] for command in calls] == ["init", "validate", "plan", "show"]
    verified = verify_foundation_plan(
        directory=Path(arguments[arguments.index("--work-dir") + 1]),
        profile=profile,
        expected_review_digest=review["review_digest"],
    )
    assert verified["apply_authorized"] is False


def test_unpinned_terraform_never_runs(tmp_path) -> None:
    executable = tmp_path / "terraform"
    executable.write_bytes(b"unexpected")
    executable.chmod(0o700)
    with pytest.raises(ValueError, match="toolchain digest"):
        source_foundation._copy_terraform(executable, tmp_path / "copy", expected_digest="a" * 64)
    assert not (tmp_path / "copy").exists()
