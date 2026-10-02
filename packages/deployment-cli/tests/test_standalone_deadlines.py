"""Deterministic deadline evidence without Azure, approvals, or remote effects."""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

from fdai_deployment_cli import (
    standalone_application_completion,
    standalone_deploy,
    standalone_foundation_adoption,
)


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
        "create_runner_image": None,
        "foundation_adoption": None,
        "preparation_calls": 0,
        "foundation_source_commit": None,
        "foundation_env": None,
    }

    def prepare(**kwargs):
        clock[0] += options["preparation_elapsed"]
        options["preparation_calls"] += 1
        options["create_runner_image"] = kwargs["create_runner_image"]
        if options["foundation_source_commit"] is not None:
            prepared.foundation_source_commit = options["foundation_source_commit"]
        prepared.root.mkdir(parents=True, mode=0o700)
        return prepared

    def foundation(*args, **kwargs):
        clock[0] += options["foundation_elapsed"]
        options["foundation_command"] = args[0]
        options["foundation_env"] = kwargs.get("env")
        return subprocess.CompletedProcess([], 2)

    def identity(**_kwargs):
        clock[0] += options["identity_elapsed"]
        return {}

    def prompt(*_args, **kwargs):
        options["prompt_timeout"] = kwargs["timeout"]
        raise RuntimeError("stop-after-prompt")

    def application(**kwargs):
        options["application_timeout"] = kwargs["timeout_seconds"]
        return {
            "receipt_digest": "e" * 64,
            "catalog_review_receipt_digest": "c" * 64,
            "catalog_review_state": "skipped",
            "license_mode": "observation-only",
        }

    modules = {
        "genesis_prepare": SimpleNamespace(prepare_standalone_genesis=prepare),
        "genesis_supervisor": SimpleNamespace(_configure_entra=identity),
        "genesis_entra": SimpleNamespace(plan_entra=dict),
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
    monkeypatch.setattr(
        standalone_application_completion.importlib,
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
    monkeypatch.setattr(
        standalone_foundation_adoption,
        "stage_recovered_foundation",
        lambda **kwargs: (
            options.__setitem__("foundation_adoption", kwargs)
            or SimpleNamespace(
                prepared=prepared,
                status={
                    "foundation_report": {"foundation_plan": {"plan_ref": "foundation-adoption"}}
                },
                receipt={
                    "foundation_state_receipt_digest": "f" * 64,
                    "receipt_digest": "9" * 64,
                },
            )
        ),
    )
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
    monkeypatch.setattr(
        standalone_application_completion,
        "deploy_standalone_application",
        application,
    )
    monkeypatch.setattr(standalone_deploy, "_current_operator_object_id", lambda: "synthetic")

    def invoke(
        *,
        runner_receipt=None,
        online=True,
        foundation_adoption=False,
        product_add_ons=(),
    ):
        return standalone_deploy.deploy_azure_foundation(
            work_dir=root,
            online=online,
            offline_kit=None if online else tmp_path / "kit",
            online_url=None,
            region="koreacentral",
            monthly_cost_ceiling=1000,
            timeout_seconds=2000,
            runtime_profile=standalone_deploy.RuntimeDeploymentProfile.create(
                runtime_platform="container-apps",
                database_placement="postgres-flex",
                product_add_ons=product_add_ons,
            ),
            trial_token=None,
            adopt_runner_image_receipt=runner_receipt,
            adopt_foundation_directory=(
                tmp_path / "retained-foundation" if foundation_adoption else None
            ),
            adopt_foundation_recovery_directory=(
                tmp_path / "retained-recovery" if foundation_adoption else None
            ),
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
    invoke(product_add_ons=("enterprise-identity-governance",))
    assert options["application_timeout"] == 200


def test_default_profile_skips_the_identity_stage_budget(coordinator):
    invoke, options, _clock = coordinator
    options.update(application=True, foundation_elapsed=1700, identity_elapsed=100)
    invoke()
    assert options["application_timeout"] == 300


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
    assert options["create_runner_image"] is False
    assert "--create-runner-image" not in command
    assert "--runner-image-terraform" not in command
    variables = command[command.index("--foundation-variables-file") + 1]
    assert variables.endswith("foundation-with-runner-image.json")


def test_connected_deployment_uses_marketplace_bootstrap_without_image_build(coordinator):
    invoke, options, _clock = coordinator
    with pytest.raises(RuntimeError, match="stop-after-prompt"):
        invoke()

    command = options["foundation_command"]
    assert options["create_runner_image"] is False
    assert "--create-runner-image" not in command
    assert "--runner-image-terraform" not in command
    variables = command[command.index("--foundation-variables-file") + 1]
    assert variables.endswith("vars.json")


def test_foundation_adoption_skips_foundation_effects(coordinator):
    invoke, options, _clock = coordinator

    result = invoke(foundation_adoption=True)

    assert options["preparation_calls"] == 0
    assert options["foundation_command"] is None
    assert options["foundation_adoption"]["application_source_commit"] == "a" * 40
    assert result["foundation_state_receipt_digest"] == "f" * 64
    assert result["foundation_adoption_receipt_digest"] == "9" * 64
    assert result["deployment_ready"] is True


def test_foundation_adoption_rejects_runner_image_reselection(coordinator, tmp_path):
    invoke, options, _clock = coordinator

    with pytest.raises(ValueError, match="cannot combine"):
        invoke(
            runner_receipt=tmp_path / "runner-receipt.json",
            foundation_adoption=True,
        )

    assert options["preparation_calls"] == 0
    assert options["foundation_command"] is None


def test_offline_deployment_retains_image_build_context(coordinator):
    invoke, options, _clock = coordinator
    with pytest.raises(RuntimeError, match="stop-after-prompt"):
        invoke(online=False)

    command = options["foundation_command"]
    assert options["create_runner_image"] is True
    assert "--create-runner-image" in command
    assert "--runner-image-terraform" in command


def _source_argument(options: dict[str, object]) -> str:
    command = list(options["foundation_command"])  # type: ignore[call-overload]
    return str(command[command.index("--source-commit") + 1])


def test_a_new_installation_binds_the_foundation_to_the_kit_source(coordinator):
    invoke, options, _clock = coordinator
    with pytest.raises(RuntimeError, match="stop-after-prompt"):
        invoke()

    evidence = json.loads(options["foundation_env"]["FDAI_SIGNED_SOURCE_EVIDENCE"])
    assert _source_argument(options) == "a" * 40
    assert evidence["source_commit"] == evidence["foundation_source_commit"] == "a" * 40


def test_an_offline_upgrade_continues_the_foundation_under_its_retained_lineage(coordinator):
    invoke, options, _clock = coordinator
    options["foundation_source_commit"] = "f" * 40

    # A new Foundation plan under the old lineage is refused before any approval prompt.
    with pytest.raises(ValueError, match="cannot approve a new Foundation plan"):
        invoke()

    evidence = json.loads(options["foundation_env"]["FDAI_SIGNED_SOURCE_EVIDENCE"])
    assert _source_argument(options) == "f" * 40
    assert evidence["source_commit"] == "a" * 40
    assert evidence["foundation_source_commit"] == "f" * 40
    assert options["prompt_timeout"] is None


def test_an_offline_upgrade_reaches_the_application_with_the_kit_source(coordinator):
    invoke, options, _clock = coordinator
    options.update(application=True, foundation_source_commit="f" * 40)

    invoke(product_add_ons=("enterprise-identity-governance",))

    assert _source_argument(options) == "f" * 40
    assert options["application_timeout"] is not None
