"""Ontology FunctionType for exact-target control-plane change evidence."""

from __future__ import annotations

import hashlib
from pathlib import Path

from fdai.shared.contracts.models import (
    CeilingRole,
    LogicExecutionClass,
    OntologyFunctionKind,
    OntologyFunctionType,
)

RESOURCE_ACTIVITY_FUNCTION_NAME = "query.resource_change_activity"
MAX_RESOURCE_ACTIVITY_LOOKBACK_SECONDS = 7 * 24 * 60 * 60


def resource_activity_function_type() -> OntologyFunctionType:
    """Return the fixed read-only declaration for bounded change activity."""
    return OntologyFunctionType(
        name=RESOURCE_ACTIVITY_FUNCTION_NAME,
        version="1.1.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest=f"sha256:{hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}",
        publisher="fdai",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["query_result", "lookback_seconds"],
            "properties": {
                "query_result": {"type": "object", "x-fdai-dependency-only": True},
                "lookback_seconds": {
                    "type": "integer",
                    "minimum": 60,
                    "maximum": MAX_RESOURCE_ACTIVITY_LOOKBACK_SECONDS,
                },
            },
        },
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["rows", "complete", "truncation_reason"],
            "properties": {
                "rows": {"type": "array", "maxItems": 32},
                "complete": {"type": "boolean"},
                "truncation_reason": {"type": ["string", "null"]},
            },
        },
        read_sets=["Resource"],
        execution_class=LogicExecutionClass.DETERMINISTIC,
        required_role=CeilingRole.READER,
        purpose_bindings=["operations-review"],
        timeout_seconds=15,
        cpu_millis=250,
        memory_bytes=67_108_864,
        max_output_bytes=262_144,
        network_allowed=False,
        credentials_allowed=False,
    )


__all__ = [
    "MAX_RESOURCE_ACTIVITY_LOOKBACK_SECONDS",
    "RESOURCE_ACTIVITY_FUNCTION_NAME",
    "resource_activity_function_type",
]
