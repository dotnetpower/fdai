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


def docker(*arguments: str, timeout: int = 30) -> str:
    if DOCKER is None:
        pytest.fail("Docker is required for the explicitly selected packaged-image checks.")
    result = subprocess.run(  # noqa: S603 - Explicit test image and task-owned Docker resources.
        [DOCKER, *arguments],
        capture_output=True,
        text=True,
        timeout=timeout,
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
    result = subprocess.run(  # noqa: S603 - Explicit task-built image, no shared ports or secrets.
        [DOCKER, "run", "--rm", "--network", "none", image],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
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
import httpx, time
deadline = time.monotonic() + 10
while time.monotonic() < deadline:
    try:
        response = httpx.get("http://127.0.0.1:8080/healthz", timeout=1, trust_env=False)
        if response.status_code == 200:
            break
    except httpx.TransportError:
        pass
    time.sleep(0.1)
else:
    raise SystemExit("Task-owned Hub did not become ready within ten seconds.")
""",
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
        if docker("container", "ls", "-aq", "--filter", f"name=^{name}$"):
            docker("rm", "-f", name, timeout=15)
        docker("volume", "rm", volume)
