"""Canonical serialization and identity checks for operational evidence bundles."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime

from fdai.shared.contracts.models import Autonomy

from .evidence_bundle_models import (
    CatalogEvidenceItem,
    CitationManifestEntry,
    ClaimRecord,
    DocumentEvidenceExcerpt,
    EvidenceConflict,
    EvidenceLane,
    OntologyEvidenceItem,
    OperationalEvidenceBundle,
    StateEvidenceItem,
    digest_json,
    utc_timestamp,
)
from .models import OperationalContextEvidencePath

EvidenceItem = (
    OntologyEvidenceItem | StateEvidenceItem | CatalogEvidenceItem | DocumentEvidenceExcerpt
)


def evidence_item_payload(item: EvidenceItem) -> dict[str, object]:
    """Return canonical lane content without the source envelope that binds it."""

    if isinstance(item, OntologyEvidenceItem):
        return {
            "evidence_ref": item.evidence_ref,
            "path": _path_payload(item.path),
            "target_object_id": item.target_object_id,
        }
    if isinstance(item, StateEvidenceItem):
        return {
            "evidence_ref": item.evidence_ref,
            "state_fact": item.state_fact.to_mapping(),
        }
    if isinstance(item, CatalogEvidenceItem):
        return {
            "catalog_ref": item.catalog_ref,
            "evidence_ref": item.evidence_ref,
        }
    if isinstance(item, DocumentEvidenceExcerpt):
        return {
            "document_ref": item.document_ref,
            "evidence_ref": item.evidence_ref,
            "excerpt_id": item.excerpt_id,
            "instruction_authority": False,
            "text": item.text,
        }
    raise TypeError(f"unsupported evidence item {type(item).__name__}")


def evidence_item_digest(item: EvidenceItem) -> str:
    """Return the exact canonical lane-content digest bound by its source receipt."""

    return f"sha256:{digest_json(evidence_item_payload(item))}"


def bind_evidence_item_source[EvidenceItemT: EvidenceItem](
    item: EvidenceItemT,
    *,
    membership_evidence: dict[str, object],
) -> EvidenceItemT:
    """Bind an item's exact digest and source inclusion proof into a new source receipt."""

    lane = _evidence_lane(item)
    source = item.source.bind_evidence_item(
        lane=lane.value,
        item_digest=evidence_item_digest(item),
        membership_evidence=membership_evidence,
    )
    return replace(item, source=source)


def evidence_payload(item: EvidenceItem) -> dict[str, object]:
    """Return one lane item's full canonical bundle representation."""

    return {
        **evidence_item_payload(item),
        "source": item.source.to_mapping(),
    }


def _evidence_lane(item: EvidenceItem) -> EvidenceLane:
    if isinstance(item, OntologyEvidenceItem):
        return EvidenceLane.ONTOLOGY
    if isinstance(item, StateEvidenceItem):
        return EvidenceLane.STATE
    if isinstance(item, CatalogEvidenceItem):
        return EvidenceLane.CATALOG
    if isinstance(item, DocumentEvidenceExcerpt):
        return EvidenceLane.DOCUMENT
    raise TypeError(f"unsupported evidence item {type(item).__name__}")


def bundle_body(
    *,
    cutoff: datetime,
    trusted_recorded_at: datetime,
    ontology_release_digest: str,
    catalog_revision: str,
    purpose: str,
    scope: tuple[str, ...],
    claims: Sequence[ClaimRecord],
    ontology: Sequence[OntologyEvidenceItem],
    state: Sequence[StateEvidenceItem],
    catalog: Sequence[CatalogEvidenceItem],
    documents: Sequence[DocumentEvidenceExcerpt],
    citation_manifest: Sequence[CitationManifestEntry],
    conflicts: Sequence[EvidenceConflict],
    missing_paths: tuple[str, ...],
    evidence_issues: tuple[str, ...],
    hold_reasons: tuple[str, ...],
    max_items: int,
    max_bytes: int,
    used_items: int,
    used_bytes: int,
    autonomy_ceiling: Autonomy,
) -> dict[str, object]:
    """Return the full canonical payload covered by bundle identity."""

    return {
        "autonomy_ceiling": autonomy_ceiling.value,
        "catalog_revision": catalog_revision,
        "catalog": tuple(evidence_payload(item) for item in catalog),
        "citation_manifest": tuple(
            {
                "cutoff": utc_timestamp(item.cutoff),
                "evidence_ref": item.evidence_ref,
                "item_digest": item.item_digest,
                "lane": item.lane.value,
                "redaction_summary": item.redaction_summary,
                "source_revision": item.source_revision,
            }
            for item in citation_manifest
        ),
        "claims": tuple(item.to_mapping() for item in claims),
        "conflicts": tuple(
            (item.kind, item.scope, item.claim_ids, item.canonical_values) for item in conflicts
        ),
        "cutoff": utc_timestamp(cutoff),
        "documents": tuple(evidence_payload(item) for item in documents),
        "evidence_issues": evidence_issues,
        "grants_action_authority": False,
        "hold_reasons": hold_reasons,
        "max_bytes": max_bytes,
        "max_items": max_items,
        "missing_paths": missing_paths,
        "ontology": tuple(evidence_payload(item) for item in ontology),
        "ontology_release_digest": ontology_release_digest,
        "purpose": purpose,
        "scope": scope,
        "state": tuple(evidence_payload(item) for item in state),
        "trusted_recorded_at": utc_timestamp(trusted_recorded_at),
        "used_bytes": used_bytes,
        "used_items": used_items,
    }


def compute_bundle_digest(bundle: OperationalEvidenceBundle) -> str:
    """Recompute the digest implied by every immutable bundle field."""

    body = bundle_body(
        cutoff=bundle.cutoff,
        trusted_recorded_at=bundle.trusted_recorded_at,
        ontology_release_digest=bundle.ontology_release_digest,
        catalog_revision=bundle.catalog_revision,
        purpose=bundle.purpose,
        scope=bundle.scope,
        claims=bundle.claims,
        ontology=bundle.ontology,
        state=bundle.state,
        catalog=bundle.catalog,
        documents=bundle.documents,
        citation_manifest=bundle.citation_manifest,
        conflicts=bundle.conflicts,
        missing_paths=bundle.missing_paths,
        evidence_issues=bundle.evidence_issues,
        hold_reasons=bundle.hold_reasons,
        max_items=bundle.max_items,
        max_bytes=bundle.max_bytes,
        used_items=bundle.used_items,
        used_bytes=bundle.used_bytes,
        autonomy_ceiling=bundle.autonomy_ceiling,
    )
    return f"sha256:{digest_json(body)}"


def _path_payload(path: OperationalContextEvidencePath) -> dict[str, object]:
    return {
        "effective_from": utc_timestamp(path.effective_from) if path.effective_from else None,
        "effective_to": utc_timestamp(path.effective_to) if path.effective_to else None,
        "links": tuple(
            {
                "from_id": link.from_id,
                "link_type": link.link_type,
                "observation_metadata": (
                    link.observation_metadata.to_mapping()
                    if link.observation_metadata is not None
                    else None
                ),
                "to_id": link.to_id,
            }
            for link in path.links
        ),
        "object_id": path.object_id,
        "object_type": path.object_type,
        "provenance_refs": path.provenance_refs,
        "revision": path.revision,
    }


__all__ = [
    "bind_evidence_item_source",
    "bundle_body",
    "compute_bundle_digest",
    "evidence_item_digest",
    "evidence_item_payload",
    "evidence_payload",
]
