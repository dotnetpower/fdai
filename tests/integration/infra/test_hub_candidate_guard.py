"""Run the native Hub runbook guard on synthetic files; never contact Azure."""

from __future__ import annotations

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
test "$*" = "account show --query {subscription:id,tenant:tenantId} -o json" || exit 64
printf '{"subscription":"%s","tenant":"%s"}\\n' "$TEST_SUBSCRIPTION" "$TEST_TENANT"
""",
        "terraform": """#!/bin/bash
if [[ "$TEST_TERRAFORM_FAILURE" == 1 ]]; then exit 69; fi
test "$*" = "-chdir=$ROOT show -json $PRIVATE_PLAN" || exit 64
cat "$TEST_RENDERED_PLAN"
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
        "TEST_TERRAFORM_FAILURE": "0",
        "SUBSCRIPTION_ID": "synthetic-subscription",
        "TENANT_ID": "synthetic-tenant",
        "TEST_SUBSCRIPTION": "synthetic-subscription",
        "TEST_TENANT": "synthetic-tenant",
        "RUNTIME_IMAGE": IMAGE,
        "ROOT": "infra/release-hub" if kind == "release" else "infra/lifecycle-hub",
        "TARGET": kind,
        "TEST_RENDERED_PLAN": str(tmp_path / "rendered-plan.json"),
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
                                "values": {
                                    "resource_group_name": "synthetic-group",
                                    "name": "synthetic-job",
                                    "template": [{"container": [{"name": "hub", "image": IMAGE}]}],
                                },
                            }
                            for resource in ("azurerm_container_app", "azurerm_container_app_job")
                        ]
                    }
                ]
            }
        },
    }
    return environment, plan


def _run(tmp_path: Path, environment, plan, action: str = ""):
    Path(environment["PRIVATE_PLAN_JSON"]).write_text(json.dumps(plan))
    Path(environment["TEST_RENDERED_PLAN"]).write_text(json.dumps(plan))
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
    )
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
