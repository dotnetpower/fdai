"""Pinned source-date projection tests with explicit test-only read providers."""

from __future__ import annotations

import importlib.util
import socket
import sys
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import NoReturn, cast

import pytest
from fdai.core.knowledge.cloud_reference import citation_dates, citation_times
from fdai.core.knowledge.governed_document_reader import AuthorizedGovernedDocumentReader
from fdai.core.ontology_platform.governed_document_queries import (
    GovernedDocumentCollection,
    GovernedDocumentExcerpt,
)
from fdai.shared.contracts import DocumentPurpose, DocumentVersion
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.providers.document_ingestion import DocumentAccessProvider, DocumentMetadataStore
from fdai.shared.providers.knowledge import KnowledgeChunk
from fdai_core_service.semantic_turn_processor import (
    _answer_row_values,
    _render_governed_document_answer,
)
from fdai_service_contracts import cloud_knowledge as cloud
from fdai_service_contracts.cloud_knowledge_release import KnowledgeReleaseBinding

NOW = datetime(2026, 9, 14, 12, tzinfo=UTC)
COLLECTED = NOW - timedelta(days=60)
ORIGINAL_CHECK = NOW - timedelta(days=50)
TEXT = "Synthetic reference guidance"
LABELS = {
    "fresh": ("checked as of", "확인 시점 기준"),
    "refresh_due": ("refresh due", "갱신 확인 필요"),
    "stale": ("historical reference only", "과거 참조용"),
    "unknown": ("freshness unknown", "최신성 확인 불가"),
    "update_pending": ("source update pending", "새 원본 검토 대기"),
}


def _deny_io(*_args: object, **_kwargs: object) -> NoReturn:
    raise AssertionError("external I/O is forbidden in these synthetic tests")


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    for target, name in (
        (socket, "getaddrinfo"),
        (socket, "create_connection"),
        (socket.socket, "connect"),
        (socket.socket, "connect_ex"),
    ):
        monkeypatch.setattr(target, name, _deny_io)


