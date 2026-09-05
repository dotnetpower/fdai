"""Regression coverage for repository CI workflow contracts."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
import yaml
from scripts.deployment.service.select_changed_images import IMAGE_TARGETS

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_contract_module() -> ModuleType:
    script = (
        Path(__file__).resolve().parents[3] / "scripts" / "quality" / "ci" / "check-ci-contracts.py"
    )
    spec = importlib.util.spec_from_file_location("check_ci_contracts", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load CI contract checker: {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_action_refs_reject_stale_and_unknown_remote_actions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_contract_module()
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "ci.yml").write_text(
        "steps:\n"
        "  - uses: actions/checkout@v4\n"
        "  - uses: example/unreviewed-action@v1\n"
        "  - uses: ./.github/actions/local\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)

    assert module._validate_action_runtime_versions() == [
        ".github/workflows/ci.yml must pin actions/checkout to an immutable "
        "40-character SHA; found v4",
        ".github/workflows/ci.yml uses unapproved remote action example/unreviewed-action@v1",
    ]


def test_all_workflows_require_reviewed_immutable_action_refs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_contract_module()
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "deploy-dev.yml").write_text(
        "steps:\n"
        "  - uses: actions/checkout@v7.0.1\n"
        "  - uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a\n"
        "  - uses: example/unreviewed-action@" + "a" * 40 + " # v1.0.0\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)

    assert module._validate_action_runtime_versions() == [
        ".github/workflows/deploy-dev.yml must pin actions/checkout to an immutable "
        "40-character SHA; found v7.0.1",
        ".github/workflows/deploy-dev.yml must document actions/upload-artifact@"
        "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a with trusted version comment # v7.0.1",
        ".github/workflows/deploy-dev.yml uses unapproved remote action "
        f"example/unreviewed-action@{'a' * 40}",
    ]


def test_workflow_accepts_reviewed_immutable_action_ref(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_contract_module()
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "container-supply-chain.yml").write_text(
        "steps:\n  - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)

    assert module._validate_action_runtime_versions() == []


def test_deploy_workspace_preparation_runs_before_checkout() -> None:
    workflow = (_REPO_ROOT / ".github/workflows/deploy-dev.yml").read_text(encoding="utf-8")
    prepare_start = workflow.index("- name: Prepare self-hosted runner workspace")
    checkout_start = workflow.index("- name: Checkout", prepare_start)
    prepare_step = workflow[prepare_start:checkout_start]

    assert "working-directory: ${{ runner.temp }}" in prepare_step


def test_destroy_helper_dispatches_the_protected_main_commit() -> None:
    helper = (_REPO_ROOT / "scripts/deployment/azure/teardown-env.sh").read_text(encoding="utf-8")

    assert 'COMMIT_SHA="$(gh api "repos/$REPO/commits/main" --jq .sha)"' in helper
    assert '[[ "$COMMIT_SHA" =~ ^[0-9a-f]{40}$ ]]' in helper
    assert '-f commit_sha="$COMMIT_SHA"' in helper


def test_destroy_helper_refuses_to_deallocate_an_ephemeral_runner() -> None:
    helper = (_REPO_ROOT / "scripts/deployment/azure/teardown-env.sh").read_text(encoding="utf-8")

    posture_check = "storageProfile.osDisk.diffDiskSettings.option"
    assert posture_check in helper
    assert helper.index(posture_check) < helper.index('az vm deallocate -g "$OPS_RG" -n "$VM"')
    assert "runner-stop is unsupported for an ephemeral OS disk" in helper


@pytest.mark.parametrize(
    "workflow",
    (
        "permissions:\n  contents: write\n",
        "permissions:\n  packages: write\n",
        "permissions:\n  pages: write\n",
        "permissions:\n  issues: write\n",
        "permissions:\n  attestations: write\n",
        "permissions: write-all\n",
        "permissions: {contents: read, packages: write}\n",
        "jobs:\n  deploy:\n    runs-on: [self-hosted, fdai-deploy]\n",
        "jobs:\n  deploy:\n    runs-on: self-hosted\n",
        "jobs:\n  smoke:\n    runs-on:\n      - self-hosted\n      - custom\n",
        "permissions:\n  id-token: write\n",
        "steps:\n  - run: terraform apply saved.plan\n",
        "steps:\n  - run: terraform destroy -auto-approve\n",
    ),
)
def test_privileged_workflow_detection_uses_security_properties(workflow: str) -> None:
    module = _load_contract_module()

    assert module._is_privileged_workflow(workflow)


def test_privileged_workflow_guard_is_required_by_properties(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_contract_module()
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "custom-operation.yml").write_text(
        "on:\n"
        "  workflow_dispatch:\n"
        "    inputs:\n"
        "      commit_sha:\n"
        "        required: true\n"
        "permissions:\n"
        "  contents: read\n"
        "jobs:\n"
        "  apply:\n"
        "    runs-on: [self-hosted, custom]\n"
        "    steps:\n"
        "      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1\n"
        "      - run: terraform apply saved.plan\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)

    errors = module._validate_privileged_workflow_guards()

    assert errors
    assert all("custom-operation.yml" in error for error in errors)
    assert any("protected-source guard" in error for error in errors)


def test_event_scoped_issue_mutation_does_not_require_repository_guard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_contract_module()
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "issue-policy.yml").write_text(
        "on:\n"
        "  issues:\n"
        "permissions:\n"
        "  issues: write\n"
        "jobs:\n"
        "  validate:\n"
        "    if: github.event_name == 'issues' && github.event.issue.pull_request == null\n"
        "    steps:\n"
        "      - uses: actions/github-script@d746ffe35508b1917358783b479e04febd2b8f71 # v9.0.0\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)

    assert module._validate_privileged_workflow_guards() == []


def test_issue_lifecycle_ignores_events_created_by_its_own_token() -> None:
    workflow = (_REPO_ROOT / ".github/workflows/issue-lifecycle.yml").read_text(encoding="utf-8")

    assert "github.actor != 'github-actions[bot]'" in workflow


def test_frozen_scenario_gate_targets_the_service_owned_directory() -> None:
    workflow = (_REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "'services/core-control-plane/tests/scenarios/v*/*.json'" in workflow
    assert "-- 'tests/scenarios/v*/*.json'" not in workflow
    assert "--diff-filter=MDRT" in workflow
    assert '--diff-filter=A "$base_sha...HEAD"' in workflow
    assert 'git cat-file -e "$base_sha:$version_dir"' in workflow


def test_required_lint_job_enforces_independent_service_boundaries() -> None:
    workflow = yaml.safe_load((_REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))

    lint_job = workflow["jobs"]["lint"]
    assert "if" not in lint_job
    boundary_step = next(
        (
            step
            for step in lint_job["steps"]
            if step.get("run")
            == "uv run python scripts/quality/architecture/check-independent-services.py"
        ),
        None,
    )
    assert boundary_step is not None
    assert boundary_step.get("continue-on-error") not in {True, "true"}
    assert "lint" in workflow["jobs"]["required"]["needs"]


def test_devbox_smoke_is_manual_protected_and_label_indirected() -> None:
    workflow = (_REPO_ROOT / ".github/workflows/devbox-smoke.yml").read_text(encoding="utf-8")

    assert "  workflow_dispatch:" in workflow
    assert "pull_request:" not in workflow
    assert "  push:" not in workflow
    assert "    runs-on:\n      - self-hosted\n      - ${{ vars.DEVBOX_RUNNER_LABEL }}" in workflow
    assert "Verify protected workflow source" in workflow
    assert "workflow-path: .github/workflows/devbox-smoke.yml" in workflow
    assert "ref: ${{ inputs.commit_sha }}" in workflow
    assert "secrets." not in workflow
    assert 'runner_root="$(dirname "$(dirname "$RUNNER_WORKSPACE")")"' in workflow
    assert '[[ -x "$runner_root/config.sh" ]] && config_available=true' in workflow
    assert "sudo -n true" in workflow


def test_shipped_workflows_satisfy_security_contracts() -> None:
    module = _load_contract_module()

    assert module._validate_action_runtime_versions() == []
    assert module._validate_privileged_workflow_guards() == []


def test_shipped_privileged_workflow_inventory_is_explicitly_audited() -> None:
    module = _load_contract_module()
    workflow_dir = Path(__file__).resolve().parents[3] / ".github" / "workflows"

    privileged = {
        path.name
        for path in workflow_dir.glob("*.yml")
        if module._is_privileged_workflow(path.read_text(encoding="utf-8"))
    }

    assert privileged == {
        "automatic-version.yml",
        "container-supply-chain.yml",
        "deploy-dev.yml",
        "devbox-smoke.yml",
        "destroy-env.yml",
        "infra-drift.yml",
        "issue-lifecycle.yml",
        "model-lifecycle-reconcile.yml",
        "model-settings-projection.yml",
        "pages.yml",
        "publish-console.yml",
        "refresh-catalogs.yml",
        "request-protected-operation.yml",
        "remote-evidence-attest.yml",
        "service-deploy.yml",
        "sre-demo-lab.yml",
    }


def test_uv_cache_contract_allows_one_writer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_contract_module()
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    workflow = workflow_dir / "ci.yml"
    setup = (
        "      - name: Set up uv (Python 3.13)\n"
        "        uses: astral-sh/setup-uv@v8.3.2\n"
        "        with:\n"
        '          python-version: "3.13"\n'
        "          enable-cache: true\n"
    )
    workflow.write_text(f"jobs:\n  first:\n{setup}  second:\n{setup}", encoding="utf-8")
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)

    assert module._validate_uv_cache_writers() == [
        "ci.yml must have exactly one setup-uv cache writer; found 2"
    ]

    workflow.write_text(
        f"jobs:\n  first:\n{setup}  second:\n{setup}          save-cache: false\n",
        encoding="utf-8",
    )
    assert module._validate_uv_cache_writers() == []


def test_uv_cache_contract_requires_python_313_pin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_contract_module()
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "ci.yml").write_text(
        "      - name: Install uv for regression tests\n"
        "        uses: astral-sh/setup-uv@v8.3.2\n"
        "        with:\n"
        "          enable-cache: true\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)

    assert module._validate_uv_cache_writers() == [
        "every ci.yml Python 3.13 setup-uv block must pin python-version: 3.13"
    ]


def test_base_images_must_stay_mirror_overridable_and_digest_pinned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A disconnected build redirects where bytes come from, never which bytes."""
    module = _load_contract_module()
    dockerfile = tmp_path / "services" / "example" / "docker" / "Dockerfile"
    dockerfile.parent.mkdir(parents=True)
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    dockerfile.write_text(
        "FROM docker.io/library/python:3.13 AS builder\nFROM builder AS runtime\n",
        encoding="utf-8",
    )

    assert module._validate_base_images() == [
        "Dockerfile must declare ARG BASE_IMAGE_REGISTRY with a default",
        "Dockerfile base image docker.io/library/python:3.13 must be prefixed with "
        "${BASE_IMAGE_REGISTRY}/",
        "Dockerfile base image docker.io/library/python:3.13 must be digest-pinned",
    ]


