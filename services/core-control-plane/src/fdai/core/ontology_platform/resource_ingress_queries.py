"""Ontology FunctionType for exact-target Resource ingress configuration."""

from __future__ import annotations

import hashlib
from pathlib import Path

from fdai.shared.contracts.models import (
    CeilingRole,
    LogicExecutionClass,
    OntologyFunctionKind,
    OntologyFunctionType,
)

RESOURCE_INGRESS_FUNCTION_NAME = "query.resource_ingress_configuration"
RESOURCE_INGRESS_MEASURE_CONCEPTS = (
    "ingress_allow_insecure",
    "ingress_configuration",
    "ingress_external",
    "ingress_fqdn",
    "ingress_target_port",
    "ingress_traffic",
    "ingress_transport",
)


def resource_ingress_function_type() -> OntologyFunctionType:
    """Return the fixed read-only declaration for one ingress projection."""

    return OntologyFunctionType(
        name=RESOURCE_INGRESS_FUNCTION_NAME,
        version="1.0.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest=f"sha256:{hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}",
        publisher="fdai",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["query_result"],
            "properties": {"query_result": {"type": "object"}},
        },
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["rows", "complete", "truncation_reason"],
            "x-fdai-measure-concepts": list(RESOURCE_INGRESS_MEASURE_CONCEPTS),
            "properties": {
                "rows": {"type": "array", "maxItems": 1},
                "complete": {"type": "boolean"},
                "truncation_reason": {"type": ["string", "null"]},
            },
        },
        read_sets=["Resource"],
        execution_class=LogicExecutionClass.DETERMINISTIC,
        required_role=CeilingRole.READER,
        purpose_bindings=["operations-review"],
        timeout_seconds=5,
        cpu_millis=100,
        memory_bytes=33_554_432,
        max_output_bytes=32_768,
        network_allowed=False,
        credentials_allowed=False,
    )


__all__ = [
    "RESOURCE_INGRESS_FUNCTION_NAME",
    "RESOURCE_INGRESS_MEASURE_CONCEPTS",
    "resource_ingress_function_type",
]
