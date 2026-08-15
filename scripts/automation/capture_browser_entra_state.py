#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import cast

BOOTSTRAP_KEY = "fdai:e2e:browser-entra-session"
DEFAULT_ORIGIN = "http://localhost:5273"
DEFAULT_OUTPUT = Path(".fdai/live-validation/browser-entra-storage-state.json")
MAX_PAYLOAD_BYTES = 4 * 1024 * 1024


class CaptureContractError(ValueError):
    """Indicate that a browser capture payload violates the local state contract."""


def build_storage_state(payload: object, expected_origin: str) -> dict[str, object]:
    """Validate a browser payload and return the Playwright bootstrap state."""
    if not isinstance(payload, dict):
        raise CaptureContractError("capture payload must be an object")
    origin = payload.get("origin")
    if origin != expected_origin:
        raise CaptureContractError("capture origin does not match the expected origin")
    raw_entries = payload.get("sessionStorage")
    if not isinstance(raw_entries, list):
        raise CaptureContractError("sessionStorage must be an array")

    entries: list[list[str]] = []
    for raw_entry in raw_entries:
        if (
            not isinstance(raw_entry, list)
            or len(raw_entry) != 2
            or not all(isinstance(value, str) for value in raw_entry)
        ):
            raise CaptureContractError("sessionStorage entries must be string pairs")
        entries.append(raw_entry)

    return {
        "cookies": [],
        "origins": [
            {
                "origin": origin,
                "localStorage": [
                    {
                        "name": BOOTSTRAP_KEY,
                        "value": json.dumps(entries, ensure_ascii=False, separators=(",", ":")),
                    }
                ],
            }
        ],
    }


def write_storage_state(destination: Path, state: dict[str, object]) -> None:
    """Atomically write storage state with owner-only permissions."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o600)
        temporary.replace(destination)
        destination.chmod(0o600)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


class CaptureServer(HTTPServer):
    """Receive one Browser Entra session capture on loopback."""

    def __init__(self, address: tuple[str, int], expected_origin: str, destination: Path) -> None:
        super().__init__(address, CaptureRequestHandler)
        self.expected_origin = expected_origin
        self.destination = destination
        self.capture_succeeded = False


class CaptureRequestHandler(BaseHTTPRequestHandler):
    """Validate and persist a single browser capture request without logging its body."""

    def do_POST(self) -> None:
        server = cast(CaptureServer, self.server)
        if self.headers.get("Origin") != server.expected_origin:
            self._respond(403)
            return
        try:
            content_length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._respond(411)
            return
        if content_length <= 0 or content_length > MAX_PAYLOAD_BYTES:
            self._respond(413)
            return

        try:
            payload = json.loads(self.rfile.read(content_length))
            state = build_storage_state(payload, server.expected_origin)
            write_storage_state(server.destination, state)
        except (CaptureContractError, json.JSONDecodeError, UnicodeDecodeError):
            self._respond(400)
            return
        server.capture_succeeded = True
        self._respond(204)

    def _respond(self, status: int) -> None:
        server = cast(CaptureServer, self.server)
        self.send_response(status)
        if self.headers.get("Origin") == server.expected_origin:
            self.send_header("Access-Control-Allow-Origin", server.expected_origin)
            self.send_header("Vary", "Origin")
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        pass


def _validated_destination(candidate: Path) -> Path:
    allowed_directory = (Path.cwd() / ".fdai/live-validation").resolve()
    destination = candidate.resolve()
    try:
        destination.relative_to(allowed_directory)
    except ValueError as error:
        raise CaptureContractError("destination must be beneath .fdai/live-validation") from error
    return destination


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--origin", default=DEFAULT_ORIGIN)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()

    try:
        destination = _validated_destination(args.output)
    except CaptureContractError as error:
        parser.error(str(error))

    server = CaptureServer((args.host, args.port), args.origin, destination)
    server.timeout = args.timeout
    host, port = server.server_address
    print(f"receiver-ready url=http://{host}:{port} destination={destination}", flush=True)
    try:
        server.handle_request()
    finally:
        server.server_close()
    return 0 if server.capture_succeeded else 1


if __name__ == "__main__":
    raise SystemExit(main())
