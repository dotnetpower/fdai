from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import BinaryIO

import pytest

from fdai_deployment_cli import cli, foundation_plan
from fdai_deployment_cli.contracts import ProvisionProfile, canonical_digest
from fdai_deployment_cli.private_output import read_private_bytes, write_private_bytes

pytest_plugins = ["test_foundation_plan"]

_PLAN = b"\x00synthetic-private-plan\xff"


@pytest.fixture
def saved_command(
    foundation_command: tuple[list[str], Path, ProvisionProfile],
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[str], Path, ProvisionProfile, dict[str, object], list[list[str]]]:
    args, root, profile = foundation_command
    calls: list[list[str]] = []
    projection: dict[str, object] = {
        "format_version": "1.2",
        "terraform_version": "1.9.8",
        "complete": True,
        "errored": False,
        "applyable": True,
    }

    def run(
        command: list[str], *, stdout: BinaryIO | None = None, **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if command[1] == "plan":
            output = Path(next(value[5:] for value in command if value.startswith("-out=")))
            assert kwargs["umask"] == 0o077
            write_private_bytes(output, _PLAN)
            variables_path = Path(
                next(value[10:] for value in command if value.startswith("-var-file="))
            )
            projection.setdefault(
                "variables",
                {
                    key: {"value": value}
                    for key, value in json.loads(variables_path.read_bytes()).items()
                },
            )
        if command[1] == "show":
            assert stdout is not None
            stdout.write(json.dumps(projection).encode())
        return subprocess.CompletedProcess(command, 0, "private-provider-marker", "")

    monkeypatch.setattr(cli.subprocess, "run", run)
    monkeypatch.setattr(foundation_plan, "load_profile", lambda _: profile)
    return [*args, "--save-plan"], root.parents[2] / "work", profile, projection, calls


def _verify(work: Path, profile: ProvisionProfile, receipt: dict[str, object]) -> dict[str, object]:
    digest = receipt["review_digest"]
    assert isinstance(digest, str)
    return foundation_plan.verify_foundation_plan(
        directory=work, profile=profile, expected_review_digest=digest
    )


def _receipt(work: Path) -> dict[str, object]:
    return json.loads((work / foundation_plan.REVIEW_NAME).read_bytes())


def _rewrite_receipt(work: Path, receipt: dict[str, object]) -> dict[str, object]:
    receipt.pop("review_digest", None)
    receipt["review_digest"] = canonical_digest(receipt)
    (work / foundation_plan.REVIEW_NAME).write_text(json.dumps(receipt))
    return receipt


def test_saved_plan_is_private_bound_and_verifiable_without_execution(
    saved_command: tuple[list[str], Path, ProvisionProfile, dict[str, object], list[list[str]]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    args, work, profile, _, calls = saved_command
    assert cli.main(args) == 0
    output = capsys.readouterr()
    assert "private-provider-marker" not in output.out + output.err
    assert "synthetic-private-plan" not in output.out
    receipt = _receipt(work)
    assert json.loads(output.out)["saved_plan"] == receipt
    assert (work / foundation_plan.PLAN_NAME).read_bytes() == _PLAN
    assert [command[1] for command in calls] == ["init", "plan", "show"]
    assert receipt["plan_digest"] == hashlib.sha256(_PLAN).hexdigest()
    context = receipt["context"]
    assert isinstance(context, dict)
    assert context["profile_digest"] == canonical_digest(profile.to_mapping())
    assert context["terraform_digest"] == "c" * 64
    assert context["deployment_bundle_digest"] == "b" * 64
    assert context["offline_manifest_digest"] == "a" * 64
    for name in (foundation_plan.PLAN_NAME, foundation_plan.REVIEW_NAME):
        assert (work / name).stat().st_mode & 0o777 == 0o600
    assert not (work / "plan.auto.tfvars.json").exists()
    assert list(work.glob("foundation-plan-*")) == []
    assert _verify(work, profile, receipt)["integrity_verified"] is True
    assert (
        cli.main(
            [
                "provision",
                "verify-foundation-plan",
                "--directory",
                str(work),
                "--profile",
                str(work / "profile.json"),
                "--expected-review-digest",
                str(receipt["review_digest"]),
                "--output",
                "json",
            ]
        )
        == 0
    )
    verification = json.loads(capsys.readouterr().out)
    assert verification["integrity_verified"] is True
    assert verification["apply_authorized"] is False
    assert verification["subscription_ready"] is False
    assert verification["source_eligibility_verified"] is False
    assert verification["plan_origin_verified"] is False
    assert len(calls) == 3


def test_saved_plan_text_exposes_digest_but_not_provider_values(
    saved_command: tuple[list[str], Path, ProvisionProfile, dict[str, object], list[list[str]]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    args, work, _, _, _ = saved_command
    args[args.index("--output") + 1] = "text"
    assert cli.main(args) == 0
    output = capsys.readouterr()
    assert str(_receipt(work)["review_digest"]) in output.out
    assert "no apply authorized" in output.out
    assert "private-provider-marker" not in output.out + output.err


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("format_version", "2.0"),
        ("format_version", None),
        ("complete", False),
        ("complete", 1),
        ("errored", True),
        ("errored", 0),
        ("applyable", None),
        ("applyable", 1),
        ("deferred_changes", [{"deferred": True}]),
        ("variables", {}),
        ("terraform_version", "private-provider-marker"),
    ],
)
def test_invalid_projection_never_publishes_plan(
    saved_command: tuple[list[str], Path, ProvisionProfile, dict[str, object], list[list[str]]],
    key: str,
    value: object,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args, work, _, projection, _ = saved_command
    projection[key] = value
    assert cli.main(args) == 3
    output = capsys.readouterr()
    assert output.out == ""
    assert "private-provider-marker" not in output.err
    assert not (work / foundation_plan.PLAN_NAME).exists()
    assert not (work / foundation_plan.REVIEW_NAME).exists()
    assert not (work / "plan.auto.tfvars.json").exists()
    assert list(work.glob("foundation-plan-*")) == []


@pytest.mark.parametrize("stage", ["init", "plan", "show", "show-timeout", "lock"])
def test_failed_attempt_leaves_no_saved_plan_or_private_temporary_input(
    saved_command: tuple[list[str], Path, ProvisionProfile, dict[str, object], list[list[str]]],
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    args, work, _, _, _ = saved_command
    original = cli.subprocess.run

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if command[1] == stage:
            return subprocess.CompletedProcess(command, 1, "private-provider-marker", "")
        if command[1] == "show" and stage == "show-timeout":
            raise subprocess.TimeoutExpired(command, 300)
        result = original(command, **kwargs)
        if command[1] == "plan" and stage == "lock":
            (work.parent / "bundle/infra/genesis-foundation/.terraform.lock.hcl").write_text(
                "changed"
            )
        return result

    monkeypatch.setattr(cli.subprocess, "run", run)
    assert cli.main(args) == 3
    assert not (work / foundation_plan.PLAN_NAME).exists()
    assert not (work / foundation_plan.REVIEW_NAME).exists()
    assert not (work / "plan.auto.tfvars.json").exists()
    assert list(work.glob("foundation-plan-*")) == []


def test_failed_receipt_write_removes_only_new_saved_plan(
    saved_command: tuple[list[str], Path, ProvisionProfile, dict[str, object], list[list[str]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args, work, _, _, _ = saved_command

    def fail(*args: object, **kwargs: object) -> None:
        raise OSError("synthetic write failure")

    monkeypatch.setattr(foundation_plan, "write_private_output", fail)
    assert cli.main(args) == 3
    assert not (work / foundation_plan.PLAN_NAME).exists()
    assert not (work / foundation_plan.REVIEW_NAME).exists()
    assert list(work.glob("foundation-plan-*")) == []


@pytest.mark.parametrize("mutation", ["changed-plan", "boolean-as-number", "missing-plan"])
def test_saved_plan_inspection_rejects_changed_or_missing_bytes_and_input_types(
    saved_command: tuple[list[str], Path, ProvisionProfile, dict[str, object], list[list[str]]],
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    args, work, _, projection, _ = saved_command
    source = Path(args[args.index("--variables-file") + 1])
    values = json.loads(source.read_bytes())
    values["enable_public_egress"] = True
    source.write_text(json.dumps(values))
    original = cli.subprocess.run

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if command[1] == "show":
            if mutation == "changed-plan":
                Path(command[-1]).write_bytes(b"replaced-after-first-read")
            if mutation == "boolean-as-number":
                actual = projection["variables"]
                assert isinstance(actual, dict)
                actual["enable_public_egress"] = {"value": 1}
        result = original(command, **kwargs)
        if command[1] == "plan" and mutation == "missing-plan":
            Path(next(value[5:] for value in command if value.startswith("-out="))).unlink()
        return result

    monkeypatch.setattr(cli.subprocess, "run", run)
    assert cli.main(args) == 3
    assert not (work / foundation_plan.PLAN_NAME).exists()
    assert not (work / foundation_plan.REVIEW_NAME).exists()
    assert not (work / "plan.auto.tfvars.json").exists()
    assert list(work.glob("foundation-plan-*")) == []


@pytest.mark.parametrize("mutation", ["plan", "receipt", "expected", "profile"])
def test_verification_rejects_mismatched_artifacts(
    saved_command: tuple[list[str], Path, ProvisionProfile, dict[str, object], list[list[str]]],
    mutation: str,
) -> None:
    args, work, profile, _, _ = saved_command
    assert cli.main(args) == 0
    receipt = _receipt(work)
    if mutation == "plan":
        (work / foundation_plan.PLAN_NAME).write_bytes(b"changed")
    elif mutation == "receipt":
        changed = dict(receipt)
        changed["plan_digest"] = "d" * 64
        _rewrite_receipt(work, changed)
    elif mutation == "expected":
        receipt["review_digest"] = "e" * 64
    else:
        profile = replace(profile, monthly_cost_ceiling=501)
    with pytest.raises(ValueError, match="match"):
        _verify(work, profile, receipt)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("apply_authorized", True),
        ("mutation_performed", 0),
        ("schema_version", "unknown"),
        ("state", "ready"),
        ("context", {}),
        ("context", None),
        ("created_at", "not-a-date"),
        ("expires_at", 0),
        ("created_at", "2026-01-01T00:00:00"),
        ("expires_at", "2026-01-01T00:00:00+01:00"),
    ],
)
def test_self_consistent_but_invalid_review_is_rejected(
    saved_command: tuple[list[str], Path, ProvisionProfile, dict[str, object], list[list[str]]],
    key: str,
    value: object,
) -> None:
    args, work, profile, _, _ = saved_command
    assert cli.main(args) == 0
    receipt = _receipt(work)
    receipt[key] = value
    _rewrite_receipt(work, receipt)
    with pytest.raises(ValueError):
        _verify(work, profile, receipt)


@pytest.mark.parametrize("offset", [-2, 2])
def test_saved_review_must_be_in_its_local_review_window(
    saved_command: tuple[list[str], Path, ProvisionProfile, dict[str, object], list[list[str]]],
    offset: int,
) -> None:
    args, work, profile, _, _ = saved_command
    assert cli.main(args) == 0
    receipt = _receipt(work)
    created = datetime.now(UTC) + timedelta(hours=offset)
    receipt["created_at"] = created.isoformat()
    receipt["expires_at"] = (created + timedelta(hours=1)).isoformat()
    _rewrite_receipt(work, receipt)
    with pytest.raises(ValueError, match="time window"):
        _verify(work, profile, receipt)


def test_platform_rejects_save_before_any_external_call(
    foundation_command: tuple[list[str], Path, ProvisionProfile],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args, _, _ = foundation_command
    args[args.index("foundation")] = "platform"

    def unexpected() -> None:
        pytest.fail("target query before refusing platform saved plan")

    monkeypatch.setattr(cli, "azure_active_target_binding", unexpected)
    assert cli.main([*args, "--save-plan"]) == 3


@pytest.mark.parametrize(
    "kind", ["symlink", "ancestor", "hardlink", "fifo", "directory", "mode", "empty", "large"]
)
def test_private_binary_reader_refuses_unsafe_files(tmp_path: Path, kind: str) -> None:
    source = tmp_path / "plan"
    source.write_bytes(b"private-bytes")
    source.chmod(0o600)
    if kind == "symlink":
        link = tmp_path / "link"
        link.symlink_to(source)
        source = link
    elif kind == "ancestor":
        alias = tmp_path / "alias"
        alias.symlink_to(tmp_path, target_is_directory=True)
        source = alias / source.name
    elif kind == "hardlink":
        os.link(source, tmp_path / "alias")
    elif kind == "fifo":
        source.unlink()
        os.mkfifo(source, 0o600)
    elif kind == "directory":
        source.unlink()
        source.mkdir()
    elif kind == "mode":
        source.chmod(0o644)
    elif kind == "empty":
        source.write_bytes(b"")
    with pytest.raises((ValueError, OSError)):
        read_private_bytes(source, max_bytes=3 if kind == "large" else 100)


def test_private_binary_writer_preserves_existing_output(tmp_path: Path) -> None:
    path = tmp_path / "plan"
    write_private_bytes(path, _PLAN)
    assert read_private_bytes(path, max_bytes=100) == _PLAN
    with pytest.raises(FileExistsError):
        write_private_bytes(path, b"replacement")
    assert path.read_bytes() == _PLAN
