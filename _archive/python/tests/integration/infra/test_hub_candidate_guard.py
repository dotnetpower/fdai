"""Run the native Hub runbook guard on synthetic files; never contact Azure."""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

README = Path(__file__).resolve().parents[3] / "infra/modules/hub-service/README.md"
GUARD = (
    "candidate_context() {"
    + README.read_text().split("```bash\ncandidate_context() {", 1)[1].split("\n```", 1)[0]
)
IMAGE = "registry.example.com/hub@sha256:" + "a" * 64
PREVIOUS_IMAGE = "registry.example.com/hub@sha256:" + "b" * 64


def _fixture(tmp_path: Path, kind: str = "release"):
    tools = tmp_path / "bin"
    tools.mkdir()
    scripts = {
        "git": """#!/bin/bash
if [[ "${TEST_GIT_FAILURE:-0}" == 1 ]]; then exit 69; fi
case "$*" in
  "rev-parse HEAD") printf '%s\\n' "$TEST_SOURCE_SHA" ;;
  "status --porcelain --untracked-files=normal")
    if [[ "$TEST_GIT_FAILURE" == status ]]; then exit 69; fi
    printf '%s' "$TEST_GIT_STATUS" ;;
  *) exit 64 ;;
esac
""",
        "az": """#!/bin/bash
if [[ "$TEST_AZ_FAILURE" == 1 ]]; then exit 69; fi
if [[ "$*" == "account show --query {subscription:id,tenant:tenantId} -o json" ]]; then
  printf '{"subscription":"%s","tenant":"%s"}\\n' "$TEST_SUBSCRIPTION" "$TEST_TENANT"
elif [[ "$1 $2 $3 $4" == "containerapp job show --ids" ]]; then
  test "$6 $7" = "-o json" || exit 64
  if [[ "${TEST_JOB_READ_FAILURE:-0}" == 1 ]]; then exit 69; fi
  cat "$TEST_LIVE_JOB"
else
  exit 64
fi
""",
        "terraform": """#!/bin/bash
if [[ "$TEST_TERRAFORM_FAILURE" == 1 ]]; then exit 69; fi
if [[ "$2" == plan ]]; then
  test "$#" = 7 || exit 64
  test "$1" = "-chdir=$ROOT" || exit 64
  test "$2 $3" = "plan -refresh-only" || exit 64
  test "$4 $5" = "-input=false -lock-timeout=10s" || exit 64
  test "$6" = "-var-file=$PRIVATE_INPUTS" || exit 64
  for argument in "$@"; do
    case "$argument" in -out=*) output="${argument#-out=}" ;; esac
  done
  cp "$TEST_LIVE_PLAN" "$output"
  exit "${TEST_READBACK_EXIT:-0}"
fi
if [[ "$*" == "-chdir=$ROOT show -json $PRIVATE_PLAN" ]]; then
  cat "$TEST_RENDERED_PLAN"
elif [[ "$2 $3" == "show -json" ]]; then
  cat "$4"
else
  exit 64
fi
""",
    }
    for name, content in scripts.items():
        path = tools / name
        path.write_text(content)
        path.chmod(0o700)
    environment = {
        "PATH": str(tools) + os.pathsep + os.environ["PATH"],
        "HOME": str(tmp_path),
        "SOURCE_SHA": "a" * 40,
        "TEST_SOURCE_SHA": "a" * 40,
        "TEST_GIT_STATUS": "",
        "TEST_GIT_FAILURE": "0",
        "TEST_AZ_FAILURE": "0",
        "TEST_JOB_READ_FAILURE": "0",
        "TEST_TERRAFORM_FAILURE": "0",
        "SUBSCRIPTION_ID": "synthetic-subscription",
        "TENANT_ID": "synthetic-tenant",
        "TEST_SUBSCRIPTION": "synthetic-subscription",
        "TEST_TENANT": "synthetic-tenant",
        "RUNTIME_IMAGE": IMAGE,
        "APP_IMAGE": IMAGE,
        "ROOT": "infra/release-hub" if kind == "release" else "infra/lifecycle-hub",
        "TARGET": kind,
        "TEST_RENDERED_PLAN": str(tmp_path / "rendered-plan.json"),
        "TEST_LIVE_PLAN": str(tmp_path / "live-plan.json"),
        "TEST_LIVE_JOB": str(tmp_path / "live-job.json"),
    }
    for variable in (
        "PRIVATE_BUILD_METADATA",
        "PRIVATE_BACKEND",
        "PRIVATE_INPUTS",
        "PRIVATE_PLAN",
        "PRIVATE_PLAN_JSON",
        "PRIVATE_STAGE_CONTEXT",
        "PRIVATE_STAGE_HASHES",
    ):
        environment[variable] = str(tmp_path / variable.lower())
    for variable in ("PRIVATE_BACKEND", "PRIVATE_INPUTS", "PRIVATE_PLAN"):
        Path(environment[variable]).write_text("synthetic fixture\n")
    Path(environment["PRIVATE_BUILD_METADATA"]).write_text(
        json.dumps(
            {
                "containerimage.digest": "sha256:" + "a" * 64,
                "buildx.build.provenance": {
                    "invocation": {
                        "parameters": {"root": {"request": {"args": {"vcs:revision": "a" * 40}}}}
                    }
                },
            }
        )
    )
    plan = {
        "variables": {
            "subscription_id": {"value": environment["SUBSCRIPTION_ID"]},
            "tenant_id": {"value": environment["TENANT_ID"]},
            "image": {"value": IMAGE},
            "app_image": {"value": None},
        },
        "configuration": {
            "root_module": {
                "module_calls": {"hub": {"expressions": {"kind": {"constant_value": kind}}}}
            }
        },
        "planned_values": {
            "root_module": {
                "child_modules": [
                    {
                        "resources": [
                            {
                                "mode": "managed",
                                "type": resource,
                                "name": "bootstrap",
                                "address": f"module.hub.{resource}.bootstrap[0]",
                                "values": {
                                    "id": f"/synthetic/{resource}/bootstrap",
                                    "resource_group_name": "synthetic-group",
                                    "name": "synthetic-job",
                                    "identity": [
                                        {
                                            "type": "UserAssigned",
                                            "identity_ids": ["/synthetic/identities/bootstrap"],
                                        }
                                    ],
                                    "template": [
                                        {
                                            "container": [
                                                {
                                                    "name": "hub",
                                                    "image": IMAGE,
                                                    "command": [
                                                        "python",
                                                        "-m",
                                                        "synthetic.bootstrap",
                                                    ],
                                                    "args": [],
                                                    "env": [],
                                                    "cpu": 0.5,
                                                    "memory": "1Gi",
                                                }
                                            ]
                                        }
                                    ],
                                },
                            }
                            for resource in ("azurerm_container_app", "azurerm_container_app_job")
                        ]
                    }
                ]
            }
        },
    }
    plan["resource_changes"] = [
        {
            "address": f"module.hub.{resource}.bootstrap[0]",
            "mode": "managed",
            "type": resource,
            "name": "bootstrap",
            "change": {"actions": ["no-op"], "after_unknown": {}},
        }
        for resource in ("azurerm_container_app", "azurerm_container_app_job")
    ]
    Path(environment["TEST_LIVE_JOB"]).write_text(
        json.dumps(
            {
                "id": "/synthetic/azurerm_container_app_job/bootstrap",
                "identity": {
                    "type": "UserAssigned",
                    "userAssignedIdentities": {
                        "/synthetic/identities/bootstrap": {"clientId": "synthetic-client"},
                    },
                },
                "properties": {
                    "environmentId": "/synthetic/environment",
                    "workloadProfileName": "Consumption",
                    "configuration": {"triggerType": "Manual", "replicaTimeout": 120},
                    "template": {
                        "containers": [
                            {
                                "name": "hub",
                                "image": IMAGE,
                                "command": ["python", "-m", "synthetic.bootstrap"],
                            }
                        ]
                    },
                },
            }
        )
    )
    return environment, plan


