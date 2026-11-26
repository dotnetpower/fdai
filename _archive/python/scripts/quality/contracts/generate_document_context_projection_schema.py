#!/usr/bin/env python3
"""Generate the Core projection schema with exact document-context binding."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCHEMAS = ROOT / "packages/service-contracts/src/fdai_service_contracts/schemas"
OUTPUT = SCHEMAS / "core-operator-projection/1.7.0.json"


def render_schema() -> str:
    """Extend the current projection with an optional exact context digest."""

    schema = json.loads((SCHEMAS / "core-operator-projection/1.6.0.json").read_text())
    schema["$id"] = "https://fdai.dev/service-contracts/core-operator-projection/1.7.0"
    schema["description"] += (
        " Exact document turns bind the terminal result to the authorized request context."
    )
    schema["properties"]["schema_version"] = {"const": "1.7.0"}
    schema["properties"]["semantic_result"]["properties"]["document_context_digest"] = {
        "type": "string",
        "pattern": "^sha256:[a-f0-9]{64}$",
    }
    return json.dumps(schema, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = render_schema()
    if args.check:
        return 0 if OUTPUT.exists() and OUTPUT.read_text() == rendered else 1
    OUTPUT.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
