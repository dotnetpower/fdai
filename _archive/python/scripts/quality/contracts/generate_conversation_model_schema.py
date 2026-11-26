#!/usr/bin/env python3
"""Generate the operator request schema with per-turn conversation model selection."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fdai_service_contracts import SemanticTurnRequest

ROOT = Path(__file__).resolve().parents[3]
SCHEMAS = ROOT / "packages/service-contracts/src/fdai_service_contracts/schemas"
OUTPUT = SCHEMAS / "operator-core-request/1.7.0.json"


def render_schema() -> str:
    """Add the no-authority model tier selection to the latest request schema."""

    schema = json.loads((SCHEMAS / "operator-core-request/1.6.0.json").read_text())
    schema["$id"] = "https://fdai.dev/service-contracts/operator-core-request/1.7.0"
    schema["description"] += (
        " An optional operator-selected conversation model tier applies only to"
        " model-authored stages and grants no execution authority."
    )
    schema["properties"]["schema_version"] = {"const": "1.7.0"}
    request_model = SemanticTurnRequest.model_json_schema()
    schema["properties"]["semantic_turn"]["properties"]["conversation_model_tier"] = request_model[
        "properties"
    ]["conversation_model_tier"]
    schema.setdefault("$defs", {})["SemanticConversationModelTier"] = request_model["$defs"][
        "SemanticConversationModelTier"
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
