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


def _wheel_name(name: str, version: str = "0.1.0") -> str:
    return f"{name.replace('-', '_')}-{version}-py3-none-any.whl"


def _archive(
    directory: Path,
    *,
    versions: dict[str, str] | None = None,
    extra: dict[str, bytes] | None = None,
) -> tuple[Path, str]:
    members: dict[str, bytes] = {"requirements.txt": _LOCKED}
    pins = []
    for name in support.WORKSPACE_PACKAGES:
        version = (versions or {}).get(name, "0.1.0")
        content = f"wheel {name}".encode()
        members[f"wheels/{_wheel_name(name, version)}"] = content
        pins.append(f"{name}=={version} --hash=sha256:{hashlib.sha256(content).hexdigest()}")
    members["workspace.txt"] = ("\n".join(pins) + "\n").encode()
    members.update(extra or {})
    content = support._deterministic_tar(members)
    path = directory / support.INPUT_NAME
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


class FakeUv:
    def __init__(self, export: bytes = _LOCKED) -> None:
        self.export = export
        self.calls: list[tuple[tuple[str, ...], Path | None]] = []

    def __call__(self, command: tuple[str, ...], **kwargs: object) -> SimpleNamespace:
        cwd = kwargs.get("cwd")
        self.calls.append((tuple(command), Path(str(cwd)) if cwd is not None else None))
        if command[1] == "export":
            return SimpleNamespace(returncode=0, stdout=self.export, stderr=b"")
        name = command[command.index("--package") + 1]
        out = Path(command[command.index("--out-dir") + 1])
        (out / _wheel_name(name)).write_bytes(f"wheel {name}".encode())
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")


def test_prepare_bundles_locked_requirements_and_hashed_workspace_wheels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _private(tmp_path)
    source = _source_tree(root / "tree")
    prepared = root / "prepared"
    prepared.mkdir(mode=0o700)
    uv = FakeUv()
    monkeypatch.setenv("UV", "/opt/uv")
    monkeypatch.setattr(support.subprocess, "run", uv)

    digest = support.prepare_runtime_support_input(source, prepared)

    archive = prepared / support.INPUT_NAME
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == digest
    members = support._read_input(archive, digest)
    assert members["requirements.txt"] == _LOCKED
    assert sorted(name for name in members if name.startswith("wheels/")) == sorted(
        f"wheels/{_wheel_name(name)}" for name in support.WORKSPACE_PACKAGES
    )
    export = uv.calls[0][0]
    assert {"--locked", "--offline", "--no-dev", "--no-emit-workspace"} <= set(export)
    builds = [call for call in uv.calls if call[0][1] == "build"]
    assert [call[0][call[0].index("--package") + 1] for call in builds] == list(
        support.WORKSPACE_PACKAGES
    )
    # Wheels build from a private copy; the verified snapshot is never the build directory.
    assert all(cwd is not None and cwd != source for _command, cwd in builds)
    assert support.prepare_runtime_support_input(source, prepared) == digest
    assert not any(path.name.startswith(".runtime-support-") for path in prepared.iterdir())


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"alembic==1.16.5\n",
        b"-e ./services/core-control-plane\n    --hash=sha256:" + b"a" * 64 + b"\n",
        b"pkg @ https://example.invalid/pkg.whl \\\n    --hash=sha256:" + b"a" * 64 + b"\n",
    ],
)
def test_prepare_rejects_unhashed_or_non_index_requirements(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: bytes
) -> None:
    root = _private(tmp_path)
    source = _source_tree(root / "tree")
    monkeypatch.setenv("UV", "/opt/uv")
    monkeypatch.setattr(support.subprocess, "run", FakeUv(content))
    with pytest.raises(ValueError):
        support.prepare_runtime_support_input(source, root)
    assert not (root / support.INPUT_NAME).exists()


def test_install_uses_hashes_only_and_never_builds_or_indexes_workspace_packages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _private(tmp_path)
    work = root / "work"
    work.mkdir(mode=0o700)
    source = _source_tree(root / "tree")
    archive, digest = _archive(root)
    host = FakeHost(_installed())
    monkeypatch.setattr(support.subprocess, "run", host)

    support.install_source_runtime_support(
        work, source_root=source, archive=archive, archive_digest=digest, snapshot_digest="d" * 64
    )

    pip = str(work / "runtime-venv/bin/pip")
    installs = [call for call in host.calls if call[:2] == (pip, "install")]
    assert len(installs) == 2
    locked, workspace = installs
    assert {"--require-hashes", "--only-binary", ":all:"} <= set(locked)
    assert {"--require-hashes", "--no-index", "--no-deps", "--only-binary"} <= set(workspace)
    assert workspace[workspace.index("--find-links") + 1] == str(
        work / "runtime-support-input/wheels"
    )
    assert not any(str(source) in item for call in host.calls for item in call)
    receipt = json.loads((work / "runtime-support-installation.json").read_text())
    assert receipt["input_digest"] == digest

    host.calls.clear()
    support.install_source_runtime_support(
        work, source_root=source, archive=archive, archive_digest=digest, snapshot_digest="d" * 64
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
    archive, digest = _archive(root)
    host = FakeHost(_installed())
    monkeypatch.setattr(support.subprocess, "run", host)

    support.install_source_runtime_support(
        work, source_root=source, archive=archive, archive_digest=digest, snapshot_digest="d" * 64
    )

    assert any(call[1:3] == ("-m", "venv") for call in host.calls)
    assert (work / "runtime-support-installation.json").exists()


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("digest", "differs from the transferred digest"),
        ("version", "pins differ from the snapshot"),
        ("member", "member is invalid"),
        ("installed", "differ from the snapshot"),
    ],
)
def test_install_refuses_changed_or_mismatched_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str, message: str
) -> None:
    root = _private(tmp_path)
    work = root / "work"
    work.mkdir(mode=0o700)
    source = _source_tree(root / "tree")
    archive, digest = _archive(
        root,
        versions={"fdai-core-control-plane": "9.9.9"} if case == "version" else None,
        extra={"../escape.txt": b"x"} if case == "member" else None,
    )
    installed = _installed({"fdai-core-control-plane": "9.9.9"} if case == "installed" else None)
    monkeypatch.setattr(support.subprocess, "run", FakeHost(installed))
    with pytest.raises(ValueError, match=message):
        support.install_source_runtime_support(
            work,
            source_root=source,
            archive=archive,
            archive_digest="f" * 64 if case == "digest" else digest,
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
    archive, digest = _archive(root)
    host = FakeHost(_installed())
    host.fail = "--no-index"
    monkeypatch.setattr(support.subprocess, "run", host)

    with pytest.raises(ValueError, match="workspace package installation failed"):
        support.install_source_runtime_support(
            work,
            source_root=source,
            archive=archive,
            archive_digest=digest,
            snapshot_digest="d" * 64,
        )
    assert not (work / "runtime-support-installation.json").exists()


def test_prepare_reports_an_unavailable_uv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _private(tmp_path)
    monkeypatch.delenv("UV", raising=False)
    monkeypatch.setattr(support.shutil, "which", lambda _name: None)
    with pytest.raises(ValueError, match="requires uv"):
        support.prepare_runtime_support_input(root, root)

    def fail(*_args: object, **_kwargs: object) -> None:
        raise subprocess.TimeoutExpired("uv", 120)

    source = _source_tree(root / "tree")
    monkeypatch.setenv("UV", "/opt/uv")
    monkeypatch.setattr(support.subprocess, "run", fail)
    with pytest.raises(ValueError, match="export failed"):
        support.prepare_runtime_support_input(source, root)
