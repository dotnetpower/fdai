"""Opt-in real packaged-image smoke tests; never start or stop a shared server."""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest

DOCKER = shutil.which("docker")


def command_timeout(native: int) -> int:
    return native * (4 if os.environ.get("FDAI_TEST_HUB_EMULATION") == "1" else 1)


@pytest.mark.parametrize(("emulation", "expected"), [(None, 15), ("0", 15), ("1", 60)])
def test_command_timeout_preserves_native_budget(monkeypatch, emulation, expected):
    if emulation is None:
        monkeypatch.delenv("FDAI_TEST_HUB_EMULATION", raising=False)
    else:
        monkeypatch.setenv("FDAI_TEST_HUB_EMULATION", emulation)
    assert command_timeout(15) == expected


def test_independent_image_build_inputs():
    root = Path(__file__).resolve().parents[3]
    dockerfile = (root / "lifecycle/Dockerfile.hubs").read_text()
    lifecycle_ui = dockerfile.split("FROM ui-base AS lifecycle-ui\n")[1].split("\nFROM ")[0]
    release_ui = dockerfile.split("FROM ui-base AS release-ui\n")[1].split("\nFROM ")[0]
    assert "release-hub" not in lifecycle_ui
    assert "npm --prefix lifecycle/hub/ui" not in release_ui
    assert "lifecycle/hub/ui/src/auth.css" in release_ui
    assert "lifecycle/hub/ui/tsconfig.json" in release_ui
    assert "lifecycle/hub/ui/public" in release_ui
    assert "FROM --platform=$BUILDPLATFORM ${NODE_IMAGE} AS ui-base" in dockerfile
    for name in ("NODE_IMAGE", "PYTHON_IMAGE", "UV_IMAGE"):
        assert f"ARG {name}\n" in dockerfile
    ignore = (root / "lifecycle/Dockerfile.hubs.dockerignore").read_text()
    assert "!lifecycle/hub/uv.lock\n" in ignore
    assert "!lifecycle/release-hub/uv.lock\n" in ignore
    target = dockerfile.split("FROM base AS target\n")[1].split("\nFROM ")[0]
    assert "--from=lifecycle-ui" in target and "--from=release" not in target
    release_wheels = dockerfile.split("FROM wheels AS release-wheels\n")[1].split("\nFROM ")[0]
    assert "uv export --project lifecycle/release-hub --frozen" in release_wheels
    assert "--require-hashes -r /release-requirements.txt" in release_wheels


def docker(*arguments: str, timeout: int = 30) -> str:
    if DOCKER is None:
        pytest.fail("Docker is required for the explicitly selected packaged-image checks.")
    result = subprocess.run(  # noqa: S603 - Explicit test image and task-owned Docker resources.
        [DOCKER, *arguments],
        capture_output=True,
        text=True,
        timeout=command_timeout(timeout),
        check=False,
    )
    if result.returncode:
        pytest.fail(
            f"Task-owned Docker command failed: {arguments[0]}; inspect local Docker diagnostics."
        )
    return result.stdout.strip()


@pytest.mark.parametrize("kind", ["release", "target"])
def test_packaged_remote_entrypoint_refuses_unconfigured_startup(kind):
    image = os.environ.get(f"FDAI_TEST_{kind.upper()}_HUB_IMAGE")
    if not image:
        pytest.skip("Set explicit task-built Hub image references to run packaged-image checks.")
    if DOCKER is None:
        pytest.fail("Docker is required for explicitly selected image checks.")
    name = f"hub-unconfigured-{kind}-{secrets.token_hex(4)}"
    try:
        result = subprocess.run(  # noqa: S603 - Explicit task-built image, no shared ports or secrets.
            [DOCKER, "run", "--rm", "--name", name, "--network", "none", image],
            capture_output=True,
            text=True,
            timeout=command_timeout(15),
            check=False,
        )
    finally:
        if docker("container", "ls", "-aq", "--filter", f"name=^{name}$"):
            docker("rm", "-f", name, timeout=15)
    assert result.returncode != 0
    assert "Remote Hub startup rejected" in result.stderr
    assert "Traceback" not in result.stderr
    assert docker("image", "inspect", "-f", "{{.Config.User}}", image) == "10001:10001"