def _run(tmp_path: Path, environment, plan, action: str = ""):
    Path(environment["PRIVATE_PLAN_JSON"]).write_text(json.dumps(plan))
    Path(environment["TEST_RENDERED_PLAN"]).write_text(json.dumps(plan))
    if not Path(environment["TEST_LIVE_PLAN"]).exists():
        Path(environment["TEST_LIVE_PLAN"]).write_text(
            json.dumps({"prior_state": {"values": plan["planned_values"]}})
        )
    bash = shutil.which("bash")
    assert bash, "Bash is required for the native candidate checks."
    for tool in ("jq", "sha256sum", "cmp", "timeout"):
        assert shutil.which(tool), f"{tool} is required for the native candidate checks."
    return subprocess.run(  # noqa: S603 - Extracted repository runbook and literal synthetic cases.
        [
            bash,
            "-euo",
            "pipefail",
            "-c",
            GUARD
            + "\nseal_candidate\n"
            + action
            + '\nverify_candidate\nprintf dispatched > "$HOME/dispatched"\n',
        ],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )


@pytest.mark.parametrize("kind", ["release", "target"])
def test_each_product_dispatches_only_its_sealed_candidate(tmp_path, kind):
    environment, plan = _fixture(tmp_path, kind)
    result = _run(tmp_path, environment, plan)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "dispatched").read_text() == "dispatched"
    for variable in ("PRIVATE_STAGE_CONTEXT", "PRIVATE_STAGE_HASHES"):
        assert Path(environment[variable]).stat().st_mode & 0o777 == 0o400
    assert not result.stdout


