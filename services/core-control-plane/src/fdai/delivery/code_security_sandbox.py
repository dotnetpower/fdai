"""Bubblewrap sandbox for deterministic-lane code scanners.

Each scanner runs as one sandboxed process with:

- no network and new user, PID, IPC, and UTS namespaces (``--unshare-all``);
- the exact acquired source mounted read-only at ``/source``, and optional read-only ``/rules``
  (FDAI rule pack) and ``/cache`` (pre-provisioned offline database) mounts;
- the scanner executable mounted read-only at ``/opt/scanner/bin``;
- writable tmpfs ``/scratch`` and ``/tmp`` only, a cleared environment, and CPU, address-space,
  and file-size limits. Only the native proof lane may drop the address-space limit, because
  AddressSanitizer reserves terabytes of shadow address space; its harness bounds memory itself;
- standard output read up to the scanner's byte limit. Exceeding it or the timeout kills the
  process group and marks the run truncated or timed out, which the coverage receipt treats as
  incomplete.

The sandbox observes completion itself, so a scanner cannot claim success through its SARIF.
"""

from __future__ import annotations

import asyncio
import os
import resource
import signal
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from fdai.rule_catalog.code_security_scanners import ScannerSpec, resolve_argv

_MOUNTS = {"source": "/source", "rules": "/rules", "cache": "/cache"}
_STDERR_TAIL = 2_000


@dataclass(frozen=True, slots=True)
class ScannerRunResult:
    scanner_id: str
    producer: str
    stdout: bytes
    exit_code: int | None
    completed: bool
    truncated: bool
    timed_out: bool
    duration_ms: int
    stderr_tail: str


@dataclass(frozen=True, slots=True)
class SandboxLimits:
    memory_bytes: int = 4 * 1024**3
    file_size_bytes: int = 1024**3


class BubblewrapScannerSandbox:
    """Run catalog scanners under bubblewrap with fixed mounts and limits."""

    def __init__(self, bwrap: Path = Path("/usr/bin/bwrap"), limits: SandboxLimits | None = None):
        self._bwrap = bwrap
        self._limits = limits or SandboxLimits()

    def command(
        self,
        spec: ScannerSpec,
        executable: Path,
        source: Path,
        *,
        rules: Path | None = None,
        cache: Path | None = None,
    ) -> list[str]:
        """Return the full bubblewrap argv for one scanner run."""
        for name, value in (("executable", executable), ("source", source)):
            if not value.is_absolute():
                raise ValueError(f"{name} path must be absolute")
        argv = [
            str(self._bwrap),
            "--die-with-parent",
            "--new-session",
            "--unshare-all",
            "--ro-bind", "/usr", "/usr",
            "--ro-bind-try", "/bin", "/bin",
            "--ro-bind-try", "/lib", "/lib",
            "--ro-bind-try", "/lib64", "/lib64",
            "--ro-bind-try", "/etc/ssl", "/etc/ssl",
            "--ro-bind", str(executable), "/opt/scanner/bin",
            "--ro-bind", str(source), _MOUNTS["source"],
        ]  # fmt: skip
        for mount, host in (("rules", rules), ("cache", cache)):
            if mount in spec.mounts:
                if host is None or not host.is_absolute():
                    raise ValueError(f"scanner needs an absolute {mount} path")
                argv += ["--ro-bind", str(host), _MOUNTS[mount]]
        argv += [
            "--tmpfs", "/scratch",
            "--tmpfs", "/tmp",  # noqa: S108 - private tmpfs inside the sandbox
            "--dev", "/dev",
            "--proc", "/proc",
            "--chdir", "/scratch",
            "--clearenv",
            "--setenv", "HOME", "/scratch",
            "--setenv", "TMPDIR", "/tmp",  # noqa: S108 - the sandbox's own tmpfs
            "--setenv", "PATH", "/usr/bin:/bin",
        ]  # fmt: skip
        if spec.cache_env:
            argv += ["--setenv", spec.cache_env, _MOUNTS["cache"]]
        argv += ["--", "/opt/scanner/bin", *resolve_argv(spec, dict(_MOUNTS))]
        return argv

    def _limit_child(
        self, timeout_seconds: int, address_space: int | None = None, *, limit_address: bool = True
    ) -> None:
        cpu = timeout_seconds + 5
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
        if limit_address:
            memory = address_space or self._limits.memory_bytes
            resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
        size = self._limits.file_size_bytes
        resource.setrlimit(resource.RLIMIT_FSIZE, (size, size))

    async def run(
        self,
        scanner_id: str,
        spec: ScannerSpec,
        executable: Path,
        source: Path,
        *,
        rules: Path | None = None,
        cache: Path | None = None,
        environ: Mapping[str, str] | None = None,
        limit_address_space: bool = True,
    ) -> ScannerRunResult:
        """Run one scanner and return its bounded output and observed completion.

        ``limit_address_space=False`` is reserved for the native proof harness, which applies its
        own address-space limit to the compiler and an RSS limit to sanitizer builds.
        """
        argv = self.command(spec, executable, source, rules=rules, cache=cache)
        started = time.monotonic()
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=dict(environ) if environ is not None else {"PATH": "/usr/bin:/bin"},
            start_new_session=True,
            preexec_fn=lambda: self._limit_child(
                spec.timeout_seconds,
                spec.address_space_bytes,
                limit_address=limit_address_space,
            ),
        )
        reader, errors = process.stdout, process.stderr
        if reader is None or errors is None:
            raise RuntimeError("scanner process pipes are unavailable")
        stdout = bytearray()
        truncated = False
        timed_out = False

        async def drain_stdout() -> None:
            nonlocal truncated
            while chunk := await reader.read(65_536):
                if len(stdout) + len(chunk) > spec.max_output_bytes:
                    truncated = True
                    _kill(process)
                    return
                stdout.extend(chunk)

        stderr_task = asyncio.ensure_future(errors.read())
        try:
            await asyncio.wait_for(drain_stdout(), timeout=spec.timeout_seconds)
        except TimeoutError:
            timed_out = True
            _kill(process)
        exit_code = await process.wait()
        stderr = await stderr_task
        completed = not truncated and not timed_out and exit_code in spec.success_exit_codes
        return ScannerRunResult(
            scanner_id=scanner_id,
            producer=spec.producer,
            stdout=bytes(stdout),
            exit_code=exit_code,
            completed=completed,
            truncated=truncated,
            timed_out=timed_out,
            duration_ms=int((time.monotonic() - started) * 1000),
            stderr_tail=stderr[-_STDERR_TAIL:].decode("utf-8", "replace"),
        )


def _kill(process: asyncio.subprocess.Process) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def sandbox_available(bwrap: Path = Path("/usr/bin/bwrap")) -> bool:
    """Return whether unprivileged bubblewrap namespaces work on this host."""
    import subprocess

    try:
        proc = subprocess.run(  # noqa: S603 - fixed probe argv
            [str(bwrap), "--unshare-all", "--ro-bind", "/", "/", "true"],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


__all__ = [
    "BubblewrapScannerSandbox",
    "SandboxLimits",
    "ScannerRunResult",
    "sandbox_available",
]
