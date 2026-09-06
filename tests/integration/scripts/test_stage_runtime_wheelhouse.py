"""Synthetic runtime-wheelhouse checks; no uv, package network, or Azure execution."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/deployment/release/stage-runtime-wheelhouse.py"
EXPECTED = {
    "fdai-service-contracts",
    "fdai-core-control-plane",
    "fdai-operator-service",
    "fdai-document-ingestion-api",
    "fdai-document-processing-worker",
    "fdai-isolated-executor-service",
}
REQUIREMENTS = b"example-dependency==1.0 \\\n    --hash=sha256:" + b"a" * 64 + b"\n"


@pytest.fixture
def module(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("runtime_wheelhouse", SCRIPT)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


@pytest.fixture
def repository(tmp_path, module):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text('[project]\nname = "fdai"\nversion = "0.0.0"\n')
    entries = []
    for name, relative in module.RUNTIME_PACKAGES.items():
        project = repo / relative
        project.mkdir(parents=True)
        (project / "pyproject.toml").write_text(f'[project]\nname = "{name}"\nversion = "1.0"\n')
        entries.append(
            f'[[package]]\nname = "{name}"\nversion = "1.0"\n'
            f'source = {{ editable = "{relative}" }}\n'
        )
    for name, relative in (
        ("fdai-evaluation-sdk", "evaluation-sdk"),
        ("fdai-benchmark-cybergym", "benchmarks/cybergym"),
        ("fdai-code-assurance", "extensions/code-assurance"),
    ):
        entries.append(
            f'[[package]]\nname = "{name}"\nversion = "1.0"\n'
            f'source = {{ editable = "{relative}" }}\n'
        )
    (repo / "uv.lock").write_text("\n".join(entries))
    cli = repo / "packages/deployment-cli"
    cli.mkdir()
    (cli / "pyproject.toml").write_text(
        '[project]\nname = "fdai-deployment-cli"\nversion = "1.0"\n'
        '[dependency-groups]\nrelease = ["pip==26.2.1"]\n'
    )
    (cli / "uv.lock").write_text("version = 1\n")
    return repo


class RecordingRunner:
    """Materialize minimal wheel artifacts while recording subprocess contracts."""

    def __init__(self, repo):
        self.repo = repo
        self.calls = []
        self.fail = None
        self.omit_build = False
        self.omit_download = False
        self.committed = {
            relative: (repo / relative).read_bytes()
            for relative in ("uv.lock", "packages/deployment-cli/uv.lock")
        }

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        if self.fail == args[1]:
            raise subprocess.TimeoutExpired(args, kwargs["timeout"])
        output = b""
        if args[:2] == ["git", "rev-parse"]:
            output = str(self.repo).encode() + b"\n"
        elif args[:2] == ["git", "show"]:
            output = self.committed[args[2].removeprefix("HEAD:")]
        elif args[1] == "export":
            kwargs["stdout"].write(REQUIREMENTS)
        elif args[1] == "build" and not self.omit_build:
            name = args[args.index("--package") + 1]
            destination = Path(args[args.index("--out-dir") + 1])
            filename = f"{name.replace('-', '_')}-1.0-py3-none-any.whl"
            with zipfile.ZipFile(destination / filename, "w") as wheel:
                wheel.writestr(
                    f"{name.replace('-', '_')}-1.0.dist-info/METADATA",
                    f"Metadata-Version: 2.3\nName: {name}\nVersion: 1.0\n",
                )
        elif args[1] == "run" and not self.omit_download:
            destination = Path(args[args.index("--dest") + 1])
            (destination / "example_dependency-1.0-py3-none-any.whl").write_bytes(b"synthetic")
        return subprocess.CompletedProcess(args, 0, stdout=output)


def test_exact_roots_locked_exports_binary_hash_downloads(module, repository, tmp_path):
    runner = RecordingRunner(repository)
    out = tmp_path / "wheelhouse"
    inventory = module.stage_runtime_wheelhouse(out, repository, runner=runner)
    assert set(inventory["packages"]) == EXPECTED == set(module.RUNTIME_PACKAGES)
    assert inventory["support_packages"] == {}
    assert inventory["production_release_eligible"] is False
    assert json.loads((out / "inventory.json").read_text()) == inventory
    assert out.stat().st_mode & 0o777 == 0o700
    assert len(runner.calls) == 20
    for args, options in runner.calls:
        assert options["cwd"] == repository
        assert 0 < options["timeout"] <= module.STAGE_TIMEOUT
        assert options["check"] is True
        assert not options.get("shell")
        if args[0] == "git":
            continue
        assert options["env"]["UV_PROJECT_ENVIRONMENT"] == str(out / ".work/release-env")
        assert "VIRTUAL_ENV" not in options["env"]
        assert options["env"]["TMPDIR"] == str(out / ".work/scratch")
        if args[1] == "export":
            assert args[2:8] == [
                "--locked",
                "--package",
                args[4],
                "--no-dev",
                "--no-default-groups",
                "--no-emit-workspace",
            ]
            assert "--no-hashes" not in args
            assert args[args.index("--format") + 1] == "requirements-txt"
            assert "--extra" not in args and "--all-packages" not in args
        if args[1] == "run":
            assert args[:9] == [
                "uv",
                "run",
                "--project",
                "packages/deployment-cli",
                "--locked",
                "--no-dev",
                "--group",
                "release",
                "--python",
            ]
            assert args[9] == sys.executable
            assert args[10:16] == [
                "python",
                "-m",
                "pip",
                "download",
                "--only-binary=:all:",
                "--require-hashes",
            ]
    for info in inventory["packages"].values():
        assert info["version"] == "1.0"
        assert (out / info["requirements"]).read_bytes() == REQUIREMENTS
        assert info["wheel"].startswith("build/")
    assert len(inventory["files"]) == 19
    support = (out / inventory["support_requirements"]).read_text()
    for name in EXPECTED:
        assert f"{name}==1.0 --hash=sha256:" in support
    for relative, digest in inventory["files"].items():
        assert hashlib.sha256((out / relative).read_bytes()).hexdigest() == digest
        assert not relative.startswith(".work/")


def test_required_workspace_support_is_not_silently_omitted(module, repository, tmp_path):
    lock = repository / "uv.lock"
    lock.write_text(
        lock.read_text().replace(
            'source = { editable = "services/core-control-plane" }',
            'source = { editable = "services/core-control-plane" }\n'
            'dependencies = [{ name = "fdai-github-app-auth" }]',
        )
        + '\n[[package]]\nname = "fdai-github-app-auth"\nversion = "1.0"\n'
        'source = { editable = "packages/github-app-auth" }\n'
    )
    support = repository / "packages/github-app-auth"
    support.mkdir()
    (support / "pyproject.toml").write_text(
        '[project]\nname = "fdai-github-app-auth"\nversion = "1.0"\n'
    )
    inventory = module.stage_runtime_wheelhouse(
        tmp_path / "out", repository, runner=RecordingRunner(repository)
    )
    assert set(inventory["packages"]) == EXPECTED
    assert set(inventory["support_packages"]) == {"fdai-github-app-auth"}


@pytest.mark.parametrize("failure", ["export", "build", "run", "missing-wheel", "missing-download"])
def test_failure_leaves_no_success_inventory(module, repository, tmp_path, failure):
    runner = RecordingRunner(repository)
    runner.fail = failure
    runner.omit_build = failure == "missing-wheel"
    runner.omit_download = failure == "missing-download"
    out = tmp_path / "out"
    with pytest.raises(module.StagingError):
        module.stage_runtime_wheelhouse(out, repository, runner=runner)
    assert not (out / "inventory.json").exists()
    assert sum(args[1] == failure for args, _ in runner.calls) <= 1


def test_deadline_shrinks_each_command_and_stops_without_inventory(module, repository, tmp_path):
    runner = RecordingRunner(repository)
    ticks = iter([0, 1, 2, 3, 4, 3500, 3501, 3599, 3600])
    out = tmp_path / "out"
    with pytest.raises(module.StagingError, match="total deadline"):
        module.stage_runtime_wheelhouse(out, repository, runner=runner, clock=lambda: next(ticks))
    assert [options["timeout"] for _, options in runner.calls] == [600, 600, 100, 1]
    assert not (out / "inventory.json").exists()


@pytest.mark.parametrize("relative", ["uv.lock", "packages/deployment-cli/uv.lock"])
def test_uncommitted_lock_is_rejected(module, repository, tmp_path, relative):
    runner = RecordingRunner(repository)
    (repository / relative).write_bytes(runner.committed[relative] + b"\n")
    with pytest.raises(module.StagingError, match="committed HEAD"):
        module.stage_runtime_wheelhouse(tmp_path / "out", repository, runner=runner)
    assert all(args[0] == "git" for args, _ in runner.calls)


@pytest.mark.parametrize(
    "kind",
    [
        "relative",
        "repo",
        "home",
        "parent",
        "root",
        "traversal",
        "nonempty",
        "public",
        "symlink",
        "ancestor-link",
        "writable-parent",
    ],
)
def test_unsafe_output_rejected_without_overwrite(module, repository, tmp_path, kind):
    out = tmp_path / "out"
    if kind in {"relative", "repo", "home", "parent", "root", "traversal"}:
        out = {
            "relative": Path("relative"),
            "repo": repository,
            "home": Path.home(),
            "parent": tmp_path,
            "root": Path("/"),
            "traversal": tmp_path / ".." / "out",
        }[kind]
    elif kind == "symlink":
        out.symlink_to(repository, target_is_directory=True)
    elif kind in {"ancestor-link", "writable-parent"}:
        parent = tmp_path / "parent"
        if kind == "ancestor-link":
            parent.symlink_to(repository, target_is_directory=True)
        else:
            parent.mkdir()
            parent.chmod(0o777)
        out = parent / "out"
    else:
        out.mkdir(mode=0o755 if kind == "public" else 0o700)
        if kind == "nonempty":
            (out / "keep").write_bytes(b"unchanged")
    with pytest.raises((OSError, RuntimeError)):
        module.stage_runtime_wheelhouse(out, repository, runner=RecordingRunner(repository))
    if kind == "nonempty":
        assert (out / "keep").read_bytes() == b"unchanged"


def test_empty_owned_directory_and_default_git_root(module, repository, tmp_path):
    out = tmp_path / "out"
    out.mkdir(mode=0o700)
    runner = RecordingRunner(repository)
    module.stage_runtime_wheelhouse(out, runner=runner)
    assert runner.calls[0][0] == ["git", "rev-parse", "--show-toplevel"]
    assert all(options["cwd"] == repository for _, options in runner.calls[1:])


def test_foreign_owned_output_rejected(module, tmp_path, monkeypatch):
    out = tmp_path / "out"
    out.mkdir(mode=0o700)
    owner = module.os.geteuid()
    monkeypatch.setattr(module.os, "geteuid", lambda: owner + 1)
    with pytest.raises(RuntimeError):
        module._prepare_output(out, tmp_path / "repo")
    assert not list(out.iterdir())


def test_cli_reports_incomplete_without_exposing_command_output(
    module, repository, tmp_path, monkeypatch, capsys
):
    runner = RecordingRunner(repository)
    runner.fail = "build"
    monkeypatch.setattr(module.subprocess, "run", runner)
    assert module.main(["--out-dir", str(tmp_path / "out"), "--repo-root", str(repository)]) == 1
    captured = capsys.readouterr()
    assert not captured.out
    assert "incomplete" in captured.err