@pytest.mark.parametrize("kind", ["release", "target"])
def test_upgrade_migrates_candidate_while_retaining_previous_app(tmp_path, kind):
    environment, plan = _fixture(tmp_path, kind)
    environment["APP_IMAGE"] = PREVIOUS_IMAGE
    plan["variables"]["app_image"]["value"] = PREVIOUS_IMAGE
    app, job = plan["planned_values"]["root_module"]["child_modules"][0]["resources"]
    app["values"]["template"][0]["container"][0]["image"] = PREVIOUS_IMAGE
    job["name"] = "migrate"
    result = _run(tmp_path, environment, plan, "verify_live_job migrate")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "dispatched").exists()


@pytest.mark.parametrize("kind", ["release", "target"])
@pytest.mark.parametrize(
    "invalid",
    ["input", "app", "job", "mutable", "bootstrap", "missing-job", "missing-app", "pending-app"],
)
def test_upgrade_rejects_unbound_images_or_bootstrap(tmp_path, kind, invalid):
    environment, plan = _fixture(tmp_path, kind)
    environment["APP_IMAGE"] = PREVIOUS_IMAGE
    plan["variables"]["app_image"]["value"] = PREVIOUS_IMAGE
    app, job = plan["planned_values"]["root_module"]["child_modules"][0]["resources"]
    app["values"]["template"][0]["container"][0]["image"] = PREVIOUS_IMAGE
    job["name"] = "migrate"
    if invalid == "input":
        plan["variables"]["app_image"]["value"] = IMAGE
    elif invalid == "app":
        app["values"]["template"][0]["container"][0]["image"] = IMAGE
    elif invalid == "job":
        job["values"]["template"][0]["container"][0]["image"] = PREVIOUS_IMAGE
    elif invalid == "mutable":
        environment["APP_IMAGE"] = "registry.example.com/hub:latest"
    elif invalid == "bootstrap":
        job["name"] = "bootstrap"
    elif invalid == "missing-job":
        plan["planned_values"]["root_module"]["child_modules"][0]["resources"].pop()
    elif invalid == "missing-app":
        plan["planned_values"]["root_module"]["child_modules"][0]["resources"].pop(0)
    else:
        plan["resource_changes"][0]["change"]["actions"] = ["update"]
    result = _run(tmp_path, environment, plan, "verify_live_job migrate")
    assert result.returncode != 0
    assert not (tmp_path / "dispatched").exists()
    assert "Hub " in result.stderr


