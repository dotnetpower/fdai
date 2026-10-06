from __future__ import annotations

import ast
import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from fdai_deployment_cli import source_runtime_support as support

_REPO = Path(__file__).resolve().parents[3]
_LOCKED = (
    b"alembic==1.16.5 \\\n"
    b"    --hash=sha256:" + b"a" * 64 + b"\n"
    b"colorama==0.4.6 ; sys_platform == 'win32' \\\n"
    b"    --hash=sha256:" + b"b" * 64 + b"\n"
)


def _private(tmp_path: Path) -> Path:
    tmp_path.chmod(0o700)
    return tmp_path


def _source_tree(root: Path, *, version: str = "0.1.0") -> Path:
    for name, path in support.WORKSPACE_PACKAGES.items():
        project = root / path
        project.mkdir(parents=True)
        (project / "pyproject.toml").write_text(
            f'[project]\nname = "{name}"\nversion = "{version}"\n', encoding="utf-8"
        )
    return root


def _requirements(directory: Path, content: bytes = _LOCKED) -> tuple[Path, str]:
    path = directory / support.REQUIREMENTS_NAME
    path.write_bytes(content)
    path.chmod(0o600)
    return path, hashlib.sha256(content).hexdigest()


class FakeHost:
    def __init__(self, versions: dict[str, str]) -> None:
        self.versions = versions
        self.calls: list[tuple[str, ...]] = []
        self.fail: str | None = None

    def __call__(self, command: tuple[str, ...], **_kwargs: object) -> SimpleNamespace:
        self.calls.append(tuple(command))
        if command[1:3] == ("-m", "venv"):
            Path(command[3], "bin").mkdir(parents=True)
        step = command[1] if len(command) > 1 else ""
        if self.fail is not None and self.fail in command:
            return SimpleNamespace(returncode=1, stdout=b"", stderr=b"")
        if step == "list":
            entries = [{"name": name, "version": value} for name, value in self.versions.items()]
            return SimpleNamespace(returncode=0, stdout=json.dumps(entries).encode(), stderr=b"")
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")


def _installed(versions: dict[str, str] | None = None) -> dict[str, str]:
    observed = {name: "0.1.0" for name in support.WORKSPACE_PACKAGES}
    observed["alembic"] = "1.16.5"
    observed.update(versions or {})
    return observed


def test_workspace_packages_match_the_kit_runtime_wheelhouse() -> None:
    tree = ast.parse(
        (_REPO / "scripts/deployment/release/stage-runtime-wheelhouse.py").read_text("utf-8")
    )
    declared = {
        target.id: ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name) and target.id in {"RUNTIME_PACKAGES", "SUPPORT_PACKAGES"}
    }
    assert support.WORKSPACE_PACKAGES == {
        **declared["RUNTIME_PACKAGES"],
        **declared["SUPPORT_PACKAGES"],
    }


def test_export_uses_the_committed_lock_offline_and_binds_its_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _private(tmp_path)
    seen: dict[str, object] = {}

    def run(command: tuple[str, ...], **kwargs: object) -> SimpleNamespace:
        seen["command"] = command
        seen["env"] = kwargs["env"]
        return SimpleNamespace(returncode=0, stdout=_LOCKED, stderr=b"")

    monkeypatch.setenv("UV", "/opt/uv")
    monkeypatch.setattr(support.subprocess, "run", run)

    digest = support.export_runtime_requirements(root / "tree", root / support.REQUIREMENTS_NAME)

    command = seen["command"]
    assert isinstance(command, tuple)
    assert command[:4] == ("/opt/uv", "export", "--directory", str(root / "tree"))
    assert {"--locked", "--offline", "--no-dev", "--no-emit-workspace"} <= set(command)
    assert [command[i + 1] for i, item in enumerate(command) if item == "--package"] == list(
        support.WORKSPACE_PACKAGES
    )
    assert digest == hashlib.sha256(_LOCKED).hexdigest()
    assert (root / support.REQUIREMENTS_NAME).read_bytes() == _LOCKED
    assert (
        support.export_runtime_requirements(root / "tree", root / support.REQUIREMENTS_NAME)
        == digest
    )


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"alembic==1.16.5\n",
        b"-e ./services/core-control-plane\n    --hash=sha256:" + b"a" * 64 + b"\n",
        b"pkg @ https://example.invalid/pkg.whl \\\n    --hash=sha256:" + b"a" * 64 + b"\n",
        b"./packages/service-contracts \\\n    --hash=sha256:" + b"a" * 64 + b"\n",
    ],
)
def test_export_rejects_unhashed_or_non_index_requirements(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: bytes
) -> None:
    root = _private(tmp_path)
    monkeypatch.setenv("UV", "/opt/uv")
    monkeypatch.setattr(
        support.subprocess,
        "run",
        lambda *_a, **_k: SimpleNamespace(returncode=0, stdout=content, stderr=b""),
    )
    with pytest.raises(ValueError):
        support.export_runtime_requirements(root, root / support.REQUIREMENTS_NAME)
    assert not (root / support.REQUIREMENTS_NAME).exists()


