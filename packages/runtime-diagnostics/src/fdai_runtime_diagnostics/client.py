"""Bounded client for one owner-only development diagnostic socket."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fdai_runtime_diagnostics.models import DevelopmentProfilePacket

_MAX_RESPONSE_BYTES = 1024 * 1024


async def request_profile(
    socket_path: Path,
    *,
    duration_ms: int = 0,
    cpu: bool = True,
    heap: bool = True,
    timeout_seconds: float = 35,
) -> DevelopmentProfilePacket:
    """Request one snapshot or bounded capture and verify the returned packet."""
    reader, writer = await asyncio.wait_for(asyncio.open_unix_connection(socket_path), timeout=2)
    request: dict[str, Any] = {
        "schema_version": "1.0.0",
        "command": "snapshot" if duration_ms == 0 else "capture",
    }
    if duration_ms:
        request.update({"duration_ms": duration_ms, "cpu": cpu, "heap": heap})
    writer.write(json.dumps(request, separators=(",", ":")).encode() + b"\n")
    try:
        await asyncio.wait_for(writer.drain(), timeout=2)
        raw = await asyncio.wait_for(reader.readline(), timeout=timeout_seconds)
    finally:
        writer.close()
        await writer.wait_closed()
    if not raw or len(raw) > _MAX_RESPONSE_BYTES or not raw.endswith(b"\n"):
        raise RuntimeError("development diagnostic response is invalid")
    response = json.loads(raw)
    if not isinstance(response, dict) or response.get("status") != "ok":
        reason = response.get("reason") if isinstance(response, dict) else None
        raise RuntimeError(str(reason or "development diagnostic request failed"))
    return DevelopmentProfilePacket.model_validate(response.get("packet"))


__all__ = ["request_profile"]
