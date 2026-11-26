"""Credential-free bubblewrap runner for reviewed read-only tool pipelines."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import resource
import secrets
import shutil
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from fdai.core.programmatic_pipeline.client import generate_pipeline_client
from fdai.shared.providers.programmatic_pipeline import (
    PipelineRunnerOutput,
    PipelineRunnerStatus,
    PipelineRunSpec,
    PipelineToolBroker,
    PipelineToolCall,
)

_MAX_BROKER_REQUEST = 1_000_512
_MAX_BROKER_RESPONSE = 5_005_000


@dataclass(frozen=True, slots=True)
class LocalPipelineConfig:
    workspace_root: Path
    bubblewrap: str = "/usr/bin/bwrap"
    memory_bytes: int = 512 * 1024 * 1024

    def __post_init__(self) -> None:
        if not self.workspace_root.is_absolute():
            raise ValueError("pipeline workspace_root MUST be absolute")
        if not 128 * 1024 * 1024 <= self.memory_bytes <= 2 * 1024 * 1024 * 1024:
            raise ValueError("pipeline memory_bytes is outside the permitted range")


@dataclass(slots=True)
class _ActiveRun:
    process: asyncio.subprocess.Process | None = None
    cancelled: bool = False


class LocalProgrammaticPipelineRunner:
    """Isolate a child with no host workspace, network, or inherited environment.

    The caller supplies an owned workspace root; no system temporary directory is
    used. A private source mount and a distinct socket mount are removed on every
    exit. The runner does not issue capabilities or dispatch tools itself.
    """

    def __init__(self, config: LocalPipelineConfig) -> None:
        self._config = config
        self._active: dict[str, _ActiveRun] = {}

    async def run(
        self, spec: PipelineRunSpec, *, broker: PipelineToolBroker
    ) -> PipelineRunnerOutput:
        _verify_spec(spec)
        if spec.run_id in self._active:
            raise ValueError("pipeline run is already active")
        active = _ActiveRun()
        self._active[spec.run_id] = active
        started = time.monotonic()
        directory: Path | None = None
        server: asyncio.AbstractServer | None = None
        calls: set[asyncio.Task[None]] = set()
        try:
            root = self._config.workspace_root
            root.mkdir(mode=0o700, parents=True, exist_ok=True)
            if root.is_symlink() or root.stat().st_mode & 0o077:
                raise ValueError("pipeline workspace_root MUST be a private directory")
            directory = root / secrets.token_hex(4)
            source_dir, socket_dir = directory / "source", directory / "socket"
            directory.mkdir(mode=0o700)
            source_dir.mkdir(mode=0o700)
            socket_dir.mkdir(mode=0o700)
            (source_dir / "pipeline.py").write_text(spec.source, encoding="utf-8")
            (source_dir / "fdai_pipeline_client.py").write_text(
                spec.client.source, encoding="utf-8"
            )
            (source_dir / "worker.py").write_text(
                Path(__file__)
                .with_name("local_programmatic_pipeline_worker.py")
                .read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            for path in source_dir.iterdir():
                path.chmod(0o400)

            async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
                task = asyncio.current_task()
                if task is None:
                    writer.close()
                    await writer.wait_closed()
                    return
                calls.add(task)
                try:
                    line = await asyncio.wait_for(reader.readline(), timeout=spec.timeout_seconds)
                    if not line.endswith(b"\n") or len(line) > _MAX_BROKER_REQUEST:
                        return
                    payload = json.loads(line)
                    if not isinstance(payload, dict):
                        return
                    call = PipelineToolCall(**payload)
                    response = await asyncio.wait_for(
                        broker.dispatch(call), timeout=spec.timeout_seconds
                    )
                    encoded = (
                        json.dumps(
                            {
                                "ok": response.ok,
                                "output_json": response.output_json,
                                "error_code": response.error_code,
                            },
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ).encode("utf-8")
                        + b"\n"
                    )
                    if len(encoded) <= _MAX_BROKER_RESPONSE:
                        writer.write(encoded)
                        await writer.drain()
                except (TimeoutError, ValueError, TypeError, asyncio.LimitOverrunError):
                    pass
                finally:
                    writer.close()
                    await writer.wait_closed()
                    calls.discard(task)

            socket_fd = os.open(socket_dir, os.O_RDONLY | os.O_DIRECTORY)
            try:
                server = await asyncio.start_unix_server(
                    handle, path=f"/proc/self/fd/{socket_fd}/b", limit=_MAX_BROKER_REQUEST
                )
            finally:
                os.close(socket_fd)
            (socket_dir / "b").chmod(0o600)
            argv = _sandbox_command(
                self._config.bubblewrap, source_dir=source_dir, socket_dir=socket_dir
            )
            environment = {
                "FDAI_PIPELINE_RUN_ID": spec.run_id,
                "FDAI_PIPELINE_CAPABILITY_TOKEN": spec.capability_token,
                "FDAI_PIPELINE_BROKER_SOCKET": "/run/fdai/b",
                "FDAI_PIPELINE_CALL_TIMEOUT": str(spec.timeout_seconds),
                "PYTHONDONTWRITEBYTECODE": "1",
                "PATH": "/usr/bin:/bin",
                "LANG": "C.UTF-8",
                "TMPDIR": "/scratch",
            }
            active.process = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=environment,
                start_new_session=True,
                preexec_fn=lambda: _limit_child(
                    timeout_seconds=spec.timeout_seconds, memory_bytes=self._config.memory_bytes
                ),
            )
            if active.cancelled:
                _kill_group(active.process)
            payload = json.dumps(
                {
                    "inputs": spec.input_json,
                    "max_stdout": spec.max_stdout_bytes,
                    "max_stderr": spec.max_stderr_bytes,
                    "max_final": spec.max_final_json_bytes,
                },
                separators=(",", ":"),
            ).encode("utf-8")
            max_envelope = (
                2 * (spec.max_stdout_bytes + spec.max_stderr_bytes + spec.max_final_json_bytes)
                + 4096
            )
            try:
                stdout, _ = await asyncio.wait_for(
                    _exchange(active.process, payload, max_envelope), timeout=spec.timeout_seconds
                )
            except TimeoutError:
                _kill_group(active.process)
                await active.process.wait()
                return _terminal(PipelineRunnerStatus.TIMED_OUT, started)
            if active.cancelled:
                return _terminal(PipelineRunnerStatus.CANCELLED, started)
            if active.process.returncode != 0 or stdout is None:
                return _terminal(PipelineRunnerStatus.INCOMPLETE, started)
            try:
                envelope = json.loads(stdout)
                if not isinstance(envelope, dict):
                    raise ValueError("invalid child envelope")
                if envelope.get("ok") is False:
                    return _terminal(PipelineRunnerStatus.FAILED, started)
                if envelope.get("ok") is not True:
                    raise ValueError("invalid child status")
                final_json = envelope["final_json"]
                if final_json is not None and not isinstance(final_json, str):
                    raise ValueError("invalid final JSON")
                if (
                    final_json is not None
                    and len(final_json.encode("utf-8")) > spec.max_final_json_bytes
                ):
                    raise ValueError("oversized final JSON")
                if final_json is not None:
                    json.loads(final_json)
                for name, bound in (
                    ("stdout", spec.max_stdout_bytes),
                    ("stderr", spec.max_stderr_bytes),
                ):
                    if (
                        not isinstance(envelope[name], str)
                        or len(envelope[name].encode("utf-8")) > bound
                    ):
                        raise ValueError("oversized child output")
                for name in ("stdout_truncated", "stderr_truncated", "final_truncated"):
                    if not isinstance(envelope[name], bool):
                        raise ValueError("invalid child status")
                return PipelineRunnerOutput(
                    status=(
                        PipelineRunnerStatus.INCOMPLETE
                        if envelope["final_truncated"]
                        else PipelineRunnerStatus.SUCCEEDED
                    ),
                    stdout=envelope["stdout"],
                    stderr=envelope["stderr"],
                    final_json=final_json,
                    duration_ms=int((time.monotonic() - started) * 1000),
                    stdout_truncated=envelope["stdout_truncated"],
                    stderr_truncated=envelope["stderr_truncated"],
                    final_json_truncated=envelope["final_truncated"],
                )
            except (KeyError, TypeError, ValueError, UnicodeDecodeError):
                return _terminal(PipelineRunnerStatus.INCOMPLETE, started)
        except asyncio.CancelledError:
            if active.process is not None:
                _kill_group(active.process)
                await active.process.wait()
            raise
        finally:
            if active.process is not None and active.process.returncode is None:
                _kill_group(active.process)
                await active.process.wait()
            if server is not None:
                server.close()
                await server.wait_closed()
            for task in calls:
                task.cancel()
            if calls:
                await asyncio.gather(*calls, return_exceptions=True)
            if directory is not None and directory.exists():
                shutil.rmtree(directory)
            self._active.pop(spec.run_id, None)

    async def cancel(self, run_id: str) -> bool:
        active = self._active.get(run_id)
        if active is None:
            return False
        active.cancelled = True
        if active.process is not None and active.process.returncode is None:
            _kill_group(active.process)
        return True


def _verify_spec(spec: PipelineRunSpec) -> None:
    if hashlib.sha256(spec.source.encode("utf-8")).hexdigest() != spec.source_digest:
        raise ValueError("local pipeline source digest mismatch")
    if not spec.source or len(spec.source.encode("utf-8")) > 256_000:
        raise ValueError("local pipeline source exceeds its byte limit")
    if spec.client != generate_pipeline_client(frozenset(spec.client.allowed_tools)):
        raise ValueError("local pipeline generated client mismatch")
    if not spec.capability_token or not 0.1 <= spec.timeout_seconds <= 300:
        raise ValueError("local pipeline capability or timeout is invalid")
    if (
        len(spec.input_json) > 1_000
        or sum(len(item.encode("utf-8")) for item in spec.input_json) > 5_000_000
    ):
        raise ValueError("local pipeline input exceeds its byte limit")
    if any(
        not 1 <= value <= 5_000_000
        for value in (
            spec.max_stdout_bytes,
            spec.max_stderr_bytes,
            spec.max_final_json_bytes,
        )
    ):
        raise ValueError("local pipeline output limit is invalid")


def _sandbox_command(executable: str, *, source_dir: Path, socket_dir: Path) -> list[str]:
    base = Path(sys.base_prefix).resolve()
    python = Path(getattr(sys, "_base_executable", sys.executable)).resolve()
    if not python.is_relative_to(base):
        raise ValueError("local pipeline Python MUST belong to its base prefix")
    argv = [
        executable,
        "--die-with-parent",
        "--unshare-all",
        "--ro-bind",
        "/usr",
        "/usr",
        "--ro-bind-try",
        "/lib",
        "/lib",
        "--ro-bind-try",
        "/lib64",
        "/lib64",
        "--ro-bind",
        str(base),
        "/python",
        "--ro-bind",
        str(source_dir),
        "/source",
        "--ro-bind",
        str(socket_dir),
        "/run/fdai",
        "--tmpfs",
        "/scratch",
        "--dev",
        "/dev",
        "--proc",
        "/proc",
        "--chdir",
        "/source",
        "--",
        str(Path("/python") / python.relative_to(base)),
        "-I",
        "-S",
        "-B",
        "worker.py",
    ]
    return argv


def _limit_child(*, timeout_seconds: float, memory_bytes: int) -> None:
    cpu_seconds = math.ceil(timeout_seconds) + 1
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
    resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))


def _kill_group(process: asyncio.subprocess.Process) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _terminal(status: PipelineRunnerStatus, started: float) -> PipelineRunnerOutput:
    return PipelineRunnerOutput(
        status=status,
        stdout="",
        stderr="",
        final_json=None,
        duration_ms=int((time.monotonic() - started) * 1000),
    )


async def _exchange(
    process: asyncio.subprocess.Process, payload: bytes, max_envelope: int
) -> tuple[bytes | None, bytes | None]:
    stdin, stdout_stream, stderr_stream = process.stdin, process.stdout, process.stderr
    if stdin is None or stdout_stream is None or stderr_stream is None:
        raise RuntimeError("pipeline child streams are not connected")

    async def drain(stream: asyncio.StreamReader, limit: int) -> bytes | None:
        data = bytearray()
        while chunk := await stream.read(8192):
            if len(data) + len(chunk) > limit:
                _kill_group(process)
                return None
            data.extend(chunk)
        return bytes(data)

    async def feed() -> None:
        try:
            stdin.write(payload)
            await stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            stdin.close()

    stdout, stderr, _, _ = await asyncio.gather(
        drain(stdout_stream, max_envelope),
        drain(stderr_stream, 4096),
        feed(),
        process.wait(),
    )
    return stdout, stderr


__all__ = ["LocalPipelineConfig", "LocalProgrammaticPipelineRunner"]
