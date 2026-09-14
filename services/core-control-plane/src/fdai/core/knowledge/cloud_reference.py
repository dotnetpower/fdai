"""No-authority read contract and deterministic dated public-source presentation."""

from datetime import datetime
from typing import Protocol, runtime_checkable

from fdai_service_contracts.cloud_knowledge import Applicability, CloudSourceEvidence
from fdai_service_contracts.cloud_knowledge_release import KnowledgeReleaseBinding

from fdai.shared.providers.document_ingestion import GovernedDocumentSearchResult


@runtime_checkable
class ApplicableDocumentSearch(Protocol):
    """Apply a canonical provider/SKU target before either retrieval ranker sees candidates."""

    async def search_applicable_governed(
        self,
        query: str,
        *,
        collection_id: str,
        allowed_access_refs: frozenset[str],
        target: Applicability,
        k: int,
    ) -> GovernedDocumentSearchResult: ...


class CloudReferenceReader(Protocol):
    """Recheck source/trust policy and same-body observations without mutating a release."""

    async def resolve(
        self, binding: KnowledgeReleaseBinding, source_id: str, now: datetime
    ) -> tuple[CloudSourceEvidence, bool]: ...


def citation_dates(source: CloudSourceEvidence, *, status: str, korean: bool) -> str:
    """Render immutable collection and verified check times separately from local import."""
    return citation_times(
        source.collected_at, source.check.checked_at, status=status, korean=korean
    )


def citation_times(
    collected_at: datetime, checked_at: datetime, *, status: str, korean: bool
) -> str:
    """Render only validated time values and server-owned freshness labels."""
    if collected_at.utcoffset() is None or checked_at.utcoffset() is None:
        raise ValueError("citation timestamps MUST be timezone-aware")
    collected = collected_at.isoformat()
    checked = checked_at.isoformat()
    labels = {
        "fresh": ("확인 시점 기준", "checked as of"),
        "refresh_due": ("갱신 확인 필요", "refresh due"),
        "stale": ("과거 참조용", "historical reference only"),
        "unknown": ("최신성 확인 불가", "freshness unknown"),
        "update_pending": ("새 원본 검토 대기", "source update pending"),
    }
    label = labels.get(status, labels["unknown"])[0 if korean else 1]
    if korean:
        return f"수집: {collected}; 원본 확인: {checked}; {label}. 실시간 리소스 관측이 아닙니다."
    return (
        f"Collected: {collected}; source checked: {checked}; {label}. "
        "Not a live resource observation."
    )
