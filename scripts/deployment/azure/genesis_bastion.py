#!/usr/bin/env python3
"""Provide a bounded host-key-checked SSH transport through Azure Bastion."""

from __future__ import annotations

import os
import signal
import socket
import stat
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from types import TracebackType

from genesis_subprocess import run_with_heartbeat

_TUNNEL_START_SECONDS = 120
_TUNNEL_STOP_SECONDS = 5


class BastionTunnel:
    """Own one local Azure Bastion tunnel and its bounded SSH/SCP clients."""

    def __init__(
        self,
        *,
        subscription_id: str,
        resource_group: str,
        bastion_name: str,
        vm_id: str,
        username: str,
        private_key: Path,
        known_hosts: Path,
        host_key_alias: str,
        cwd: Path,
        timeout: int,
        trust_new_host_key: bool,
    ) -> None:
        self.subscription_id = subscription_id
        self.resource_group = resource_group
        self.bastion_name = bastion_name
        self.vm_id = vm_id
        self.username = username
        self.private_key = private_key
        self.known_hosts = known_hosts
        self.host_key_alias = host_key_alias
        self.cwd = cwd
        self.timeout = timeout
        self.trust_new_host_key = trust_new_host_key
        self.port = 0
        self._process: subprocess.Popen[bytes] | None = None

    def __enter__(self) -> BastionTunnel:
        """Start the tunnel and wait for its loopback listener without probing the VM."""

        self.port = _reserve_port()
        command = (
            "az",
            "network",
            "bastion",
            "tunnel",
            "--subscription",
            self.subscription_id,
            "--resource-group",
            self.resource_group,
            "--name",
            self.bastion_name,
            "--target-resource-id",
            self.vm_id,
            "--resource-port",
            "22",
            "--port",
            str(self.port),
            "--timeout",
            str(self.timeout),
            "--only-show-errors",
        )
        self._process = subprocess.Popen(  # noqa: S603 - fixed Azure CLI command
            command,
            cwd=self.cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            umask=0o077,
        )
        deadline = time.monotonic() + min(_TUNNEL_START_SECONDS, self.timeout)
        next_heartbeat = time.monotonic() + 10
        try:
            while time.monotonic() < deadline:
                if self._process.poll() is not None:
                    raise RuntimeError("Azure Bastion tunnel stopped before becoming ready")
                try:
                    with socket.create_connection(("127.0.0.1", self.port), timeout=0.2):
                        return self
                except OSError:
                    now = time.monotonic()
                    if now >= next_heartbeat:
                        print(".", end="", file=sys.stderr, flush=True)
                        next_heartbeat = now + 10
                    time.sleep(0.2)
        except BaseException:
            self._stop()
            raise
        self._stop()
        raise TimeoutError("Azure Bastion tunnel readiness timed out")

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Stop the complete Azure CLI process group and wait for bounded cleanup."""

        del exc_type, exc_value, traceback
        self._stop()

    def _stop(self) -> None:
        process = self._process
        self._process = None
        if process is None or process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=_TUNNEL_STOP_SECONDS)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=_TUNNEL_STOP_SECONDS)
        except ProcessLookupError:
            return

    def ssh(
        self,
        remote_arguments: Sequence[str],
        *,
        timeout: int,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Run one fixed remote command with no pseudo-terminal or shell expansion locally."""

        if not remote_arguments or any(not item or "\n" in item for item in remote_arguments):
            raise ValueError("Bastion remote command arguments are invalid")
        return run_with_heartbeat(
            (*self._ssh_prefix(), f"{self.username}@127.0.0.1", *remote_arguments),
            cwd=self.cwd,
            timeout=timeout,
            capture_output=True,
            umask=0o077,
            input_text=input_text,
        )

    def copy_to(self, source: Path, destination: str, *, timeout: int) -> None:
        """Copy one private regular file to the runner over the held tunnel."""

        _require_private_regular_file(source, max_bytes=8 * 1024 * 1024 * 1024)
        prefix = f"/home/{self.username}/.fdai-transfer-"
        if not destination.startswith(prefix) or "\n" in destination:
            raise ValueError("Bastion remote destination is invalid")
        command = (
            "scp",
            *self._ssh_options(port_flag="-P"),
            str(source),
            f"{self.username}@127.0.0.1:{destination}",
        )
        completed = run_with_heartbeat(
            command,
            cwd=self.cwd,
            timeout=timeout,
            capture_output=True,
            umask=0o077,
        )
        if completed.returncode != 0:
            raise RuntimeError("Bastion private file transfer failed")

    def copy_from(self, source: str, destination: Path, *, timeout: int) -> None:
        """Retrieve one bounded private evidence file without replacing local content."""

        prefix = f"/home/{self.username}/.fdai-state-handoff/"
        if not source.startswith(prefix) or "\n" in source:
            raise ValueError("Bastion remote evidence source is invalid")
        if destination.exists() or destination.is_symlink():
            raise FileExistsError("Bastion local evidence destination already exists")
        parent = destination.parent
        details = parent.stat()
        if (
            not parent.is_dir()
            or details.st_uid != os.geteuid()
            or stat.S_IMODE(details.st_mode) != 0o700
        ):
            raise PermissionError("Bastion local evidence directory must be owner-only")
        command = (
            "scp",
            *self._ssh_options(port_flag="-P"),
            f"{self.username}@127.0.0.1:{source}",
            str(destination),
        )
        completed = run_with_heartbeat(
            command,
            cwd=self.cwd,
            timeout=timeout,
            capture_output=True,
            umask=0o077,
        )
        if completed.returncode != 0:
            destination.unlink(missing_ok=True)
            raise RuntimeError("Bastion private evidence retrieval failed")
        destination.chmod(0o600)
        _require_private_regular_file(destination, max_bytes=64 * 1024 * 1024)

    def _ssh_prefix(self) -> tuple[str, ...]:
        return ("ssh", *self._ssh_options(port_flag="-p"), "-T")

    def _ssh_options(self, *, port_flag: str) -> tuple[str, ...]:
        strict = "accept-new" if self.trust_new_host_key else "yes"
        return (
            port_flag,
            str(self.port),
            "-i",
            str(self.private_key),
            "-o",
            "BatchMode=yes",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            f"StrictHostKeyChecking={strict}",
            "-o",
            f"UserKnownHostsFile={self.known_hosts}",
            "-o",
            "GlobalKnownHostsFile=/dev/null",
            "-o",
            f"HostKeyAlias={self.host_key_alias}",
            "-o",
            "PasswordAuthentication=no",
            "-o",
            "KbdInteractiveAuthentication=no",
            "-o",
            "LogLevel=ERROR",
            "-o",
            "ConnectTimeout=30",
        )


