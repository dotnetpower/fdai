"""Owner-only Unix socket lifecycle for local development diagnostics."""

from __future__ import annotations

import asyncio
import fcntl
import json
import os
import socket as socket_module
import stat
from pathlib import Path
from typing import Any

from fdai_runtime_diagnostics.config import DevelopmentDiagnosticsConfig
from fdai_runtime_diagnostics.probe import RuntimeProbe

_MAX_REQUEST_BYTES = 4096
_MAX_RESPONSE_BYTES = 1024 * 1024


class DevelopmentDiagnosticServer:
    """Serve bounded profile requests without joining a product transport."""

    def __init__(self, config: DevelopmentDiagnosticsConfig) -> None:
        self._config = config
        self._probe = RuntimeProbe(config)
        self._server: asyncio.Server | None = None
        self._socket_identity: tuple[int, int] | None = None
        self._lock_fd: int | None = None

    async def start(self) -> None:
        if self._server is not None:
            raise RuntimeError("development diagnostic server is already started")
        socket = self._config.socket_path
        socket.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(socket.parent, 0o700)
        lock_path = socket.with_suffix(".lock")
        lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        bound_socket: socket_module.socket | None = None
        try:
            metadata = os.fstat(lock_fd)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
                raise ValueError("development diagnostic lock is not an owned regular file")
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError("development diagnostic socket is already owned") from exc
            _remove_stale_socket(socket)
            bound_socket = socket_module.socket(socket_module.AF_UNIX, socket_module.SOCK_STREAM)
            bound_socket.bind(str(socket))
            bound_socket.listen(socket_module.SOMAXCONN)
            bound_socket.setblocking(False)
            os.chmod(socket, 0o600)
            socket_metadata = socket.lstat()
            self._socket_identity = (socket_metadata.st_dev, socket_metadata.st_ino)
            self._server = await asyncio.start_unix_server(
                self._handle,
                sock=bound_socket,
                limit=_MAX_REQUEST_BYTES + 1,
            )
            bound_socket = None
            self._lock_fd = lock_fd
        except BaseException:
            if bound_socket is not None:
                bound_socket.close()
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
            raise

    async def aclose(self) -> None:
        server = self._server
        self._server = None
        if server is not None:
            server.close()
            await server.wait_closed()
        socket = self._config.socket_path
        try:
            metadata = socket.lstat()
            identity = (metadata.st_dev, metadata.st_ino)
            if (
                self._socket_identity is not None
                and identity == self._socket_identity
                and stat.S_ISSOCK(metadata.st_mode)
                and metadata.st_uid == os.getuid()
            ):
                socket.unlink()
        except FileNotFoundError:
            pass
        finally:
            self._socket_identity = None
            lock_fd = self._lock_fd
            self._lock_fd = None
            if lock_fd is not None:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                os.close(lock_fd)

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            raw = await asyncio.wait_for(reader.readline(), timeout=2)
            if not raw or len(raw) > _MAX_REQUEST_BYTES or not raw.endswith(b"\n"):
                raise ValueError("development diagnostic request is invalid")
            request = json.loads(raw)
            if not isinstance(request, dict) or request.get("schema_version") != "1.0.0":
                raise ValueError("development diagnostic request schema is invalid")
            command = request.get("command")
            if command == "snapshot":
                packet = await self._probe.capture()
            elif command == "capture":
                duration_ms = request.get("duration_ms")
                cpu = request.get("cpu", True)
                heap = request.get("heap", True)
                if type(duration_ms) is not int or type(cpu) is not bool or type(heap) is not bool:
                    raise ValueError("development diagnostic capture arguments are invalid")
                packet = await self._probe.capture(duration_ms=duration_ms, cpu=cpu, heap=heap)
            else:
                raise ValueError("development diagnostic command is unsupported")
            response: dict[str, Any] = {
                "status": "ok",
                "packet": packet.model_dump(mode="json"),
            }
        except (asyncio.TimeoutError, json.JSONDecodeError, RuntimeError, ValueError) as exc:
            response = {"status": "error", "reason": str(exc)[:256] or "diagnostic_error"}
        encoded = json.dumps(response, ensure_ascii=True, separators=(",", ":")).encode() + b"\n"
        if len(encoded) > _MAX_RESPONSE_BYTES:
            encoded = b'{"status":"error","reason":"diagnostic_response_too_large"}\n'
        writer.write(encoded)
        try:
            await asyncio.wait_for(writer.drain(), timeout=2)
        finally:
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), timeout=1)
            except (BrokenPipeError, ConnectionResetError, asyncio.TimeoutError):
                pass


def _remove_stale_socket(path: Path) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return
    if path.is_symlink() or not stat.S_ISSOCK(metadata.st_mode) or metadata.st_uid != os.getuid():
        raise ValueError("development diagnostic socket path is not an owned socket")
    path.unlink()


__all__ = ["DevelopmentDiagnosticServer"]