@pytest.fixture
def helpers(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    path = Path(__file__).with_name("test_governed_document_reader.py")
    spec = importlib.util.spec_from_file_location("_cloud_reference_test_helpers", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def _source(checked_at: datetime, *, text: str = TEXT) -> cloud.CloudSourceEvidence:
    digest = cloud.content_digest(text.encode())
    check = cloud.SourceCheckReceipt(
        source_id="source-a",
        source_url="https://example.com/reference",
        checked_at=checked_at,
        outcome="unchanged",
        content_sha256=digest,
        equivalence="body_hash",
        collector_id="synthetic-collector",
    )
    return cloud.CloudSourceEvidence(
        source_id=check.source_id,
        source_url=check.source_url,
        source_sha256=digest,
        normalized_sha256=digest,
        collected_at=COLLECTED,
        source_updated_at=COLLECTED - timedelta(days=1),
        check=check,
        applicability=cloud.Applicability(resource_type="network", service_generation="v1"),
        policy=cloud.RefreshPolicy(),
        license_ref="synthetic-license",
    )


class _CloudReferences:
    """Return injected observations only; this fake does not prove trust or activation."""

    def __init__(self, source: cloud.CloudSourceEvidence, pending: bool) -> None:
        self.source = source
        self.pending = pending
        self.calls: list[tuple[KnowledgeReleaseBinding, str, datetime]] = []

    async def resolve(
        self, binding: KnowledgeReleaseBinding, source_id: str, now: datetime
    ) -> tuple[cloud.CloudSourceEvidence, bool]:
        self.calls.append((binding, source_id, now))
        return self.source, self.pending


@dataclass
class _Case:
    reader: AuthorizedGovernedDocumentReader
    references: _CloudReferences
    binding: KnowledgeReleaseBinding
    source: cloud.CloudSourceEvidence
    status: str

    async def search(self) -> GovernedDocumentCollection:
        return await self.reader.search(
            query="reference",
            principal_ref="operator-a",
            principal_role=CeilingRole.READER,
            principal_groups=frozenset({"group:responders"}),
            purpose="operations-review",
            limit=2,
        )


def _case(
    helpers: ModuleType,
    *,
    age: int = 1,
    pending: bool = False,
    status: str = "fresh",
    with_reference: bool = True,
) -> _Case:
    original = _source(ORIGINAL_CHECK)
    source = _source(NOW - timedelta(days=age))
    binding = KnowledgeReleaseBinding(
        release_id="synthetic-release",
        sequence=1,
        manifest_digest=cloud.content_digest(b"synthetic retained manifest"),
        registry_digest=cloud.content_digest(b"synthetic approved registry"),
        package_created_at=NOW - timedelta(days=2),
        imported_at=NOW - timedelta(hours=1),
        admission_expires_at=NOW + timedelta(hours=1),
        verified_key_id="synthetic-key",
        sources=(original,),
    )
    # A pre-existing READY metadata fixture is not an assertion that any worker ran.
    version = DocumentVersion.model_validate(
        helpers._version().model_dump()
        | {
            "cloud_knowledge": binding,
            "source_sha256": binding.manifest_digest,
            "purposes": (DocumentPurpose.KNOWLEDGE_BASE, DocumentPurpose.CLOUD_REFERENCE),
            "created_at": binding.imported_at,
            "updated_at": binding.imported_at,
        }
    )
    base_hit = cast(KnowledgeChunk, helpers._hit())
    hit = replace(
        base_hit,
        text=TEXT,
        metadata={**base_hit.metadata, "cloud_source": original.model_dump_json()},
    )
    references = _CloudReferences(source, pending)
    reader = AuthorizedGovernedDocumentReader(
        search=helpers._Search((hit,)),
        metadata=cast(DocumentMetadataStore, helpers._Metadata((version,))),
        access=cast(DocumentAccessProvider, helpers._Access()),
        scopes=helpers._Scopes(),
        clock=lambda: NOW,
        retrieval_mode="lexical",
        cloud_reference=references if with_reference else None,
    )
    return _Case(reader, references, binding, source, status)


async def test_typed_applicability_requires_prefilter_capability(helpers: ModuleType) -> None:
    case = _case(helpers)
    with pytest.raises(RuntimeError, match="applicability-aware"):
        await case.reader.search(
            query="reference",
            principal_ref="operator-a",
            principal_role=CeilingRole.READER,
            principal_groups=frozenset({"group:responders"}),
            purpose="operations-review",
            limit=2,
            target=case.source.applicability,
        )


@pytest.fixture(
    params=[
        (1, False, "fresh"),
        (7, False, "refresh_due"),
        (30, False, "stale"),
        (1, True, "update_pending"),
    ],
    ids=["fresh", "refresh_due", "stale", "update_pending"],
)
def reference_case(request: pytest.FixtureRequest, helpers: ModuleType) -> _Case:
    age, pending, status = cast(tuple[int, bool, str], request.param)
    return _case(helpers, age=age, pending=pending, status=status)


def _values(excerpt: GovernedDocumentExcerpt) -> dict[str, object]:
    assert excerpt.cloud_source is not None
    return asdict(excerpt) | {
        "record_kind": "excerpt",
        "cloud_source": excerpt.cloud_source.model_dump(mode="json"),
        "execution_authority": False,
    }


def _output(collection: GovernedDocumentCollection) -> dict[str, object]:
    summary = {
        "record_kind": "summary",
        "index_generation": collection.index_generation,
        "access_scope_digest": collection.access_scope_digest,
        "retrieval_mode": collection.retrieval_mode,
    }
    return {
        "source_complete": collection.complete,
        "source_truncation_reason": collection.limitation,
        "display_truncated": False,
        "rows": [
            {"row_id": "summary", "values": summary},
            *(
                {"row_id": excerpt.chunk_id, "values": _answer_row_values(_values(excerpt))}
                for excerpt in collection.excerpts
            ),
        ],
    }


@pytest.mark.parametrize("status", [*LABELS, "unrecognized"])
@pytest.mark.parametrize("korean", [False, True])
def test_citation_times_distinguishes_collection_check_and_status(
    status: str, korean: bool
) -> None:
    source = _source(NOW - timedelta(days=1))
    collected, checked = source.collected_at.isoformat(), source.check.checked_at.isoformat()
    label = LABELS.get(status, LABELS["unknown"])[int(korean)]
    expected = (
        f"수집: {collected}; 원본 확인: {checked}; {label}. 실시간 리소스 관측이 아닙니다."
        if korean
        else (
            f"Collected: {collected}; source checked: {checked}; {label}. "
            "Not a live resource observation."
        )
    )
    actual = citation_times(
        source.collected_at, source.check.checked_at, status=status, korean=korean
    )
    assert actual == expected
    assert citation_dates(source, status=status, korean=korean) == expected


@pytest.mark.parametrize("naive_field", ["collected", "checked"])
def test_citation_times_rejects_naive_dates(naive_field: str) -> None:
    collected = COLLECTED.replace(tzinfo=None) if naive_field == "collected" else COLLECTED
    checked = NOW.replace(tzinfo=None) if naive_field == "checked" else NOW
    with pytest.raises(ValueError, match="timezone-aware"):
        citation_times(collected, checked, status="fresh", korean=False)


async def test_reader_retains_source_dates_and_freshness(reference_case: _Case) -> None:
    result = await reference_case.search()
    assert result.complete and result.observed_at == NOW and result.retrieval_mode == "lexical"
    assert len(result.excerpts) == 1
    excerpt = result.excerpts[0]
    assert excerpt.cloud_source == reference_case.source
    assert excerpt.cloud_status == reference_case.status
    assert excerpt.instruction_authority is False
    assert reference_case.references.calls == [(reference_case.binding, "source-a", NOW)]
    assert reference_case.binding.sources[0].check.checked_at == ORIGINAL_CHECK
    assert reference_case.source.collected_at == COLLECTED
    assert reference_case.source.check.checked_at != reference_case.binding.imported_at


async def test_answer_row_values_preserves_source_dates(reference_case: _Case) -> None:
    excerpt = (await reference_case.search()).excerpts[0]
    original = _values(excerpt)
    projected = _answer_row_values(original)
    assert projected["cloud_collected_at"] == COLLECTED.isoformat()
    assert projected["cloud_checked_at"] == reference_case.source.check.checked_at.isoformat()
    assert projected["cloud_source_id"] == "source-a"
    assert projected["cloud_status"] == reference_case.status
    assert projected["instruction_authority"] is projected["execution_authority"] is False
    assert projected["redaction_applied"] is False
    assert "cloud_source" not in projected and "source_url" not in projected
    assert original["cloud_source"] == reference_case.source.model_dump(mode="json")


@pytest.mark.parametrize("korean", [False, True])
async def test_renderer_includes_bilingual_collect_check_status(
    reference_case: _Case, korean: bool
) -> None:
    output = _output(await reference_case.search())
    answer = _render_governed_document_answer(
        [output], korean=korean, output_shape="governed_document_excerpts"
    )
    assert answer is not None
    assert answer == _render_governed_document_answer(
        [output], korean=korean, output_shape="governed_document_excerpts"
    )
    collected_label = "수집" if korean else "Collected"
    checked_label = "원본 확인" if korean else "source checked"
    assert f"{collected_label}: {COLLECTED.isoformat()}" in answer
    assert f"{checked_label}: {reference_case.source.check.checked_at.isoformat()}" in answer
    assert LABELS[reference_case.status][int(korean)] in answer
    disclaimer = "실시간 리소스 관측이 아닙니다." if korean else "Not a live resource observation."
    assert disclaimer in answer
    assert reference_case.binding.imported_at.isoformat() not in answer
    assert "instruction_authority=false" in answer and "execution_authority=false" in answer
    assert TEXT in answer and "https://example.com" not in answer


async def test_reader_skips_unknown_future_source_dates(helpers: ModuleType) -> None:
    case = _case(helpers)
    case.references.source = _source(NOW + timedelta(seconds=1))
    assert (await case.search()).excerpts == ()
    assert case.references.calls == [(case.binding, "source-a", NOW)]


async def test_reader_requires_cloud_reference_verifier(helpers: ModuleType) -> None:
    case = _case(helpers, with_reference=False)
    with pytest.raises(RuntimeError, match="source verification is unavailable"):
        await case.search()
    assert case.references.calls == []


async def test_reader_rejects_changed_source_digest(helpers: ModuleType) -> None:
    case = _case(helpers)
    case.references.source = _source(NOW, text="Different synthetic source body")
    with pytest.raises(RuntimeError, match="source identity changed"):
        await case.search()
