"""Regression coverage for repository CI workflow contracts."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest


def _load_contract_module() -> ModuleType:
    script = (
        Path(__file__).resolve().parents[2] / "scripts" / "quality" / "ci" / "check-ci-contracts.py"
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


def test_shipped_workflows_satisfy_security_contracts() -> None:
    module = _load_contract_module()

    assert module._validate_action_runtime_versions() == []
    assert module._validate_privileged_workflow_guards() == []


def test_release_bundle_uses_exact_commit_and_reviewed_action_shas() -> None:
    workflow = (
        Path(__file__).resolve().parents[2]
        / ".github"
        / "workflows"
        / "release-deployment-bundle.yml"
    ).read_text(encoding="utf-8")
    uses = re.findall(r"^\s*uses:\s+([^\s#]+)", workflow, re.MULTILINE)
    pins = {
        "actions/checkout": "3d3c42e5aac5ba805825da76410c181273ba90b1",
        "actions/setup-node": "820762786026740c76f36085b0efc47a31fe5020",
        "actions/upload-artifact": "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
        "actions/download-artifact": "3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c",
        "astral-sh/setup-uv": "11f9893b081a58869d3b5fccaea48c9e9e46f990",
        "pypa/gh-action-pip-audit": "1220774d901786e6f652ae159f7b6bc8fea6d266",
        "pypa/gh-action-pypi-publish": "2834a314042ef964da07689278dd1e9d773e8afd",
    }

    assert "commit_sha:" in workflow
    assert 'description: "Exact protected origin/main commit to release."' in workflow
    assert workflow.count("ref: ${{ inputs.commit_sha }}") == 4
    assert "github.sha" not in workflow
    assert uses and all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", value) for value in uses)
    for action, sha in pins.items():
        assert f"{action}@{sha}" in uses


def test_shipped_privileged_workflow_inventory_is_explicitly_audited() -> None:
    module = _load_contract_module()
    workflow_dir = Path(__file__).resolve().parents[2] / ".github" / "workflows"

    privileged = {
        path.name
        for path in workflow_dir.glob("*.yml")
        if module._is_privileged_workflow(path.read_text(encoding="utf-8"))
    }

    assert privileged == {
        "automatic-version.yml",
        "container-supply-chain.yml",
        "deploy-dev.yml",
        "destroy-env.yml",
        "infra-drift.yml",
        "issue-lifecycle.yml",
        "pages.yml",
        "release-deployment-bundle.yml",
        "service-deploy.yml",
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


def test_base_images_must_stay_mirror_overridable_and_digest_pinned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A disconnected build redirects where bytes come from, never which bytes."""
    module = _load_contract_module()
    dockerfile = tmp_path / "Dockerfile"
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
    (tmp_path / "Dockerfile").write_text(
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


def test_resolved_model_manifest_reaches_container_build_context() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    dockerfile = (repo_root / "Dockerfile").read_text(encoding="utf-8")
    dockerignore = (repo_root / ".dockerignore").read_text(encoding="utf-8").splitlines()

    assert "COPY --chown=65532:65532 resolved-models.json /app/resolved-models.json" in dockerfile
    assert "resolved-models*.json" in dockerignore
    assert "!resolved-models.json" in dockerignore


def test_diagnostic_ontology_ledger_reaches_runtime_image() -> None:
    root = Path(__file__).resolve().parents[3]
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
    dockerignore = (root / ".dockerignore").read_text(encoding="utf-8")

    assert (
        "COPY --chown=65532:65532 docs/internals/sregym-absorption-ledger.json "
        "/app/docs/internals/sregym-absorption-ledger.json"
    ) in dockerfile
    assert "!docs/internals/sregym-absorption-ledger.json" in dockerignore


def test_sregym_image_uses_frozen_workspace_and_includes_ontology_ledger() -> None:
    dockerfile = (
        Path(__file__).resolve().parents[2] / "benchmarks" / "sregym" / "Dockerfile"
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
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
    service_dockerfile = (root / "services" / "Dockerfile").read_text(encoding="utf-8")

    assert "--no-install-workspace" in dockerfile
    assert "COPY evaluation-sdk/ ./evaluation-sdk/" in dockerfile
    assert "COPY benchmarks/sregym/pyproject.toml" in dockerfile
    assert "COPY benchmarks/cybergym/pyproject.toml" in dockerfile
    assert "uv sync --frozen --package fdai" in dockerfile
    assert "fdai-isolated-executor" not in dockerfile
    assert "RUN test -x /app/.venv/bin/fdai-isolated-executor-service" in service_dockerfile
    assert 'ENTRYPOINT ["fdai-isolated-executor-service"]' in service_dockerfile


def test_ci_installs_and_audits_the_frozen_runtime_workspace() -> None:
    workflow = (Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    chaos_job = workflow.split("  chaos-scenarios:", 1)[1].split("\n  core-imports:", 1)[0]
    audit_job = workflow.split("  deps-audit:", 1)[1].split("\n  exemption-check:", 1)[0]

    assert "uv sync --frozen --package fdai --no-dev" in chaos_job
    assert "python3 -m pip install --quiet -e ." not in chaos_job
    assert "uv export --format requirements.txt --frozen --no-dev" in audit_job
    assert "--no-emit-workspace --output-file audit-requirements.txt" in audit_job
    assert "inputs: audit-requirements.txt" in audit_job


def test_container_scan_blocks_all_medium_high_and_critical_vulnerabilities() -> None:
    workflow = (
        Path(__file__).resolve().parents[2] / ".github" / "workflows" / "container-supply-chain.yml"
    ).read_text(encoding="utf-8")

    assert workflow.count("--severity MEDIUM,HIGH,CRITICAL") == 2
    assert "--ignore-unfixed" not in workflow


def test_infrastructure_scan_blocks_medium_high_and_critical_findings() -> None:
    workflow = (
        Path(__file__).resolve().parents[2] / ".github" / "workflows" / "infra-lint.yml"
    ).read_text(encoding="utf-8")

    assert "trivy config --exit-code 1 --severity MEDIUM,HIGH,CRITICAL infra" in workflow