def test_compliant_base_images_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_contract_module()
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    dockerfile = tmp_path / "services" / "example" / "docker" / "Dockerfile"
    dockerfile.parent.mkdir(parents=True)
    dockerfile.write_text(
        "ARG BASE_IMAGE_REGISTRY=docker.io\n"
        "FROM ${BASE_IMAGE_REGISTRY}/library/python@sha256:" + "a" * 64 + " AS builder\n"
        "FROM builder AS runtime\n",
        encoding="utf-8",
    )

    assert module._validate_base_images() == []


def test_shipped_dockerfile_satisfies_the_base_image_contract() -> None:
    module = _load_contract_module()

    assert module._validate_base_images() == []


def test_shipped_build_context_is_complete_or_materialized() -> None:
    module = _load_contract_module()

    assert module._validate_build_context() == []


def test_dockerignore_copy_source_check_honors_ordered_exceptions() -> None:
    module = _load_contract_module()
    rules = (
        "scripts/",
        "!scripts/deployment/local/materialize-authoritative-catalogs.py",
    )

    assert not module._docker_path_is_ignored(
        "scripts/deployment/local/materialize-authoritative-catalogs.py", rules
    )
    assert module._docker_path_is_ignored("scripts/deployment/local/other.py", rules)


def test_resolved_model_manifest_reaches_container_build_context() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    dockerfile = (
        repo_root / "services" / "core-control-plane" / "docker" / "Dockerfile"
    ).read_text(encoding="utf-8")
    dockerignore = (repo_root / ".dockerignore").read_text(encoding="utf-8").splitlines()

    assert (
        "COPY --chown=65532:65532 services/assets/resolved-models.json /app/resolved-models.json"
    ) in dockerfile
    assert "resolved-models*.json" in dockerignore
    assert "!resolved-models.json" in dockerignore


