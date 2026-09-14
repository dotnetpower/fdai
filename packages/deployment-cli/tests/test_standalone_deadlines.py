"""Deterministic deadline evidence without Azure, approvals, or remote effects."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from fdai_deployment_cli import standalone_deploy


@pytest.fixture
def coordinator(tmp_path, monkeypatch):
    clock = [0.0]
    bundle = tmp_path / "bundle"
    (bundle / "scripts/deployment/azure").mkdir(parents=True)
    root = tmp_path / "work"
    prepared = SimpleNamespace(
        root=root / "run",
        offline_kit=tmp_path / "kit",
        release_root=tmp_path / "release.pub",
        bundle_public_key=tmp_path / "bundle.pub",
        profile=tmp_path / "profile.json",
        variables=tmp_path / "vars.json",
        terraform=tmp_path / "terraform",
        ssh_private_key=tmp_path / "key-path-only",
        run_binding="a" * 64,
    )
    kit = SimpleNamespace(
        bundle_root=bundle,
        source_commit="a" * 40,
        verification=SimpleNamespace(manifest_digest="b" * 64),
        bundle_manifest_digest="c" * 64,
        runtime=SimpleNamespace(digest="d" * 64),
    )
    options = {
        "preparation_elapsed": 0,
        "foundation_elapsed": 0,
        "identity_elapsed": 0,
        "application": False,
        "prompt_timeout": None,
        "application_timeout": None,
        "foundation_command": None,
        "runner_receipt": None,
    }

    def prepare(**_kwargs):
        clock[0] += options["preparation_elapsed"]
        prepared.root.mkdir(parents=True, mode=0o700)
        return prepared

    def foundation(*args, **_kwargs):
        clock[0] += options["foundation_elapsed"]
        options["foundation_command"] = args[0]
        return subprocess.CompletedProcess([], 2)

    def identity(**_kwargs):
        clock[0] += options["identity_elapsed"]
        return {}

    def prompt(*_args, **kwargs):
        options["prompt_timeout"] = kwargs["timeout"]
        raise RuntimeError("stop-after-prompt")

    def application(**kwargs):
        options["application_timeout"] = kwargs["timeout_seconds"]
        return {"receipt_digest": "e" * 64, "license_mode": "observation-only"}

    modules = {
        "genesis_prepare": SimpleNamespace(prepare_standalone_genesis=prepare),
        "genesis_supervisor": SimpleNamespace(_configure_entra=identity),
        "genesis_entra": SimpleNamespace(plan_entra=lambda: {}),
        "genesis_approval_prompt": SimpleNamespace(current_actor_digest=lambda _binding: "a" * 64),
        "genesis_runner_image_contract": SimpleNamespace(
            materialize_foundation_image_input=lambda **kwargs: (
                options.__setitem__("runner_receipt", kwargs["image_receipt"]),
                kwargs["destination"].write_text("{}", encoding="utf-8"),
            ),
            verify_foundation_image_input=lambda **_kwargs: None,
        ),
    }
    original_import = standalone_deploy.importlib.import_module
    monkeypatch.setattr(
        standalone_deploy.importlib,
        "import_module",
        lambda name: modules[name] if name in modules else original_import(name),
    )
    monkeypatch.setattr(standalone_deploy, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(
        standalone_deploy,
        "active_azure_target",
        lambda: SimpleNamespace(
            subscription_id="00000000-0000-0000-0000-000000000001",
            tenant_id="00000000-0000-0000-0000-000000000000",
        ),
    )
    monkeypatch.setattr(standalone_deploy, "acquire_deployment_kit", lambda **_kwargs: kit)
    monkeypatch.setattr(standalone_deploy, "run_foundation_process", foundation)
    monkeypatch.setattr(standalone_deploy, "prior_attempt", lambda _path: 0)
    monkeypatch.setattr(
        standalone_deploy,
        "current_status",
        lambda *_args, **_kwargs: {
            "current_stage": "application-plan" if options["application"] else "foundation-apply",
            "route": "private-runner",
            "completed_stages": ["foundation-state"],
            "foundation_report": {"state_handoff": {"receipt_digest": "f" * 64}},
        },
    )
    monkeypatch.setattr(standalone_deploy.subprocess, "run", prompt)
    monkeypatch.setattr(standalone_deploy, "deploy_standalone_application", application)
    monkeypatch.setattr(standalone_deploy, "_current_operator_object_id", lambda: "synthetic")

    def invoke(*, runner_receipt=None):
        return standalone_deploy.deploy_azure_foundation(
            work_dir=root,
            online=True,
            offline_kit=None,
            online_url=None,
            region="koreacentral",
            monthly_cost_ceiling=1000,
            timeout_seconds=2000,
            license_signing_key=None,
            trial_token=None,
            adopt_runner_image_receipt=runner_receipt,
        )

    return invoke, options, clock


def test_approval_prompt_uses_only_remaining_deadline(coordinator):
    invoke, options, _clock = coordinator
    options["foundation_elapsed"] = 1980
    with pytest.raises(RuntimeError, match="stop-after-prompt"):
        invoke()
    assert options["prompt_timeout"] == 20


def test_application_receives_budget_after_foundation_and_identity(coordinator):
    invoke, options, _clock = coordinator
    options.update(application=True, foundation_elapsed=1700, identity_elapsed=100)
    invoke()
    assert options["application_timeout"] == 200


def test_preparation_does_not_reset_the_overall_deadline(coordinator):
    invoke, options, _clock = coordinator
    options["preparation_elapsed"] = 1900
    with pytest.raises(TimeoutError, match="remaining budget"):
        invoke()
    assert options["prompt_timeout"] is None


def test_verified_runner_receipt_skips_image_build(coordinator, tmp_path):
    invoke, options, _clock = coordinator
    receipt = tmp_path / "runner-receipt.json"
    with pytest.raises(RuntimeError, match="stop-after-prompt"):
        invoke(runner_receipt=receipt)

    command = options["foundation_command"]
    assert options["runner_receipt"] == receipt
    assert "--create-runner-image" not in command
    assert "--runner-image-terraform" not in command
    variables = command[command.index("--foundation-variables-file") + 1]
    assert variables.endswith("foundation-with-runner-image.json")