@pytest.mark.parametrize("kind", ["release", "target"])
@pytest.mark.parametrize("change", ["update-job", "replace-job", "create-job", "update-other"])
def test_retained_stage_only_allows_in_place_migration_update(tmp_path, kind, change):
    environment, plan = _fixture(tmp_path, kind)
    environment["APP_IMAGE"] = PREVIOUS_IMAGE
    plan["variables"]["app_image"]["value"] = PREVIOUS_IMAGE
    app, job = plan["planned_values"]["root_module"]["child_modules"][0]["resources"]
    app["values"]["template"][0]["container"][0]["image"] = PREVIOUS_IMAGE
    job["name"] = "migrate"
    job_change = plan["resource_changes"][1]
    job_change["name"] = "migrate"
    job_change["change"]["actions"] = {
        "update-job": ["update"],
        "replace-job": ["delete", "create"],
        "create-job": ["create"],
        "update-other": ["no-op"],
    }[change]
    if change == "update-other":
        plan["resource_changes"].append(
            {
                "mode": "managed",
                "type": "azurerm_resource_group",
                "name": "hub",
                "change": {"actions": ["update"]},
            }
        )
    result = _run(tmp_path, environment, plan)
    assert (result.returncode == 0) == (change == "update-job"), result.stderr
    assert (tmp_path / "dispatched").exists() == (change == "update-job")


@pytest.mark.parametrize("kind", ["release", "target"])
@pytest.mark.parametrize("app_image", [None, IMAGE])
def test_activation_binds_app_and_migration_to_candidate(tmp_path, kind, app_image):
    environment, plan = _fixture(tmp_path, kind)
    plan["variables"]["app_image"]["value"] = app_image
    job = plan["planned_values"]["root_module"]["child_modules"][0]["resources"][1]
    job["name"] = "migrate"
    result = _run(tmp_path, environment, plan, "verify_live_job migrate")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "dispatched").exists()


@pytest.mark.parametrize("kind", ["release", "target"])
def test_retained_app_live_drift_still_blocks_migration_dispatch(tmp_path, kind):
    environment, plan = _fixture(tmp_path, kind)
    environment["APP_IMAGE"] = PREVIOUS_IMAGE
    plan["variables"]["app_image"]["value"] = PREVIOUS_IMAGE
    app, job = plan["planned_values"]["root_module"]["child_modules"][0]["resources"]
    app["values"]["template"][0]["container"][0]["image"] = PREVIOUS_IMAGE
    job["name"] = "migrate"
    Path(environment["TEST_LIVE_PLAN"]).write_text(
        json.dumps(
            {
                "prior_state": {"values": plan["planned_values"]},
                "resource_drift": [{"address": app["address"], "change": {"actions": ["update"]}}],
            }
        )
    )
    result = _run(tmp_path, environment, plan, "verify_live_job migrate")
    assert result.returncode != 0
    assert not (tmp_path / "dispatched").exists()
    assert "Hub " in result.stderr


@pytest.mark.parametrize("kind", ["release", "target"])
@pytest.mark.parametrize("job", ["bootstrap", "migrate"])
def test_job_dispatch_requires_matching_live_complete_resource(tmp_path, kind, job):
    environment, plan = _fixture(tmp_path, kind)
    resource = plan["planned_values"]["root_module"]["child_modules"][0]["resources"][1]
    resource["name"] = job
    result = _run(tmp_path, environment, plan, f"verify_live_job {job}")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "dispatched").exists()
    assert not result.stdout


