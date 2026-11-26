"""Context-only reuse refuses dirty, mutable, or external validation inputs."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from scripts.automation import local_validation_context as context
from scripts.automation.local_validation_inputs import git

pytestmark = pytest.mark.no_cover


@pytest.fixture
def checkout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, dict[str, str]]:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "--quiet", "--initial-branch=main")
    git(root, "config", "user.name", "Example User")
    git(root, "config", "user.email", "user@example.com")
    (root / "pyproject.toml").write_text("[project]\nname='example'\n", encoding="utf-8")
    (root / "uv.lock").write_text("version=1\n", encoding="utf-8")
    (root / ".gitignore").write_text("ignored.txt\n.venv/\n", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "--quiet", "-m", "initial")
    venv = root / ".venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin/python").write_bytes(b"interpreter")
    (venv / "pyvenv.cfg").write_text(
        "include-system-site-packages = false\n",
        encoding="utf-8",
    )
    tool = tmp_path / "tool"
    tool.write_bytes(b"tool")
    monkeypatch.setattr(context.shutil, "which", lambda _name, **_kwargs: str(tool))
    return root, {
        "UV_NO_SYNC": "1",
        "UV_NO_CONFIG": "1",
        "PYTHONNOUSERSITE": "1",
        "UV_PROJECT_ENVIRONMENT": str(venv),
    }


def test_metadata_only_commit_preserves_content_not_history(
    checkout: tuple[Path, dict[str, str]],
) -> None:
    root, environment = checkout
    before = context.validation_context(root, environment=environment)
    git(root, "commit", "--allow-empty", "--quiet", "-m", "metadata only")
    after = context.validation_context(root, environment=environment)
    assert before["content"] == after["content"]
    assert before["history"] != after["history"]


@pytest.mark.parametrize("name", ["uv.lock", "untracked.txt", "ignored.txt"])
def test_dirty_tracked_untracked_and_ignored_inputs_disable_reuse(
    checkout: tuple[Path, dict[str, str]],
    name: str,
) -> None:
    root, environment = checkout
    (root / name).write_text("dirty\n", encoding="utf-8")
    with pytest.raises(ValueError):
        context.validation_context(root, environment=environment)


def test_dirty_index_cannot_certify_clean_worktree_bytes(
    checkout: tuple[Path, dict[str, str]],
) -> None:
    root, environment = checkout
    path = root / "uv.lock"
    original = path.read_bytes()
    path.write_bytes(b"staged changes")
    git(root, "add", "uv.lock")
    path.write_bytes(original)
    with pytest.raises(subprocess.CalledProcessError):
        context.validation_context(root, environment=environment)


def test_dependency_and_ambient_environment_changes_invalidate_content(
    checkout: tuple[Path, dict[str, str]],
) -> None:
    root, environment = checkout
    before = context.validation_context(root, environment=environment)
    (root / ".venv/bin/python").write_bytes(b"changed interpreter")
    assert context.validation_context(root, environment=environment)["content"] != before["content"]
    changed = context.validation_context(root, environment=environment)
    environment["FILE_LOC_MODE"] = "enforce"
    assert (
        context.validation_context(root, environment=environment)["content"] != changed["content"]
    )


@pytest.mark.parametrize(
    "key,value",
    [
        ("CI", "true"),
        ("UV_NO_SYNC", "0"),
        ("UV_NO_CONFIG", "0"),
        ("PYTHONNOUSERSITE", "0"),
        ("PYTHONPATH", "/unverified/source"),
    ],
)
def test_unsafe_execution_context_disables_reuse(
    checkout: tuple[Path, dict[str, str]],
    key: str,
    value: str,
) -> None:
    root, environment = checkout
    environment[key] = value
    with pytest.raises(ValueError):
        context.validation_context(root, environment=environment)


def test_external_editable_dependency_is_not_a_verified_input(
    checkout: tuple[Path, dict[str, str]],
) -> None:
    root, environment = checkout
    metadata = root / ".venv/direct_url.json"
    metadata.write_text(
        json.dumps(
            {
                "url": root.parent.as_uri(),
                "dir_info": {"editable": True},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="editable dependency"):
        context.validation_context(root, environment=environment)


def test_untracked_alias_into_venv_is_still_untracked(
    checkout: tuple[Path, dict[str, str]],
) -> None:
    root, environment = checkout
    (root / "source.py").symlink_to(root / ".venv/bin/python")
    with pytest.raises(ValueError, match="untracked"):
        context.validation_context(root, environment=environment)
