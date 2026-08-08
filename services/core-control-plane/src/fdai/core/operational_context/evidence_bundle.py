"""Deterministic assembly and validation of operational evidence bundles."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import datetime

from fdai.shared.contracts.models import Autonomy

from .evidence_bundle_identity import (
    bind_evidence_item_source,
    bundle_body,
    evidence_item_digest,
    evidence_item_payload,
    evidence_payload,
)
from .evidence_bundle_models import (
    CatalogEvidenceItem,
    CitationBinding,
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
from .evidence_bundle_sources import VerifiedEvidenceSourceReceipt

EvidenceItem = (
    OntologyEvidenceItem | StateEvidenceItem | CatalogEvidenceItem | DocumentEvidenceExcerpt
)
BundleItem = ClaimRecord | EvidenceItem
Candidate = tuple[str, str, BundleItem, object]
ReceiptValidator = Callable[
    [
        VerifiedEvidenceSourceReceipt,
        EvidenceLane,
        str,
        dict[str, object],
        dict[str, object],
    ],
    bool,
]

_MAX_CANDIDATES = 2_048
_MAX_DIAGNOSTICS = 128


def build_operational_evidence_bundle(
    *,
    cutoff: datetime,
    trusted_recorded_at: datetime,
    ontology_release_digest: str,
    catalog_revision: str,
    purpose: str,
    scope: tuple[str, ...],
    claims: Sequence[ClaimRecord],
    ontology: Sequence[OntologyEvidenceItem] = (),
    state: Sequence[StateEvidenceItem] = (),
    catalog: Sequence[CatalogEvidenceItem] = (),
    documents: Sequence[DocumentEvidenceExcerpt] = (),
    max_items: int,
    max_bytes: int,
    autonomy_ceiling: Autonomy = Autonomy.ENFORCE_AUTO,
    receipt_validator: ReceiptValidator | None = None,
) -> OperationalEvidenceBundle:
    """Build a bounded bundle whose validation can only preserve or lower autonomy.

    Document text is serialized as untrusted data. The builder performs no semantic inference:
    contradiction detection compares only exact subject, predicate, cutoff scope, and canonical
    typed values. Citation, freshness, completeness, and budget failures produce hold evidence.
    """

    if cutoff.tzinfo is None or trusted_recorded_at.tzinfo is None:
        raise ValueError("bundle timestamps MUST be timezone-aware")
    if cutoff > trusted_recorded_at:
        raise ValueError("bundle cutoff MUST NOT exceed trusted recorded time")
    if not ontology_release_digest.startswith("sha256:") or len(ontology_release_digest) != 71:
        raise ValueError("ontology_release_digest MUST be a SHA-256 digest")
    if not catalog_revision.strip() or not purpose.strip():
        raise ValueError("catalog_revision and purpose MUST be non-empty")
    canonical_scope = tuple(sorted(set(scope)))
    if not canonical_scope or any(not item.strip() for item in canonical_scope):
        raise ValueError("bundle scope MUST contain non-empty values")
    for field_name, budget_value in (("max_items", max_items), ("max_bytes", max_bytes)):
        if isinstance(budget_value, bool) or not isinstance(budget_value, int):
            raise ValueError(f"{field_name} MUST be an integer")
        if budget_value < 1:
            raise ValueError(f"{field_name} MUST be >= 1")
    claim_ids = [claim.claim_id for claim in claims]
    if len(claim_ids) != len(set(claim_ids)):
        raise ValueError("claims MUST be unique")

    candidates = _ordered_candidates(
        claims=claims,
        ontology=ontology,
        state=state,
        catalog=catalog,
        documents=documents,
    )
    if len(candidates) > _MAX_CANDIDATES:
        raise ValueError("evidence bundle candidate count exceeds limit")
    for lane, item in _evidence_items(
        ontology=ontology,
        state=state,
        catalog=catalog,
        documents=documents,
    ):
        _validate_source_admission(
            item=item,
            lane=lane,
            ontology_release_digest=ontology_release_digest,
            catalog_revision=catalog_revision,
            purpose=purpose,
            scope=canonical_scope,
            receipt_validator=receipt_validator,
        )

    selected = list(candidates[:max_items])
    missing_paths = [
        f"budget:{category}:{identity}" for category, identity, _, _ in candidates[max_items:]
    ]
    while True:
        partitioned = _partition_candidates(selected)
        selected_claims, selected_ontology, selected_state, selected_catalog, selected_documents = (
            partitioned
        )
        manifest, manifest_conflicts = _citation_manifest(
            ontology=selected_ontology,
            state=selected_state,
            catalog=selected_catalog,
            documents=selected_documents,
        )
        current_missing = [*missing_paths]
        manifest_bindings = {
            (entry.evidence_ref, entry.item_digest, entry.source_revision) for entry in manifest
        }
        for claim in selected_claims:
            if not claim.citations:
                current_missing.append(f"claim:{claim.claim_id}:citation_required")
            for citation in claim.citations:
                binding = (citation.evidence_ref, citation.item_digest, citation.source_revision)
                if binding not in manifest_bindings:
                    current_missing.append(
                        f"claim:{claim.claim_id}:citation:{citation.evidence_ref}"
                    )

        conflicts = (*manifest_conflicts, *_exact_claim_conflicts(selected_claims))
        evidence_issues = _evidence_issues(
            cutoff=cutoff,
            trusted_recorded_at=trusted_recorded_at,
            claims=selected_claims,
            ontology=selected_ontology,
            state=selected_state,
            catalog=selected_catalog,
            documents=selected_documents,
        )
        normalized_missing = _bounded_strings(current_missing, category="missing")
        normalized_conflicts = _bounded_conflicts(conflicts)
        normalized_issues = _bounded_strings(evidence_issues, category="issues")
        normalized_holds = _hold_reasons(
            missing_paths=normalized_missing,
            conflicts=normalized_conflicts,
            evidence_issues=normalized_issues,
        )
        output_ceiling = Autonomy.SHADOW_ONLY if normalized_holds else autonomy_ceiling
        body, used_bytes = _sized_body(
            cutoff=cutoff,
            trusted_recorded_at=trusted_recorded_at,
            ontology_release_digest=ontology_release_digest,
            catalog_revision=catalog_revision,
            purpose=purpose,
            scope=canonical_scope,
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
            used_items=len(selected),
            autonomy_ceiling=output_ceiling,
        )
        if used_bytes <= max_bytes:
            digest = f"sha256:{digest_json(body)}"
            return OperationalEvidenceBundle(
                bundle_id=f"operational-evidence-bundle:{digest}",
                digest=digest,
                cutoff=cutoff,
                trusted_recorded_at=trusted_recorded_at,
                ontology_release_digest=ontology_release_digest,
                catalog_revision=catalog_revision,
                purpose=purpose,
                scope=canonical_scope,
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
                used_items=len(selected),
                used_bytes=used_bytes,
                autonomy_ceiling=output_ceiling,
            )
        if not selected:
            raise ValueError("max_bytes is too small for the canonical bundle envelope")
        category, identity, _, _ = selected.pop()
        missing_paths.append(f"budget:{category}:{identity}")


def bind_citation(item: EvidenceItem) -> CitationBinding:
    """Bind an exact evidence item digest and revision into a claim identity."""

    return CitationBinding(
        evidence_ref=item.evidence_ref,
        item_digest=evidence_item_digest(item),
        source_revision=item.source.source_revision,
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


def _partition_candidates(
    candidates: Sequence[Candidate],
) -> tuple[
    tuple[ClaimRecord, ...],
    tuple[OntologyEvidenceItem, ...],
    tuple[StateEvidenceItem, ...],
    tuple[CatalogEvidenceItem, ...],
    tuple[DocumentEvidenceExcerpt, ...],
]:
    claims: list[ClaimRecord] = []
    ontology: list[OntologyEvidenceItem] = []
    state: list[StateEvidenceItem] = []
    catalog: list[CatalogEvidenceItem] = []
    documents: list[DocumentEvidenceExcerpt] = []
    for _, _, value, _ in candidates:
        if isinstance(value, ClaimRecord):
            claims.append(value)
        elif isinstance(value, OntologyEvidenceItem):
            ontology.append(value)
        elif isinstance(value, StateEvidenceItem):
            state.append(value)
        elif isinstance(value, CatalogEvidenceItem):
            catalog.append(value)
        else:
            documents.append(value)
    return tuple(claims), tuple(ontology), tuple(state), tuple(catalog), tuple(documents)


def _validate_source_admission(
    *,
    item: EvidenceItem,
    lane: EvidenceLane,
    ontology_release_digest: str,
    catalog_revision: str,
    purpose: str,
    scope: tuple[str, ...],
    receipt_validator: ReceiptValidator | None,
) -> None:
    receipt = item.source
    item_payload = evidence_item_payload(item)
    item_digest = evidence_item_digest(item)
    if receipt.ontology_release_digest != ontology_release_digest:
        raise ValueError("source receipt ontology release does not match bundle")
    if receipt.catalog_revision != catalog_revision:
        raise ValueError("source receipt catalog revision does not match bundle")
    if receipt.purpose != purpose or receipt.scope != scope:
        raise ValueError("source receipt purpose or scope does not match bundle")
    if lane is EvidenceLane.DOCUMENT and receipt.document_revision is None:
        raise ValueError("document source receipt MUST pin document revision")
    if not receipt.binds_evidence_item:
        raise ValueError("source receipt MUST bind exact evidence item")
    if receipt.evidence_lane != lane.value:
        raise ValueError("source receipt evidence lane does not match item")
    if receipt.evidence_item_digest != item_digest:
        raise ValueError("source receipt evidence item digest does not match item")
    membership_evidence = receipt.membership_evidence_mapping()
    if receipt_validator is not None and not receipt_validator(
        receipt,
        lane,
        item_digest,
        item_payload,
        membership_evidence,
    ):
        raise ValueError("source receipt validator rejected evidence")


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
            item_digest=evidence_item_digest(item),
            source_revision=source.source_revision,
            cutoff=source.temporal_scope.evidence_cutoff,
            redaction_summary=source.redaction_summary,
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
        temporal_scope = claim.temporal_scope.to_mapping()
        del temporal_scope["recorded_at"]
        grouped[
            (
                claim.subject,
                claim.predicate,
                canonical_json(temporal_scope),
            )
        ].append(claim)
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
    trusted_recorded_at: datetime,
    claims: Sequence[ClaimRecord],
    ontology: Sequence[OntologyEvidenceItem],
    state: Sequence[StateEvidenceItem],
    catalog: Sequence[CatalogEvidenceItem],
    documents: Sequence[DocumentEvidenceExcerpt],
) -> tuple[str, ...]:
    issues: list[str] = []
    for claim in claims:
        issues.extend(
            _temporal_issues(
                identity=f"claim:{claim.claim_id}",
                effective_from=claim.temporal_scope.effective_from,
                effective_to=claim.temporal_scope.effective_to,
                evidence_cutoff=claim.temporal_scope.evidence_cutoff,
                recorded_at=claim.temporal_scope.recorded_at,
                cutoff=cutoff,
                trusted_recorded_at=trusted_recorded_at,
                freshness_ceiling_seconds=None,
            )
        )
    for _, item in _evidence_items(
        ontology=ontology,
        state=state,
        catalog=catalog,
        documents=documents,
    ):
        source = item.source
        temporal = source.temporal_scope
        issues.extend(
            _temporal_issues(
                identity=item.evidence_ref,
                effective_from=temporal.effective_from,
                effective_to=temporal.effective_to,
                evidence_cutoff=temporal.evidence_cutoff,
                recorded_at=temporal.recorded_at,
                cutoff=cutoff,
                trusted_recorded_at=trusted_recorded_at,
                freshness_ceiling_seconds=source.freshness_ceiling_seconds,
            )
        )
        if source.completeness < 1.0:
            issues.append(f"incomplete:{item.evidence_ref}")
        issues.extend(
            f"source_conflict:{item.evidence_ref}:{conflict}" for conflict in source.conflicts
        )
        if source.synthetic:
            issues.append(f"synthetic:{item.evidence_ref}")
        if isinstance(item, StateEvidenceItem):
            fact = item.state_fact
            state_identity = f"state_fact:{item.evidence_ref}"
            issues.extend(
                _temporal_issues(
                    identity=state_identity,
                    effective_from=fact.effective_at,
                    effective_to=None,
                    evidence_cutoff=fact.evidence_cutoff,
                    recorded_at=fact.recorded_at,
                    cutoff=cutoff,
                    trusted_recorded_at=trusted_recorded_at,
                    freshness_ceiling_seconds=fact.freshness_ceiling_seconds,
                )
            )
            if fact.completeness < 1.0:
                issues.append(f"state_incomplete:{item.evidence_ref}")
            if fact.synthetic:
                issues.append(f"state_synthetic:{item.evidence_ref}")
            issues.extend(
                f"state_conflict:{item.evidence_ref}:{conflict}" for conflict in fact.conflicts
            )
        if isinstance(item, OntologyEvidenceItem):
            if source.verification_method != "secured-object-set-query":
                issues.append(f"unsecured_ontology_source:{item.evidence_ref}")
            issues.extend(
                _path_issues(
                    item=item,
                    cutoff=cutoff,
                    trusted_recorded_at=trusted_recorded_at,
                )
            )
    return tuple(issues)


def _temporal_issues(
    *,
    identity: str,
    effective_from: datetime,
    effective_to: datetime | None,
    evidence_cutoff: datetime,
    recorded_at: datetime,
    cutoff: datetime,
    trusted_recorded_at: datetime,
    freshness_ceiling_seconds: int | None,
) -> tuple[str, ...]:
    issues: list[str] = []
    if evidence_cutoff > cutoff:
        issues.append(f"after_cutoff:{identity}")
    elif (
        freshness_ceiling_seconds is not None
        and (cutoff - evidence_cutoff).total_seconds() > freshness_ceiling_seconds
    ):
        issues.append(f"stale:{identity}")
    if recorded_at > trusted_recorded_at:
        issues.append(f"after_trusted_recorded_at:{identity}")
    if effective_from > cutoff or (effective_to is not None and cutoff >= effective_to):
        issues.append(f"outside_effective_scope:{identity}")
    return tuple(issues)


def _path_issues(
    *,
    item: OntologyEvidenceItem,
    cutoff: datetime,
    trusted_recorded_at: datetime,
) -> tuple[str, ...]:
    issues: list[str] = []
    path = item.path
    if path.effective_from is not None and path.effective_from > cutoff:
        issues.append(f"path_outside_effective_scope:{item.evidence_ref}")
    if path.effective_to is not None and cutoff >= path.effective_to:
        issues.append(f"path_outside_effective_scope:{item.evidence_ref}")
    for index, link in enumerate(path.links):
        identity = f"{item.evidence_ref}:link:{index}"
        metadata = link.observation_metadata
        if metadata is None:
            issues.append(f"link_unverified:{identity}")
            continue
        if not metadata.verified:
            issues.append(f"link_unverified:{identity}")
        fact = metadata.state_fact
        issues.extend(
            _temporal_issues(
                identity=identity,
                effective_from=fact.effective_at,
                effective_to=None,
                evidence_cutoff=fact.evidence_cutoff,
                recorded_at=fact.recorded_at,
                cutoff=cutoff,
                trusted_recorded_at=trusted_recorded_at,
                freshness_ceiling_seconds=fact.freshness_ceiling_seconds,
            )
        )
        if fact.completeness < 1.0:
            issues.append(f"link_incomplete:{identity}")
        if fact.synthetic:
            issues.append(f"link_synthetic:{identity}")
        issues.extend(f"link_conflict:{identity}:{conflict}" for conflict in fact.conflicts)
    return tuple(issues)


def _bounded_strings(values: Sequence[str], *, category: str) -> tuple[str, ...]:
    canonical = tuple(sorted(set(values)))
    if len(canonical) <= _MAX_DIAGNOSTICS:
        return canonical
    return (
        *canonical[: _MAX_DIAGNOSTICS - 1],
        f"diagnostic_overflow:{category}:{len(canonical) - _MAX_DIAGNOSTICS + 1}",
    )


def _bounded_conflicts(values: Sequence[EvidenceConflict]) -> tuple[EvidenceConflict, ...]:
    canonical = tuple(sorted(values, key=lambda item: (item.kind, item.scope)))
    if len(canonical) <= _MAX_DIAGNOSTICS:
        return canonical
    return (
        *canonical[: _MAX_DIAGNOSTICS - 1],
        EvidenceConflict(
            kind="diagnostic_overflow",
            scope="conflicts",
            claim_ids=(),
            canonical_values=(str(len(canonical) - _MAX_DIAGNOSTICS + 1),),
        ),
    )


def _hold_reasons(
    *,
    missing_paths: tuple[str, ...],
    conflicts: tuple[EvidenceConflict, ...],
    evidence_issues: tuple[str, ...],
) -> tuple[str, ...]:
    holds: set[str] = set()
    if any(path.startswith("budget:") for path in missing_paths):
        holds.add("context_budget_truncated")
    if any(path.startswith("claim:") for path in missing_paths):
        holds.add("citation_incomplete")
    if any(conflict.kind == "citation_ref_collision" for conflict in conflicts):
        holds.add("citation_manifest_conflict")
    if any(conflict.kind == "exact_claim_contradiction" for conflict in conflicts):
        holds.add("exact_claim_contradiction")
    issue_holds = {
        "stale:": "evidence_stale",
        "incomplete:": "evidence_incomplete",
        "after_cutoff:": "evidence_after_cutoff",
        "after_trusted_recorded_at:": "evidence_after_trusted_recorded_at",
        "outside_effective_scope:": "evidence_outside_effective_scope",
        "source_conflict:": "source_conflict",
        "synthetic:": "synthetic_evidence",
        "unsecured_ontology_source:": "unsecured_ontology_source",
        "path_outside_effective_scope:": "path_outside_effective_scope",
        "link_unverified:": "link_unverified",
        "link_incomplete:": "link_incomplete",
        "link_synthetic:": "link_synthetic",
        "link_conflict:": "link_conflict",
        "state_incomplete:": "evidence_incomplete",
        "state_synthetic:": "synthetic_evidence",
        "state_conflict:": "source_conflict",
    }
    for prefix, hold in issue_holds.items():
        if any(issue.startswith(prefix) for issue in evidence_issues):
            holds.add(hold)
    diagnostics = (*missing_paths, *evidence_issues)
    if any(value.startswith("diagnostic_overflow:") for value in diagnostics):
        holds.add("diagnostic_limits_exceeded")
    if any(conflict.kind == "diagnostic_overflow" for conflict in conflicts):
        holds.add("diagnostic_limits_exceeded")
    return tuple(sorted(holds))


def _sized_body(
    **values: object,
) -> tuple[dict[str, object], int]:
    used_bytes = 0
    for _ in range(8):
        body = bundle_body(**values, used_bytes=used_bytes)  # type: ignore[arg-type]
        actual = len(canonical_json(body).encode())
        if actual == used_bytes:
            return body, actual
        used_bytes = actual
    raise RuntimeError("canonical bundle size did not converge")


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


__all__ = [
    "bind_citation",
    "bind_evidence_item_source",
    "build_operational_evidence_bundle",
]