@pytest.mark.parametrize(
    "drift",
    [
        "identity",
        "image",
        "command",
        "args",
        "environment",
        "cpu",
        "volume",
        "registry",
        "secret",
        "missing",
        "refresh-error",
        "refresh-drift",
        "refresh-resource-drift",
        "output-drift",
        "unknown-output",
        "invalid-json",
        "sealed-create",
        "unknown-id",
        "unknown-template",
    ],
)
def test_live_job_drift_or_unknown_observation_never_dispatches(tmp_path, drift):
    environment, plan = _fixture(tmp_path)
    live = copy.deepcopy(plan)
    resource = live["planned_values"]["root_module"]["child_modules"][0]["resources"][1]
    values = resource["values"]
    container = values["template"][0]["container"][0]
    if drift == "identity":
        values["identity"][0]["identity_ids"] = ["/synthetic/identities/other"]
    elif drift in {"image", "command", "args", "cpu"}:
        container[drift] = {
            "image": IMAGE.replace("a" * 64, "b" * 64),
            "command": ["unexpected"],
            "args": ["unexpected"],
            "cpu": 1,
        }[drift]
    elif drift == "environment":
        container["env"].append({"name": "UNREVIEWED", "value": "synthetic"})
    elif drift == "volume":
        values["template"][0]["volume"] = [{"name": "unexpected"}]
    elif drift in {"registry", "secret"}:
        values[drift] = [{"name": "unexpected"}]
    elif drift == "missing":
        live["planned_values"]["root_module"]["child_modules"][0]["resources"].pop()
    elif drift in {"refresh-error", "refresh-drift"}:
        environment["TEST_READBACK_EXIT"] = "69" if drift == "refresh-error" else "2"
    elif drift == "refresh-resource-drift":
        live["resource_drift"] = [{"change": {"actions": ["update"]}}]
    elif drift in {"output-drift", "unknown-output"}:
        live["output_changes"] = {
            "deployment": {
                "actions": ["update"] if drift == "output-drift" else ["no-op"],
                "after_unknown": drift == "unknown-output",
            }
        }
    elif drift == "sealed-create":
        plan["resource_changes"][1]["change"]["actions"] = ["create"]
    elif drift == "unknown-id":
        plan["planned_values"]["root_module"]["child_modules"][0]["resources"][1]["values"][
            "id"
        ] = None
    elif drift == "unknown-template":
        plan["resource_changes"][1]["change"]["after_unknown"] = {"template": True}
    Path(environment["TEST_LIVE_PLAN"]).write_text(
        "{"
        if drift == "invalid-json"
        else json.dumps(
            {
                "prior_state": {"values": live["planned_values"]},
                "resource_drift": live.get("resource_drift", []),
                "output_changes": live.get("output_changes", {}),
            }
        )
    )
    result = _run(tmp_path, environment, plan, "verify_live_job bootstrap")
    assert result.returncode != 0
    assert not (tmp_path / "dispatched").exists()
    assert "Hub " in result.stderr
    assert "UNREVIEWED" not in result.stderr + result.stdout


def test_bootstrap_and_migration_starts_require_live_verification_without_overrides():
    procedure = README.read_text()
    for job in ("bootstrap", "migrate"):
        assert (
            f"verify_live_job {job}\n"
            '   EXECUTION=$(az containerapp job start -g "$RG" -n "$JOB" --query name -o tsv)'
        ) in procedure
    assert "Job starts in this procedure accept no execution-template" in procedure


@pytest.mark.parametrize(
    "drift",
    ["template-extra", "identity", "configuration", "unavailable", "incomplete", "wrong-id"],
)
def test_native_azure_only_job_drift_is_rejected_even_when_terraform_view_matches(tmp_path, drift):
    environment, plan = _fixture(tmp_path)
    definition = json.loads(Path(environment["TEST_LIVE_JOB"]).read_text())
    if drift == "template-extra":
        definition["properties"]["template"]["futureExecutionField"] = "unreviewed"
    elif drift == "identity":
        definition["identity"]["userAssignedIdentities"] = {"/synthetic/other": {}}
    elif drift == "configuration":
        definition["properties"]["configuration"]["replicaTimeout"] = 600
    elif drift == "incomplete":
        definition.pop("identity")
    elif drift == "wrong-id":
        definition["id"] = "/synthetic/other-job"
    Path(tmp_path / "changed-live-job.json").write_text(json.dumps(definition))
    action = (
        "TEST_JOB_READ_FAILURE=1"
        if drift == "unavailable"
        else 'TEST_LIVE_JOB="$HOME/changed-live-job.json"'
    )
    result = _run(tmp_path, environment, plan, action + "\nverify_live_job bootstrap")
    assert result.returncode != 0
    assert not (tmp_path / "dispatched").exists()
    assert "Hub " in result.stderr
    assert "unreviewed" not in result.stderr + result.stdout


