"""Deterministic claim inventory and completeness accounting.

The inventory is intentionally conservative. It makes likely operational
claims visible before model extraction so a missing model candidate cannot
silently disappear from coverage measurement.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence

from fdai.rule_catalog.pipeline.distill.ontology_models import (
    AuthorityClass,
    ClaimDisposition,
    ClaimKind,
    ClaimResolution,
    ClaimUnit,
    SourceEvidence,
)
from fdai.shared.providers.distiller import DistilledCandidate, ManualDocument

_FENCE_RE = re.compile(r"^(?P<marker>`{3,}|~{3,})")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_NORMATIVE = re.compile(
    r"\b(?:must|must\s+not|shall|required|prohibited|forbidden|should|may\s+not)\b|"
    r"(?:해야|필수|금지|않아야)",
    re.IGNORECASE,
)
_THRESHOLD = re.compile(
    r"(?:>=|<=|==|!=|>|<|\bat\s+least\b|\bat\s+most\b|\bmore\s+than\b|"
    r"\bless\s+than\b|\babove\b|\bbelow\b|\bwithin\b).*?\d|"
    r"\b\d+(?:\.\d+)?\s*(?:%|ms|s|m|h|gb|tb|usd)(?!\w)",
    re.IGNORECASE,
)
_RELATIONSHIP = re.compile(
    r"\b(?:depends\s+on|runs\s+on|implemented\s+by|owned\s+by|delivered\s+by|"
    r"contains|requires|uses|governed\s+by)\b|(?:의존|소유|담당|구현)",
    re.IGNORECASE,
)
_PROCEDURE = re.compile(
    r"\b(?:restart|rollback|roll\s+back|failover|fail\s+over|scale|restore|notify|"
    r"escalate|stop|deploy|drain|rotate|reconcile)\b|"
    r"(?:재시작|롤백|복구|배포|확장|축소|중지|에스컬레이션)",
    re.IGNORECASE,
)
_TELEMETRY = re.compile(
    r"\b(?:cpu|memory|latency|throughput|error\s+rate|availability|slo|rto|rpo|"
    r"telemetry|metric|measured|observed)\b|(?:메모리|지연|오류율|가용성|측정|관측)",
    re.IGNORECASE,
)
_PROVIDER = re.compile(
    r"\b(?:resource|cluster|container\s+app|virtual\s+machine|database|network|"
    r"storage|topology|revision)\b|(?:리소스|클러스터|데이터베이스|네트워크|스토리지|토폴로지)",
    re.IGNORECASE,
)
_HISTORY = re.compile(
    r"\b(?:incident|postmortem|outage|occurred|previously|historical|root\s+cause)\b|"
    r"(?:장애|사후분석|발생|과거|근본\s*원인)",
    re.IGNORECASE,
)
_ENTITY = re.compile(
    r"\b(?:service|workload|resource|environment|owner|team|application|component)\b|"
    r"(?:서비스|워크로드|리소스|환경|담당자|팀|애플리케이션|컴포넌트)",
    re.IGNORECASE,
)
_EXECUTION_AUTHORITY = re.compile(
    r"\b(?:permission|authorized|authorization|approve|approval|autonomy|execute)\b|"
    r"(?:권한|승인|자율|실행)",
    re.IGNORECASE,
)
_OBSERVATION_CUE = re.compile(
    r"\b(?:current|currently|observed|deployed|exists|shows)\b|(?:현재|관측|배포됨|존재)",
    re.IGNORECASE,
)
_LIST_PREFIX = re.compile(r"^(?:[-*+]\s+|\d+[.)]\s+)")
_MAX_DOCUMENT_BYTES = 5_000_000


def inventory_claims(document: ManualDocument) -> tuple[ClaimUnit, ...]:
    """Return stable operational claims detected in one governed document."""
    if len(document.text.encode("utf-8")) > _MAX_DOCUMENT_BYTES:
        raise ValueError("ontology claim inventory document exceeds the byte limit")
    content_sha = document_content_digest(document)
    revision = document.metadata.get("revision", content_sha)
    claims: list[ClaimUnit] = []
    fence_marker: str | None = None

    for line_number, raw_line in enumerate(document.text.splitlines(), start=1):
        stripped = raw_line.strip()
        fence = _FENCE_RE.match(stripped)
        if fence is not None:
            marker = fence.group("marker")[0]
            if fence_marker is None:
                fence_marker = marker
            elif fence_marker == marker:
                fence_marker = None
            continue
        if fence_marker is not None or not stripped or stripped.startswith("#"):
            continue

        semantic_line = _LIST_PREFIX.sub("", stripped)
        for unit_ordinal, text in enumerate(_split_claim_units(semantic_line), start=1):
            kind = _claim_kind(text)
            if kind is None:
                continue
            authority = _authority_class(text, kind)
            text_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
            claim_material = "\0".join(
                [document.source_ref, content_sha, str(line_number), str(unit_ordinal), text_sha]
            )
            claim_id = "claim-" + hashlib.sha256(claim_material.encode("utf-8")).hexdigest()
            claims.append(
                ClaimUnit(
                    claim_id=claim_id,
                    kind=kind,
                    authority=authority,
                    evidence=SourceEvidence(
                        source_ref=document.source_ref,
                        document_id=document.doc_id,
                        document_revision=revision,
                        content_sha256=content_sha,
                        line_start=line_number,
                        line_end=line_number,
                        text_sha256=text_sha,
                    ),
                    critical=kind
                    in {
                        ClaimKind.NORMATIVE,
                        ClaimKind.THRESHOLD,
                        ClaimKind.RELATIONSHIP,
                        ClaimKind.PROCEDURE,
                    }
                    or authority is AuthorityClass.EXECUTION_AUTHORITY,
                )
            )

    return tuple(claims)


def reconcile_claims(
    claims: Sequence[ClaimUnit],
    candidates: Sequence[DistilledCandidate],
    *,
    exact_candidate_claims: Mapping[str, str] | None = None,
) -> tuple[ClaimResolution, ...]:
    """Account for every claim using candidate source-line coverage."""
    resolutions: list[ClaimResolution] = []
    candidate_ids = [candidate.candidate_id for candidate in candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("distilled candidate ids MUST be unique for claim reconciliation")
    exact = exact_candidate_claims or {}
    if not set(exact).issubset(candidate_ids):
        raise ValueError("exact candidate claim mapping MUST reference known candidates")
    if not set(exact.values()).issubset({claim.claim_id for claim in claims}):
        raise ValueError("exact candidate claim mapping MUST reference known claims")

    for claim in claims:
        matching = tuple(
            candidate.candidate_id
            for candidate in candidates
            if (
                exact.get(candidate.candidate_id) == claim.claim_id
                if candidate.candidate_id in exact
                else candidate.source_ref == claim.evidence.source_ref
                and candidate.source_lines[0] <= claim.evidence.line_start
                and candidate.source_lines[1] >= claim.evidence.line_end
            )
        )
        if matching:
            resolutions.append(
                ClaimResolution(
                    claim_id=claim.claim_id,
                    disposition=ClaimDisposition.MAPPED,
                    candidate_ids=matching,
                )
            )
        else:
            resolutions.append(
                ClaimResolution(
                    claim_id=claim.claim_id,
                    disposition=ClaimDisposition.NEEDS_REVIEW,
                    reason_code="unmapped_claim",
                )
            )
    return tuple(resolutions)


def claim_text_records(
    document: ManualDocument,
    claims: Sequence[ClaimUnit],
) -> tuple[tuple[str, str], ...]:
    """Reconstruct ephemeral claim text for verification without storing it."""
    by_line: dict[int, list[str]] = {}
    fence_marker: str | None = None
    for line_number, raw_line in enumerate(document.text.splitlines(), start=1):
        stripped = raw_line.strip()
        fence = _FENCE_RE.match(stripped)
        if fence is not None:
            marker = fence.group("marker")[0]
            if fence_marker is None:
                fence_marker = marker
            elif fence_marker == marker:
                fence_marker = None
            continue
        if fence_marker is not None or not stripped or stripped.startswith("#"):
            continue
        by_line[line_number] = list(_split_claim_units(_LIST_PREFIX.sub("", stripped)))

    records: list[tuple[str, str]] = []
    for claim in claims:
        candidates = by_line.get(claim.evidence.line_start, [])
        matched = [
            text
            for text in candidates
            if hashlib.sha256(text.encode("utf-8")).hexdigest() == claim.evidence.text_sha256
        ]
        if not matched:
            raise ValueError("inventoried claim text MUST remain reconstructable")
        records.append((claim.claim_id, matched[0]))
    return tuple(records)


def _split_claim_units(line: str) -> tuple[str, ...]:
    return tuple(unit.strip() for unit in _SENTENCE.split(line) if unit.strip())


def _claim_kind(text: str) -> ClaimKind | None:
    if _HISTORY.search(text):
        return ClaimKind.HISTORY
    if _THRESHOLD.search(text):
        return ClaimKind.THRESHOLD
    if _NORMATIVE.search(text):
        return ClaimKind.NORMATIVE
    if _RELATIONSHIP.search(text):
        return ClaimKind.RELATIONSHIP
    if _PROCEDURE.search(text):
        return ClaimKind.PROCEDURE
    if _TELEMETRY.search(text):
        return ClaimKind.OBSERVATION
    if _ENTITY.search(text):
        return ClaimKind.ENTITY
    return None


def _authority_class(text: str, kind: ClaimKind) -> AuthorityClass:
    if _EXECUTION_AUTHORITY.search(text):
        return AuthorityClass.EXECUTION_AUTHORITY
    if kind is ClaimKind.HISTORY:
        return AuthorityClass.HISTORICAL_EVIDENCE
    if kind in {ClaimKind.NORMATIVE, ClaimKind.THRESHOLD}:
        return AuthorityClass.DECLARED_INTENT
    if _PROVIDER.search(text) and _OBSERVATION_CUE.search(text):
        return AuthorityClass.PROVIDER_OBSERVATION
    if _TELEMETRY.search(text):
        return AuthorityClass.TELEMETRY_OBSERVATION
    if kind is ClaimKind.PROCEDURE:
        return AuthorityClass.PROCEDURE
    return AuthorityClass.DECLARED_INTENT


def document_content_digest(document: ManualDocument) -> str:
    """Return and verify the exact SHA-256 digest of document text."""
    computed = hashlib.sha256(document.text.encode("utf-8")).hexdigest()
    if not document.content_sha:
        return computed
    if re.fullmatch(r"[a-f0-9]{64}", document.content_sha) is None:
        raise ValueError("ManualDocument.content_sha MUST be a lowercase SHA-256 digest")
    if document.content_sha != computed:
        raise ValueError("ManualDocument.content_sha MUST match the provided document text")
    return document.content_sha


__all__ = [
    "claim_text_records",
    "document_content_digest",
    "inventory_claims",
    "reconcile_claims",
]
