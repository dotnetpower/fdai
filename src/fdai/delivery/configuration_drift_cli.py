"""CLI for freezing, validating, and comparing configuration baselines."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from fdai.core.detection.configuration_drift import FrozenConfigurationBaseline
from fdai.core.detection.configuration_drift_codec import report_to_dict
from fdai.core.detection.configuration_drift_service import ConfigurationDriftService
from fdai.delivery.configuration_drift import (
    JsonFileConfigurationBaselineSource,
    JsonFileConfigurationObservationSource,
)
from fdai.shared.providers.local.document_structure import extract_ooxml

_MAX_DOCUMENT_BYTES: Final[int] = 16 * 1024 * 1024
_GUID = re.compile(
    r"\b(?!00000000-0000-0000-0000-000000000000\b)"
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_PROHIBITED_TEXT = re.compile(
    r"/subscriptions/|\btenant[ _-]?id\b|\bsubscription[ _-]?id\b|"
    r"\bclient[ _-]?secret\b|\bconnection[ _-]?string\b|\bpassword\b|"
    r"\bsas[ _-]?token\b",
    re.IGNORECASE,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fdai-configuration-drift")
    commands = parser.add_subparsers(dest="command", required=True)

    freeze = commands.add_parser("freeze")
    freeze.add_argument("--observation", type=Path, required=True)
    freeze.add_argument("--document", type=Path, required=True)
    freeze.add_argument("--version", required=True)
    freeze.add_argument("--source", required=True)
    freeze.add_argument("--created-at", required=True)
    freeze.add_argument("--output", type=Path, required=True)
    freeze.add_argument("--allowed-exception", action="append", default=[])
    freeze.add_argument("--unknown-item", action="append", default=[])

    validate = commands.add_parser("validate")
    validate.add_argument("--baseline", type=Path, required=True)
    validate.add_argument("--document", type=Path, required=True)

    check = commands.add_parser("check")
    check.add_argument("--baseline", type=Path, required=True)
    check.add_argument("--observation", type=Path, required=True)
    check.add_argument("--expected-version", required=True)
    check.add_argument("--expected-sha256", required=True)
    check.add_argument("--expected-scope", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run one bounded artifact operation."""

    args = _parser().parse_args(argv)
    try:
        if args.command == "freeze":
            return asyncio.run(_freeze(args))
        if args.command == "validate":
            return asyncio.run(_validate(args))
        if args.command == "check":
            return asyncio.run(_check(args))
    except Exception as exc:  # noqa: BLE001 - CLI boundary returns a bounded error kind
        print(f"configuration drift command failed: {type(exc).__name__}", file=sys.stderr)
        return 2
    return 2


async def _freeze(args: argparse.Namespace) -> int:
    document_sha256 = _validate_document(args.document)
    observation_source = JsonFileConfigurationObservationSource(
        args.observation,
        args.expected_scope
        if hasattr(args, "expected_scope")
        else _observation_scope(args.observation),
    )
    scope = observation_source.allowed_scope
    observation = await observation_source.observe(scope=scope)
    created_at = _timestamp(args.created_at)
    baseline = FrozenConfigurationBaseline(
        version=args.version,
        created_at=created_at,
        scope=scope,
        source=args.source,
        document_sha256=document_sha256,
        resources=observation.resources,
        links=observation.links,
        allowed_exceptions=tuple(args.allowed_exception),
        unknown_items=tuple(args.unknown_item),
    )
    _atomic_json(args.output, baseline.to_dict())
    print(json.dumps({"baseline_sha256": baseline.sha256, "document_sha256": document_sha256}))
    return 0


async def _validate(args: argparse.Namespace) -> int:
    document_sha256 = _validate_document(args.document)
    baseline = await JsonFileConfigurationBaselineSource(args.baseline).load()
    if baseline.document_sha256 != document_sha256:
        raise ValueError("baseline document digest does not match")
    print(json.dumps({"baseline_sha256": baseline.sha256, "document_sha256": document_sha256}))
    return 0


async def _check(args: argparse.Namespace) -> int:
    service = ConfigurationDriftService(
        baseline_source=JsonFileConfigurationBaselineSource(args.baseline),
        observation_source=JsonFileConfigurationObservationSource(
            args.observation,
            args.expected_scope,
        ),
        expected_version=args.expected_version,
        expected_sha256=args.expected_sha256,
        expected_scope=args.expected_scope,
    )
    report = await service.run()
    print(json.dumps(report_to_dict(report), sort_keys=True, ensure_ascii=False))
    return 0 if report.verdict.value == "passed" else 1


def _observation_scope(path: Path) -> str:
    raw = _read_json(path)
    scope = raw.get("scope")
    if not isinstance(scope, str) or not scope.strip():
        raise ValueError("observation scope MUST be a non-empty string")
    return scope


def _validate_document(path: Path) -> str:
    content = path.read_bytes()
    if not content or len(content) > _MAX_DOCUMENT_BYTES:
        raise ValueError("DOCX size is outside the allowed range")
    units = extract_ooxml(content)
    if not units:
        raise ValueError("DOCX contains no readable content")
    visible_text = "\n".join(unit.text for unit in units)
    if _GUID.search(visible_text) or _PROHIBITED_TEXT.search(visible_text):
        raise ValueError("DOCX visible text contains a prohibited identifier or credential marker")
    return hashlib.sha256(content).hexdigest()


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("created-at MUST be timezone-aware")
    return parsed.astimezone(UTC)


def _read_json(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("JSON document MUST be an object")
    return raw


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