def validate_ssh_private_key(path: Path) -> str:
    """Validate one owner-only private key and return its normalized public-key digest."""

    _require_private_regular_file(path, max_bytes=1024 * 1024)
    completed = run_with_heartbeat(
        ("ssh-keygen", "-y", "-f", str(path)),
        cwd=path.parent,
        timeout=30,
        capture_output=True,
        umask=0o077,
    )
    public_key = completed.stdout.strip()
    if completed.returncode != 0 or not public_key.startswith(("ssh-ed25519 ", "ssh-rsa ")):
        raise ValueError("runner SSH private key is invalid or requires interactive input")
    import hashlib

    return hashlib.sha256(public_key.encode()).hexdigest()


def create_known_hosts(path: Path) -> None:
    """Create a new owner-only known-hosts file for first-contact pinning."""

    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    os.close(descriptor)


def validate_known_hosts(path: Path) -> None:
    """Require a nonempty owner-only host-key file before strict reconnection."""

    _require_private_regular_file(path, max_bytes=65_536)
    if path.stat().st_size == 0:
        raise ValueError("Bastion known-hosts evidence is empty")


def _require_private_regular_file(path: Path, *, max_bytes: int) -> None:
    if not path.is_absolute():
        raise ValueError("private transport file path must be absolute")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        details = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_uid != os.geteuid()
            or stat.S_IMODE(details.st_mode) != 0o600
            or not 0 < details.st_size <= max_bytes
        ):
            raise PermissionError("private transport file must be an owner-only regular file")


def _reserve_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])
