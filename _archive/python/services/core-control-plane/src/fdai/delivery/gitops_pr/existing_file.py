"""Bounded existing-file reads on the publisher's fixed repository and branch."""

from __future__ import annotations

import base64
import binascii
import json
import re
from collections.abc import Awaitable, Callable
from pathlib import PurePosixPath

import httpx

_MAX_CONTENT_BYTES = 1_000_000
_MAX_RESPONSE_BYTES = 1_500_000


def existing_file_path(path: str) -> str:
    """Reject aliases/traversal and retain one exact ASCII repository-relative path."""
    if (
        type(path) is not str
        or not 1 <= len(path) <= 512
        or re.fullmatch(r"[A-Za-z0-9_./-]+", path) is None
        or PurePosixPath(path).is_absolute()
        or str(PurePosixPath(path)) != path
        or any(part in {".", "..", ".git"} for part in path.split("/"))
    ):
        raise ValueError("existing IaC path MUST be exact and repository-relative")
    return path


async def read_existing_file(
    *,
    client: httpx.AsyncClient,
    url: str,
    path: str,
    headers: Callable[[], Awaitable[dict[str, str]]],
    timeout_seconds: float,
) -> str | None:
    """Read UTF-8 file bytes only; never follow a download URL, redirect or symlink."""
    existing_file_path(path)
    try:
        async with client.stream(
            "GET", url, headers=await headers(), timeout=timeout_seconds, follow_redirects=False
        ) as response:
            if response.status_code == 404:
                return None
            if response.status_code != 200:
                raise ValueError("existing IaC file read was not accepted")
            chunks = bytearray()
            async for chunk in response.aiter_bytes():
                if len(chunks) + len(chunk) > _MAX_RESPONSE_BYTES:
                    raise ValueError("existing IaC response exceeds its bound")
                chunks.extend(chunk)
        row = json.loads(chunks, object_pairs_hook=_unique)
        if (
            not isinstance(row, dict)
            or row.get("type") != "file"
            or row.get("path") != path
            or row.get("encoding") != "base64"
            or type(row.get("size")) is not int
            or not 0 <= row["size"] <= _MAX_CONTENT_BYTES
            or type(row.get("content")) is not str
            or "target" in row
            or "submodule_git_url" in row
        ):
            raise ValueError("existing IaC response is not an exact regular file")
        encoded = row["content"].replace("\n", "")
        value = base64.b64decode(encoded, validate=True)
        if len(value) != row["size"] or len(value) > _MAX_CONTENT_BYTES:
            raise ValueError("existing IaC byte count mismatch")
        return value.decode("utf-8", errors="strict")
    except (ValueError, TypeError, binascii.Error, httpx.HTTPError, RecursionError):
        raise ValueError("existing IaC file is unavailable or malformed") from None


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate existing-file field")
        result[key] = value
    return result
