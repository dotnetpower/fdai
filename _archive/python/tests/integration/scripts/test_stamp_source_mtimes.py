"""Contracts for content-derived source times that keep cached bytecode valid across checkouts."""

from __future__ import annotations

import importlib.util
import os
import py_compile
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "stamp_source_mtimes", ROOT / "scripts/quality/ci/stamp-source-mtimes.py"
)
assert SPEC is not None and SPEC.loader is not None
STAMP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STAMP)


def _git(repository: Path, *arguments: str) -> None:
    subprocess.run(  # noqa: S603
        ["/usr/bin/git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.invalid",
            "HOME": str(repository),
        },
    )


def _checkout(path: Path, files: dict[str, str]) -> Path:
    path.mkdir()
    _git(path, "init", "-q")
    for name, text in files.items():
        (path / name).parent.mkdir(parents=True, exist_ok=True)
        (path / name).write_text(text, encoding="utf-8")
    _git(path, "add", "-A")
    return path


def test_the_stamp_comes_from_the_blob_id_inside_the_pyc_header_range() -> None:
    listing = (
        "100644 ab12cd34ef567890ab12cd34ef567890ab12cd34 0\tpkg/a.py\n"
        "100755 ffffffffffffffffffffffffffffffffffffffff 0\tpkg/b.py\n"
        "120000 1111111111111111111111111111111111111111 0\tlink.py\n"
        "160000 2222222222222222222222222222222222222222 0\tmodule.py\n"
        "100644 0000000000000000000000000000000000000000 0\tzero.py\n"
    )
    stamps = STAMP.stamps(listing)
    assert set(stamps) == {"pkg/a.py", "pkg/b.py", "zero.py"}
    assert stamps["pkg/a.py"] == 0xAB12CD34 & 0x7FFFFFFF
    assert all(0 < value <= 0x7FFFFFFF for value in stamps.values())


def test_identical_content_gets_the_same_time_in_independent_checkouts(tmp_path: Path) -> None:
    files = {"a.py": "x = 1\n", "pkg/b.py": "y = 2\n"}
    first = _checkout(tmp_path / "one", files)
    second = _checkout(tmp_path / "two", files)
    os.utime(second / "a.py", (1_700_000_000, 1_700_000_000))
    assert STAMP.main(["--root", str(first)]) == 0
    assert STAMP.main(["--root", str(second)]) == 0
    for name in files:
        assert (first / name).stat().st_mtime == (second / name).stat().st_mtime


def test_changed_content_changes_the_time(tmp_path: Path) -> None:
    repository = _checkout(tmp_path / "repo", {"a.py": "x = 1\n"})
    STAMP.main(["--root", str(repository)])
    before = (repository / "a.py").stat().st_mtime
    (repository / "a.py").write_text("x = 2\n", encoding="utf-8")
    _git(repository, "add", "-A")
    STAMP.main(["--root", str(repository)])
    assert (repository / "a.py").stat().st_mtime != before


def test_bytecode_from_one_checkout_validates_in_another(tmp_path: Path) -> None:
    files = {"module.py": "VALUE = 41\n"}
    first = _checkout(tmp_path / "one", files)
    second = _checkout(tmp_path / "two", files)
    for repository in (first, second):
        STAMP.main(["--root", str(repository)])
    cached = Path(py_compile.compile(str(first / "module.py"), doraise=True))
    other = Path(importlib.util.cache_from_source(str(second / "module.py")))
    other.parent.mkdir(exist_ok=True)
    other.write_bytes(cached.read_bytes())
    _, flags, mtime, size = struct.unpack("<4sIII", other.read_bytes()[:16])
    source = (second / "module.py").stat()
    assert flags == 0
    assert (mtime, size) == (int(source.st_mtime) & 0xFFFFFFFF, source.st_size)


def test_untracked_and_symlinked_files_are_left_alone(tmp_path: Path) -> None:
    repository = _checkout(tmp_path / "repo", {"tracked.py": "a = 1\n"})
    (repository / "untracked.py").write_text("b = 2\n", encoding="utf-8")
    os.utime(repository / "untracked.py", (1_600_000_000, 1_600_000_000))
    (repository / "link.py").symlink_to("tracked.py")
    _git(repository, "add", "link.py")
    STAMP.main(["--root", str(repository)])
    assert (repository / "untracked.py").stat().st_mtime == 1_600_000_000


def test_unstaged_same_size_changes_are_refused_before_stamping(tmp_path: Path) -> None:
    repository = _checkout(tmp_path / "repo", {"module.py": "VALUE = 1\n"})
    assert STAMP.main(["--root", str(repository)]) == 0
    before = (repository / "module.py").stat().st_mtime
    (repository / "module.py").write_text("VALUE = 2\n", encoding="utf-8")
    os.utime(repository / "module.py", (before + 1, before + 1))
    assert STAMP.main(["--root", str(repository)]) == 1
    assert (repository / "module.py").stat().st_mtime == before + 1


