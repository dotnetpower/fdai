"""Bounded private artifact and GitHub JSON decoding."""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Mapping
from pathlib import Path


def _private_artifact_json(path: Path, label: str) -> dict[str, object]:
    return dict(_json_object(_private_artifact_bytes(path, label).decode("utf-8"), label))


def _private_artifact_bytes(path: Path, label: str) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        details = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_uid != os.geteuid()
            or details.st_size > 262_144
        ):
            raise ValueError(f"github_{label.replace(' ', '_')}_file_invalid")
        return stream.read(262_145)


def _json_array(raw: str, label: str) -> list[Mapping[str, object]]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} response is invalid") from exc
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ValueError(f"{label} response MUST be an array of objects")
    if len(payload) > 50:
        raise ValueError(f"{label} response exceeds the requested bound")
    return payload


def _json_object(raw: str, label: str) -> Mapping[str, object]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} response is invalid") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} response MUST be an object")  # noqa: TRY004
    return payload
