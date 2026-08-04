"""Freeze one observation into paired DOCX and canonical JSON artifacts."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from fdai.core.detection.configuration_drift import FrozenConfigurationBaseline
from fdai.delivery.configuration_baseline_docx import (
    render_configuration_baseline_docx,
    write_configuration_baseline_docx,
)
from fdai.delivery.configuration_drift import JsonFileConfigurationObservationSource


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fdai-configuration-baseline-freeze")
    parser.add_argument("--observation", type=Path, required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-docx", type=Path, required=True)
    parser.add_argument("--allowed-exception", action="append", default=[])
    parser.add_argument("--unknown-item", action="append", default=[])
    return parser


def main(argv: list[str] | None = None) -> int:
    """Generate paired artifacts from one validated observation."""

    args = _parser().parse_args(argv)
    try:
        return asyncio.run(_freeze(args))
    except Exception as exc:  # noqa: BLE001 - CLI boundary emits a bounded error kind
        print(f"configuration baseline freeze failed: {type(exc).__name__}", file=sys.stderr)
        return 2


async def _freeze(args: argparse.Namespace) -> int:
    created_at = _timestamp(args.created_at)
    observation = await JsonFileConfigurationObservationSource(
        args.observation,
        args.scope,
    ).observe(scope=args.scope)
    document = render_configuration_baseline_docx(
        observation=observation,
        version=args.version,
        created_at=created_at,
        source=args.source,
        allowed_exceptions=tuple(args.allowed_exception),
        unknown_items=tuple(args.unknown_item),
    )
    document_sha256 = hashlib.sha256(document).hexdigest()
    baseline = FrozenConfigurationBaseline(
        version=args.version,
        created_at=created_at,
        scope=args.scope,
        source=args.source,
        document_sha256=document_sha256,
        resources=observation.resources,
        links=observation.links,
        allowed_exceptions=tuple(args.allowed_exception),
        unknown_items=tuple(args.unknown_item),
    )

    json_temp = args.output_json.with_name(f".{args.output_json.name}.{os.getpid()}.tmp")
    docx_temp = args.output_docx.with_name(f".{args.output_docx.name}.{os.getpid()}.tmp")
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_docx.parent.mkdir(parents=True, exist_ok=True)
    try:
        write_configuration_baseline_docx(docx_temp, document)
        json_temp.write_text(
            json.dumps(baseline.to_dict(), sort_keys=True, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        docx_temp.replace(args.output_docx)
        json_temp.replace(args.output_json)
    finally:
        docx_temp.unlink(missing_ok=True)
        json_temp.unlink(missing_ok=True)

    print(
        json.dumps(
            {
                "baseline_sha256": baseline.sha256,
                "document_sha256": document_sha256,
            },
            sort_keys=True,
        )
    )
    return 0


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("created-at MUST be timezone-aware")
    return parsed.astimezone(UTC)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
