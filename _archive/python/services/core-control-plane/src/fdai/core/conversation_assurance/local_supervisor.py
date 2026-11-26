"""Private Unix-socket transport for the explicit conversation-assurance supervisor."""

from __future__ import annotations

import json
import os
import socket
import socketserver
from collections.abc import Callable, Mapping
from pathlib import Path

from fdai.core.conversation_assurance.pantheon_ledger import open_private_lock

Dispatch = Callable[[Mapping[str, object]], Mapping[str, object]]


def serve(*, socket_path: Path, lock_path: Path, dispatch: Dispatch) -> int:
    """Wait for explicit local commands without starting work on process launch."""

    socket_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = open_private_lock(lock_path)
    if lock is None:
        print("conversation assurance supervisor already active")
        return 0

    class ControlServer(socketserver.UnixStreamServer):
        pass

    class ControlHandler(socketserver.StreamRequestHandler):
        def handle(self) -> None:
            try:
                raw = json.loads(self.rfile.readline(65_537))
                if not isinstance(raw, Mapping):
                    raise ValueError("supervisor request MUST be an object")
                response = dispatch({str(key): value for key, value in raw.items()})
            except (json.JSONDecodeError, OSError, RuntimeError, TypeError, ValueError) as error:
                response = {
                    "state": "error",
                    "reason": f"supervisor_request_failed:{type(error).__name__}",
                }
            self.wfile.write((json.dumps(response, separators=(",", ":")) + "\n").encode())

    with lock:
        if socket_path.exists() and not socket_path.is_socket():
            raise ValueError("supervisor socket path MUST be a socket")
        socket_path.unlink(missing_ok=True)
        previous_umask = os.umask(0o177)
        try:
            server = ControlServer(str(socket_path), ControlHandler)
        finally:
            os.umask(previous_umask)
        try:
            with server:
                os.chmod(socket_path, 0o600)
                print("conversation-assurance-supervisor ready", flush=True)
                server.serve_forever()
        finally:
            if socket_path.is_socket():
                socket_path.unlink()
    return 0


def request(
    *,
    socket_path: Path,
    payload: Mapping[str, object],
) -> dict[str, object] | None:
    """Send one explicit command when a supervisor socket is available."""

    if not socket_path.is_socket():
        return None
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(600)
        client.connect(str(socket_path))
        client.sendall((json.dumps(dict(payload), separators=(",", ":")) + "\n").encode())
        raw = client.makefile("rb").readline(65_537)
    decoded = json.loads(raw)
    if not isinstance(decoded, Mapping):
        raise RuntimeError("supervisor response MUST be an object")
    return {str(key): value for key, value in decoded.items()}


__all__ = ["request", "serve"]
