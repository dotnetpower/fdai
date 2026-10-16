#!/usr/bin/env python3
"""Generate the Operational Readiness remediation request schema."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fdai_service_contracts.readiness_remediation import ReadinessRemediationRequest

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = (
    ROOT
    / "packages/service-contracts/src/fdai_service_contracts/schemas"
    / "readiness-remediation-request"
    / "1.0.0.json"
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    schema = ReadinessRemediationRequest.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "https://fdai.dev/service-contracts/readiness-remediation-request/1.0.0"
    rendered = json.dumps(schema, indent=2, ensure_ascii=False) + "\n"
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != rendered:
            print("readiness-remediation-schema: stale")
            return 1
    else:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(rendered, encoding="utf-8")
    print("readiness-remediation-schema: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
