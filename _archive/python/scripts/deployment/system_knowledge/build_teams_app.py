#!/usr/bin/env python3
"""Build a deterministic Teams application package for the knowledge bot."""

from __future__ import annotations

import argparse
import binascii
import json
import struct
import uuid
import zipfile
import zlib
from pathlib import Path
from typing import Any

_TEMPLATE = (
    Path(__file__).resolve().parents[3]
    / "services"
    / "system-knowledge-service"
    / "teams-app"
    / "manifest.template.json"
)
_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


def build_package(
    *,
    app_id: str,
    bot_id: str,
    output: Path,
    template: Path = _TEMPLATE,
) -> None:
    """Validate identifiers and write one deterministic three-file app package."""

    app_guid = _guid(app_id, "Teams app id")
    bot_guid = _guid(bot_id, "Bot app id")
    raw = template.read_text(encoding="utf-8")
    manifest = json.loads(
        raw.replace("${TEAMS_APP_ID}", app_guid).replace("${BOT_APP_ID}", bot_guid)
    )
    _validate_manifest(manifest, app_id=app_guid, bot_id=bot_guid)
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest_bytes = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        _write(archive, "manifest.json", manifest_bytes)
        _write(archive, "color.png", _icon(192, outline=False))
        _write(archive, "outline.png", _icon(32, outline=True))


def _validate_manifest(manifest: Any, *, app_id: str, bot_id: str) -> None:
    if not isinstance(manifest, dict):
        raise ValueError("Teams manifest MUST be an object")
    bots = manifest.get("bots")
    bot = bots[0] if isinstance(bots, list) and len(bots) == 1 else None
    if (
        manifest.get("id") != app_id
        or manifest.get("manifestVersion") != "1.30"
        or not isinstance(bot, dict)
        or bot.get("botId") != bot_id
        or bot.get("scopes") != ["team"]
        or "authorization" in manifest
    ):
        raise ValueError("Teams manifest exceeds the mention-only bot contract")


def _guid(value: str, label: str) -> str:
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise ValueError(f"{label} MUST be a UUID") from exc
    rendered = str(parsed)
    if rendered != value.lower():
        raise ValueError(f"{label} MUST use canonical lowercase UUID form")
    return rendered


def _write(archive: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    archive.writestr(info, data)


def _icon(size: int, *, outline: bool) -> bytes:
    pixels = bytearray()
    for y in range(size):
        pixels.append(0)
        for x in range(size):
            pixels.extend(_pixel(size, x, y, outline=outline))
    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(bytes(pixels), level=9))
        + _chunk(b"IEND", b"")
    )


def _pixel(size: int, x: int, y: int, *, outline: bool) -> tuple[int, int, int, int]:
    nx = x / max(size - 1, 1)
    ny = y / max(size - 1, 1)
    arrow = (0.24 <= nx <= 0.62 and 0.42 <= ny <= 0.58) or (
        0.48 <= nx <= 0.77 and abs(ny - 0.5) <= (nx - 0.48) * 0.8
    )
    if outline:
        return (255, 255, 255, 255) if arrow else (0, 0, 0, 0)
    circle = (nx - 0.5) ** 2 + (ny - 0.5) ** 2 <= 0.22
    if arrow:
        return (255, 255, 255, 255)
    if circle:
        return (37, 99, 235, 255)
    return (0, 0, 0, 0)


def _chunk(kind: bytes, data: bytes) -> bytes:
    checksum = binascii.crc32(kind + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-id", required=True)
    parser.add_argument("--bot-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    build_package(
        app_id=arguments.app_id,
        bot_id=arguments.bot_id,
        output=arguments.output,
    )
    print(f"system-knowledge-teams-package: {arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
