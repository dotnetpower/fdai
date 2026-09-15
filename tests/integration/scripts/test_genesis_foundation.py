"""Private Genesis Foundation planning adapter regressions."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT_DIR = _ROOT / "scripts/deployment/azure"
sys.path.insert(0, str(_SCRIPT_DIR))

import genesis_foundation_recovery_plan as recovery_planner  # noqa: E402
from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest  # noqa: E402
from fdai_deployment_cli.private_output import write_private_bytes  # noqa: E402
from fdai_deployment_cli.target import compute_target_binding  # noqa: E402
from genesis_foundation import (  # noqa: E402
    FoundationPlanError,
    FoundationPlanInputs,
    SourceFoundationPlanInputs,
    missing_foundation_report,
    prepare_foundation_plan,
)
from genesis_foundation_recovery import (  # noqa: E402
    select_public_ip_tags,
    validate_recovery_plan,
)
from genesis_foundation_recovery_plan import (  # noqa: E402
    prepare_recovery_plan,
    require_naming_only,
)
from genesis_status import StatusStore  # noqa: E402


@pytest.mark.parametrize("defect", [None, "concurrent-state", "existing-group", "expanded-role"])
def test_foundation_recovery_planner_never_applies_or_copies_state(
    tmp_path, monkeypatch, recovery_plans, defect, *, successor_case=None
):
    old_projection, projection, state = successor_case or recovery_plans
    parent = tmp_path / "foundation"
    parent.mkdir(mode=0o700)
    original = parent / "original"
    original.mkdir(mode=0o700)
    write_private_bytes(parent / "source-execution.lock", b"")
    snapshot = tmp_path / "snapshot"
    infra = snapshot / "tree/infra/genesis-foundation"
    infra.mkdir(parents=True)
    current = _ROOT / "infra/genesis-foundation"
    main = (
        (current / "main.tf")
        .read_bytes()
        .replace(
            b'  application_suffix    = "${coalesce(var.application_workload, var.workload)}'
            b'-${var.env}-${var.region_short}"\n',
            b"",
        )
        .replace(b'"rg-${local.application_suffix}"', b'"rg-${local.suffix}"')
    )
    variables_text = (current / "variables.tf").read_text()
    start = variables_text.index('variable "application_workload"')
    end = variables_text.index('variable "env"', start)
    (infra / "main.tf").write_bytes(main)
    (infra / "main.tf").write_bytes(
        main.replace(b"  operations_public_ip_tags    = var.operations_public_ip_tags\n", b"")
    )
    (infra / "variables.tf").write_text(variables_text[:start] + variables_text[end:])
    bootstrap = infra.parent / "bootstrap"
    bootstrap.mkdir()
    for name in ("nat.tf", "bastion.tf"):
        content = (_ROOT / "infra/bootstrap" / name).read_bytes()
        (bootstrap / name).write_bytes(
            content.replace(b"  ip_tags             = var.operations_public_ip_tags\n", b"")
        )
    (bootstrap / "variables.tf").write_bytes(
        recovery_planner._without_variable(
            (_ROOT / "infra/bootstrap/variables.tf").read_bytes(), "operations_public_ip_tags"
        )
    )
    if successor_case:
        from genesis_foundation_recovery_successor import REPAIRS

        content = (_ROOT / "infra/bootstrap/main.tf").read_bytes()
        for before, after in REPAIRS:
            content = content.replace(after, before)
        (bootstrap / "main.tf").write_bytes(content)
    persistent = original / "foundation-apply-bundle/source"
    persistent.mkdir(mode=0o700, parents=True)
    recovery_planner._copy_private_tree(snapshot / "tree/infra", persistent / "infra")
    state_path = persistent / "infra/genesis-foundation/terraform.tfstate"
    state_bytes = canonical_bytes(state)
    write_private_bytes(state_path, state_bytes)
    write_private_bytes(
        original / "foundation-apply-claim.json", canonical_bytes({"claim": "original"})
    )
    provider = original / "terraform-data"
    provider.mkdir(mode=0o700)
    write_private_bytes(provider / "provider", b"locked-provider")
    source_record = {"source_commit": "a" * 40}
    variables = {"workload": "example", "env": "dev"}
    if successor_case:
        expected_variables = {
            **variables,
            "application_workload": "exampleaks",
            "operations_public_ip_tags": {},
        }
        for document in (old_projection, projection):
            document["variables"] = {
                key: {"value": value} for key, value in expected_variables.items()
            }
        predecessor = (
            {
                "variables_digest": canonical_digest(expected_variables),
                "original_lineage_digest": canonical_digest({"lineage": state["lineage"]}),
                "review_digest": "9" * 64,
            },
            {"claim": "predecessor"},
            old_projection,
        )
        monkeypatch.setattr(
            recovery_planner, "load_predecessor", lambda *_args, **_kwargs: predecessor
        )
    review = {
        "schema_version": "fdai.foundation-saved-source-plan.v1",
        "context": {
            "source_snapshot_digest": "d" * 64,
            "source_input_digest": canonical_digest(source_record),
            "source_commit": "a" * 40,
            "terraform_digest": "f" * 64,
            "variables_digest": canonical_digest(variables),
        },
        "plan_json_digest": hashlib.sha256(canonical_bytes(old_projection)).hexdigest(),
    }
    write_private_bytes(original / "foundation-plan.json", canonical_bytes(review))
    target = SimpleNamespace(
        tenant_id="00000000-0000-0000-0000-000000000000",
        subscription_id="00000000-0000-0000-0000-000000000001",
    )
    binding = compute_target_binding(
        tenant_id=target.tenant_id, subscription_id=target.subscription_id
    )
    monkeypatch.setattr(
        recovery_planner,
        "load_profile",
        lambda *_args: SimpleNamespace(
            environment="dev", transport="manual", target_binding=binding, region="koreacentral"
        ),
    )
    monkeypatch.setattr(recovery_planner, "verify_foundation_plan", lambda **_kwargs: {})
    monkeypatch.setattr(
        recovery_planner, "load_apply_claim", lambda *_args, **_kwargs: {"claim": "original"}
    )
    monkeypatch.setattr(
        recovery_planner, "verify_source_snapshot", lambda *_args, **_kwargs: source_record
    )
    monkeypatch.setattr(
        recovery_planner,
        "inspect_source",
        lambda *_args: SimpleNamespace(root=_ROOT, commit="b" * 40, reverify=lambda: None),
    )
    monkeypatch.setattr(recovery_planner, "active_azure_target", lambda: target)
    monkeypatch.setattr(recovery_planner.image, "_trusted_terraform", lambda path: path)
    monkeypatch.setattr(recovery_planner.image, "_file_digest", lambda *_args: "f" * 64)
    monkeypatch.setattr(
        recovery_planner,
        "snapshot_foundation_input",
        lambda _source, output, **_kwargs: write_private_bytes(output, canonical_bytes(variables)),
    )
    work = tmp_path / "recovery"
    monkeypatch.setattr(
        recovery_planner.image,
        "_terraform_environment",
        lambda *_args, **_kwargs: {"TF_DATA_DIR": str(work / "terraform-data")},
    )
    monkeypatch.setattr(recovery_planner.image, "_trusted_azure_cli", lambda: Path("/synthetic/az"))
    monkeypatch.setattr(
        recovery_planner.image,
        "_capture",
        lambda *_args, **_kwargs: (
            "true"
            if defect == "existing-group"
            else "synthetic-group"
            if successor_case
            else "false"
        ),
    )
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        assert "apply" not in command
        assert kwargs["timeout"] <= 60
        if command[1] == "init":
            shutil.copytree(provider, work / "terraform-data")
        if command[1] == "plan":
            assert f"-state={state_path}" in command
            write_private_bytes(work / "recovery.tfplan", b"new-plan")
            if defect == "concurrent-state":
                state_path.write_bytes(canonical_bytes({**state, "serial": 28}))
            if defect == "expanded-role":
                projection["resource_changes"][2]["change"]["after"]["role_definition_name"] = (
                    "Owner"
                )
        output = (
            canonical_bytes(
                old_projection if command[-1].endswith("foundation.tfplan") else projection
            ).decode()
            if command[1] == "show"
            else "ok"
        )
        return subprocess.CompletedProcess(command, 0, output, "")

    monkeypatch.setattr(recovery_planner, "run_with_heartbeat", run)
    arguments = dict(
        repository_root=_ROOT,
        original_directory=original,
        source_snapshot=snapshot,
        work_dir=work,
        terraform=tmp_path / "terraform",
        expected_review_digest="c" * 64,
        application_workload="exampleaks",
        timeout_seconds=60,
    )
    if successor_case:
        arguments["predecessor_directory"] = tmp_path / "predecessor"
    if defect is None:
        result = prepare_recovery_plan(**arguments)
        assert result["original_state_unchanged"] is True
        assert result["apply_authorized"] is False
        assert result["application_group_absent"] is (successor_case is None)
        if successor_case:
            assert result["application_group_preserved"] is True
            assert result["predecessor_claim_digest"] == canonical_digest({"claim": "predecessor"})
        assert result["original_state_digest"] == hashlib.sha256(state_bytes).hexdigest()
    else:
        with pytest.raises(ValueError):
            prepare_recovery_plan(**arguments)
        assert not (work / "recovery-review.json").exists()
    assert not list(work.rglob("terraform.tfstate"))
    assert commands
    if defect != "concurrent-state":
        assert state_path.read_bytes() == state_bytes


def test_recovery_configuration_permits_only_application_naming(tmp_path):
    current = _ROOT / "infra/genesis-foundation"
    original = tmp_path / "original"
    original.mkdir()
    main = (
        (current / "main.tf")
        .read_bytes()
        .replace(
            b'  application_suffix    = "${coalesce(var.application_workload, var.workload)}'
            b'-${var.env}-${var.region_short}"\n',
            b"",
        )
        .replace(b'"rg-${local.application_suffix}"', b'"rg-${local.suffix}"')
    )
    variables = (current / "variables.tf").read_text()
    start = variables.index('variable "application_workload"')
    end = variables.index('variable "env"', start)
    main = main.replace(b"  operations_public_ip_tags    = var.operations_public_ip_tags\n", b"")
    (original / "main.tf").write_bytes(main)
    (original / "variables.tf").write_text(variables[:start] + variables[end:])
    require_naming_only(original, current)
    (original / "main.tf").write_bytes(main + b"\nchanged\n")
    with pytest.raises(ValueError, match="more than application"):
        require_naming_only(original, current)


def test_recovery_requires_original_lock_before_any_planning(tmp_path):
    original = tmp_path / "original"
    original.mkdir()
    with pytest.raises(FileNotFoundError):
        prepare_recovery_plan(
            repository_root=_ROOT,
            original_directory=original,
            source_snapshot=tmp_path / "snapshot",
            work_dir=tmp_path / "new",
            terraform=tmp_path / "terraform",
            expected_review_digest="a" * 64,
            application_workload="exampleaks",
        )
    assert not (tmp_path / "new").exists()


@pytest.fixture
def recovery_plans():
    variables = {"workload": {"value": "example"}, "env": {"value": "dev"}}
    entries = [
        {
            "address": "azapi_resource.app_resource_group",
            "type": "azapi_resource",
            "mode": "managed",
            "change": {
                "actions": ["create"],
                "before": None,
                "after": {"name": "original", "tags": {"run": "same"}},
                "after_unknown": {"id": True},
            },
        },
        {
            "address": "azurerm_virtual_network.ops",
            "type": "azurerm_virtual_network",
            "mode": "managed",
            "change": {
                "actions": ["create"],
                "before": None,
                "after": {"name": "ops", "id": None},
                "after_unknown": {"id": True},
            },
        },
        {
            "address": "azurerm_role_assignment.app",
            "type": "azurerm_role_assignment",
            "mode": "managed",
            "change": {
                "actions": ["create"],
                "before": None,
                "after": {"role_definition_name": "Contributor", "scope": None},
                "after_unknown": {"scope": True},
            },
        },
    ]
    original = {"variables": variables, "resource_changes": entries}
    current = copy.deepcopy(original)
    current.update({"complete": True, "errored": False, "applyable": True})
    current["variables"]["application_workload"] = {"value": "exampleaks"}
    current["resource_changes"][0]["change"]["after"]["name"] = "separate"
    preserved = current["resource_changes"][1]["change"]
    preserved.update({"actions": ["no-op"], "after": {"id": "synthetic-id", "name": "ops"}})
    preserved["before"] = copy.deepcopy(preserved["after"])
    state = {
        "version": 4,
        "serial": 27,
        "lineage": "synthetic",
        "resources": [
            {
                "mode": "managed",
                "type": "azurerm_virtual_network",
                "name": "ops",
                "instances": [{"attributes": {"id": "synthetic-id"}}],
            }
        ],
    }
    return original, current, state


@pytest.mark.parametrize("drift", [False, True])
def test_recovery_preserves_real_state_not_original_planning_defaults(recovery_plans, drift):
    original, current, state = recovery_plans
    attributes = state["resources"][0]["instances"][0]["attributes"]
    attributes.update({"name": "ops", "tags": {}, "dns_servers": None})
    change = current["resource_changes"][1]["change"]
    change["after"].update({"tags": {}, "dns_servers": [], "name": "changed" if drift else "ops"})
    change["before"] = copy.deepcopy(change["after"])
    original["resource_changes"][1]["change"]["after"]["tags"] = {"initial": "planned"}
    if drift:
        with pytest.raises(ValueError, match="known resource setting"):
            validate_recovery_plan(current, original, state, application_workload="exampleaks")
    else:
        validate_recovery_plan(current, original, state, application_workload="exampleaks")


@pytest.mark.parametrize(
    "tags",
    [{}, {"FirstPartyUsage": "/Unprivileged"}, {"FirstPartyUsage": "other"}, {"other": "tag"}],
)
def test_recovery_limits_observed_ip_tags(recovery_plans, tags):
    state = copy.deepcopy(recovery_plans[2])
    state["resources"] = [
        {
            "module": "module.bootstrap",
            "mode": "managed",
            "type": "azurerm_public_ip",
            "name": name,
            "instances": [{"index_key": 0, "attributes": {"id": name, "ip_tags": tags}}],
        }
        for name in ("bastion", "nat")
    ]
    if tags in ({}, {"FirstPartyUsage": "/Unprivileged"}):
        assert select_public_ip_tags(state) == tags
    else:
        with pytest.raises(ValueError, match="policy tags"):
            select_public_ip_tags(state)


def test_residual_foundation_only_names_missing_application_group(recovery_plans):
    original, current, state = recovery_plans
    result = validate_recovery_plan(current, original, state, application_workload="exampleaks")
    assert result["preserved_managed_count"] == 1
    assert len(result["remaining_addresses"]) == 2
    assert result["apply_authorized"] is False
    assert result["mutation_performed"] is False
    assert result["deployment_ready"] is False


@pytest.mark.parametrize(
    "defect",
    [
        "delete",
        "replace",
        "role",
        "state-id",
        "variable",
        "duplicate",
        "missing",
        "import",
        "tainted",
        "deposed",
        "checks",
        "deferred",
        "same-name",
        "changed-tag",
        "moved",
    ],
)
def test_residual_foundation_rejects_scope_expansion(recovery_plans, defect):
    original, current, state = recovery_plans
    entries = current["resource_changes"]
    if defect in {"delete", "replace"}:
        entries[1]["change"]["actions"] = ["delete"] if defect == "delete" else ["delete", "create"]
    elif defect == "role":
        entries[2]["change"]["after"]["role_definition_name"] = "Owner"
    elif defect == "state-id":
        state["resources"][0]["instances"][0]["attributes"]["id"] = "different"
    elif defect == "variable":
        current["variables"]["workload"] = {"value": "different"}
    elif defect == "duplicate":
        entries.append(copy.deepcopy(entries[0]))
    elif defect == "missing":
        entries.pop()
    elif defect == "import":
        entries[0]["change"]["importing"] = {"id": "existing"}
    elif defect in {"tainted", "deposed"}:
        state["resources"][0]["instances"][0]["status" if defect == "tainted" else "deposed"] = (
            defect
        )
    elif defect == "checks":
        current["checks"] = [{"status": "fail"}]
    elif defect == "deferred":
        current["deferred_changes"] = [{}]
    elif defect == "same-name":
        entries[0]["change"]["after"]["name"] = "original"
    elif defect == "changed-tag":
        entries[0]["change"]["after"]["tags"]["run"] = "different"
    else:
        entries[0]["previous_address"] = "another"
    with pytest.raises(ValueError):
        validate_recovery_plan(current, original, state, application_workload="exampleaks")


@pytest.fixture(autouse=True)
def _isolate_host_provider_preflight(monkeypatch):
    """This suite owns saved-plan orchestration; VM provider boundaries have dedicated tests."""
    monkeypatch.setattr("genesis_foundation.recheck_foundation_vm", lambda **_kwargs: None)


def _inputs(tmp_path: Path) -> FoundationPlanInputs:
    return FoundationPlanInputs(
        offline_kit=tmp_path / "offline-kit",
        release_root=tmp_path / "release-root.pem",
        bundle_public_key=tmp_path / "bundle-public-key.pem",
        profile=tmp_path / "profile.json",
        variables_file=tmp_path / "variables.json",
    )


def _saved_result(*, expires_at: str = "2999-09-10T12:00:00+00:00") -> str:
    return json.dumps(
        {
            "schema_version": "fdai.provision-plan.v1",
            "stage": "foundation",
            "state": "review",
            "apply_authorized": False,
            "mutation_performed": False,
            "subscription_ready": False,
            "saved_plan": {
                "schema_version": "fdai.foundation-saved-plan.v1",
                "state": "review",
                "apply_authorized": False,
                "mutation_performed": False,
                "subscription_ready": False,
                "review_digest": "a" * 64,
                "plan_digest": "b" * 64,
                "expires_at": expires_at,
            },
        }
    )


def test_missing_report_names_every_external_boundary_without_paths() -> None:
    report = missing_foundation_report()

    assert report["state"] == "waiting"
    assert report["required_count"] == 5
    assert report["supplied_count"] == 0
    assert report["missing"] == [
        "signed_offline_kit",
        "release_public_key",
        "bundle_public_key",
        "foundation_profile",
        "foundation_variables",
    ]
    assert report["apply_authorized"] is False
    assert report["subscription_ready"] is False
    assert not any("/" in str(value) for value in report.values())


def test_complete_inputs_generate_only_an_exact_saved_plan(tmp_path: Path) -> None:
    calls: list[tuple[tuple[str, ...], str, dict[str, object]]] = []

    def capture(command: tuple[str, ...], reason: str, **kwargs: object) -> str:
        calls.append((command, reason, kwargs))
        return _saved_result()

    report = prepare_foundation_plan(
        inputs=_inputs(tmp_path),
        repository_root=_ROOT,
        orchestration_work_dir=tmp_path / "run",
        attempt=3,
        prior_report=None,
        timeout=900,
        capture=capture,
    )

    assert len(calls) == 1
    command, reason, options = calls[0]
    assert command[:3] == (sys.executable, "-m", "fdai_deployment_cli")
    assert command[3:7] == ("provision", "plan", "--stage", "foundation")
    assert "--save-plan" in command
    assert "apply" not in command
    assert command[command.index("--work-dir") + 1].endswith("/foundation-plan-attempt-3")
    assert reason == "foundation_plan_generation_failed"
    assert options == {"strip": False, "timeout": 900}
    assert report == {
        "schema_version": "fdai.genesis-foundation-plan.v1",
        "state": "review",
        "plan_ref": "foundation-plan-attempt-3",
        "attempt": 3,
        "review_digest": "a" * 64,
        "plan_digest": "b" * 64,
        "expires_at": "2999-09-10T12:00:00+00:00",
        "integrity_verified": True,
        "apply_authorized": False,
        "mutation_performed": False,
        "subscription_ready": False,
    }


@pytest.mark.parametrize("defect", [None, "kit-result", "kit-review", "snapshot", "signature"])
def test_source_foundation_plan_never_adopts_kit_provenance(tmp_path, monkeypatch, defect):
    snapshot_digest = "d" * 64
    monkeypatch.setattr(
        "genesis_foundation.verify_source_snapshot", lambda *_, **__: {"source_commit": "c" * 40}
    )
    inputs = SourceFoundationPlanInputs(
        source_snapshot=tmp_path / "snapshot",
        source_snapshot_digest=snapshot_digest,
        terraform=tmp_path / "terraform",
        profile=tmp_path / "profile.json",
        variables_file=tmp_path / "variables.json",
    )

    def capture(command, _reason, **_kwargs):
        assert "--source-snapshot" in command
        assert "--offline-kit" not in command
        assert "--release-root" not in command
        assert "--bundle-public-key" not in command
        result = json.loads(_saved_result())
        result.update(
            {
                "schema_version": "fdai.provision-source-plan.v1",
                "source_snapshot_digest": snapshot_digest,
                "provenance": "operator-selected-source",
                "release_signature_verified": False,
                "deployment_ready": False,
            }
        )
        result["saved_plan"]["schema_version"] = "fdai.foundation-saved-source-plan.v1"
        if defect == "kit-result":
            result["schema_version"] = "fdai.provision-plan.v1"
        elif defect == "kit-review":
            result["saved_plan"]["schema_version"] = "fdai.foundation-saved-plan.v1"
        elif defect == "snapshot":
            result["source_snapshot_digest"] = "e" * 64
        elif defect == "signature":
            result["release_signature_verified"] = True
        return json.dumps(result)

    arguments = dict(
        inputs=inputs,
        repository_root=_ROOT,
        orchestration_work_dir=tmp_path / "run",
        attempt=1,
        prior_report=None,
        timeout=900,
        capture=capture,
    )
    if defect is None:
        result = prepare_foundation_plan(**arguments)
        assert result["state"] == "review"
        assert result["apply_authorized"] is False
    else:
        with pytest.raises(FoundationPlanError):
            prepare_foundation_plan(**arguments)


def test_unexpired_prior_plan_is_reverified_without_replanning(tmp_path: Path) -> None:
    prior = json.loads(
        json.dumps(
            {
                "schema_version": "fdai.genesis-foundation-plan.v1",
                "state": "review",
                "plan_ref": "foundation-plan-attempt-1",
                "attempt": 1,
                "review_digest": "a" * 64,
                "plan_digest": "b" * 64,
                "expires_at": "2999-09-10T12:00:00+00:00",
                "integrity_verified": True,
                "apply_authorized": False,
                "mutation_performed": False,
                "subscription_ready": False,
            }
        )
    )
    calls: list[tuple[str, ...]] = []

    def capture(command: tuple[str, ...], _reason: str, **_kwargs: object) -> str:
        calls.append(command)
        return json.dumps(
            {
                "schema_version": "fdai.foundation-plan-integrity.v1",
                "state": "review",
                "review_digest": "a" * 64,
                "plan_digest": "b" * 64,
                "integrity_verified": True,
                "apply_authorized": False,
                "mutation_performed": False,
                "subscription_ready": False,
            }
        )

    report = prepare_foundation_plan(
        inputs=_inputs(tmp_path),
        repository_root=_ROOT,
        orchestration_work_dir=tmp_path / "run",
        attempt=2,
        prior_report=prior,
        timeout=900,
        capture=capture,
    )

    assert report == prior
    assert len(calls) == 1
    assert calls[0][:5] == (
        sys.executable,
        "-m",
        "fdai_deployment_cli",
        "provision",
        "verify-foundation-plan",
    )
    assert "plan" not in calls[0][6:]


def test_expired_prior_plan_creates_a_new_attempt(tmp_path: Path) -> None:
    prior = {
        "schema_version": "fdai.genesis-foundation-plan.v1",
        "state": "review",
        "plan_ref": "foundation-plan-attempt-1",
        "attempt": 1,
        "review_digest": "a" * 64,
        "plan_digest": "b" * 64,
        "expires_at": "2000-09-10T12:00:00+00:00",
        "integrity_verified": True,
        "apply_authorized": False,
        "mutation_performed": False,
        "subscription_ready": False,
    }
    calls: list[tuple[str, ...]] = []

    def capture(command: tuple[str, ...], _reason: str, **_kwargs: object) -> str:
        calls.append(command)
        return _saved_result()

    report = prepare_foundation_plan(
        inputs=_inputs(tmp_path),
        repository_root=_ROOT,
        orchestration_work_dir=tmp_path / "run",
        attempt=2,
        prior_report=prior,
        timeout=900,
        capture=capture,
    )

    assert calls[0][3:5] == ("provision", "plan")
    assert report["plan_ref"] == "foundation-plan-attempt-2"


def test_status_preserves_exact_plan_report_for_retry(tmp_path: Path) -> None:
    work = tmp_path / "status"
    work.mkdir(mode=0o700)
    report = {
        "schema_version": "fdai.genesis-foundation-plan.v1",
        "state": "review",
        "plan_ref": "foundation-plan-attempt-1",
        "attempt": 1,
        "review_digest": "a" * 64,
        "plan_digest": "b" * 64,
        "expires_at": "2999-09-10T12:00:00+00:00",
        "integrity_verified": True,
        "apply_authorized": False,
        "mutation_performed": False,
        "subscription_ready": False,
    }
    first = StatusStore(
        path=work / "status.json",
        source_commit="c" * 40,
        target_binding="d" * 64,
        mode="apply",
        deadline_at="2999-09-10T12:00:00Z",
    )
    first.foundation_report = report
    first.update(stage="foundation-plan", state="waiting")

    retry = StatusStore(
        path=work / "status.json",
        source_commit="c" * 40,
        target_binding="d" * 64,
        mode="apply",
        deadline_at="2999-09-10T13:00:00Z",
    )

    assert retry.foundation_report == report
    assert retry.attempt == 2


@pytest.mark.parametrize(
    "mutation",
    ["apply", "mutation", "ready", "review-digest", "expires", "offset"],
)
def test_invalid_or_authority_bearing_plan_result_is_rejected(
    tmp_path: Path, mutation: str
) -> None:
    result = json.loads(_saved_result())
    saved = result["saved_plan"]
    assert isinstance(saved, dict)
    if mutation == "apply":
        result["apply_authorized"] = True
    elif mutation == "mutation":
        saved["mutation_performed"] = True
    elif mutation == "ready":
        saved["subscription_ready"] = True
    elif mutation == "review-digest":
        saved["review_digest"] = "invalid"
    elif mutation == "expires":
        saved["expires_at"] = "not-a-time"
    else:
        saved["expires_at"] = "2999-09-10T13:00:00+01:00"

    with pytest.raises(FoundationPlanError):
        prepare_foundation_plan(
            inputs=_inputs(tmp_path),
            repository_root=_ROOT,
            orchestration_work_dir=tmp_path / "run",
            attempt=1,
            prior_report=None,
            timeout=900,
            capture=lambda *_args, **_kwargs: json.dumps(result),
        )


def test_relative_inputs_are_rejected_before_external_execution(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    relative = FoundationPlanInputs(
        offline_kit=Path("offline-kit"),
        release_root=inputs.release_root,
        bundle_public_key=inputs.bundle_public_key,
        profile=inputs.profile,
        variables_file=inputs.variables_file,
    )

    with pytest.raises(FoundationPlanError, match="absolute"):
        prepare_foundation_plan(
            inputs=relative,
            repository_root=_ROOT,
            orchestration_work_dir=tmp_path / "run",
            attempt=1,
            prior_report=None,
            timeout=900,
            capture=lambda *_args, **_kwargs: pytest.fail("external command was invoked"),
        )
