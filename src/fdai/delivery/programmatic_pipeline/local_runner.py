"""Local bubblewrap-compatible isolated programmatic pipeline runner."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from fdai.delivery.programmatic_pipeline.child_runtime import CHILD_RUNTIME_SOURCE
from fdai.shared.providers.programmatic_pipeline import (
    PipelineRunnerOutput,
    PipelineRunnerStatus,
    PipelineRunSpec,
    PipelineToolBroker,
    PipelineToolCall,
)

_SANDBOX_TMP: Final[str] = "/tmp"  # noqa: S108 - private bubblewrap tmpfs


@dataclass(frozen=True, slots=True)
class LocalProgrammaticPipelineRunnerConfig:
    python_executable: str = sys.executable
    bubblewrap_executable: str = "/usr/bin/bwrap"
    use_bubblewrap: bool = True
    max_memory_bytes: int = 256 * 1024 * 1024
    max_broker_request_bytes: int = 1_000_000
    temp_root: str | None = None

    def __post_init__(self) -> None:
        if not Path(self.python_executable).is_absolute():
            raise ValueError("pipeline python_executable MUST be absolute")
        if self.use_bubblewrap and not Path(self.bubblewrap_executable).is_absolute():
            raise ValueError("pipeline bubblewrap_executable MUST be absolute")
        if self.max_memory_bytes < 64 * 1024 * 1024:
            raise ValueError("pipeline max_memory_bytes MUST be at least 64 MiB")
        if not 1_024 <= self.max_broker_request_bytes <= 5_000_000:
            raise ValueError("pipeline max_broker_request_bytes MUST be in [1024, 5000000]")


class LocalProgrammaticPipelineRunner:
    def __init__(
        self,
        config: LocalProgrammaticPipelineRunnerConfig | None = None,
    ) -> None:
        self._config: Final = config or LocalProgrammaticPipelineRunnerConfig()
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._cancelled: set[str] = set()
        self._lock = asyncio.Lock()

    async def run(
        self,
        spec: PipelineRunSpec,
        *,
        broker: PipelineToolBroker,
    ) -> PipelineRunnerOutput:
        started = time.monotonic()
        with (
            tempfile.TemporaryDirectory(
                prefix="fdai-pipeline-",
                dir=self._config.temp_root,
            ) as temporary_root,
            tempfile.TemporaryDirectory(
                prefix="fdai-pipe-sock-",
            ) as socket_root,
        ):
            root = Path(temporary_root)
            source_dir = root / "source"
            runtime_dir = Path(socket_root)
            source_dir.mkdir(mode=0o700)
            (source_dir / "pipeline.py").write_text(spec.source, encoding="utf-8")
            (source_dir / f"{spec.client.module_name}.py").write_text(
                spec.client.source,
                encoding="utf-8",
            )
            (source_dir / "child.py").write_text(CHILD_RUNTIME_SOURCE, encoding="utf-8")
            socket_path = runtime_dir / "b.sock"
            server = await asyncio.start_unix_server(
                lambda reader, writer: self._handle_broker(reader, writer, broker),
                path=socket_path,
                limit=self._config.max_broker_request_bytes + 1,
            )
            try:
                return await self._run_child(
                    spec=spec,
                    source_dir=source_dir,
                    runtime_dir=runtime_dir,
                    socket_path=socket_path,
                    server=server,
                    started=started,
                )
            finally:
                server.close()
                await server.wait_closed()

    async def cancel(self, run_id: str) -> bool:
        async with self._lock:
            process = self._processes.get(run_id)
            if process is None or process.returncode is not None:
                return False
            self._cancelled.add(run_id)
            _kill_process_group(process)
            return True

    async def _run_child(
        self,
        *,
        spec: PipelineRunSpec,
        source_dir: Path,
        runtime_dir: Path,
        socket_path: Path,
        server: asyncio.AbstractServer,
        started: float,
    ) -> PipelineRunnerOutput:
        del server
        argv, env = self._command(
            spec=spec,
            source_dir=source_dir,
            runtime_dir=runtime_dir,
            socket_path=socket_path,
        )
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            start_new_session=True,
        )
        async with self._lock:
            if spec.run_id in self._processes:
                _kill_process_group(process)
                await process.wait()
                raise ValueError("pipeline run_id is already active")
            self._processes[spec.run_id] = process
        envelope_limit = (
            spec.max_stdout_bytes + spec.max_stderr_bytes + spec.max_final_json_bytes + 65_536
        )
        stdout_task = asyncio.create_task(_read_bounded(process.stdout, envelope_limit))
        stderr_task = asyncio.create_task(_read_bounded(process.stderr, spec.max_stderr_bytes))
        timed_out = False
        try:
            await asyncio.wait_for(process.wait(), timeout=spec.timeout_seconds)
        except TimeoutError:
            timed_out = True
            _kill_process_group(process)
            await process.wait()
        except asyncio.CancelledError:
            _kill_process_group(process)
            await process.wait()
            raise
        finally:
            stdout_bytes, stdout_overflow = await stdout_task
            stderr_bytes, stderr_overflow = await stderr_task
            async with self._lock:
                self._processes.pop(spec.run_id, None)
                cancelled = spec.run_id in self._cancelled
                self._cancelled.discard(spec.run_id)
        duration_ms = int((time.monotonic() - started) * 1000)
        if timed_out:
            return _terminal(PipelineRunnerStatus.TIMED_OUT, duration_ms, "pipeline timed out")
        if cancelled:
            return _terminal(PipelineRunnerStatus.CANCELLED, duration_ms, "pipeline cancelled")
        if stdout_overflow or stderr_overflow:
            return PipelineRunnerOutput(
                status=PipelineRunnerStatus.INCOMPLETE,
                stdout="",
                stderr=_decode(stderr_bytes),
                final_json=None,
                duration_ms=duration_ms,
                stdout_truncated=stdout_overflow,
                stderr_truncated=stderr_overflow,
                detail="child transport output exceeded its limit",
            )
        return _decode_envelope(
            stdout_bytes,
            process_stderr=stderr_bytes,
            duration_ms=duration_ms,
            spec=spec,
            returncode=process.returncode,
        )

    async def _handle_broker(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        broker: PipelineToolBroker,
    ) -> None:
        try:
            payload = await reader.readline()
            if not payload or len(payload) > self._config.max_broker_request_bytes:
                response = {"ok": False, "error_code": "request_too_large"}
            else:
                raw = json.loads(payload)
                if not isinstance(raw, dict):
                    raise ValueError("broker request MUST be an object")
                broker_response = await broker.dispatch(
                    PipelineToolCall(
                        run_id=str(raw["run_id"]),
                        capability_token=str(raw["capability_token"]),
                        call_id=str(raw["call_id"]),
                        tool_id=str(raw["tool_id"]),
                        arguments_json=str(raw["arguments_json"]),
                    )
                )
                response = {
                    "ok": broker_response.ok,
                    "output_json": broker_response.output_json,
                    "error_code": broker_response.error_code,
                    "error_message": broker_response.error_message,
                }
        except Exception:  # noqa: BLE001 - untrusted child transport boundary
            response = {"ok": False, "error_code": "invalid_broker_request"}
        writer.write(json.dumps(response, separators=(",", ":")).encode("utf-8") + b"\n")
        try:
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    def _command(
        self,
        *,
        spec: PipelineRunSpec,
        source_dir: Path,
        runtime_dir: Path,
        socket_path: Path,
    ) -> tuple[tuple[str, ...], dict[str, str]]:
        socket_value = "/run/fdai/broker.sock" if self._config.use_bubblewrap else str(socket_path)
        env = {
            "HOME": _SANDBOX_TMP,
            "LANG": "C",
            "LC_ALL": "C",
            "PATH": "/usr/bin:/bin",
            "PYTHONDONTWRITEBYTECODE": "1",
            "FDAI_PIPELINE_RUN_ID": spec.run_id,
            "FDAI_PIPELINE_CAPABILITY_TOKEN": spec.capability_token,
            "FDAI_PIPELINE_BROKER_SOCKET": socket_value,
            "FDAI_PIPELINE_SOURCE_DIR": (
                "/workspace" if self._config.use_bubblewrap else str(source_dir)
            ),
            "FDAI_PIPELINE_CALL_TIMEOUT": str(spec.timeout_seconds),
            "FDAI_PIPELINE_INPUTS": json.dumps(spec.input_json, separators=(",", ":")),
            "FDAI_PIPELINE_CPU_SECONDS": str(max(1, int(spec.timeout_seconds) + 1)),
            "FDAI_PIPELINE_MEMORY_BYTES": str(self._config.max_memory_bytes),
        }
        if not self._config.use_bubblewrap:
            return (
                (self._config.python_executable, "-I", str(source_dir / "child.py")),
                env,
            )
        return _bubblewrap_argv(
            config=self._config,
            source_dir=source_dir,
            runtime_dir=runtime_dir,
            environment=env,
        ), env


async def _read_bounded(
    stream: asyncio.StreamReader | None,
    limit: int,
) -> tuple[bytes, bool]:
    if stream is None:
        return b"", False
    output = bytearray()
    overflow = False
    while chunk := await stream.read(8_192):
        remaining = max(0, limit - len(output))
        output.extend(chunk[:remaining])
        overflow = overflow or len(chunk) > remaining
    return bytes(output), overflow


def _decode_envelope(
    payload: bytes,
    *,
    process_stderr: bytes,
    duration_ms: int,
    spec: PipelineRunSpec,
    returncode: int | None,
) -> PipelineRunnerOutput:
    try:
        envelope = json.loads(payload)
        if not isinstance(envelope, dict):
            raise ValueError("child envelope is not an object")
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return PipelineRunnerOutput(
            status=PipelineRunnerStatus.INCOMPLETE,
            stdout="",
            stderr=_decode(process_stderr),
            final_json=None,
            duration_ms=duration_ms,
            detail=f"child exited without a valid final envelope ({returncode})",
        )
    stdout, stdout_truncated = _truncate(str(envelope.get("stdout") or ""), spec.max_stdout_bytes)
    child_stderr = str(envelope.get("stderr") or "")
    if process_stderr:
        child_stderr = f"{child_stderr}\n{_decode(process_stderr)}".strip()
    stderr, stderr_truncated = _truncate(child_stderr, spec.max_stderr_bytes)
    final_json = envelope.get("final_json")
    final_text = final_json if isinstance(final_json, str) else None
    final_truncated = False
    if final_text is not None and len(final_text.encode("utf-8")) > spec.max_final_json_bytes:
        final_text = None
        final_truncated = True
    child_succeeded = envelope.get("status") == "succeeded" and returncode == 0
    status = (
        PipelineRunnerStatus.SUCCEEDED
        if child_succeeded and not final_truncated
        else PipelineRunnerStatus.INCOMPLETE
        if final_truncated
        else PipelineRunnerStatus.FAILED
    )
    return PipelineRunnerOutput(
        status=status,
        stdout=stdout,
        stderr=stderr,
        final_json=final_text if status is PipelineRunnerStatus.SUCCEEDED else None,
        duration_ms=duration_ms,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
        final_json_truncated=final_truncated,
        detail=None if child_succeeded else str(envelope.get("detail") or "child failed"),
    )


def _bubblewrap_argv(
    *,
    config: LocalProgrammaticPipelineRunnerConfig,
    source_dir: Path,
    runtime_dir: Path,
    environment: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    argv = [
        config.bubblewrap_executable,
        "--die-with-parent",
        "--new-session",
        "--unshare-all",
        "--cap-drop",
        "ALL",
    ]
    for path in ("/usr", "/bin", "/lib", "/lib64"):
        if Path(path).exists():
            argv.extend(("--ro-bind", path, path))
    resolved_python = Path(config.python_executable).resolve()
    resolved_prefix = resolved_python.parent.parent
    sandbox_python = config.python_executable
    if not str(resolved_prefix).startswith(("/usr", "/bin")):
        argv.extend(("--dir", "/runtime", "--ro-bind", str(resolved_prefix), "/runtime/python"))
        sandbox_python = f"/runtime/python/bin/{resolved_python.name}"
    argv.extend(
        (
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            _SANDBOX_TMP,
            "--dir",
            "/workspace",
            "--dir",
            "/run",
            "--dir",
            "/run/fdai",
            "--ro-bind",
            str(source_dir),
            "/workspace",
            "--bind",
            str(runtime_dir),
            "/run/fdai",
            "--chdir",
            "/workspace",
            "--clearenv",
        )
    )
    for key, value in sorted((environment or {}).items()):
        argv.extend(("--setenv", key, value))
    return tuple((*argv, "--", sandbox_python, "-I", "/workspace/child.py"))


def _kill_process_group(process: asyncio.subprocess.Process) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _terminal(status: PipelineRunnerStatus, duration_ms: int, detail: str) -> PipelineRunnerOutput:
    return PipelineRunnerOutput(status, "", "", None, duration_ms, detail=detail)


def _truncate(value: str, limit: int) -> tuple[str, bool]:
    encoded = value.encode("utf-8")
    if len(encoded) <= limit:
        return value, False
    marker = "\n[truncated]"
    marker_bytes = marker.encode("utf-8")
    body = encoded[: max(0, limit - len(marker_bytes))].decode("utf-8", errors="ignore")
    return f"{body}{marker}", True


def _decode(value: bytes) -> str:
    return value.decode("utf-8", errors="replace")


__all__ = [
    "LocalProgrammaticPipelineRunner",
    "LocalProgrammaticPipelineRunnerConfig",
]