def test_diagnostic_ontology_ledger_reaches_runtime_image() -> None:
    root = Path(__file__).resolve().parents[3]
    dockerfile = (root / "services" / "core-control-plane" / "docker" / "Dockerfile").read_text(
        encoding="utf-8"
    )
    dockerignore = (root / ".dockerignore").read_text(encoding="utf-8")

    assert (
        "COPY --chown=65532:65532 docs/internals/sregym-absorption-ledger.json "
        "/app/docs/internals/sregym-absorption-ledger.json"
    ) in dockerfile
    assert "!docs/internals/sregym-absorption-ledger.json" in dockerignore


def test_sregym_image_uses_frozen_workspace_and_includes_ontology_ledger() -> None:
    dockerfile = (
        Path(__file__).resolve().parents[3] / "benchmarks" / "sregym" / "Dockerfile"
    ).read_text(encoding="utf-8")

    assert "COPY pyproject.toml uv.lock README.md LICENSE ./" in dockerfile
    assert "FROM sregym-agent-base@sha256:" in dockerfile
    assert "COPY --from=opa-builder /go/bin/opa /usr/local/bin/opa" in dockerfile
    assert "uv==0.11.32" in dockerfile
    assert (
        "uv sync --frozen --package fdai --package fdai-benchmark-sregym --no-dev --no-editable"
    ) in dockerfile
    assert (
        "COPY docs/internals/sregym-absorption-ledger.json "
        "./docs/internals/sregym-absorption-ledger.json"
    ) in dockerfile
    assert "USER 65532" in dockerfile


