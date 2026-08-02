"""Request boundary parsing for the chat SSE route."""

from __future__ import annotations

import json
from typing import Any

from starlette.exceptions import HTTPException
from starlette.requests import Request


async def read_chat_stream_body(
    request: Request,
    *,
    max_body_bytes: int,
) -> dict[str, Any]:
    declared_len = request.headers.get("content-length")
    if declared_len is not None:
        try:
            if int(declared_len) > max_body_bytes:
                raise HTTPException(status_code=413, detail="chat body too large")
        except ValueError:
            pass
    body_bytes = await request.body()
    if len(body_bytes) > max_body_bytes:
        raise HTTPException(status_code=413, detail="chat body too large")
    try:
        body = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="chat body MUST be JSON") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="chat body MUST be a JSON object")
    return body
