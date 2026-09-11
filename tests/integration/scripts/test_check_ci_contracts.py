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


def _load_frozen_scenario_module() -> ModuleType:
    script = _REPO_ROOT / "scripts" / "quality" / "ci" / "check-frozen-scenario-additions.py"
    spec = importlib.util.spec_from_file_location("check_frozen_scenario_additions", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load frozen scenario checker: {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _new_frozen_version_fixture() -> tuple[set[str], dict[str, object]]:
    root = "services/core-control-plane/tests/scenarios"
    version = "v2099.01"
    paths = {
        f"{root}/{version}/sre-example.json",
        f"{root}/enrichment/{version}/sre-example.json",
        f"{root}/cross-objective/{version}-sre-change.json",
        f"{root}/manifests/{version}.json",
    }
    documents: dict[str, object] = {
        f"{root}/{version}/sre-example.json": {"id": "sre.example.001"},
        f"{root}/enrichment/{version}/sre-example.json": {"scenario_id": "sre.example.001"},
        f"{root}/cross-objective/{version}-sre-change.json": {
            "id": "conflict.sre-change.001",
            "scenario_set_version": version,
        },
        f"{root}/manifests/{version}.json": {
            "scenario_set_version": version,
            "capability_packs": {
                "sre": {
                    "scenario_ids": ["sre.example.001"],
                    "conflict_spec_ids": ["conflict.sre-change.001"],
                }
            },
        },
    }
    return paths, documents


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


def test_ci_expensive_jobs_follow_change_scope_and_python_uses_four_shards() -> None:
    workflow = yaml.safe_load((_REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    jobs = workflow["jobs"]
    outputs = jobs["changes"]["outputs"]

    assert set(outputs) == {
        "python",
        "docs",
        "terraform",
        "operator",
        "evaluation",
        "dependencies",
        "scenarios",
    }
    scoped_jobs = {
        "python-tests": "python",
        "python-coverage-shards": "python",
        "operator-surfaces": "operator",
        "governance-runtime-contracts": "python",
        "evaluation-packages": "evaluation",
        "deps-audit": "dependencies",
        "db-integration": "python",
        "terraform-validate": "terraform",
    }
    for job_name, scope in scoped_jobs.items():
        job = jobs[job_name]
        assert job["needs"] == "changes"
        assert job["if"] == f"needs.changes.outputs.{scope} == 'true'"

    freeze = jobs["freeze-scenarios"]
    assert freeze["needs"] == "changes"
    assert "needs.changes.outputs.scenarios == 'true'" in freeze["if"]

    python_tests = jobs["python-tests"]
    assert python_tests["strategy"]["matrix"]["shard"] == [1, 2, 3, 4]
    assert python_tests["env"]["FDAI_PYTEST_MODE"] == "regression"
    assert python_tests["env"]["FDAI_PYTEST_SHARD_COUNT"] == "4"
    assert {step["name"] for step in python_tests["steps"]}.isdisjoint(
        {"Prepare coverage data", "Upload coverage data"}
    )

    contracts = jobs["contracts"]
    assert contracts["needs"] == "changes"
    docs_step = next(
        step
        for step in contracts["steps"]
        if step["name"] == "Check documentation source contracts"
    )
    assert docs_step["if"] == "needs.changes.outputs.docs == 'true'"

    assert {
        "lint",
        "python-regression",
        "translations",
        "design-contracts",
        "repository-contracts",
        "db-migrations",
        "provider-contracts-docker",
        "terraform-security",
    }.isdisjoint(jobs)


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


def test_privileged_workflow_rejects_remote_action_before_source_guard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_contract_module()
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    action_dir = tmp_path / ".github" / "actions" / "verify-protected-workflow-source"
    action_dir.mkdir(parents=True)
    action_dir.joinpath("action.yml").write_text(
        "\n".join(
            (
                "+refs/heads/main:refs/remotes/origin/main",
                'merge-base --is-ancestor "$TARGET_COMMIT_SHA"',
                '"$TARGET_COMMIT_SHA:$PROTECTED_WORKFLOW_PATH"',
                '"refs/remotes/origin/main:$PROTECTED_WORKFLOW_PATH"',
                "diff --quiet",
            )
        ),
        encoding="utf-8",
    )
    workflow_dir.joinpath("custom-operation.yml").write_text(
        "on:\n"
        "  workflow_dispatch:\n"
        "    inputs:\n"
        "      commit_sha:\n"
        "        required: true\n"
        "permissions:\n"
        "  contents: read\n"
        "jobs:\n"
        "  apply:\n"
        "    if: github.ref == 'refs/heads/main'\n"
        "    runs-on: [self-hosted, custom]\n"
        "    steps:\n"
        "      - name: Checkout protected workflow verifier\n"
        "        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1\n"
        "        with:\n"
        "          ref: main\n"
        "          sparse-checkout: .github/actions/verify-protected-workflow-source\n"
        "          path: .fdai-protected-workflow-verifier\n"
        "      - name: Untrusted action\n"
        "        uses: example/untrusted@0000000000000000000000000000000000000000\n"
        "      - name: Verify protected workflow source\n"
        "        uses: ./.fdai-protected-workflow-verifier/.github/actions/"
        "verify-protected-workflow-source\n"
        "        with:\n"
        "          target-commit-sha: ${{ inputs.commit_sha }}\n"
        "          workflow-path: .github/workflows/custom-operation.yml\n"
        "          origin-url: ${{ github.server_url }}/${{ github.repository }}.git\n"
        "          github-token: ${{ github.token }}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)

    errors = module._validate_privileged_workflow_guards()

    assert errors == [
        ".github/workflows/custom-operation.yml executes an additional action before its "
        "protected-source guard"
    ]


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
    workflow_path = _REPO_ROOT / ".github/workflows/ci.yml"
    workflow = workflow_path.read_text(encoding="utf-8")
    jobs = yaml.safe_load(workflow)["jobs"]
    freeze_steps = jobs["freeze-scenarios"]["steps"]
    checkout = next(step for step in freeze_steps if step["name"] == "Checkout")
    detection = next(
        step
        for step in freeze_steps
        if step["name"] == "Detect modifications / deletions in frozen versions"
    )

    assert checkout["with"]["fetch-depth"] == 0
    assert all(step["name"] != "Fetch base ref" for step in freeze_steps)
    assert detection["env"] == {"PR_BASE_SHA": "${{ github.event.pull_request.base.sha }}"}
    assert 'base_sha="$PR_BASE_SHA"' in detection["run"]
    assert "'services/core-control-plane/tests/scenarios/v*/*.json'" in workflow
    assert "'services/core-control-plane/tests/scenarios/enrichment/v*/*.json'" in workflow
    assert "'services/core-control-plane/tests/scenarios/manifests/v*.json'" in workflow
    assert "'services/core-control-plane/tests/scenarios/cross-objective/v*.json'" in workflow
    assert "-- 'tests/scenarios/v*/*.json'" not in workflow
    assert "--diff-filter=MDRT" in workflow
    assert '--diff-filter=A "$base_sha...HEAD"' in workflow
    assert 'git cat-file -e "$base_sha:$manifest"' in workflow
    assert "check-frozen-scenario-additions.py" in workflow


def test_frozen_scenario_additions_reject_orphan_version_without_atomic_manifest() -> None:
    module = _load_frozen_scenario_module()
    paths, documents = _new_frozen_version_fixture()
    manifest_path = "services/core-control-plane/tests/scenarios/manifests/v2099.01.json"

    errors = module.validate_new_version_inventory(
        paths - {manifest_path},
        paths,
        documents.__getitem__,
    )

    assert errors == ["v2099.01: new corpus artifacts require an atomically added manifest"]


def test_frozen_scenario_additions_accept_complete_atomic_inventory() -> None:
    module = _load_frozen_scenario_module()
    paths, documents = _new_frozen_version_fixture()

    assert module.validate_new_version_inventory(paths, paths, documents.__getitem__) == []


def test_frozen_scenario_additions_reject_incomplete_manifest_inventory() -> None:
    module = _load_frozen_scenario_module()
    paths, documents = _new_frozen_version_fixture()
    root = "services/core-control-plane/tests/scenarios"
    extra_scenario = f"{root}/v2099.01/finops-example.json"
    extra_enrichment = f"{root}/enrichment/v2099.01/finops-example.json"
    paths.update({extra_scenario, extra_enrichment})
    documents[extra_scenario] = {"id": "finops.example.002"}
    documents[extra_enrichment] = {"scenario_id": "finops.example.002"}

    errors = module.validate_new_version_inventory(paths, paths, documents.__getitem__)

    assert errors == ["v2099.01: manifest scenario inventory does not exactly match scenario files"]


def test_frozen_scenario_additions_reject_manifest_only_version() -> None:
    module = _load_frozen_scenario_module()
    paths, documents = _new_frozen_version_fixture()
    manifest_path = "services/core-control-plane/tests/scenarios/manifests/v2099.01.json"
    manifest = documents[manifest_path]
    assert isinstance(manifest, dict)
    manifest["capability_packs"] = {}

    errors = module.validate_new_version_inventory(
        {manifest_path},
        {manifest_path},
        documents.__getitem__,
    )

    assert errors == [
        "v2099.01: version inventory has no scenario files",
        "v2099.01: version inventory has no enrichment overlays",
        "v2099.01: version inventory has no conflict files",
    ]


def test_required_python_job_enforces_independent_service_boundaries() -> None:
    workflow = yaml.safe_load((_REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))

    python_job = workflow["jobs"]["python-tests"]
    boundary_step = next(
        (
            step
            for step in python_job["steps"]
            if "uv run python scripts/quality/architecture/check-independent-services.py"
            in step.get("run", "")
        ),
        None,
    )
    assert boundary_step is not None
    assert boundary_step["if"] == "matrix.shard == 1"
    assert boundary_step.get("continue-on-error") not in {True, "true"}
    assert "python-tests" in workflow["jobs"]["required"]["needs"]


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


def test_non_history_workflows_use_shallow_checkouts() -> None:
    for name in (
        "automatic-version.yml",
        "destroy-env.yml",
        "devbox-smoke.yml",
        "infra-drift.yml",
        "remote-evidence-attest.yml",
        "sre-demo-lab.yml",
    ):
        workflow = (_REPO_ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        assert "fetch-depth: 0" not in workflow


def test_redundant_workflow_stages_stay_consolidated() -> None:
    pages = yaml.safe_load(
        (_REPO_ROOT / ".github/workflows/pages.yml").read_text(encoding="utf-8")
    )["jobs"]
    assert set(pages) == {"build", "deploy"}
    assert "needs" not in pages["build"]
    assert [step["name"] for step in pages["build"]["steps"][:2]] == [
        "Checkout protected workflow verifier",
        "Verify protected workflow source",
    ]
    page_commands = "\n".join(str(step.get("run", "")) for step in pages["build"]["steps"])
    assert "npm --prefix tools/architecture-diagrams ci" in page_commands
    assert "npm --prefix site ci" in page_commands
    assert "npm --prefix site test" in page_commands
    assert "npm run build" in page_commands
    assert "npm run check:built" in page_commands
    assert "git diff --exit-code -- src/data/publication-routes.json" in page_commands

    remote_evidence = (_REPO_ROOT / ".github/workflows/remote-evidence-attest.yml").read_text(
        encoding="utf-8"
    )
    publish_console = (_REPO_ROOT / ".github/workflows/publish-console.yml").read_text(
        encoding="utf-8"
    )
    infra_drift = (_REPO_ROOT / ".github/workflows/infra-drift.yml").read_text(encoding="utf-8")
    destroy = (_REPO_ROOT / ".github/workflows/destroy-env.yml").read_text(encoding="utf-8")
    assert "Verify protected-main ancestry" not in remote_evidence
    assert "Verify exact protected revision" not in publish_console
    assert "Activate bootstrap remote state backend" not in infra_drift
    assert "Activate remote state backends" in infra_drift
    assert "Activate remote state backend" not in destroy
    assert "Initialize Terraform remote state" in destroy


def test_ci_supports_exact_main_revalidation() -> None:
    workflow = (_REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "  workflow_dispatch:" in workflow
    assert "  push:" in workflow
    assert "  pull_request:" in workflow
    assert "github.event_name != 'workflow_dispatch'" in workflow
    assert "gitleaks_8.24.3_linux_x64.tar.gz" in workflow
    assert "9991e0b2903da4c8f6122b5c3186448b927a5da4deef1fe45271c3793f4ee29c" in workflow
    assert "curl --fail --location --silent --show-error" in workflow
    assert "--retry-max-time 120" in workflow
    assert '--log-opts="HEAD^..HEAD"' in workflow


def test_ci_cancels_only_superseded_pull_request_runs() -> None:
    workflow = (_REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert (
        "group: ci-${{ github.workflow }}-${{ github.event_name }}-"
        "${{ github.event_name == 'pull_request' && github.ref || github.run_id }}" in workflow
    )
    assert "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in workflow


def test_ci_concurrency_contract_rejects_cancellable_main_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_contract_module()
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "ci.yml").write_text(
        "concurrency:\n"
        "  group: ci-${{ github.workflow }}-${{ github.ref }}\n"
        "  cancel-in-progress: true\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)

    errors = module._validate_ci_concurrency()

    assert len(errors) == 2
    assert all("evidence-preserving concurrency contract" in error for error in errors)


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
        "cohort-observation-import.yml",
        "container-supply-chain.yml",
        "deploy-dev.yml",
        "deploy-channel-edge-secrets.yml",
        "decision-evidence-admission.yml",
        "devbox-smoke.yml",
        "destroy-env.yml",
        "infra-drift.yml",
        "framework-assessment-shadow.yml",
        "issue-lifecycle.yml",
        "model-lifecycle-reconcile.yml",
        "model-settings-projection.yml",
        "operational-history-certification.yml",
        "operational-instance-certification.yml",
        "pages.yml",
        "publish-console.yml",
        "refresh-catalogs.yml",
        "request-protected-operation.yml",
        "remote-evidence-attest.yml",
        "service-deploy.yml",
        "sre-demo-lab.yml",
        "system-knowledge-deploy.yml",
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
        "      - name: Set up Python\n"
        "        uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97\n"
        "        with:\n"
        '          python-version: "3.13"\n'
        "      - name: Set up uv (Python 3.13)\n"
        "        uses: astral-sh/setup-uv@v8.3.2\n"
        "        with:\n"
        '          version: "0.12.11"\n'
        '          python-version: "3.13"\n'
        "          enable-cache: true\n"
        "          cache-dependency-glob: uv.lock\n"
    )
    prefix = "env:\n  UV_PYTHON_DOWNLOADS: never\njobs:\n"
    workflow.write_text(f"{prefix}  first:\n{setup}  second:\n{setup}", encoding="utf-8")
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)

    assert module._validate_uv_cache_writers() == [
        "ci.yml must have exactly one setup-uv cache writer; found 2"
    ]

    workflow.write_text(
        f"{prefix}  first:\n{setup}  second:\n{setup}          save-cache: false\n",
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
        "env:\n"
        "  UV_PYTHON_DOWNLOADS: never\n"
        "      - name: Set up Python\n"
        "        uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97\n"
        "      - name: Install uv for regression tests\n"
        "        uses: astral-sh/setup-uv@v8.3.2\n"
        "        with:\n"
        '          version: "0.12.11"\n'
        "          enable-cache: true\n"
        "          cache-dependency-glob: uv.lock\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)

    assert module._validate_uv_cache_writers() == [
        "every ci.yml Python 3.13 setup-uv block must pin python-version: 3.13"
    ]


def test_uv_cache_contract_requires_explicit_locked_setup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_contract_module()
    workflow = tmp_path / ".github" / "workflows" / "ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "env:\n"
        "  UV_PYTHON_DOWNLOADS: never\n"
        "      - name: Set up uv\n"
        "        uses: astral-sh/setup-uv@v8.3.2\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)

    assert module._validate_uv_cache_writers() == [
        "every ci.yml setup-uv block must configure enable-cache explicitly",
        "every ci.yml setup-uv block must pin uv version 0.12.11",
        "ci.yml must have exactly one setup-uv cache writer; found 0",
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
    dockerfiles = set((root / "services").glob("*/docker/Dockerfile"))
    expected = {
        root / target.dockerfile
        for target in IMAGE_TARGETS
        if target.dockerfile.startswith("services/")
    }
    assert dockerfiles == expected
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


def test_shipped_runtime_images_pin_fixed_runtime_packages() -> None:
    root = Path(__file__).resolve().parents[3]
    dockerfiles = {root / target.dockerfile for target in IMAGE_TARGETS}

    assert dockerfiles == {
        *set((root / "services").glob("*/docker/Dockerfile")),
        root / "extensions" / "cost-governance" / "docker" / "Dockerfile",
    }
    for dockerfile in dockerfiles:
        text = dockerfile.read_text(encoding="utf-8")
        assert "ARG SQLITE_LIBS_VERSION=3.53.4-r0" in text
        assert "ARG UTIL_LINUX_LIBS_VERSION=2.42.3-r1" in text
        assert "https://dl-cdn.alpinelinux.org/alpine/edge/main" in text
        assert '"libuuid=${UTIL_LINUX_LIBS_VERSION}"' in text
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


def test_ci_partitions_database_and_provider_checks_across_two_shards() -> None:
    workflow_path = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
    jobs = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))["jobs"]
    integration_job = jobs["db-integration"]

    assert integration_job["strategy"]["matrix"]["shard"] == [1, 2]
    assert integration_job["env"]["FDAI_PYTEST_MODE"] == "integration"
    assert integration_job["env"]["FDAI_PYTEST_SHARD_COUNT"] == "2"
    assert integration_job["env"]["FDAI_PYTEST_SHARD_INDEX"] == "${{ matrix.shard }}"
    integration_steps = [step["name"] for step in integration_job["steps"]]
    assert integration_steps.index("Run alembic upgrade head") < integration_steps.index(
        "Run integration test shard"
    )
    assert integration_steps.index("Run service-owned migrations") < integration_steps.index(
        "Run serial service migration lifecycle tests"
    )
    service_step = next(
        step
        for step in integration_job["steps"]
        if step["name"] == "Run service-owned database tests"
    )
    assert service_step["if"] == "matrix.shard == 1"
    assert service_step["env"]["FDAI_DATABASE_URL"] == "${{ env.FDAI_SERVICE_DATABASE_URL }}"
    provider_stack_step = next(
        step for step in integration_job["steps"] if step["name"] == "Start loopback provider stack"
    )
    assert provider_stack_step["if"] == "matrix.shard == 2"
    assert provider_stack_step["env"]["POSTGRES_PASSWORD"] == "ci"
    provider_step = next(
        step
        for step in integration_job["steps"]
        if step["name"] == "Run the shared provider contract matrix"
    )
    assert provider_step["if"] == "matrix.shard == 2"
    assert provider_step["env"]["FDAI_PROVIDER_CONTRACT_BACKENDS"] == "real"


def test_ci_runs_regression_without_coverage_and_merges_focused_coverage() -> None:
    jobs = yaml.safe_load(
        (_REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )["jobs"]
    regression_job = jobs["python-tests"]
    shard_job = jobs["python-coverage-shards"]
    merge_job = jobs["python-coverage"]

    assert regression_job["strategy"]["matrix"]["shard"] == [1, 2, 3, 4]
    assert regression_job["env"]["FDAI_PYTEST_MODE"] == "regression"
    assert {step["name"] for step in regression_job["steps"]}.isdisjoint(
        {"Prepare coverage data", "Upload coverage data"}
    )
    assert shard_job["strategy"]["matrix"]["shard"] == [1, 2]
    assert shard_job["env"]["FDAI_PYTEST_MODE"] == "coverage"
    assert shard_job["env"]["FDAI_PYTEST_SHARD_COUNT"] == "2"
    assert shard_job["env"]["FDAI_PYTEST_SHARD_INDEX"] == "${{ matrix.shard }}"
    assert merge_job["needs"] == ["changes", "python-coverage-shards"]
    merge_step = next(
        step
        for step in merge_job["steps"]
        if step["name"] == "Enforce aggregate safety-core coverage"
    )
    assert "coverage combine coverage-data" in merge_step["run"]
    assert "coverage report --fail-under=90" in merge_step["run"]


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

    assert "terraform-validate:" in workflow
    assert "needs.changes.outputs.terraform == 'true'" in workflow
    assert "trivy config --exit-code 1 --severity MEDIUM,HIGH,CRITICAL infra" in workflow
    assert "terraform-security:" not in workflow
    assert "checkov -d infra --quiet --compact --framework terraform" in workflow
    assert "--baseline" not in workflow
