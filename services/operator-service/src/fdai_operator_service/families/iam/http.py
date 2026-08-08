"""Shared bounded HTTP parsing and error rendering for the IAM family."""

from __future__ import annotations

import json
from typing import Any

from fdai_operator_service.families.iam.errors import IamFamilyError, IamUnavailableError
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse


async def read_json_object(request: Request, *, maximum: int) -> dict[str, Any]:
    """Read one bounded JSON object, rejecting oversized declared and actual bodies."""
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > maximum:
                raise HTTPException(status_code=413, detail="request body too large")
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail="content-length MUST be an integer",
            ) from exc
    raw = await request.body()
    if len(raw) > maximum:
        raise HTTPException(status_code=413, detail="request body too large")
    try:
        value = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="request body MUST be JSON") from exc
    if not isinstance(value, dict):
        raise HTTPException(status_code=400, detail="request body MUST be an object")
    return value


def require_string(value: dict[str, Any], key: str) -> str:
    """Return a required string field without silently coercing input."""
    item = value.get(key)
    if not isinstance(item, str):
        raise HTTPException(status_code=400, detail=f"{key} MUST be a string")
    return item


def require_revision(value: dict[str, Any], *, positive: bool = False) -> int:
    """Return an exact non-boolean expected revision."""
    revision = value.get("expected_revision")
    minimum = 1 if positive else 0
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < minimum:
        operator = "positive" if positive else ">= 0"
        raise HTTPException(status_code=400, detail=f"expected_revision MUST be {operator}")
    return revision


def require_dependency(value: object | None, name: str) -> object:
    """Fail closed when an authoritative family dependency is not configured."""
    if value is None:
        raise IamUnavailableError(f"{name} is not configured")
    return value


def family_error(exc: IamFamilyError) -> JSONResponse:
    """Render stable legacy-style error envelopes for injected port failures."""
    return error_response(exc.status_code, str(exc))


def error_response(status: int, message: str, *, kind: str | None = None) -> JSONResponse:
    """Render one stable Operator API error envelope."""
    error: dict[str, object] = {"status": status, "message": message}
    if kind is not None:
        error["kind"] = kind
    return JSONResponse({"error": error}, status_code=status)


__all__ = [
    "error_response",
    "family_error",
    "read_json_object",
    "require_dependency",
    "require_revision",
    "require_string",
]