def test_dockerfile_installs_only_runtime_workspace_packages() -> None:
    root = Path(__file__).resolve().parents[3]
    assert not (root / "Dockerfile").exists()
    assert not (root / "services" / "Dockerfile").exists()
    dockerfiles = sorted((root / "services").glob("*/docker/Dockerfile"))
    assert len(dockerfiles) == 5
    for dockerfile in dockerfiles:
        text = dockerfile.read_text(encoding="utf-8")
        assert "--no-install-package fdai-service-contracts" in text
        assert "USER 65532" in text
        assert "ENTRYPOINT" in text


def test_azd_is_infrastructure_only_without_a_stale_service_target() -> None:
    root = Path(__file__).resolve().parents[3]
    azure = (root / "azure.yaml").read_text(encoding="utf-8")

    assert "provider: terraform" in azure
    assert "\nservices:" not in azure
    assert "azd-service-name: core" not in azure


def test_shipped_runtime_images_pin_the_fixed_sqlite_package() -> None:
    root = Path(__file__).resolve().parents[3]
    dockerfiles = sorted((root / "services").glob("*/docker/Dockerfile"))

    assert len(dockerfiles) == 5
    for dockerfile in dockerfiles:
        text = dockerfile.read_text(encoding="utf-8")
        assert "ARG SQLITE_LIBS_VERSION=3.53.4-r0" in text
        assert "https://dl-cdn.alpinelinux.org/alpine/edge/main" in text
        assert '"sqlite-libs=${SQLITE_LIBS_VERSION}"' in text


