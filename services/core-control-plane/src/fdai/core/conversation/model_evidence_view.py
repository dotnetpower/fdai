"""Model-safe evidence projection for answer authors and reviewers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, cast

from fdai_service_contracts.ontology_query import (
    EvidenceAuthority,
    OntologyQueryPlan,
    canonical_json,
    content_digest,
)

from fdai.core.ontology_platform import QueryPlanExecution
from fdai.core.ontology_platform.query_values import QueryRow, QueryTable

_CELL_ALLOWLIST = frozenset(
    {
        "cloud_checked_at",
        "cloud_collected_at",
        "cloud_source_id",
        "cloud_status",
        "display_content_digest",
        "health",
        "inventory_read_at",
        "location",
        "name",
        "property",
        "property_name",
        "property_value",
        "provisioning_status",
        "redaction_applied",
        "revision_name",
        "running_status",
        "source_observed_at",
        "state",
        "status",
        "text",
        "type",
        "value",
    }
)
_LINK_EVIDENCE_ALLOWLIST = frozenset(
    {
        "authority",
        "completeness",
        "effective_time",
        "freshness_ceiling",
        "verification_method",
        "verified",
    }
)
_LINK_MARKERS = frozenset(
    {
        "from_id",
        "from_name",
        "from_ref",
        "link_type",
        "relationship",
        "to_id",
        "to_name",
        "to_ref",
    }
)


@dataclass(frozen=True, slots=True)
class ModelEvidenceView:
    """Canonical evidence subset allowed to cross a model boundary."""

    deployment_scope_digest: str
    authority_digest: str
    temporal_basis_digest: str
    completeness_digest: str
    release_digest: str
    verifier_digest: str
    rows: tuple[dict[str, object], ...]

    def as_payload(self) -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "deployment_scope_digest": self.deployment_scope_digest,
            "authority_digest": self.authority_digest,
            "temporal_basis_digest": self.temporal_basis_digest,
            "completeness_digest": self.completeness_digest,
            "release_digest": self.release_digest,
            "verifier_digest": self.verifier_digest,
            "rows": list(self.rows),
        }

    def canonical_json(self) -> str:
        return cast(str, canonical_json(self.as_payload()))


def model_evidence_view_from_tables(
    tables: tuple[QueryTable, ...],
    *,
    authorities: tuple[EvidenceAuthority, ...],
    release_digest: str,
    verifier_id: str = "core.secured-gateway.model-evidence-view",
) -> ModelEvidenceView:
    """Build the model-safe view from verified query tables."""

    rows: list[dict[str, object]] = []
    for table_index, table in enumerate(tables):
        for row_index, row in enumerate(table.rows):
            cells = _allowed_cells(row.values)
            rows.append(
                {
                    "row_digest": content_digest(
                        {
                            "table_index": table_index,
                            "row_index": row_index,
                            "row_id": row.row_id,
                        }
                    ),
                    "cells": cells,
                }
            )
    return ModelEvidenceView(
        deployment_scope_digest=content_digest({"release": release_digest}),
        authority_digest=content_digest([authority.value for authority in authorities]),
        temporal_basis_digest=content_digest(
            [
                {
                    "source_generation": table.source_generation,
                    "total_rows": table.total_rows,
                }
                for table in tables
            ]
        ),
        completeness_digest=content_digest(
            [
                {
                    "complete": table.complete,
                    "truncation_reason": table.truncation_reason,
                }
                for table in tables
            ]
        ),
        release_digest=release_digest,
        verifier_digest=content_digest({"verifier": verifier_id, "schema_version": "1.0"}),
        rows=tuple(rows),
    )


def adaptive_model_evidence_content(
    execution: QueryPlanExecution,
    *,
    plan: OntologyQueryPlan | None,
    document_output_ids: set[str],
) -> tuple[str, tuple[str, ...], tuple[EvidenceAuthority, ...]] | str:
    """Return model evidence content, refs, authorities, or an unavailable reason."""

    tables: list[QueryTable] = []
    refs: list[str] = []
    authorities: list[EvidenceAuthority] = []
    for node_id in execution.output_node_ids:
        if node_id in document_output_ids:
            continue
        node = execution.results.get(node_id)
        if node is None:
            return "missing_query_output"
        value = node.value
        try:
            table = (
                value
                if isinstance(value, QueryTable)
                else QueryTable(rows=(QueryRow.from_values(node_id, value),), complete=True)
            )
        except ValueError:
            return "unsupported_evidence_shape"
        tables.append(table)
        refs.extend(node.evidence_refs)
        if node.authority is not None:
            authorities.append(node.authority)
        authorities.extend(node.authority_inputs)
    release_digest = plan.ontology_release_digest if plan is not None else "sha256:" + "0" * 64
    content = model_evidence_view_from_tables(
        tuple(tables),
        authorities=tuple(dict.fromkeys(authorities)),
        release_digest=release_digest,
    ).canonical_json()
    return content, tuple(dict.fromkeys(refs)), tuple(dict.fromkeys(authorities))


def _allowed_cells(values: dict[str, Any]) -> dict[str, object]:
    allowed = _LINK_EVIDENCE_ALLOWLIST if _is_link_row(values) else _CELL_ALLOWLIST
    cells: dict[str, object] = {}
    for key, value in values.items():
        if key not in allowed:
            continue
        if isinstance(value, (dict, list)):
            continue
        try:
            json.dumps(value, allow_nan=False)
        except (TypeError, ValueError):
            continue
        cells[key] = value
    return cells


def _is_link_row(values: dict[str, Any]) -> bool:
    return bool(_LINK_MARKERS & set(values))


__all__ = [
    "ModelEvidenceView",
    "adaptive_model_evidence_content",
    "model_evidence_view_from_tables",
]
