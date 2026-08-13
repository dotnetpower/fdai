"""Read-only Incident profile and correlated audit evidence function."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from fdai.core.reporting.datasources.audit_rca import RcaAuditRow, project_rca_report
from fdai.shared.contracts.models import (
    CeilingRole,
    LogicExecutionClass,
    OntologyDeclarationKind,
    OntologyFunctionKind,
    OntologyFunctionType,
    OntologyRelease,
)

from .functions import ContextualOntologyFunction, FunctionInvocationContext

INCIDENT_EVIDENCE_FUNCTION_NAME = "query.incident_evidence"
INCIDENT_EVIDENCE_PURPOSE = "operations-review"
_MAX_RECORDS = 500


@runtime_checkable
class IncidentEvidenceReader(Protocol):
    """Return bounded audit rows for one exact incident correlation."""

    async def list_incident_evidence(
        self,
        *,
        correlation_id: str,
        limit: int,
    ) -> tuple[Sequence[Mapping[str, object]], bool]: ...


@dataclass(frozen=True, slots=True)
class _AuditRow(RcaAuditRow):
    seq: int
    event_id: str
    correlation_id: str | None
    actor: str
    action_kind: str
    mode: str
    recorded_at: str
    entry: Mapping[str, Any]


def _source_artifact_digest() -> str:
    return f"sha256:{hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}"


def incident_evidence_function_type() -> OntologyFunctionType:
    """Return the exact read-only Incident evidence declaration."""
    return OntologyFunctionType(
        name=INCIDENT_EVIDENCE_FUNCTION_NAME,
        version="1.0.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest=_source_artifact_digest(),
        publisher="fdai",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["incident_id", "limit"],
            "properties": {
                "incident_id": {
                    "type": "string",
                    "pattern": (
                        "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                        "[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
                    ),
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": _MAX_RECORDS},
            },
        },
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "required": [
                "incident_id",
                "incident_profile",
                "correlated_evidence",
                "evidence_gaps",
                "evidence_refs",
                "truncated",
                "authority",
                "cause_claim_supported",
                "execution_authority",
            ],
            "properties": {
                "incident_id": {"type": "string"},
                "incident_profile": {"type": ["object", "null"]},
                "correlated_evidence": {"type": "array", "maxItems": _MAX_RECORDS},
                "evidence_gaps": {
                    "type": "array",
                    "maxItems": 8,
                    "items": {"type": "string"},
                },
                "evidence_refs": {
                    "type": "array",
                    "maxItems": _MAX_RECORDS,
                    "items": {"type": "string"},
                },
                "truncated": {"type": "boolean"},
                "authority": {"const": "audit_projection"},
                "cause_claim_supported": {"const": False},
                "execution_authority": {"const": False},
            },
        },
        read_sets=["Incident"],
        execution_class=LogicExecutionClass.DETERMINISTIC,
        required_role=CeilingRole.READER,
        purpose_bindings=[INCIDENT_EVIDENCE_PURPOSE],
        timeout_seconds=5,
        cpu_millis=1000,
        memory_bytes=134_217_728,
        max_output_bytes=262_144,
        network_allowed=False,
        credentials_allowed=False,
    )


def incident_evidence_function(
    ontology_release: OntologyRelease,
    *,
    reader: IncidentEvidenceReader,
) -> ContextualOntologyFunction:
    """Bind correlation-scoped audit projection to one ontology release."""
    ontology_release.type_ref(
        OntologyDeclarationKind.FUNCTION,
        INCIDENT_EVIDENCE_FUNCTION_NAME,
    )

    async def evaluate(
        arguments: Mapping[str, Any],
        invocation_context: FunctionInvocationContext,
    ) -> object:
        if invocation_context.purposes != (INCIDENT_EVIDENCE_PURPOSE,):
            raise PermissionError("incident evidence purpose does not match invocation context")
        incident_id = str(UUID(str(arguments["incident_id"])))
        limit = int(arguments["limit"])
        raw_rows, truncated = await reader.list_incident_evidence(
            correlation_id=incident_id,
            limit=limit,
        )
        if len(raw_rows) > limit:
            raise RuntimeError("incident evidence reader exceeded the requested limit")
        rows = tuple(_audit_row(item, incident_id=incident_id) for item in raw_rows)
        profile_projection = project_rca_report("rca_incident_profile", rows)
        impact_projection = project_rca_report("rca_impact", rows)
        citation_projection = project_rca_report("rca_citations", rows)
        profile = (
            dict(profile_projection.rows[0])
            if profile_projection is not None and profile_projection.rows
            else None
        )
        gaps: list[str] = []
        if profile is None:
            gaps.append("incident_profile_missing")
        if impact_projection is None or not impact_projection.rows:
            gaps.append("impact_evidence_missing")
        if citation_projection is None or not citation_projection.rows:
            gaps.append("grounded_citations_missing")
        if truncated:
            gaps.append("correlated_audit_truncated")
        evidence = [
            {
                "audit_ref": f"audit:{row.seq}",
                "event_id": row.event_id,
                "action_kind": row.action_kind,
                "mode": row.mode,
                "recorded_at": row.recorded_at,
            }
            for row in rows
        ]
        return {
            "incident_id": incident_id,
            "incident_profile": profile,
            "correlated_evidence": evidence,
            "evidence_gaps": gaps,
            "evidence_refs": [item["audit_ref"] for item in evidence],
            "truncated": truncated,
            "authority": "audit_projection",
            "cause_claim_supported": False,
            "execution_authority": False,
        }

    return evaluate


def _audit_row(raw: Mapping[str, object], *, incident_id: str) -> _AuditRow:
    correlation_id = str(raw.get("correlation_id") or "")
    if correlation_id != incident_id:
        raise RuntimeError("incident evidence row correlation does not match the request")
    recorded_at = str(raw.get("recorded_at") or "")
    parsed_at = datetime.fromisoformat(recorded_at.replace("Z", "+00:00"))
    if parsed_at.tzinfo is None:
        raise RuntimeError("incident evidence recorded_at MUST be timezone-aware")
    entry = raw.get("entry")
    if not isinstance(entry, Mapping):
        raise RuntimeError("incident evidence entry MUST be an object")
    return _AuditRow(
        seq=int(str(raw["seq"])),
        event_id=str(raw["event_id"]),
        correlation_id=correlation_id,
        actor=str(raw["actor"]),
        action_kind=str(raw["action_kind"]),
        mode=str(raw["mode"]),
        recorded_at=recorded_at,
        entry=entry,
    )


__all__ = [
    "INCIDENT_EVIDENCE_FUNCTION_NAME",
    "INCIDENT_EVIDENCE_PURPOSE",
    "IncidentEvidenceReader",
    "incident_evidence_function",
    "incident_evidence_function_type",
]