@pytest.mark.parametrize(
    "action",
    [
        'printf changed >> "$PRIVATE_BUILD_METADATA"',
        'printf changed >> "$PRIVATE_BACKEND"',
        'printf changed >> "$PRIVATE_INPUTS"',
        'printf changed >> "$PRIVATE_PLAN"',
        'printf changed >> "$PRIVATE_PLAN_JSON"',
        'chmod 600 "$PRIVATE_STAGE_CONTEXT"; printf changed >> "$PRIVATE_STAGE_CONTEXT"',
        'rm "$PRIVATE_STAGE_HASHES"',
        "TEST_SOURCE_SHA=" + "b" * 40,
        "TEST_GIT_FAILURE=1",
        "TEST_GIT_FAILURE=status",
        "TEST_AZ_FAILURE=1",
        "TEST_TERRAFORM_FAILURE=1",
        "TEST_GIT_STATUS=' M tracked.tf'",
        "TEST_GIT_STATUS='?? untracked.tf'",
        "TEST_SUBSCRIPTION=another-subscription",
        "TEST_TENANT=another-tenant",
        "SUBSCRIPTION_ID=another-subscription",
        "TENANT_ID=another-tenant",
        "RUNTIME_IMAGE=registry.example.com/hub@sha256:" + "b" * 64,
        "APP_IMAGE=registry.example.com/hub@sha256:" + "b" * 64,
        "ROOT=infra/lifecycle-hub; TARGET=target",
        "ROOT=infra/lifecycle-hub",
        'cp "$PRIVATE_INPUTS" "$HOME/other-inputs"; PRIVATE_INPUTS="$HOME/other-inputs"',
        'cp "$PRIVATE_PLAN" "$HOME/other-plan"; PRIVATE_PLAN="$HOME/other-plan"',
        'printf changed >> "$TEST_RENDERED_PLAN"',
        'TEST_RENDERED_PLAN="$HOME/missing-rendered-plan"',
        "seal_candidate",
    ],
)
def test_drift_or_resealing_never_dispatches(tmp_path, action):
    environment, plan = _fixture(tmp_path)
    result = _run(tmp_path, environment, plan, action)
    assert result.returncode != 0
    assert not (tmp_path / "dispatched").exists()
    assert "Hub " in result.stderr or "new private seal paths" in result.stderr


@pytest.mark.parametrize(
    "invalid",
    ["subscription", "tenant", "product", "image", "empty", "unknown-image", "unknown-template"],
)
def test_wrong_or_unknown_saved_plan_is_not_a_candidate(tmp_path, invalid):
    environment, plan = _fixture(tmp_path)
    workloads = plan["planned_values"]["root_module"]["child_modules"][0]["resources"]
    if invalid in {"subscription", "tenant"}:
        plan["variables"][f"{invalid}_id"]["value"] = "another-target"
    elif invalid == "product":
        plan["configuration"]["root_module"]["module_calls"]["hub"]["expressions"]["kind"][
            "constant_value"
        ] = "target"
    elif invalid == "image":
        workloads[0]["values"]["template"][0]["container"][0]["image"] = "mutable:latest"
    elif invalid == "empty":
        workloads.clear()
    elif invalid == "unknown-image":
        workloads[1]["values"]["template"][0]["container"][0]["image"] = None
    else:
        workloads[1]["values"].pop("template")
    result = _run(tmp_path, environment, plan)
    assert result.returncode != 0
    assert not (tmp_path / "dispatched").exists()
    assert "saved-plan target, product or image binding is invalid" in result.stderr


@pytest.mark.parametrize("invalid", ["source", "image", "provenance"])
def test_unbound_build_metadata_is_not_a_candidate(tmp_path, invalid):
    environment, plan = _fixture(tmp_path)
    path = Path(environment["PRIVATE_BUILD_METADATA"])
    metadata = json.loads(path.read_text())
    if invalid == "source":
        metadata["buildx.build.provenance"]["invocation"]["parameters"]["root"]["request"]["args"][
            "vcs:revision"
        ] = "b" * 40
    elif invalid == "image":
        metadata["containerimage.digest"] = "sha256:" + "b" * 64
    else:
        metadata.pop("buildx.build.provenance")
    path.write_text(json.dumps(metadata))
    result = _run(tmp_path, environment, plan)
    assert result.returncode != 0
    assert not (tmp_path / "dispatched").exists()
    assert "build metadata does not bind this source and image" in result.stderr


