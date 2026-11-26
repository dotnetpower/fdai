#!/usr/bin/env python3
"""Generate the operator request schema with exact authorized document context."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fdai_service_contracts import SemanticTurnRequest

ROOT = Path(__file__).resolve().parents[3]
SCHEMAS = ROOT / "packages/service-contracts/src/fdai_service_contracts/schemas"
OUTPUT = SCHEMAS / "operator-core-request/1.8.0.json"


def render_schema() -> str:
    """Add authority-free exact-document context to the latest request schema."""

    schema = json.loads((SCHEMAS / "operator-core-request/1.7.0.json").read_text())
    schema["$id"] = "https://fdai.dev/service-contracts/operator-core-request/1.8.0"
    schema["description"] += (
        " An optional exact document context binds authorized document versions to the"
        " principal and conversation without granting execution authority."
    )
    schema["properties"]["schema_version"] = {"const": "1.8.0"}
    request_model = SemanticTurnRequest.model_json_schema()
    document_context = request_model["properties"]["document_context"]
    schema["properties"]["semantic_turn"]["properties"]["document_context"] = document_context
    schema.setdefault("$defs", {})["SemanticDocumentContext"] = request_model["$defs"][
        "SemanticDocumentContext"
    ]
    schema["$defs"]["SemanticDocumentContextSource"] = request_model["$defs"][
        "SemanticDocumentContextSource"
    ]
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
