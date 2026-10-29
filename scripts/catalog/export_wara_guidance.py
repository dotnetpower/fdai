#!/usr/bin/env python3
"""Export public illustrated guidance without reading installation or customer evidence."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from fdai.core.reporting.formats import JsonFormatEncoder
from fdai.core.wara.guidance_report import build_wara_guidance_report
from fdai.delivery.wara_office_formats import PptxFormatEncoder
from fdai_service_contracts.wara_guidance import packaged_wara_guidance


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--recommendation-id", action="append", default=[])
    selection.add_argument("--all", action="store_true")
    parser.add_argument("--locale", choices=("en", "ko"), default="en")
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    catalog = packaged_wara_guidance()
    requested = set(args.recommendation_id)
    selected = tuple(
        entry for entry in catalog.entries if args.all or entry.recommendation_id in requested
    )
    if not args.all and {entry.recommendation_id for entry in selected} != requested:
        parser.error(
            "one or more recommendation identities are not in the installed public catalog"
        )
    encoders = (JsonFormatEncoder(), PptxFormatEncoder())
    generated_at = datetime.now(UTC)
    args.output_directory.mkdir(parents=True, exist_ok=True)
    for completed, guidance in enumerate(selected, start=1):
        report = build_wara_guidance_report(
            guidance,
            locale=args.locale,
            generated_at=generated_at,
        )
        bodies = {encoder.name: encoder.encode(report) for encoder in encoders}
        basename = f"wara-guide-{guidance.recommendation_id}-{args.locale}"
        for name, body in bodies.items():
            temporary: str | None = None
            try:
                with tempfile.NamedTemporaryFile(dir=args.output_directory, delete=False) as stream:
                    temporary = stream.name
                    stream.write(body)
                os.replace(temporary, args.output_directory / f"{basename}.{name}")
            finally:
                if temporary is not None and os.path.exists(temporary):
                    os.unlink(temporary)
        if completed % 32 == 0:
            print(
                json.dumps(
                    {
                        "stage": "wara-guidance-export",
                        "completed": completed,
                        "total": len(selected),
                    }
                ),
                file=sys.stderr,
            )
    print(
        json.dumps(
            {
                "guides": len(selected),
                "formats": [encoder.name for encoder in encoders],
                "locale": args.locale,
                "catalog_digest": catalog.catalog_digest,
                "installation_evidence_included": False,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
