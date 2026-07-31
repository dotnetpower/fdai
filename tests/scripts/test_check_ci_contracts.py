"""Regression coverage for repository CI workflow contracts."""

from __future__ import annotations

import importlib.util
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
        ".github/workflows/ci.yml uses actions/checkout@v4; expected v7.0.1",
        ".github/workflows/ci.yml uses unapproved remote action example/unreviewed-action@v1",
    ]


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


def test_resolved_model_manifest_reaches_container_build_context() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    dockerfile = (repo_root / "Dockerfile").read_text(encoding="utf-8")
    dockerignore = (repo_root / ".dockerignore").read_text(encoding="utf-8").splitlines()

    assert "COPY --chown=65532:65532 resolved-models.json /app/resolved-models.json" in dockerfile
    assert "resolved-models*.json" in dockerignore
    assert "!resolved-models.json" in dockerignore


def test_dockerfile_installs_only_runtime_workspace_packages() -> None:
    dockerfile = (Path(__file__).resolve().parents[2] / "Dockerfile").read_text(encoding="utf-8")

    assert "--no-install-workspace" in dockerfile
    assert "COPY evaluation-sdk/ ./evaluation-sdk/" in dockerfile
    assert "COPY benchmarks/sregym/pyproject.toml" in dockerfile
    assert "COPY benchmarks/cybergym/pyproject.toml" in dockerfile
    assert "uv sync --frozen --package fdai" in dockerfile
