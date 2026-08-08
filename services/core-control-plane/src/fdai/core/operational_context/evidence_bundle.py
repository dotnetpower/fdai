"""Deterministic assembly and validation of operational evidence bundles."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime

from fdai.shared.contracts.models import Autonomy

from .evidence_bundle_identity import bundle_body, evidence_payload
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
    canonical_json,
    digest_json,
)

EvidenceItem = (
    OntologyEvidenceItem | StateEvidenceItem | CatalogEvidenceItem | DocumentEvidenceExcerpt
)
BundleItem = ClaimRecord | EvidenceItem
Candidate = tuple[str, str, BundleItem, object]


def build_operational_evidence_bundle(
    *,
    cutoff: datetime,
    claims: Sequence[ClaimRecord],
    ontology: Sequence[OntologyEvidenceItem] = (),
    state: Sequence[StateEvidenceItem] = (),
    catalog: Sequence[CatalogEvidenceItem] = (),
    documents: Sequence[DocumentEvidenceExcerpt] = (),
    max_items: int,
    max_bytes: int,
    autonomy_ceiling: Autonomy = Autonomy.ENFORCE_AUTO,
) -> OperationalEvidenceBundle:
    """Build a bounded bundle whose validation can only preserve or lower autonomy.

    Document text is serialized as untrusted data. The builder performs no semantic inference:
    contradiction detection compares only exact subject, predicate, cutoff scope, and canonical
    typed values. Citation, freshness, completeness, and budget failures produce hold evidence.
    """

    if cutoff.tzinfo is None:
        raise ValueError("cutoff MUST be timezone-aware")
    for field_name, budget_value in (("max_items", max_items), ("max_bytes", max_bytes)):
        if isinstance(budget_value, bool) or not isinstance(budget_value, int):
            raise ValueError(f"{field_name} MUST be an integer")
        if budget_value < 1:
            raise ValueError(f"{field_name} MUST be >= 1")

    selected_claims_list: list[ClaimRecord] = []
    selected_ontology_list: list[OntologyEvidenceItem] = []
    selected_state_list: list[StateEvidenceItem] = []
    selected_catalog_list: list[CatalogEvidenceItem] = []
    selected_documents_list: list[DocumentEvidenceExcerpt] = []
    missing_paths: list[str] = []
    used_items = 0
    used_bytes = 0

    candidates = _ordered_candidates(
        claims=claims,
        ontology=ontology,
        state=state,
        catalog=catalog,
        documents=documents,
    )
    for category, identity, candidate_value, payload in candidates:
        item_bytes = len(canonical_json(payload).encode())
        if used_items >= max_items or used_bytes + item_bytes > max_bytes:
            missing_paths.append(f"budget:{category}:{identity}")
            continue
        if isinstance(candidate_value, ClaimRecord):
            selected_claims_list.append(candidate_value)
        elif isinstance(candidate_value, OntologyEvidenceItem):
            selected_ontology_list.append(candidate_value)
        elif isinstance(candidate_value, StateEvidenceItem):
            selected_state_list.append(candidate_value)
        elif isinstance(candidate_value, CatalogEvidenceItem):
            selected_catalog_list.append(candidate_value)
        else:
            selected_documents_list.append(candidate_value)
        used_items += 1
        used_bytes += item_bytes

    selected_claims = tuple(selected_claims_list)
    selected_ontology = tuple(selected_ontology_list)
    selected_state = tuple(selected_state_list)
    selected_catalog = tuple(selected_catalog_list)
    selected_documents = tuple(selected_documents_list)

    manifest, manifest_conflicts = _citation_manifest(
        ontology=selected_ontology,
        state=selected_state,
        catalog=selected_catalog,
        documents=selected_documents,
    )
    manifest_refs = {entry.evidence_ref for entry in manifest}
    for claim in selected_claims:
        if not claim.citation_refs:
            missing_paths.append(f"claim:{claim.claim_id}:citation_required")
        for citation_ref in claim.citation_refs:
            if citation_ref not in manifest_refs:
                missing_paths.append(f"claim:{claim.claim_id}:citation:{citation_ref}")

    conflicts = (*manifest_conflicts, *_exact_claim_conflicts(selected_claims))
    evidence_issues = _evidence_issues(
        cutoff=cutoff,
        ontology=selected_ontology,
        state=selected_state,
        catalog=selected_catalog,
        documents=selected_documents,
    )
    hold_reasons: set[str] = set()
    if any(path.startswith("budget:") for path in missing_paths):
        hold_reasons.add("context_budget_truncated")
    if any(path.startswith("claim:") for path in missing_paths):
        hold_reasons.add("citation_incomplete")
    if manifest_conflicts:
        hold_reasons.add("citation_manifest_conflict")
    if any(conflict.kind == "exact_claim_contradiction" for conflict in conflicts):
        hold_reasons.add("exact_claim_contradiction")
    if any(issue.startswith("stale:") for issue in evidence_issues):
        hold_reasons.add("evidence_stale")
    if any(issue.startswith("incomplete:") for issue in evidence_issues):
        hold_reasons.add("evidence_incomplete")
    if any(issue.startswith("after_cutoff:") for issue in evidence_issues):
        hold_reasons.add("evidence_after_cutoff")
    if any(issue.startswith("source_conflict:") for issue in evidence_issues):
        hold_reasons.add("source_conflict")
    if any(issue.startswith("synthetic:") for issue in evidence_issues):
        hold_reasons.add("synthetic_evidence")

    normalized_missing = tuple(sorted(set(missing_paths)))
    normalized_conflicts = tuple(sorted(conflicts, key=lambda item: (item.kind, item.scope)))
    normalized_issues = tuple(sorted(set(evidence_issues)))
    normalized_holds = tuple(sorted(hold_reasons))
    output_ceiling = Autonomy.SHADOW_ONLY if normalized_holds else autonomy_ceiling
    body = bundle_body(
        cutoff=cutoff,
        claims=selected_claims,
        ontology=selected_ontology,
        state=selected_state,
        catalog=selected_catalog,
        documents=selected_documents,
        citation_manifest=manifest,
        conflicts=normalized_conflicts,
        missing_paths=normalized_missing,
        evidence_issues=normalized_issues,
        hold_reasons=normalized_holds,
        max_items=max_items,
        max_bytes=max_bytes,
        used_items=used_items,
        used_bytes=used_bytes,
        autonomy_ceiling=output_ceiling,
    )
    digest = f"sha256:{digest_json(body)}"
    return OperationalEvidenceBundle(
        bundle_id=f"operational-evidence-bundle:{digest}",
        digest=digest,
        cutoff=cutoff,
        claims=selected_claims,
        ontology=selected_ontology,
        state=selected_state,
        catalog=selected_catalog,
        documents=selected_documents,
        citation_manifest=manifest,
        conflicts=normalized_conflicts,
        missing_paths=normalized_missing,
        evidence_issues=normalized_issues,
        hold_reasons=normalized_holds,
        max_items=max_items,
        max_bytes=max_bytes,
        used_items=used_items,
        used_bytes=used_bytes,
        autonomy_ceiling=output_ceiling,
    )


def _ordered_candidates(
    *,
    claims: Sequence[ClaimRecord],
    ontology: Sequence[OntologyEvidenceItem],
    state: Sequence[StateEvidenceItem],
    catalog: Sequence[CatalogEvidenceItem],
    documents: Sequence[DocumentEvidenceExcerpt],
) -> tuple[Candidate, ...]:
    values: list[Candidate] = []
    values.extend(
        ("claim", item.claim_id, item, item.to_mapping())
        for item in sorted(claims, key=lambda value: value.claim_id)
    )
    for lane, item in _evidence_items(
        ontology=ontology,
        state=state,
        catalog=catalog,
        documents=documents,
    ):
        values.extend(((lane.value, item.evidence_ref, item, evidence_payload(item)),))
    return tuple(values)


def _citation_manifest(
    *,
    ontology: Sequence[OntologyEvidenceItem],
    state: Sequence[StateEvidenceItem],
    catalog: Sequence[CatalogEvidenceItem],
    documents: Sequence[DocumentEvidenceExcerpt],
) -> tuple[tuple[CitationManifestEntry, ...], tuple[EvidenceConflict, ...]]:
    entries: list[CitationManifestEntry] = []
    by_ref: dict[str, list[CitationManifestEntry]] = defaultdict(list)
    for lane, item in _evidence_items(
        ontology=ontology,
        state=state,
        catalog=catalog,
        documents=documents,
    ):
        source = item.source
        entry = CitationManifestEntry(
            evidence_ref=item.evidence_ref,
            lane=lane,
            item_digest=f"sha256:{digest_json(evidence_payload(item))}",
            source_revision=source.source_revision,
            cutoff=source.cutoff,
            redaction=source.redaction,
        )
        entries.append(entry)
        by_ref[item.evidence_ref].append(entry)
    conflicts = tuple(
        EvidenceConflict(
            kind="citation_ref_collision",
            scope=evidence_ref,
            claim_ids=(),
            canonical_values=tuple(sorted(entry.item_digest for entry in matches)),
        )
        for evidence_ref, matches in sorted(by_ref.items())
        if len(matches) > 1
    )
    return tuple(sorted(entries, key=lambda item: (item.evidence_ref, item.lane.value))), conflicts


def _exact_claim_conflicts(claims: Sequence[ClaimRecord]) -> tuple[EvidenceConflict, ...]:
    grouped: dict[tuple[str, str, str], list[ClaimRecord]] = defaultdict(list)
    for claim in claims:
        grouped[(claim.subject, claim.predicate, claim.cutoff_scope)].append(claim)
    conflicts: list[EvidenceConflict] = []
    for scope, matches in sorted(grouped.items()):
        values = tuple(sorted({item.canonical_value for item in matches}))
        if len(values) < 2:
            continue
        conflicts.append(
            EvidenceConflict(
                kind="exact_claim_contradiction",
                scope="|".join(scope),
                claim_ids=tuple(sorted(item.claim_id for item in matches)),
                canonical_values=values,
            )
        )
    return tuple(conflicts)


def _evidence_issues(
    *,
    cutoff: datetime,
    ontology: Sequence[OntologyEvidenceItem],
    state: Sequence[StateEvidenceItem],
    catalog: Sequence[CatalogEvidenceItem],
    documents: Sequence[DocumentEvidenceExcerpt],
) -> tuple[str, ...]:
    issues: list[str] = []
    for _, item in _evidence_items(
        ontology=ontology,
        state=state,
        catalog=catalog,
        documents=documents,
    ):
        source = item.source
        if source.cutoff > cutoff:
            issues.append(f"after_cutoff:{item.evidence_ref}")
        elif (cutoff - source.cutoff).total_seconds() > source.freshness_ceiling_seconds:
            issues.append(f"stale:{item.evidence_ref}")
        if source.completeness < 1.0:
            issues.append(f"incomplete:{item.evidence_ref}")
        if isinstance(item, StateEvidenceItem):
            issues.extend(
                f"source_conflict:{item.evidence_ref}:{conflict}"
                for conflict in item.state_fact.conflicts
            )
            if item.state_fact.synthetic:
                issues.append(f"synthetic:{item.evidence_ref}")
    return tuple(issues)


def _evidence_items(
    *,
    ontology: Sequence[OntologyEvidenceItem],
    state: Sequence[StateEvidenceItem],
    catalog: Sequence[CatalogEvidenceItem],
    documents: Sequence[DocumentEvidenceExcerpt],
) -> tuple[tuple[EvidenceLane, EvidenceItem], ...]:
    items: list[tuple[EvidenceLane, EvidenceItem]] = []
    items.extend((EvidenceLane.ONTOLOGY, item) for item in ontology)
    items.extend((EvidenceLane.STATE, item) for item in state)
    items.extend((EvidenceLane.CATALOG, item) for item in catalog)
    items.extend((EvidenceLane.DOCUMENT, item) for item in documents)
    return tuple(sorted(items, key=lambda pair: (pair[0].value, pair[1].evidence_ref)))


__all__ = ["build_operational_evidence_bundle"]