def test_ci_installs_and_audits_the_frozen_runtime_workspace() -> None:
    workflow = (Path(__file__).resolve().parents[3] / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    governance_job = workflow.split("  governance-runtime-contracts:", 1)[1].split(
        "\n  evaluation-packages:", 1
    )[0]
    audit_job = workflow.split("  deps-audit:", 1)[1].split("\n  exemption-check:", 1)[0]

    assert "uv sync --frozen --package fdai-core-control-plane --no-dev" in governance_job
    assert "python3 -m pip install --quiet -e ." not in governance_job
    assert "uv export --format requirements.txt --frozen --no-dev" in audit_job
    assert "--no-emit-workspace --output-file audit-requirements.txt" in audit_job
    assert "inputs: audit-requirements.txt" in audit_job


def test_ci_migrates_service_database_before_integration_tests() -> None:
    workflow_path = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
    steps = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))["jobs"]["db-migrations"][
        "steps"
    ]
    step_names = [step["name"] for step in steps]

    assert step_names.index("Run service-owned migrations") < step_names.index(
        "Run integration test suite"
    )
    integration_step = next(step for step in steps if step["name"] == "Run integration test suite")
    assert integration_step["env"]["FDAI_DATABASE_URL"] == "${{ env.FDAI_SERVICE_DATABASE_URL }}"


def test_ci_required_status_aggregates_every_execution_job() -> None:
    workflow_path = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
    jobs = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))["jobs"]
    required = jobs["required"]

    assert set(required["needs"]) == set(jobs) - {"required"}
    assert "always()" in str(required["if"])
    assert "NEEDS_JSON: ${{ toJSON(needs) }}" in workflow_path.read_text(encoding="utf-8")
    assert '{"success", "skipped"}' in workflow_path.read_text(encoding="utf-8")


def test_container_scan_blocks_all_medium_high_and_critical_vulnerabilities() -> None:
    workflow = (
        Path(__file__).resolve().parents[3] / ".github" / "workflows" / "container-supply-chain.yml"
    ).read_text(encoding="utf-8")

    assert workflow.count("--severity MEDIUM,HIGH,CRITICAL") == 2
    assert "--ignore-unfixed" not in workflow


def test_container_supply_chain_builds_only_service_owned_dockerfiles() -> None:
    root = Path(__file__).resolve().parents[3]
    workflow = (root / ".github" / "workflows" / "container-supply-chain.yml").read_text(
        encoding="utf-8"
    )
    dockerfiles = {target.dockerfile for target in IMAGE_TARGETS}

    assert "file: ${{ matrix.dockerfile }}" in workflow
    assert "python3 scripts/deployment/service/apply_image_build_override.py" in workflow
    assert "matrix: ${{ fromJSON(needs.select-images.outputs.matrix) }}" in workflow
    assert "services/Dockerfile" not in workflow
    assert "          target:" not in workflow
    for dockerfile in dockerfiles:
        assert (root / dockerfile).is_file()


def test_infrastructure_scan_blocks_medium_high_and_critical_findings() -> None:
    workflow = (Path(__file__).resolve().parents[3] / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )

    assert "terraform-security:" in workflow
    assert "needs.changes.outputs.terraform == 'true'" in workflow
    assert "trivy config --exit-code 1 --severity MEDIUM,HIGH,CRITICAL infra" in workflow
    assert "checkov -d infra --quiet --compact --framework terraform" in workflow
    assert "--baseline" not in workflow
