"""Private exact-evidence Genesis approval regressions."""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT_DIR = ROOT / "scripts/deployment/azure"
sys.path.insert(0, str(SCRIPT_DIR))

import genesis_approval_prompt as prompt  # noqa: E402
from genesis_approval import load_genesis_approval  # noqa: E402
from genesis_approval_prompt import create_approval  # noqa: E402
from genesis_checks import CheckError  # noqa: E402

RUN_BINDING = "a" * 64
SOURCE_COMMIT = "b" * 40


def _write(path: Path, value: dict[str, object]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, separators=(",", ":"))
        stream.write("\n")


def _approval(stage: str, evidence: dict[str, str]) -> dict[str, object]:
    approved_at = datetime.now(timezone.utc).replace(  # noqa: UP017 - mirrors Python 3.10 script
        microsecond=0
    )
    return {
        "schema_version": "fdai.genesis-approval.v1",
        "run_binding": RUN_BINDING,
        "source_commit": SOURCE_COMMIT,
        "stage": stage,
        "approved": True,
        "approved_at": approved_at.isoformat(),
        "expires_at": (approved_at + timedelta(minutes=30)).isoformat(),
        "actor_digest": "9" * 64,
        "evidence": evidence,
    }


def test_exact_checkpoint_approval_matches_only_its_bound_evidence(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    path = tmp_path / "approval.json"
    evidence = {"review_digest": "c" * 64, "plan_digest": "d" * 64}
    _write(path, _approval("foundation-apply", evidence))

    approval = load_genesis_approval(path, run_binding=RUN_BINDING, source_commit=SOURCE_COMMIT)

    assert approval is not None
    assert approval.authorizes("runner-image", **evidence) is False
    assert approval.authorizes("foundation-apply", **evidence) is True
    with pytest.raises(ValueError, match="does not match"):
        approval.authorizes(
            "foundation-apply",
            review_digest="c" * 64,
            plan_digest="e" * 64,
        )


@pytest.mark.parametrize(
    "mutation",
    ("target", "source", "approved", "stage", "field", "digest"),
)
def test_approval_rejects_wrong_context_authority_or_shape(tmp_path: Path, mutation: str) -> None:
    tmp_path.chmod(0o700)
    path = tmp_path / "approval.json"
    value = _approval("runner-enrollment", {"foundation_receipt_digest": "c" * 64})
    if mutation == "target":
        value["run_binding"] = "d" * 64
    elif mutation == "source":
        value["source_commit"] = "e" * 40
    elif mutation == "approved":
        value["approved"] = False
    elif mutation == "stage":
        value["stage"] = "unknown"
    elif mutation == "field":
        evidence = value["evidence"]
        assert isinstance(evidence, dict)
        evidence["unexpected"] = "f" * 64
    else:
        evidence = value["evidence"]
        assert isinstance(evidence, dict)
        evidence["foundation_receipt_digest"] = "invalid"
    _write(path, value)

    with pytest.raises(ValueError, match="Genesis approval"):
        load_genesis_approval(path, run_binding=RUN_BINDING, source_commit=SOURCE_COMMIT)


def test_approval_requires_private_single_link_file(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    path = tmp_path / "approval.json"
    _write(path, _approval("runner-image", {"review_digest": "c" * 64, "plan_digest": "d" * 64}))
    path.chmod(0o644)

    with pytest.raises(PermissionError, match="mode-0600"):
        load_genesis_approval(path, run_binding=RUN_BINDING, source_commit=SOURCE_COMMIT)


def test_approval_rejects_an_expired_window(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    path = tmp_path / "approval.json"
    value = _approval("runner-enrollment", {"foundation_receipt_digest": "c" * 64})
    value["approved_at"] = "2000-01-01T00:00:00+00:00"
    value["expires_at"] = "2000-01-01T00:30:00+00:00"
    _write(path, value)

    with pytest.raises(ValueError, match="expired"):
        load_genesis_approval(path, run_binding=RUN_BINDING, source_commit=SOURCE_COMMIT)


class _TtyInput(io.StringIO):
    def isatty(self) -> bool:
        return True


@pytest.mark.parametrize("account_type", ["user", "servicePrincipal"])
def test_prompt_actor_uses_trusted_cli_and_requires_human(
    monkeypatch: pytest.MonkeyPatch, account_type: str
) -> None:
    azure_cli = "/example/trusted/bin/az"
    environment = {"AZURE_CONFIG_DIR": "/example/private/azure"}
    commands: list[list[str]] = []
    tenant = "00000000-0000-0000-0000-000000000000"
    principal = "00000000-0000-0000-0000-000000000001"

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        assert command[0] == azure_cli
        assert kwargs["env"] == environment
        assert kwargs["timeout"] == 30
        value = (
            json.dumps({"tenantId": tenant, "type": account_type})
            if command[1] == "account"
            else principal + "\n"
        )
        return subprocess.CompletedProcess(command, 0, stdout=value, stderr="")

    monkeypatch.setattr(prompt, "_azure_identity_environment", lambda: environment)
    monkeypatch.setattr(prompt, "trusted_tool", lambda name: azure_cli if name == "az" else "")
    monkeypatch.setattr(prompt.subprocess, "run", run)
    if account_type == "user":
        assert (
            prompt.current_actor_digest(RUN_BINDING)
            == hashlib.sha256(f"{RUN_BINDING}:{tenant}:{principal}".encode()).hexdigest()
        )
    else:
        with pytest.raises(ValueError, match="authenticated human"):
            prompt.current_actor_digest(RUN_BINDING)
    assert [command[1] for command in commands] == ["account", "ad"]


def test_prompt_actor_rejects_untrusted_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable(_name: str) -> str:
        raise CheckError("required_tool_unavailable")

    monkeypatch.setattr(prompt, "_azure_identity_environment", lambda: {})
    monkeypatch.setattr(prompt, "trusted_tool", unavailable)
    monkeypatch.setattr(prompt.subprocess, "run", lambda *_args, **_kwargs: pytest.fail("no CLI"))
    with pytest.raises(CheckError, match="required_tool_unavailable"):
        prompt.current_actor_digest(RUN_BINDING)


def test_prompt_creates_actor_bound_exact_approval(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    path = tmp_path / "prompted.json"

    value = create_approval(
        stage="runner-image",
        evidence={"review_digest": "c" * 64, "plan_digest": "d" * 64},
        run_binding=RUN_BINDING,
        source_commit=SOURCE_COMMIT,
        actor_digest="9" * 64,
        output=path,
        input_stream=_TtyInput("runner-image\n"),
        output_stream=io.StringIO(),
    )

    assert value["actor_digest"] == "9" * 64
    assert path.stat().st_mode & 0o777 == 0o600
    loaded = load_genesis_approval(
        path,
        run_binding=RUN_BINDING,
        source_commit=SOURCE_COMMIT,
    )
    assert loaded is not None
    assert loaded.actor_digest == "9" * 64


def test_prompt_rejects_non_tty_or_wrong_exact_text(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    common = {
        "stage": "foundation-apply",
        "evidence": {"review_digest": "c" * 64, "plan_digest": "d" * 64},
        "run_binding": RUN_BINDING,
        "source_commit": SOURCE_COMMIT,
        "actor_digest": "9" * 64,
        "output_stream": io.StringIO(),
    }
    with pytest.raises(ValueError, match="interactive terminal"):
        create_approval(
            **common,
            output=tmp_path / "non-tty.json",
            input_stream=io.StringIO("foundation-apply\n"),
        )
    with pytest.raises(PermissionError, match="was not granted"):
        create_approval(
            **common,
            output=tmp_path / "denied.json",
            input_stream=_TtyInput("yes\n"),
        )


@pytest.fixture
def residual_review(tmp_path):
    tmp_path.chmod(0o700)
    moment = datetime.now(timezone.utc).replace(microsecond=0)  # noqa: UP017
    plan = b"exact residual binary plan"
    value = {
        "schema_version": "fdai.runner-image-residual-review.v1",
        "state": "review",
        "apply_authorized": False,
        "mutation_performed": False,
        "deployment_ready": False,
        "original_state_unchanged": True,
        "source_commit": "a" * 40,
        "recovery_source_commit": SOURCE_COMMIT,
        "plan_digest": hashlib.sha256(plan).hexdigest(),
        "provider_digest": "c" * 64,
        "original_lineage_digest": "d" * 64,
        "created_at": moment.isoformat(),
        "expires_at": (moment + timedelta(minutes=30)).isoformat(),
    }
    prompt.write_private_output(tmp_path / "residual.tfplan", plan.decode())
    return tmp_path / "residual-review.json", value


def test_residual_prompt_binds_recovery_review_not_original_status(residual_review, monkeypatch):
    path, value = residual_review
    value["review_digest"] = prompt.canonical_digest(value)
    _write(path, value)
    output = path.parent / "approval.json"
    monkeypatch.setattr(
        sys, "argv", ["prompt", "--residual-review", str(path), "--output", str(output)]
    )
    seen = []
    monkeypatch.setattr(
        prompt, "current_actor_digest", lambda binding: seen.append(binding) or "9" * 64
    )

    def interact(**kwargs):
        return create_approval(
            **kwargs, input_stream=_TtyInput("runner-image\n"), output_stream=io.StringIO()
        )

    monkeypatch.setattr(prompt, "create_approval", interact)
    assert prompt.main() == 0
    assert seen == [value["review_digest"]]
    approval = load_genesis_approval(
        output, run_binding=value["review_digest"], source_commit=SOURCE_COMMIT
    )
    assert approval.authorizes(
        "runner-image", review_digest=value["review_digest"], plan_digest=value["plan_digest"]
    )


@pytest.mark.parametrize(
    "mutation",
    ["digest", "source", "plan", "provider", "lineage", "expired", "naive", "authority", "schema"],
)
def test_residual_prompt_rejects_invalid_review_before_identity_or_approval(
    residual_review, monkeypatch, mutation
):
    path, value = residual_review
    if mutation == "source":
        value["recovery_source_commit"] = "invalid"
    elif mutation == "plan":
        value["plan_digest"] = "e" * 64
    elif mutation in {"provider", "lineage"}:
        value.pop("provider_digest" if mutation == "provider" else "original_lineage_digest")
    elif mutation == "expired":
        value["expires_at"] = "2000-01-01T00:00:00+00:00"
    elif mutation == "naive":
        value["created_at"] = "2000-01-01T00:00:00"
    elif mutation == "authority":
        value["apply_authorized"] = True
    elif mutation == "schema":
        value["schema_version"] = "original-review"
    value["review_digest"] = "f" * 64 if mutation == "digest" else prompt.canonical_digest(value)
    _write(path, value)
    output = path.parent / "approval.json"
    monkeypatch.setattr(
        sys, "argv", ["prompt", "--residual-review", str(path), "--output", str(output)]
    )
    monkeypatch.setattr(
        prompt, "current_actor_digest", lambda *_args: pytest.fail("identity must not be read")
    )
    with pytest.raises(ValueError, match="Genesis residual"):
        prompt.main()
    assert not output.exists()
