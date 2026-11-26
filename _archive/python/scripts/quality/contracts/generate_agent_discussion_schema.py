#!/usr/bin/env python3
"""Generate the additive no-authority agent-discussion request schema."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fdai_service_contracts import SemanticTurnRequest

ROOT = Path(__file__).resolve().parents[3]
SCHEMAS = ROOT / "packages/service-contracts/src/fdai_service_contracts/schemas"
OUTPUT = SCHEMAS / "operator-core-request/1.11.0.json"


def render_schema() -> str:
    schema = json.loads((SCHEMAS / "operator-core-request/1.10.0.json").read_text())
    schema["$id"] = "https://fdai.dev/service-contracts/operator-core-request/1.11.0"
    schema["description"] += (
        " Explicit agent discussion is read-only presentation and grants no authority."
    )
    schema["properties"]["schema_version"] = {"const": "1.11.0"}
    schema["properties"]["semantic_turn"]["properties"]["presentation_mode"] = (
        SemanticTurnRequest.model_json_schema()["properties"]["presentation_mode"]
    )
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
