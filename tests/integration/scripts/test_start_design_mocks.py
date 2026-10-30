from __future__ import annotations

import os
import selectors
import shutil
import socket
import subprocess
import time
from pathlib import Path
from urllib.request import urlopen

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
_BASH = shutil.which("bash") or "/bin/bash"


def test_design_mocks_launcher_uses_the_managed_singleton_runner() -> None:
    launcher = (REPO_ROOT / "scripts/deployment/local/start-design-mocks.sh").read_text(
        encoding="utf-8"
    )

    assert "run-local-service.sh" in launcher
    assert "http.server 5373 --bind 127.0.0.1" in launcher


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    root = tmp_path / "checkout with spaces"
    for relative in (
        "scripts/deployment/local/start-design-mocks.sh",
        "scripts/automation/run-local-service.sh",
        "scripts/automation/run-local-service-child.py",
        "scripts/automation/capture-local-service-log.py",
    ):
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / relative, destination)
    (root / "probe.txt").write_text("design-mocks-checkout", encoding="utf-8")
    return root


def _set_port(checkout: Path, port: int) -> Path:
    launcher = checkout / "scripts/deployment/local/start-design-mocks.sh"
    launcher.write_text(
        launcher.read_text(encoding="utf-8").replace("5373", str(port)), encoding="utf-8"
    )
    return launcher


def _wait_for_server(process: subprocess.Popen[bytes]) -> None:
    assert process.stdout is not None
    output = b""
    deadline = time.monotonic() + 5
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        while time.monotonic() < deadline:
            if not selector.select(timeout=max(0, deadline - time.monotonic())):
                break
            chunk = os.read(process.stdout.fileno(), 4096)
            if not chunk:
                break
            output += chunk
            if b"Serving HTTP on 127.0.0.1 port" in output:
                return
    raise AssertionError(f"Design mock server did not become ready: {output!r}")


@pytest.fixture
def running_server(checkout: Path):
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    launcher = _set_port(checkout, port)
    process = subprocess.Popen(  # noqa: S603
        [_BASH, str(launcher)],
        cwd=checkout.parent,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        _wait_for_server(process)
        yield process, port
    finally:
        if process.poll() is None:
            process.terminate()
        process.communicate(timeout=5)


@pytest.mark.parametrize("relative_command", [False, True])
def test_repeated_start_reuses_the_same_checkout_server(
    checkout: Path, running_server, relative_command: bool
) -> None:
    owner, port = running_server
    command = "scripts/deployment/local/start-design-mocks.sh"
    if not relative_command:
        command = str(checkout / command)
    result = subprocess.run(  # noqa: S603
        [_BASH, command], cwd=checkout, capture_output=True, text=True, timeout=5
    )

    assert result.returncode == 0, result.stderr
    assert "service=design-mocks event=reused" in result.stdout
    assert "Serving HTTP" not in result.stdout
    assert owner.poll() is None
    with urlopen(f"http://127.0.0.1:{port}/probe.txt", timeout=1) as response:
        assert response.read() == b"design-mocks-checkout"


def test_unmanaged_port_owner_is_not_replaced(checkout: Path) -> None:
    with socket.socket() as owner:
        owner.bind(("127.0.0.1", 0))
        owner.listen()
        port = owner.getsockname()[1]
        launcher = _set_port(checkout, port)
        result = subprocess.run(  # noqa: S603
            [_BASH, str(launcher)], capture_output=True, text=True, timeout=5
        )

        assert result.returncode == 75
        assert f"service already running: design-mocks (port=127.0.0.1:{port})" in (result.stderr)
        assert "Traceback" not in result.stdout + result.stderr
        assert owner.getsockname() == ("127.0.0.1", port)


def test_changed_launcher_requires_restart_without_stopping_owner(
    checkout: Path, running_server
) -> None:
    owner, _ = running_server
    launcher = checkout / "scripts/deployment/local/start-design-mocks.sh"
    launcher.write_text(launcher.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    result = subprocess.run(  # noqa: S603
        [_BASH, str(launcher)], capture_output=True, text=True, timeout=5
    )

    assert result.returncode == 75
    assert "service restart required: design-mocks (launch inputs changed)" in result.stderr
    assert owner.poll() is None


def test_stopping_the_launcher_releases_the_server(running_server) -> None:
    owner, port = running_server
    owner.terminate()
    owner.communicate(timeout=5)

    with socket.socket() as probe:
        probe.settimeout(1)
        assert probe.connect_ex(("127.0.0.1", port)) != 0
