"""Build and persist immutable diagnostic finding provenance subgraphs."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fdai.shared.providers.ontology_instance import (
    OntologyInstanceStore,
    OntologyLinkRecord,
    OntologyObjectRecord,
    canonical_json_mapping,
)

_MAX_FINDINGS = 256
_MAX_EVIDENCE_BYTES = 1_000_000


class DiagnosticProjectionConflictError(RuntimeError):
    """A content-addressed diagnostic identity resolved to different content."""


@dataclass(frozen=True, slots=True)
class DiagnosticResultProjection:
    """One bounded evidence object, hold findings, and their provenance links."""

    objects: tuple[OntologyObjectRecord, ...]
    links: tuple[OntologyLinkRecord, ...]


def build_diagnostic_result_projection(
    *,
    mechanism_id: str,
    findings: Sequence[Mapping[str, Any]],
    evidence: Mapping[str, Any],
    evidence_ref: str,
    source_revision: str,
    invocation_receipt: Mapping[str, Any],
    resource_ref: str,
    observed_at: datetime,
) -> DiagnosticResultProjection:
    """Create a hold-only projection from one exact diagnostic invocation."""

    for name, value in (
        ("mechanism_id", mechanism_id),
        ("evidence_ref", evidence_ref),
        ("source_revision", source_revision),
        ("resource_ref", resource_ref),
    ):
        if not value.strip():
            raise ValueError(f"diagnostic {name} MUST be non-empty")
    if observed_at.tzinfo is None:
        raise ValueError("diagnostic observed_at MUST be timezone-aware")
    observed_at = observed_at.astimezone(UTC)
    if len(findings) > _MAX_FINDINGS:
        raise ValueError("diagnostic finding count exceeds limit")
    function_ref = invocation_receipt.get("function_ref")
    if not isinstance(function_ref, Mapping):
        raise ValueError("diagnostic invocation receipt has no function_ref")
    if invocation_receipt.get("invocation_id") != evidence_ref:
        raise ValueError("diagnostic evidence_ref MUST match invocation receipt")
    if function_ref.get("catalog_digest") != source_revision:
        raise ValueError("diagnostic source_revision MUST match function release")
    receipt_fields = {
        "function_name": function_ref.get("name"),
        "function_version": function_ref.get("version"),
        "input_digest": invocation_receipt.get("input_digest"),
        "output_digest": invocation_receipt.get("output_digest"),
        "caller_agent": invocation_receipt.get("caller_agent"),
    }
    if any(not isinstance(value, str) or not value for value in receipt_fields.values()):
        raise ValueError("diagnostic invocation receipt is incomplete")

    normalized_evidence, encoded_evidence = canonical_json_mapping(
        evidence,
        path="diagnostic.evidence",
    )
    if len(encoded_evidence.encode("utf-8")) > _MAX_EVIDENCE_BYTES:
        raise ValueError("diagnostic evidence exceeds byte limit")
    evidence_digest = _digest(encoded_evidence)
    evidence_id = _identity(
        "diagnostic-evidence",
        (
            f"{mechanism_id}:{evidence_ref}:{source_revision}:"
            f"{observed_at.isoformat()}:{evidence_digest}"
        ),
    )
    evidence_record = OntologyObjectRecord(
        id=evidence_id,
        object_type="DiagnosticEvidence",
        properties={
            "id": evidence_id,
            "source": "ontology-function",
            "source_revision": source_revision,
            "evidence_ref": evidence_ref,
            "observed_at": observed_at,
            "complete": bool(normalized_evidence.get("evidence_complete")),
            "payload_digest": evidence_digest,
            **receipt_fields,
        },
    )

    objects: list[OntologyObjectRecord] = [evidence_record]
    links: list[OntologyLinkRecord] = []
    mechanism_ref = f"diagnostic-mechanism:{mechanism_id}"
    for finding in findings:
        normalized_finding, encoded_finding = canonical_json_mapping(
            finding,
            path="diagnostic.finding",
        )
        if normalized_finding.get("decision") != "hold":
            raise ValueError("diagnostic ontology projection accepts hold findings only")
        reason = normalized_finding.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("diagnostic finding reason MUST be non-empty")
        finding_digest = _digest(encoded_finding)
        finding_id = _identity(
            "diagnostic-finding",
            f"{mechanism_id}:{resource_ref}:{evidence_id}:{finding_digest}",
        )
        objects.append(
            OntologyObjectRecord(
                id=finding_id,
                object_type="DiagnosticFinding",
                properties={
                    "id": finding_id,
                    "mechanism_id": mechanism_id,
                    "reason": reason,
                    "decision": "hold",
                    "resource_ref": resource_ref,
                    "evidence_ref": evidence_ref,
                    "observed_at": observed_at,
                    "payload_digest": finding_digest,
                },
            )
        )
        links.extend(
            (
                OntologyLinkRecord("diagnostic_finding_produced_by", finding_id, mechanism_ref),
                OntologyLinkRecord("diagnostic_finding_derived_from", finding_id, evidence_id),
                OntologyLinkRecord("diagnostic_finding_affects_resource", finding_id, resource_ref),
            )
        )
    return DiagnosticResultProjection(objects=tuple(objects), links=tuple(links))


class DiagnosticResultProjector:
    """Atomically persist immutable diagnostic projections without replay churn."""

    def __init__(self, *, store: OntologyInstanceStore) -> None:
        self._store = store

    async def project(self, projection: DiagnosticResultProjection) -> None:
        missing: list[OntologyObjectRecord] = []
        for record in projection.objects:
            existing = await self._store.get_object(record.id)
            if existing is None:
                missing.append(record)
                continue
            normalized_properties, _ = canonical_json_mapping(
                record.properties,
                path=f"{record.object_type}.properties",
            )
            if (
                existing.object_type != record.object_type
                or existing.properties != normalized_properties
            ):
                raise DiagnosticProjectionConflictError(
                    "immutable diagnostic projection content changed"
                )
        await self._store.replace_subgraph(objects=tuple(missing), links=projection.links)


def _digest(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _identity(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return f"{prefix}:{digest}"


__all__ = [
    "DiagnosticProjectionConflictError",
    "DiagnosticResultProjection",
    "DiagnosticResultProjector",
    "build_diagnostic_result_projection",
]