@pytest.mark.parametrize("kind", ["release", "target"])
def test_packaged_ui_api_and_restart_without_shared_ports(kind):
    image = os.environ.get(f"FDAI_TEST_{kind.upper()}_HUB_IMAGE")
    if not image:
        pytest.skip("Set explicit task-built Hub image references to run packaged-image checks.")
    suffix = secrets.token_hex(4)
    name, volume = f"hub-smoke-{kind}-{suffix}", f"hub-smoke-state-{kind}-{suffix}"
    docker("volume", "create", volume)
    port = 8080
    origin = f"http://127.0.0.1:{port}"
    entry = "fdai-release-hub" if kind == "release" else "fdai-lifecycle-hub"
    environment = (
        []
        if kind == "release"
        else [
            "-e",
            "FDAI_LIFECYCLE_HUB_DATABASE_URL=sqlite:////state/hub.db",
        ]
    )

    def run_once(*arguments):
        return docker(
            "run",
            "--rm",
            "--name",
            f"{name}-init",
            "-v",
            f"{volume}:/state",
            *environment,
            "--entrypoint",
            entry,
            image,
            *arguments,
        )

    def request(method, path, *, body=None, headers=None):
        raw = docker(
            "exec",
            name,
            "python",
            "-c",
            "import httpx,json,sys; "
            "r=httpx.request(sys.argv[1],sys.argv[2],json=json.loads(sys.argv[3]),"
            "headers=json.loads(sys.argv[4]),timeout=2,trust_env=False); "
            "print(json.dumps({'status':r.status_code,'body':r.text}))",
            method,
            origin + path,
            json.dumps(body),
            json.dumps(headers),
        )
        result = json.loads(raw)
        return httpx.Response(result["status"], text=result["body"])

    def start():
        arguments = ["serve", "/state"] if kind == "release" else ["serve"]
        docker(
            "run",
            "-d",
            "--name",
            name,
            "--network",
            "none",
            "-v",
            f"{volume}:/state",
            *environment,
            "--entrypoint",
            entry,
            image,
            *arguments,
            "--port",
            str(port),
            "--ui",
            "/app/ui",
        )
        docker(
            "exec",
            name,
            "python",
            "-c",
            """
import httpx, sys, time
deadline = time.monotonic() + int(sys.argv[1])
while time.monotonic() < deadline:
    try:
        response = httpx.get("http://127.0.0.1:8080/healthz", timeout=1, trust_env=False)
        if response.status_code == 200:
            break
    except httpx.TransportError:
        pass
    time.sleep(0.1)
else:
    raise SystemExit("Task-owned Hub did not become ready within its explicit startup budget.")
""",
            str(command_timeout(10)),
            timeout=15,
        )

    try:
        run_once("dev-init", "/state") if kind == "release" else run_once("migrate")
        start()

        def check():
            page = request("GET", "/")
            assert page.status_code == 200 and 'id="app"' in page.text
            assets = re.findall(r'(?:src|href)="(/assets/[^"]+)"', page.text)
            assert assets
            for asset in assets:
                response = request("GET", asset)
                assert response.status_code == 200
                assert "-----BEGIN PRIVATE KEY-----" not in response.text
            assert request("GET", "/auth/config").json()["profile"] == "local-development"
            if kind == "release":
                for revision, action in enumerate(("register", "publish")):
                    body = {
                        "revision": revision,
                        "confirmation": "1.6.0",
                        "reason": "Synthetic packaged-image validation",
                    }
                    if action == "register":
                        body["manifest"] = (
                            Path(__file__).resolve().parents[1]
                            / "samples/catalog/releases/1.6.0.json"
                        ).read_text()
                    assert (
                        request("POST", f"/v1/releases/1.6.0/{action}", body=body).status_code
                        == 200
                    )
                assert request("GET", "/v1/catalog").json()["revision"] == 2
                assert (
                    request(
                        "POST",
                        "/v1/releases/1.6.0/recall",
                        body={
                            "revision": 2,
                            "confirmation": "1.6.0",
                            "reason": "Synthetic recall",
                        },
                        headers={"Origin": "https://untrusted.example.com"},
                    ).status_code
                    == 403
                )
            else:
                assert request("GET", "/v1/installations").json() == {"installations": []}
            assert request("GET", "/v1/not-a-route").status_code == 404

        check()
        docker("stop", "-t", "2", name)
        docker("rm", name)
        start()
        if kind == "release":
            snapshot = request("GET", "/v1/catalog").json()
            assert snapshot["revision"] == 2 and snapshot["releases"][0]["state"] == "published"
        else:
            assert request("GET", "/v1/installations").status_code == 200
        assert docker("inspect", "-f", "{{.State.Running}}", name) == "true"
        print(f"{kind}: packaged UI/assets/API/restart passed on task-owned loopback port")
    finally:
        for container in (f"{name}-init", name):
            if docker("container", "ls", "-aq", "--filter", f"name=^{container}$"):
                docker("rm", "-f", container, timeout=15)
        docker("volume", "rm", volume)


def test_unconfigured_timeout_cleans_task_container(monkeypatch):
    calls = []
    monkeypatch.setenv("FDAI_TEST_TARGET_HUB_IMAGE", "synthetic-image")
    monkeypatch.setattr(__name__ + ".DOCKER", "docker")

    def timed_out(command, **kwargs):
        calls.append(command)
        raise subprocess.TimeoutExpired(command, 15)

    def fake_docker(*arguments, **kwargs):
        calls.append(arguments)
        return "synthetic-container" if arguments[0] == "container" else ""

    monkeypatch.setattr(subprocess, "run", timed_out)
    monkeypatch.setattr(__name__ + ".docker", fake_docker)
    with pytest.raises(subprocess.TimeoutExpired):
        test_packaged_remote_entrypoint_refuses_unconfigured_startup("target")
    command = calls[0]
    name = command[command.index("--name") + 1]
    assert calls[-1] == ("rm", "-f", name)


def test_migration_timeout_cleans_job_before_volume(monkeypatch):
    calls = []
    monkeypatch.setenv("FDAI_TEST_TARGET_HUB_IMAGE", "synthetic-image")

    def fake_docker(*arguments, **kwargs):
        calls.append(arguments)
        if arguments[0] == "run":
            raise subprocess.TimeoutExpired(arguments, 30)
        return "synthetic-container" if arguments[0] == "container" else ""

    monkeypatch.setattr(__name__ + ".docker", fake_docker)
    with pytest.raises(subprocess.TimeoutExpired):
        test_packaged_ui_api_and_restart_without_shared_ports("target")
    job = calls[1][calls[1].index("--name") + 1]
    assert ("rm", "-f", job) in calls
    assert calls.index(("rm", "-f", job)) < len(calls) - 1
    assert calls[-1][0:2] == ("volume", "rm")
