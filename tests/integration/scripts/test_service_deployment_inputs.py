from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from scripts.deployment.service.deployment_inputs import (
    DeploymentInputError,
    verify_unchanged,
)


def _git(repository: Path, *arguments: str) -> str:
    git = shutil.which("git")
    assert git is not None
    completed = subprocess.run(  # noqa: S603 - resolved Git runs test-controlled arguments
        [git, *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _write_inputs(repository: Path, *, version: str, dependency: str = "1.0") -> None:
    (repository / ".github/workflows").mkdir(parents=True, exist_ok=True)
    (repository / "scripts/deployment/service").mkdir(parents=True, exist_ok=True)
    (repository / "infra/services/core").mkdir(parents=True, exist_ok=True)
    (repository / "alembic").mkdir(exist_ok=True)
    (repository / "service-migrations").mkdir(exist_ok=True)
    (repository / ".github/workflows/service-deploy.yml").write_text(
        "name: service-deploy\n", encoding="utf-8"
    )
    (repository / "scripts/deployment/service/helper.py").write_text(
        "VALUE = 1\n", encoding="utf-8"
    )
    (repository / "infra/services/core/main.tf").write_text("terraform {}\n", encoding="utf-8")
    (repository / "alembic/revision.py").write_text("revision = 'one'\n", encoding="utf-8")
    (repository / "alembic.ini").write_text("[alembic]\n", encoding="utf-8")
    (repository / "service-migrations/ownership.json").write_text("{}\n", encoding="utf-8")
    (repository / "pyproject.toml").write_text(
        f'[project]\nname = "fdai"\nversion = "{version}"\n'
        f'dependencies = ["example=={dependency}"]\n',
        encoding="utf-8",
    )
    (repository / "uv.lock").write_text(
        'version = 1\nrevision = 3\n\n[[package]]\nname = "example"\n'
        f'version = "{dependency}"\n\n[[package]]\nname = "fdai"\nversion = "{version}"\n'
        'source = { virtual = "." }\n',
        encoding="utf-8",
    )


def _repository(tmp_path: Path) -> tuple[Path, str]:
    repository = tmp_path / "repo"
    repository.mkdir()
    _git(repository, "init", "--quiet")
    _git(repository, "config", "user.email", "tests@example.com")
    _git(repository, "config", "user.name", "FDAI Tests")
    _write_inputs(repository, version="0.1.1")
    _git(repository, "add", ".")
    _git(repository, "commit", "--quiet", "-m", "initial")
    return repository, _git(repository, "rev-parse", "HEAD")


def _commit(repository: Path, message: str) -> str:
    _git(repository, "add", ".")
    _git(repository, "commit", "--quiet", "-m", message)
    return _git(repository, "rev-parse", "HEAD")


def test_accepts_release_only_root_version_change(tmp_path: Path) -> None:
    repository, before = _repository(tmp_path)
    _write_inputs(repository, version="0.1.2")
    after = _commit(repository, "release")

    verify_unchanged(repository, before, after)


def test_rejects_root_dependency_change(tmp_path: Path) -> None:
    repository, before = _repository(tmp_path)
    _write_inputs(repository, version="0.1.2", dependency="2.0")
    after = _commit(repository, "dependency")

    with pytest.raises(DeploymentInputError, match="pyproject.toml"):
        verify_unchanged(repository, before, after)


def test_rejects_lock_graph_change_even_when_project_is_unchanged(tmp_path: Path) -> None:
    repository, before = _repository(tmp_path)
    lock_path = repository / "uv.lock"
    lock = lock_path.read_text(encoding="utf-8").replace('version = "1.0"', 'version = "2.0"', 1)
    lock_path.write_text(lock, encoding="utf-8")
    after = _commit(repository, "lock")

    with pytest.raises(DeploymentInputError, match="uv.lock"):
        verify_unchanged(repository, before, after)


def test_rejects_strict_workflow_change(tmp_path: Path) -> None:
    repository, before = _repository(tmp_path)
    workflow = repository / ".github/workflows/service-deploy.yml"
    workflow.write_text("name: changed\n", encoding="utf-8")
    after = _commit(repository, "workflow")

    with pytest.raises(DeploymentInputError, match="strict deployment inputs"):
        verify_unchanged(repository, before, after)


def test_rejects_invalid_virtual_package_shape(tmp_path: Path) -> None:
    repository, before = _repository(tmp_path)
    lock_path = repository / "uv.lock"
    lock = lock_path.read_text(encoding="utf-8").replace('source = { virtual = "." }', "")
    lock_path.write_text(lock, encoding="utf-8")
    after = _commit(repository, "invalid lock")

    with pytest.raises(DeploymentInputError, match="virtual fdai package"):
        verify_unchanged(repository, before, after)