def test_cache_identity_binds_workspace_pytest_and_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _checkout(tmp_path / "one", {"a.py": "x = 1\n"})
    second = _checkout(tmp_path / "two", {"a.py": "x = 1\n"})
    identity = STAMP.cache_identity(first)
    assert identity != STAMP.cache_identity(second)
    monkeypatch.setattr(STAMP.importlib.metadata, "version", lambda _: "different-pytest")
    assert identity != STAMP.cache_identity(first)
    identity = STAMP.cache_identity(first)
    (first / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    assert identity != STAMP.cache_identity(first)


def test_changed_source_invalidates_bytecode_even_with_a_timestamp_collision(
    tmp_path: Path,
) -> None:
    repository = _checkout(tmp_path / "repo", {"module.py": "VALUE = 1\n"})
    sources = STAMP.source_digests(repository)
    identity = STAMP.cache_identity(repository)
    STAMP.validate_restored_cache(repository, sources, identity)
    cached = Path(py_compile.compile(str(repository / "module.py"), doraise=True))
    (repository / "module.py").write_text("VALUE = 2\n", encoding="utf-8")
    _git(repository, "add", "-A")
    STAMP.validate_restored_cache(repository, STAMP.source_digests(repository), identity)
    assert not cached.exists()


def test_foreign_rewritten_cache_is_invalidated_and_profile_paths_are_current(
    tmp_path: Path,
) -> None:
    text = (
        "import cProfile, pstats\n"
        "from pathlib import Path\n"
        "def work():\n"
        "    return sum(i*i for i in range(500))\n"
        "def test_profile():\n"
        "    p=cProfile.Profile(); p.runcall(work)\n"
        "    assert any(Path(name).is_relative_to(Path(__file__).parent)\n"
        "               for name, _, _ in pstats.Stats(p).stats)\n"
    )
    first = _checkout(tmp_path / "writer", {"test_profile.py": text})
    second = _checkout(tmp_path / "reader", {"test_profile.py": text})
    for root in (first, second):
        assert STAMP.main(["--root", str(root)]) == 0
    STAMP.validate_restored_cache(first, STAMP.source_digests(first), STAMP.cache_identity(first))
    environment = {**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    for key in (
        "PYTEST_ADDOPTS",
        "PYTEST_PLUGINS",
        "PYTHONPATH",
        "PYTHONDONTWRITEBYTECODE",
        "PYTHONPYCACHEPREFIX",
    ):
        environment.pop(key, None)
    command = [
        sys.executable,
        "-m",
        "pytest",
        "--assert=rewrite",
        "-q",
        "-c",
        "/dev/null",
        "test_profile.py",
    ]
    initial = subprocess.run(  # noqa: S603 - isolated synthetic test
        command, cwd=first, env=environment, capture_output=True, text=True, timeout=30
    )
    assert initial.returncode == 0, initial.stdout + initial.stderr
    shutil.copytree(first / "__pycache__", second / "__pycache__")
    manifest = second / ".fdai/ci-bytecode-sources.json"
    manifest.parent.mkdir()
    shutil.copyfile(first / ".fdai/ci-bytecode-sources.json", manifest)
    assert STAMP.main(["--root", str(second), "--validate-restored"]) == 0
    restored = subprocess.run(  # noqa: S603 - same test in a different checkout
        command, cwd=second, env=environment, capture_output=True, text=True, timeout=30
    )
    assert restored.returncode == 0, restored.stdout + restored.stderr


def test_unchanged_sources_keep_valid_cached_bytecode(tmp_path: Path) -> None:
    repository = _checkout(tmp_path / "repo", {"module.py": "VALUE = 1\n"})
    sources = STAMP.source_digests(repository)
    identity = STAMP.cache_identity(repository)
    STAMP.validate_restored_cache(repository, sources, identity)
    cached = Path(py_compile.compile(str(repository / "module.py"), doraise=True))
    STAMP.validate_restored_cache(repository, sources, identity)
    assert cached.exists()


def test_workflow_binds_cache_identity_to_the_selected_runtime_and_validates_restore() -> None:
    jobs = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))["jobs"]
    for name in (
        "python-tests",
        "python-tests-ssd",
        "python-tests-elastic",
        "python-coverage-shards",
        "db-integration",
    ):
        steps = jobs[name]["steps"]
        names = [step["name"] for step in steps]
        context = names.index("Verify and stamp tracked Python sources")
        restored = names.index("Restore cached bytecode")
        verified = names.index("Validate restored bytecode sources")
        assert names.index("Install dependencies") < context < restored < verified
        assert steps[context]["run"].startswith("uv run --frozen python ")
        cache = steps[restored]["with"]
        assert "steps.bytecode-context.outputs.key" in cache["key"]
        assert "steps.bytecode-context.outputs.key" in cache["restore-keys"]
        assert ".fdai/ci-bytecode-sources.json" in cache["path"]
    saved = next(
        step for step in jobs["python-tests"]["steps"] if step["name"] == "Save cached bytecode"
    )
    assert "success()" in saved["if"]
    assert "github.event_name == 'push'" in saved["if"]
    assert "github.ref == 'refs/heads/main'" in saved["if"]
