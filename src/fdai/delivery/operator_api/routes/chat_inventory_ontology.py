"""Ontology declaration for the verified inventory selection function."""

from __future__ import annotations

import hashlib

from fdai.delivery.operator_api.routes.chat_inventory_query import (
    inventory_query_argument_schema,
)
from fdai.shared.contracts.models import (
    CeilingRole,
    OntologyFunctionKind,
    OntologyFunctionType,
)

_FUNCTION_NAME = "inventory.select_resources"
_ARTIFACT_ID = b"fdai.inventory.select_resources.v1"


def inventory_query_function_type() -> OntologyFunctionType:
    """Return the exact read-only function declaration used by semantic plans."""

    return OntologyFunctionType(
        name=_FUNCTION_NAME,
        version="1.0.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest=f"sha256:{hashlib.sha256(_ARTIFACT_ID).hexdigest()}",
        publisher="FDAI",
        input_schema=inventory_query_argument_schema(),
        output_schema={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["matched", "partial", "unavailable", "clarification"],
                },
                "query": {"type": ["object", "null"]},
                "matched_count": {"type": "integer", "minimum": 0},
                "resources": {"type": "array", "maxItems": 40},
            },
            "required": ["status"],
            "additionalProperties": True,
        },
        read_sets=["Resource"],
        required_role=CeilingRole.READER,
        purpose_bindings=["inventory_read"],
        allowed_agents=["Bragi"],
        timeout_seconds=30,
        network_allowed=False,
        credentials_allowed=False,
    )


__all__ = ["inventory_query_function_type"]