@pytest.mark.parametrize("invalid", [None, "missing", "duplicate", "unknown-group", "unknown-name"])
def test_job_binding_comes_from_exactly_one_sealed_plan_resource(tmp_path, invalid):
    environment, plan = _fixture(tmp_path)
    workloads = plan["planned_values"]["root_module"]["child_modules"][0]["resources"]
    if invalid == "missing":
        workloads[1]["name"] = "migrate"
    elif invalid == "duplicate":
        workloads.append(workloads[1].copy())
    elif invalid == "unknown-group":
        workloads[1]["values"]["resource_group_name"] = None
    elif invalid == "unknown-name":
        workloads[1]["values"]["name"] = None
    result = _run(
        tmp_path,
        environment,
        plan,
        "binding=$(planned_job bootstrap)\n"
        'test "$(jq -r .group <<< "$binding")" = synthetic-group\n'
        'test "$(jq -r .name <<< "$binding")" = synthetic-job',
    )
    assert (result.returncode == 0) == (invalid is None)
    assert (tmp_path / "dispatched").exists() == (invalid is None)
    if invalid is not None:
        assert "does not identify one complete Job binding" in result.stderr


def test_native_terraform_plan_records_literal_product_binding(tmp_path):
    terraform = shutil.which("terraform")
    assert terraform, "Terraform is required for the native saved-plan shape check."
    module = tmp_path / "module"
    module.mkdir()
    (module / "main.tf").write_text(
        'variable "kind" { type = string }\n'
        'resource "terraform_data" "product" { input = var.kind }\n'
    )
    (tmp_path / "main.tf").write_text(
        'module "hub" {\n  source = "./module"\n  kind = "release"\n}\n'
        'data "terraform_remote_state" "observation" {\n'
        '  backend = "local"\n'
        '  config = { path = "${path.root}/synthetic-observation.tfstate" }\n'
        "}\n"
        'output "observed" {\n'
        "  value = { value = data.terraform_remote_state.observation.outputs.value }\n"
        "}\n"
    )
    observation = {
        "version": 4,
        "terraform_version": "1.9.8",
        "serial": 1,
        "outputs": {"value": {"value": "before", "type": "string"}},
        "resources": [],
    }
    observation_path = tmp_path / "synthetic-observation.tfstate"
    observation_path.write_text(json.dumps(observation))
    environment = {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path),
        "TF_IN_AUTOMATION": "1",
        "CHECKPOINT_DISABLE": "1",
    }

    def run(*arguments):
        result = subprocess.run(  # noqa: S603 - Built-in provider, synthetic local plan, no apply.
            [terraform, *arguments],
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout

    run("init", "-backend=false", "-input=false", "-no-color")
    run("plan", "-refresh=false", "-input=false", "-no-color", "-out=synthetic.plan")
    plan = json.loads(run("show", "-json", "synthetic.plan"))
    binding = plan["configuration"]["root_module"]["module_calls"]["hub"]["expressions"]["kind"]
    assert binding == {"constant_value": "release"}
    run("apply", "-input=false", "synthetic.plan")
    run("plan", "-detailed-exitcode", "-input=false", "-out=dispatch.plan")
    dispatch = json.loads(run("show", "-json", "dispatch.plan"))
    assert all(change["change"]["actions"] == ["no-op"] for change in dispatch["resource_changes"])
    run("plan", "-refresh-only", "-input=false", "-out=readback.plan")
    readback = json.loads(run("show", "-json", "readback.plan"))
    assert (
        dispatch["planned_values"]["root_module"]["child_modules"]
        == readback["prior_state"]["values"]["root_module"]["child_modules"]
    )
    observation["outputs"]["value"]["value"] = "after"
    observation_path.write_text(json.dumps(observation))
    run("plan", "-refresh-only", "-input=false", "-out=changed-observation.plan")
    changed = json.loads(run("show", "-json", "changed-observation.plan"))
    observed = next(
        resource
        for resource in changed["prior_state"]["values"]["root_module"]["resources"]
        if resource["address"] == "data.terraform_remote_state.observation"
    )
    assert observed["values"]["outputs"]["value"] == "after"
