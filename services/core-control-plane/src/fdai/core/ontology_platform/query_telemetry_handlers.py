"""Verified ontology query-node handler for reviewed telemetry recipes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from fdai_service_contracts.ontology_query import EvidenceAuthority, OntologyQueryNode

from fdai.core.rca.telemetry_evidence_codec import (
    telemetry_evidence_need_from_mapping,
    telemetry_evidence_receipt_to_mapping,
)
from fdai.core.rca.telemetry_tool import TelemetryEvidenceRecipeTool

from .query_execution import QueryNodeResult

TELEMETRY_RECIPE_ARGUMENT_SCHEMA: Final[dict[str, object]] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["need"],
    "properties": {
        "need": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "schema_version",
                "need_id",
                "incident_id",
                "resource_ref",
                "evidence_cutoff",
                "recipe_id",
                "recipe_version",
                "lookback",
                "expected_output_schema_digest",
                "max_query_count",
                "max_cost_units",
                "idempotency_key",
            ],
            "properties": {
                "schema_version": {"const": "1.0.0"},
                "need_id": {"type": "string", "pattern": r"^telemetry-need:[a-f0-9]{64}$"},
                "incident_id": {"type": "string", "minLength": 1, "maxLength": 256},
                "resource_ref": {"type": "string", "minLength": 1, "maxLength": 256},
                "evidence_cutoff": {"type": "string", "format": "date-time"},
                "recipe_id": {"type": "string", "minLength": 1, "maxLength": 256},
                "recipe_version": {"type": "string", "minLength": 1, "maxLength": 256},
                "lookback": {"enum": ["five_minutes", "fifteen_minutes", "one_hour"]},
                "expected_output_schema_digest": {
                    "type": "string",
                    "pattern": r"^sha256:[a-f0-9]{64}$",
                },
                "max_query_count": {"type": "integer", "minimum": 1, "maximum": 8},
                "max_cost_units": {"type": "integer", "minimum": 1, "maximum": 1000000},
                "idempotency_key": {"type": "string", "minLength": 1, "maxLength": 256},
            },
        }
    },
}


class TelemetryRecipeNodeHandler:
    """Invoke the typed tool after plan verification and expose only its receipt."""

    def __init__(self, tool: TelemetryEvidenceRecipeTool) -> None:
        self._tool = tool

    async def __call__(
        self,
        node: OntologyQueryNode,
        dependencies: Mapping[str, QueryNodeResult],
    ) -> QueryNodeResult:
        if dependencies or node.depends_on:
            raise ValueError("telemetry recipe query node MUST NOT have dependencies")
        if node.output_kind != "telemetry.evidence":
            raise ValueError("telemetry recipe query node output kind is invalid")
        need = telemetry_evidence_need_from_mapping(node.arguments.get("need"))
        receipt = await self._tool.run(need)
        return QueryNodeResult(
            value=telemetry_evidence_receipt_to_mapping(receipt),
            evidence_refs=(f"telemetry-receipt:{receipt.receipt_digest}",),
            authority=EvidenceAuthority.SERVER_OPERATIONAL_LOGS,
        )


__all__ = ["TELEMETRY_RECIPE_ARGUMENT_SCHEMA", "TelemetryRecipeNodeHandler"]
