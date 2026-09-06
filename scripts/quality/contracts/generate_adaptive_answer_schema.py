#!/usr/bin/env python3
"""Generate the additive advisory projection schema without rewriting prior releases."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fdai_service_contracts.adaptive_answer import AdaptiveAnswer
from fdai_service_contracts.semantic_turn import SemanticTurnRequest

ROOT = Path(__file__).resolve().parents[3]
SCHEMAS = ROOT / "packages/service-contracts/src/fdai_service_contracts/schemas"


def render_schema() -> str:
    """Extend supported 1.4 without rewriting the reserved external-response 1.5 schema."""
    schema = json.loads((SCHEMAS / "core-operator-projection/1.4.0.json").read_text())
    schema["$id"] = "https://fdai.dev/service-contracts/core-operator-projection/1.6.0"
    schema["description"] += " Advisory responses carry goal-local support, not query receipts."
    schema["properties"]["schema_version"] = {"const": "1.6.0"}
    schema["properties"]["status"]["enum"].append("advisory_response")
    semantic = schema["properties"]["semantic_result"]
    properties = semantic["properties"]
    properties["disposition"]["enum"].append("advisory_response")
    properties["semantic_route"]["enum"].append("semantic_advisory_response")
    adaptive = AdaptiveAnswer.model_json_schema()
    schema.setdefault("$defs", {}).update(adaptive.pop("$defs", {}))
    properties["adaptive_answer"] = adaptive
    semantic.setdefault("allOf", []).append(
        {
            "if": {
                "properties": {"disposition": {"const": "advisory_response"}},
                "required": ["disposition"],
            },
            "then": {
                "required": ["adaptive_answer", "answer", "semantic_route"],
                "properties": {
                    "semantic_route": {"const": "semantic_advisory_response"},
                    "evidence_refs": {"maxItems": 0},
                    "checks_completed": {"const": 0},
                    "checks_total": {"const": 0},
                },
                "not": {
                    "anyOf": [
                        {"required": [name]}
                        for name in (
                            "ontology_release_digest",
                            "principal_manifest_digest",
                            "plan_digest",
                            "execution_receipt_digest",
                            "intent_graph",
                            "intent_graph_evidence",
                            "assurance_observation",
                            "direct_response_intent",
                        )
                    ]
                },
            },
            "else": {
                "if": {"properties": {"disposition": {"const": "action_draft"}}},
                "else": {"not": {"required": ["adaptive_answer"]}},
            },
        }
    )
    schema.setdefault("allOf", []).append(
        {
            "if": {"properties": {"status": {"const": "advisory_response"}}},
            "then": {
                "required": ["semantic_result"],
                "properties": {
                    "semantic_result": {
                        "properties": {"disposition": {"const": "advisory_response"}}
                    }
                },
            },
        }
    )
    return json.dumps(schema, indent=2, ensure_ascii=False) + "\n"


def render_request_schema() -> str:
    """Add a canonical dialogue target without changing principal or execution authority."""
    schema = json.loads((SCHEMAS / "operator-core-request/1.5.0.json").read_text())
    schema["$id"] = "https://fdai.dev/service-contracts/operator-core-request/1.6.0"
    schema["description"] += (
        " Canonical dialogue targets, short-lived server-verified relationship proofs,"
        " and explicit unknown reasons convey no execution authority."
    )
    schema["properties"]["schema_version"] = {"const": "1.6.0"}
    schema["properties"]["semantic_turn"]["properties"]["target_agent"] = (
        SemanticTurnRequest.model_json_schema()["properties"]["target_agent"]
    )
    request_model = SemanticTurnRequest.model_json_schema()
    schema["properties"]["semantic_turn"]["properties"]["relationship_proof"] = request_model[
        "properties"
    ]["relationship_proof"]
    semantic = schema["properties"]["semantic_turn"]
    semantic["properties"]["relationship_unknown_reason"] = request_model["properties"][
        "relationship_unknown_reason"
    ]
    semantic.setdefault("allOf", []).append(
        {
            "not": {
                "required": ["relationship_proof", "relationship_unknown_reason"],
                "properties": {
                    "relationship_proof": {"type": "object"},
                    "relationship_unknown_reason": {"type": "string"},
                },
            },
        }
    )
    schema.setdefault("$defs", {})["AdaptiveRelationshipProof"] = request_model["$defs"][
        "AdaptiveRelationshipProof"
    ]
    return json.dumps(schema, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    """Write the owned artifacts, or compare them without modifying the worktree."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    artifacts = {
        SCHEMAS / "core-operator-projection/1.6.0.json": render_schema(),
        SCHEMAS / "operator-core-request/1.6.0.json": render_request_schema(),
    }
    if args.check:
        return (
            0
            if all(
                path.exists() and path.read_text() == rendered
                for path, rendered in artifacts.items()
            )
            else 1
        )
    for path, rendered in artifacts.items():
        path.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
