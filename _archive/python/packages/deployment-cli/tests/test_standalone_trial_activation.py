"""Deployment-time Trial activation tests."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from fdai_deployment_cli import standalone_trial_activation as activation
from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.standalone_catalog_checkpoint import (
    PostApplicationReceipts,
    run_post_application_checkpoints,
)

_INSTALLATION = "1" * 64
_ANCHOR = "2026-09-01T08:30:00Z"
_DSN = "postgresql://fdai:not-a-secret@db.invalid/fdai"
_CONTEXT = {
    "tenant_id": "00000000-0000-0000-0000-000000000001",
    "subscription_id": "00000000-0000-0000-0000-000000000002",
}


def _work_dir(tmp_path: Path) -> Path:
    for name in ("migration-receipt.json", "application-receipt.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    return tmp_path


def _context(tmp_path: Path) -> dict[str, Any]:
    return {
        **_CONTEXT,
        "infra": str(tmp_path / "bundle" / "infra"),
        "deployment_binding": activation.deployment_binding_digest(_CONTEXT, "aks-fdai-dev"),
    }


def _writer_output(**changes: object) -> str:
    value: dict[str, object] = {
        "schema_version": "fdai.trial-activation.v1",
        "outcome": "retained",
        "activated_at": "2026-09-01T08:30:00+00:00",
        "expires_at": "2026-10-01T08:30:00+00:00",
        "window_ended": False,
        "clock_blocked": False,
    }
    value.update(changes)
    return json.dumps(value)


class _Host:
    """Fake Terraform outputs, Key Vault, and the Core writer for one host run."""

    def __init__(self, writer_output: str = "", writer_code: int = 0) -> None:
        self.commands: list[tuple[str, ...]] = []
        self.writer_env: dict[str, str] = {}
        self.writer_output = writer_output or _writer_output()
        self.writer_code = writer_code
        self.logins = 0

    def output(self, _infra: Path, name: str, **_kwargs: object) -> str:
        return {
            "installation_binding": _INSTALLATION,
            "installation_created_at": _ANCHOR,
            "key_vault_uri": "https://kv-fdai-dev.vault.azure.net/",
        }[name]

    def run(self, command: tuple[str, ...], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.commands.append(tuple(command))
        if command[0] == "az":
            return subprocess.CompletedProcess(command, 0, stdout=f"{_DSN}\n", stderr="")
        self.writer_env = dict(kwargs["env"])
        return subprocess.CompletedProcess(
            command, self.writer_code, stdout=self.writer_output, stderr=""
        )

    def login(self, _context: dict[str, object], _work_dir: Path) -> None:
        self.logins += 1


@pytest.fixture
def host(monkeypatch: pytest.MonkeyPatch) -> _Host:
    fake = _Host()
    monkeypatch.setattr(activation.standalone_planned_outputs, "read_output", fake.output)
    monkeypatch.setattr(activation.subprocess, "run", fake.run)
    return fake


def test_the_deployment_binding_names_no_tenant_value() -> None:
    digest = activation.deployment_binding_digest(_CONTEXT, "aks-fdai-dev")

    assert len(digest) == 64
    assert digest == activation.deployment_binding_digest(_CONTEXT, "aks-fdai-dev")
    assert digest != activation.deployment_binding_digest(_CONTEXT, "aks-fdai-prd")
    with pytest.raises(ValueError, match="runtime name"):
        activation.deployment_binding_digest(_CONTEXT, "AKS")


def test_activation_opens_the_window_at_the_terraform_anchor(tmp_path: Path, host: _Host) -> None:
    context = _context(tmp_path)

    receipt = activation.activate_trial(context, _work_dir(tmp_path), login=host.login)

    writer = host.commands[-1]
    assert writer[1:3] == ("-m", "fdai.runtime.licensing_trial_activation")
    assert writer[writer.index("--installation-binding") + 1] == _INSTALLATION
    assert writer[writer.index("--deployment-binding") + 1] == context["deployment_binding"]
    assert writer[writer.index("--activated-at") + 1] == _ANCHOR
    assert host.writer_env["FDAI_STATE_STORE_DSN"] == _DSN
    assert receipt["state"] == "activated"
    assert receipt["expires_at"] == "2026-10-01T08:30:00+00:00"
    assert _DSN not in json.dumps(receipt)
    assert activation.require_trial_activation_receipt(receipt) == receipt


def test_a_recorded_activation_is_returned_without_running_again(
    tmp_path: Path, host: _Host
) -> None:
    work_dir = _work_dir(tmp_path)
    first = activation.activate_trial(_context(tmp_path), work_dir, login=host.login)
    count = len(host.commands)

    second = activation.activate_trial(_context(tmp_path), work_dir, login=host.login)

    assert second == first
    assert len(host.commands) == count
    assert host.logins == 1


def test_activation_requires_the_applied_application_and_binding(
    tmp_path: Path, host: _Host
) -> None:
    with pytest.raises(ValueError, match="migrated and applied"):
        activation.activate_trial(_context(tmp_path), tmp_path, login=host.login)

    context = {**_context(tmp_path), "deployment_binding": ""}
    with pytest.raises(ValueError, match="deployment binding"):
        activation.activate_trial(context, _work_dir(tmp_path), login=host.login)
    assert host.commands == []


@pytest.mark.parametrize(
    ("output", "code"),
    [
        (_writer_output(), 3),
        ("not json", 0),
        (_writer_output(outcome="failed"), 0),
        (_writer_output(window_ended="no"), 0),
    ],
)
def test_a_failed_or_malformed_writer_records_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, output: str, code: int
) -> None:
    fake = _Host(writer_output=output, writer_code=code)
    monkeypatch.setattr(activation.standalone_planned_outputs, "read_output", fake.output)
    monkeypatch.setattr(activation.subprocess, "run", fake.run)
    work_dir = _work_dir(tmp_path)

    with pytest.raises(ValueError, match="Trial activation"):
        activation.activate_trial(_context(tmp_path), work_dir, login=fake.login)

    assert not (work_dir / "trial-activation-receipt.json").exists()


def test_a_tampered_receipt_is_refused() -> None:
    receipt: dict[str, object] = {
        "schema_version": "fdai.standalone-trial-activation-receipt.v1",
        "state": "activated",
        "activated_at": _ANCHOR,
        "expires_at": "2026-10-01T08:30:00Z",
        "window_ended": False,
        "clock_blocked": False,
        "effect_verified": True,
        "mutation_performed": True,
        "subscription_ready": False,
    }
    signed = {**receipt, "receipt_digest": canonical_digest(receipt)}

    assert activation.require_trial_activation_receipt(signed) == signed
    with pytest.raises(ValueError, match="receipt is invalid"):
        activation.require_trial_activation_receipt({**signed, "window_ended": True})


@pytest.mark.parametrize(("platform", "activated"), [("aks", True), ("container-apps", False)])
def test_aks_opens_the_trial_before_the_initial_inventory(
    monkeypatch: pytest.MonkeyPatch, platform: str, activated: bool
) -> None:
    calls: list[str] = []
    trial: dict[str, object] = {
        "schema_version": "fdai.standalone-trial-activation-receipt.v1",
        "state": "activated",
        "activated_at": _ANCHOR,
        "expires_at": "2026-10-01T08:30:00Z",
        "window_ended": False,
        "clock_blocked": False,
        "effect_verified": True,
        "mutation_performed": True,
        "subscription_ready": False,
    }
    trial["receipt_digest"] = canonical_digest(trial)
    monkeypatch.setattr(
        "fdai_deployment_cli.standalone_catalog_checkpoint.require_initial_inventory_receipt",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "fdai_deployment_cli.standalone_catalog_checkpoint.require_catalog_review_receipt",
        lambda *_args: None,
    )

    def remote(_tunnel: object, _root: str, _work: str, arguments: tuple[str, ...], **_: object):
        calls.append(arguments[0])
        return trial if arguments[0] == "activate-trial" else {}

    receipts = run_post_application_checkpoints(
        object(),
        remote_root="/root",
        app_work="/work",
        runtime_platform=platform,
        remote_json=remote,
    )

    expected = ["activate-trial"] if activated else []
    assert calls == [*expected, "initial-inventory", "catalog-review"]
    assert (receipts.trial_activation is not None) is activated
    assert receipts.trial_open is activated


@pytest.mark.parametrize("closed", ["window_ended", "clock_blocked"])
def test_an_ended_or_untrusted_trial_window_is_not_reported_open(closed: str) -> None:
    trial = {"window_ended": False, "clock_blocked": False, closed: True}

    receipts = PostApplicationReceipts(inventory={}, catalog_review={}, trial_activation=trial)

    assert receipts.trial_open is False
