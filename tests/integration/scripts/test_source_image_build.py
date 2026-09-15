"""Source image preparation observes local tooling without granting deployment authority."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/deployment/azure"))

import source_image_build as images  # noqa: E402

sys.path.insert(0, str(ROOT / "packages/deployment-cli/tests"))
from test_oci_archive import COMMIT, make_archive  # noqa: E402


@pytest.mark.parametrize(
    "failure", [None, "packaged", "missing", "engine", "buildx", "output", "timeout"]
)
def test_source_builder_probe_is_local_bounded_and_fail_closed(monkeypatch, failure):
    calls = []

    def tool(name):
        assert name == "docker"
        if failure == "missing":
            raise images.CheckError("required_tool_unavailable")
        return "/usr/bin/docker"

    def run(command, **kwargs):
        calls.append(command)
        assert command[:3] == ("/usr/bin/docker", "--host", "unix:///var/run/docker.sock")
        assert 0 < kwargs["timeout"] <= 10
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert not any(key.startswith(("DOCKER_", "BUILDX_", "BUILDKIT_")) for key in kwargs["env"])
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 10)
        if failure == "output":
            return subprocess.CompletedProcess(command, 0, "invalid", "")
        output = "29.1.3\n" if len(calls) == 1 else "github.com/docker/buildx v0.30.1 example\n"
        if failure == "packaged" and len(calls) == 2:
            output = "github.com/docker/buildx 0.30.1 0.30.1-0ubuntu1~22.04.1\n"
        status = int(
            (failure == "engine" and len(calls) == 1) or (failure == "buildx" and len(calls) == 2)
        )
        return subprocess.CompletedProcess(command, status, output, "")

    monkeypatch.setenv("DOCKER_CONTEXT", "unselected-context")
    monkeypatch.setenv("BUILDKIT_HOST", "unselected-builder")
    monkeypatch.setattr(images, "trusted_tool", tool)
    monkeypatch.setattr(images.subprocess, "run", run)
    receipt = images.inspect_source_image_builder(timeout_seconds=10)
    assert receipt["state"] == ("available" if failure in {None, "packaged"} else "blocked")
    assert receipt["mutation_performed"] is False
    assert receipt["deployment_ready"] is False
    assert all("build" not in command for command in calls)


@pytest.mark.parametrize("failure", [None, "build", "revision", "digest"])
def test_source_image_build_validates_oci_and_never_repeats_claim(tmp_path, monkeypatch, failure):
    snapshot = tmp_path / "snapshot"
    tree = snapshot / "tree"
    dockerfile = tree / "services/operator-service/docker/Dockerfile"
    dockerfile.parent.mkdir(parents=True)
    dockerfile.write_text("FROM scratch\n")
    supervisor = tree / "scripts/automation/run-bounded-command.py"
    supervisor.parent.mkdir(parents=True)
    supervisor.write_text("unused test process\n")
    work = tmp_path / "images"
    monkeypatch.setattr(
        images, "verify_source_snapshot", lambda *_args, **_kwargs: {"source_commit": COMMIT}
    )
    monkeypatch.setattr(
        images, "inspect_source_image_builder", lambda **_kwargs: {"state": "available"}
    )
    monkeypatch.setattr(images, "trusted_tool", lambda *_args: "/usr/bin/docker")
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        assert "--push" not in command
        assert command[command.index("--builder") + 1] == "default"
        assert command[command.index("--host") + 1] == "unix:///var/run/docker.sock"
        assert command[-1] == str(tree)
        assert (work / "operator-service.claim.json").exists()
        if failure == "build":
            return subprocess.CompletedProcess(command, 124)
        archive = work / "operator-service.oci.tar"
        fixture = make_archive(
            archive,
            config_updates={"config": {"Labels": {"org.opencontainers.image.revision": "b" * 40}}}
            if failure == "revision"
            else None,
        )
        archive.chmod(0o600)
        metadata = work / "operator-service.metadata.json"
        metadata.write_text(
            json.dumps(
                {
                    "containerimage.digest": "sha256:" + "c" * 64
                    if failure == "digest"
                    else fixture.manifest_digest
                }
            )
        )
        metadata.chmod(0o600)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(images.subprocess, "run", run)
    arguments = dict(snapshot_digest="d" * 64, service="operator-service", timeout_seconds=3600)
    if failure:
        with pytest.raises(ValueError):
            images.build_source_image(snapshot, work, **arguments)
        assert not (work / "operator-service.receipt.json").exists()
        with pytest.raises(ValueError, match="incomplete"):
            images.build_source_image(snapshot, work, **arguments)
    else:
        receipt = images.build_source_image(snapshot, work, **arguments)
        assert receipt["state"] == "built"
        assert receipt["registry_published"] is False
        assert receipt["deployment_ready"] is False
        assert images.build_source_image(snapshot, work, **arguments) == receipt
        (work / "operator-service.oci.tar").write_bytes(b"changed")
        with pytest.raises(ValueError):
            images.build_source_image(snapshot, work, **arguments)
    assert len(calls) == 1


@pytest.mark.parametrize("blocked", [False, True])
def test_source_image_inventory_requires_every_baseline_service(tmp_path, monkeypatch, blocked):
    calls = []
    monkeypatch.setattr(
        images, "verify_source_snapshot", lambda *_args, **_kwargs: {"source_commit": COMMIT}
    )

    def build(*_args, **kwargs):
        calls.append(kwargs["service"])
        assert 0 < kwargs["timeout_seconds"] <= 3600
        return {"state": "blocked" if blocked else "built"}

    monkeypatch.setattr(images, "build_source_image", build)
    receipt = images.build_source_images(
        tmp_path / "snapshot", tmp_path / "images", snapshot_digest="d" * 64, timeout_seconds=3600
    )
    if blocked:
        assert receipt["state"] == "blocked"
        assert len(calls) == 1
    else:
        assert set(receipt["services"]) == images.RUNTIME_SERVICES
        assert set(calls) == images.RUNTIME_SERVICES
        assert receipt["registry_published"] is False
        assert receipt["dependency_images_verified"] is False


@pytest.mark.parametrize("invalid", ["inside-snapshot", "output-option", "service", "relative"])
def test_source_image_rejects_unsafe_build_selection_before_effects(tmp_path, monkeypatch, invalid):
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    work = {
        "inside-snapshot": snapshot / "generated",
        "output-option": tmp_path / "image,push=true",
        "relative": Path("relative-output"),
    }.get(invalid, tmp_path / "images")
    monkeypatch.setattr(
        images, "verify_source_snapshot", lambda *_args, **_kwargs: {"source_commit": COMMIT}
    )
    monkeypatch.setattr(
        images.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("invalid selection executed a command"),
    )
    with pytest.raises(ValueError):
        images.build_source_image(
            snapshot,
            work,
            snapshot_digest="d" * 64,
            service="unknown" if invalid == "service" else "operator-service",
            timeout_seconds=30,
        )
    assert not work.exists()
