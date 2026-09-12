from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


def _git_executable() -> str:
    executable = shutil.which("git")
    if executable is None:
        pytest.skip("git is required")
    return executable


GIT = _git_executable()


def _load_module() -> ModuleType:
    path = REPO_ROOT / "scripts/quality/architecture/check-fork-runtime-independence.py"
    spec = importlib.util.spec_from_file_location("fork_runtime_independence", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _init_repo(path: Path) -> None:
    subprocess.run(  # noqa: S603 - resolved git executable and test-owned path
        [GIT, "init", "-q"],
        cwd=path,
        check=True,
    )


def test_runtime_tree_has_no_fork_mode_branch() -> None:
    module = _load_module()

    assert module.violations() == []


@pytest.mark.parametrize(
    "relative_path",
    (
        "services/core-control-plane/src/fdai/runtime/fork_mode.py",
        "fork/entry.py",
        "delivery/launch",
        "extensions/policy.rego",
        "service-migrations/template.yaml.tftpl",
        "infra/runtime.hcl",
        "packages/runtime/pyproject.toml",
        ".github/workflows/deploy-dev.yml",
        ".github/workflows/service-deploy.yml",
        ".github/actions/verify-protected-workflow-source/action.yml",
        ".vscode/tasks.json",
        "src/fdai/runtime.py",
        "alembic.ini",
        "pyproject.toml",
        "uv.lock",
        "scripts/catalog/run-enforce-scenarios.py",
        "Makefile",
        "mocks/app.js",
        "examples/design-mock.html",
        "docs/internals/sregym-absorption-ledger.json",
        "scripts/quality/architecture/remote_service_evidence.py",
    ),
)
def test_governed_runtime_fork_mode_branch_is_rejected(
    tmp_path: Path,
    relative_path: str,
) -> None:
    module = _load_module()
    _init_repo(tmp_path)
    runtime_file = tmp_path / relative_path
    runtime_file.parent.mkdir(parents=True, exist_ok=True)
    runtime_file.write_text('enabled = os.getenv("FDAI_FORK") == "1"\n', encoding="utf-8")

    assert module.violations(tmp_path) == [
        (
            Path(relative_path),
            1,
            'enabled = os.getenv("FDAI_FORK") == "1"',
        )
    ]


def test_ignored_runtime_artifact_is_not_scanned(tmp_path: Path) -> None:
    module = _load_module()
    _init_repo(tmp_path)
    (tmp_path / ".gitignore").write_text("console/node_modules/\n", encoding="utf-8")
    ignored_file = tmp_path / "console" / "node_modules" / "dependency.js"
    ignored_file.parent.mkdir(parents=True)
    ignored_file.write_text('const fork = "FDAI_FORK";\n', encoding="utf-8")

    assert module.violations(tmp_path) == []


@pytest.mark.parametrize(
    "encoding",
    ("latin-1", "utf-16", "utf-32", "utf-32-le", "utf-32-be"),
)
def test_non_utf8_runtime_marker_is_rejected(tmp_path: Path, encoding: str) -> None:
    module = _load_module()
    _init_repo(tmp_path)
    runtime_file = tmp_path / "services" / "runtime" / "encoded.py"
    runtime_file.parent.mkdir(parents=True)
    content = '# coding: latin-1\nvalue = "FDAI_FORK"\n'
    runtime_file.write_bytes(content.encode(encoding))

    violations = module.violations(tmp_path)

    assert len(violations) == 1
    assert violations[0][:2] == (Path("services/runtime/encoded.py"), 2)
    assert "FDAI_FORK" in violations[0][2]


def test_binary_runtime_artifact_without_marker_is_ignored(tmp_path: Path) -> None:
    module = _load_module()
    _init_repo(tmp_path)
    binary_file = tmp_path / "services" / "runtime" / "artifact.bin"
    binary_file.parent.mkdir(parents=True)
    binary_file.write_bytes(b"\x00\xff\x10\x80\x00")

    assert module.violations(tmp_path) == []


def test_tracked_runtime_symlink_target_is_not_dereferenced(tmp_path: Path) -> None:
    module = _load_module()
    _init_repo(tmp_path)
    external_file = tmp_path / "outside-source"
    external_file.write_text('value = "FDAI_FORK"\n', encoding="utf-8")
    runtime_link = tmp_path / "site" / "runtime-input"
    runtime_link.parent.mkdir(parents=True)
    runtime_link.symlink_to(external_file)

    assert module.violations(tmp_path) == []


def test_tracked_runtime_parent_symlink_is_not_dereferenced(tmp_path: Path) -> None:
    module = _load_module()
    _init_repo(tmp_path)
    runtime_dir = tmp_path / "services" / "runtime"
    runtime_dir.mkdir(parents=True)
    tracked_file = runtime_dir / "module.py"
    tracked_file.write_text('value = "safe"\n', encoding="utf-8")
    subprocess.run(  # noqa: S603 - resolved git executable and test-owned path
        [GIT, "add", "services/runtime/module.py"],
        cwd=tmp_path,
        check=True,
    )
    tracked_file.unlink()
    runtime_dir.rmdir()
    external_dir = tmp_path / "outside-runtime"
    external_dir.mkdir()
    (external_dir / "module.py").write_text('value = "FDAI_FORK"\n', encoding="utf-8")
    runtime_dir.symlink_to(external_dir, target_is_directory=True)

    assert module.violations(tmp_path) == []


def test_verify_scope_covers_governed_runtime_paths() -> None:
    module = _load_module()
    verify_script = (REPO_ROOT / "scripts/verify.sh").read_text(encoding="utf-8")
    match = re.search(
        r'run_gate_scoped_or_deferred "fork-runtime-independence" \'([^\']+)\'',
        verify_script,
    )
    assert match is not None
    scoped_pattern = re.compile(match.group(1))

    for root in module.RUNTIME_ROOTS:
        path = f"{root}/probe"
        assert scoped_pattern.search(path), path
    for path in module.RUNTIME_FILES:
        assert scoped_pattern.search(path), path