def test_install_uses_hashed_binary_lock_then_snapshot_packages_without_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _private(tmp_path)
    work = root / "work"
    work.mkdir(mode=0o700)
    source = _source_tree(root / "tree")
    requirements, digest = _requirements(root)
    host = FakeHost(_installed())
    monkeypatch.setattr(support.subprocess, "run", host)

    support.install_source_runtime_support(
        work,
        source_root=source,
        requirements=requirements,
        requirements_digest=digest,
        snapshot_digest="d" * 64,
    )

    pip = str(work / "runtime-venv/bin/pip")
    locked = next(call for call in host.calls if "--requirement" in call)
    assert locked[:2] == (pip, "install")
    assert {"--require-hashes", "--only-binary", ":all:"} <= set(locked)
    local = next(call for call in host.calls if "--no-deps" in call)
    assert local[-len(support.WORKSPACE_PACKAGES) :] == tuple(
        str(source / path) for path in support.WORKSPACE_PACKAGES.values()
    )
    receipt = json.loads((work / "runtime-support-installation.json").read_text())
    assert receipt["requirements_digest"] == digest
    assert receipt["snapshot_digest"] == "d" * 64

    host.calls.clear()
    support.install_source_runtime_support(
        work,
        source_root=source,
        requirements=requirements,
        requirements_digest=digest,
        snapshot_digest="d" * 64,
    )
    assert not any("install" in call for call in host.calls)


def test_install_rebuilds_a_partial_or_stale_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _private(tmp_path)
    work = root / "work"
    (work / "runtime-venv/bin").mkdir(parents=True)
    work.chmod(0o700)
    source = _source_tree(root / "tree")
    requirements, digest = _requirements(root)
    host = FakeHost(_installed())
    monkeypatch.setattr(support.subprocess, "run", host)

    support.install_source_runtime_support(
        work,
        source_root=source,
        requirements=requirements,
        requirements_digest=digest,
        snapshot_digest="d" * 64,
    )

    assert any(call[1:3] == ("-m", "venv") for call in host.calls)
    assert (work / "runtime-support-installation.json").exists()


def test_install_refuses_a_changed_transfer_or_mismatched_snapshot_packages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _private(tmp_path)
    work = root / "work"
    work.mkdir(mode=0o700)
    source = _source_tree(root / "tree")
    requirements, digest = _requirements(root)
    monkeypatch.setattr(support.subprocess, "run", FakeHost(_installed()))
    with pytest.raises(ValueError, match="differ from the transferred digest"):
        support.install_source_runtime_support(
            work,
            source_root=source,
            requirements=requirements,
            requirements_digest="f" * 64,
            snapshot_digest="d" * 64,
        )

    monkeypatch.setattr(
        support.subprocess, "run", FakeHost(_installed({"fdai-core-control-plane": "9.9.9"}))
    )
    with pytest.raises(ValueError, match="differ from the snapshot"):
        support.install_source_runtime_support(
            work,
            source_root=source,
            requirements=requirements,
            requirements_digest=digest,
            snapshot_digest="d" * 64,
        )
    assert not (work / "runtime-support-installation.json").exists()


def test_install_reports_the_failed_step_without_writing_a_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _private(tmp_path)
    work = root / "work"
    work.mkdir(mode=0o700)
    source = _source_tree(root / "tree")
    requirements, digest = _requirements(root)
    host = FakeHost(_installed())
    host.fail = "--require-hashes"
    monkeypatch.setattr(support.subprocess, "run", host)

    with pytest.raises(ValueError, match="locked dependency installation failed"):
        support.install_source_runtime_support(
            work,
            source_root=source,
            requirements=requirements,
            requirements_digest=digest,
            snapshot_digest="d" * 64,
        )
    assert not (work / "runtime-support-installation.json").exists()


def test_export_reports_an_unavailable_uv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _private(tmp_path)
    monkeypatch.delenv("UV", raising=False)
    monkeypatch.setattr(support.shutil, "which", lambda _name: None)
    with pytest.raises(ValueError, match="requires uv"):
        support.export_runtime_requirements(root, root / support.REQUIREMENTS_NAME)

    def fail(*_args: object, **_kwargs: object) -> None:
        raise subprocess.TimeoutExpired("uv", 120)

    monkeypatch.setenv("UV", "/opt/uv")
    monkeypatch.setattr(support.subprocess, "run", fail)
    with pytest.raises(ValueError, match="export failed"):
        support.export_runtime_requirements(root, root / support.REQUIREMENTS_NAME)
