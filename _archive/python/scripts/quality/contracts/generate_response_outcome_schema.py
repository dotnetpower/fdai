#!/usr/bin/env python3
"""Generate the additive response-outcome 1.1 schema; leave the 1.0 resource intact."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services/core-control-plane/src"))


def main() -> int:
    from fdai.shared.contracts.models import ResponseOutcome

    if sys.argv[1:] not in ([], ["--check"]):
        print("usage: generate_response_outcome_schema.py [--check]", file=sys.stderr)
        return 64
    root = Path(__file__).resolve().parents[3]
    path = root / (
        "services/core-control-plane/src/fdai/shared/contracts/response-outcome/schema-1.1.0.json"
    )
    schema = ResponseOutcome.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "https://fdai.dev/schemas/response-outcome/1.1.0"
    schema["properties"]["schema_version"] = {"const": "1.1.0", "type": "string"}
    schema["properties"]["outcome_revision"] = {"type": "integer", "minimum": 1}
    schema["required"].append("outcome_revision")
    schema["allOf"] = [
        {
            "if": {"properties": {"outcome_revision": {"const": 1}}},
            "then": {"properties": {"previous_revision_digest": {"type": "null"}}},
            "else": {
                "required": ["previous_revision_digest"],
                "properties": {
                    "previous_revision_digest": {"type": "string", "pattern": "^[0-9a-f]{64}$"}
                },
            },
        }
    ]
    rendered = json.dumps(schema, indent=2, ensure_ascii=False) + "\n"
    if sys.argv[1:] == ["--check"]:
        if not path.is_file() or path.read_text(encoding="utf-8") != rendered:
            print("response-outcome 1.1 schema is stale; regenerate it", file=sys.stderr)
            return 1
        print("response-outcome 1.1 schema: OK")
    else:
        path.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
