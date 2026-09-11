from __future__ import annotations

from dataclasses import replace

import pytest
from fdai.shared.providers.behavior_knowledge import (
    EMBEDDING_DIM,
    BehaviorContent,
    BehaviorSource,
    BehaviorSpec,
)


def _source(*, source_kind: str = "code") -> BehaviorSource:
    return BehaviorSource(
        source_kind=source_kind,  # type: ignore[arg-type]
        path="services/core-control-plane/src/fdai/core/trust_router/router.py",
        symbol="TrustRouter.route",
        line_start=10,
        line_end=42,
        blob_sha="blob-1",
        authority_role="implementation",
    )


def _spec() -> BehaviorSpec:
    return BehaviorSpec(
        behavior_id="behavior.trust-routing",
        subject_kind="core",
        subject_id="trust-router",
        status="implemented",
        owner="TrustRouter",
        question_aliases=("How does trust routing work?",),
        trigger=("A normalized event arrives.",),
        preconditions=("Evidence is available.",),
        steps=("Select the lowest sufficient tier.",),
        outcomes=("A bounded route is returned.",),
        exclusions=("No execution authority.",),
        safety=("Ambiguity is held for review.",),
        sources=(_source(), _source(source_kind="test")),
        indexed_commit="commit-1",
        extractor_version="v1",
        source_manifest_hash="manifest-1",
        localized={
            "ko": BehaviorContent(
                trigger=("정규화된 이벤트가 도착합니다.",),
                preconditions=("근거를 사용할 수 있습니다.",),
                steps=("가장 낮은 충분한 계층을 선택합니다.",),
                outcomes=("범위가 제한된 경로를 반환합니다.",),
                exclusions=("실행 권한이 없습니다.",),
                safety=("모호하면 검토를 위해 보류합니다.",),
            )
        },
    )


@pytest.mark.parametrize(
    "change",
    [
        {"path": "/absolute/path.py"},
        {"path": "src/../secret.py"},
        {"symbol": ""},
        {"line_start": 0},
        {"line_start": 20, "line_end": 19},
        {"blob_sha": ""},
    ],
)
def test_behavior_source_rejects_unbounded_or_untracked_coordinates(
    change: dict[str, object],
) -> None:
    values = {
        "source_kind": "code",
        "path": "src/module.py",
        "symbol": "module.symbol",
        "line_start": 1,
        "line_end": 2,
        "blob_sha": "blob-1",
        "authority_role": "implementation",
        **change,
    }

    with pytest.raises(ValueError):
        BehaviorSource(**values)  # type: ignore[arg-type]


def test_behavior_source_citation_omits_internal_authority_metadata() -> None:
    source = _source()

    assert source.citation() == {
        "path": source.path,
        "symbol": source.symbol,
        "line_start": source.line_start,
        "line_end": source.line_end,
        "blob_sha": source.blob_sha,
    }
    assert source.manifest_record()["authority_role"] == "implementation"


@pytest.mark.parametrize(
    "field",
    [
        "behavior_id",
        "subject_kind",
        "subject_id",
        "owner",
        "indexed_commit",
        "extractor_version",
        "source_manifest_hash",
    ],
)
def test_behavior_spec_requires_stable_identity_fields(field: str) -> None:
    with pytest.raises(ValueError, match="MUST be non-empty"):
        spec = _spec()
        if field == "behavior_id":
            replace(spec, behavior_id="")
        elif field == "subject_kind":
            replace(spec, subject_kind="")
        elif field == "subject_id":
            replace(spec, subject_id="")
        elif field == "owner":
            replace(spec, owner="")
        elif field == "indexed_commit":
            replace(spec, indexed_commit="")
        elif field == "extractor_version":
            replace(spec, extractor_version="")
        else:
            replace(spec, source_manifest_hash="")


def test_behavior_spec_requires_aliases_sources_and_embedding_dimension() -> None:
    with pytest.raises(ValueError, match="question_aliases"):
        replace(_spec(), question_aliases=())
    with pytest.raises(ValueError, match="sources"):
        replace(_spec(), sources=())
    with pytest.raises(ValueError, match=str(EMBEDDING_DIM)):
        replace(_spec(), embedding=(0.0,))


def test_behavior_spec_exposes_test_backing_and_localized_search_text() -> None:
    spec = _spec()

    assert spec.test_backed is True
    assert "How does trust routing work?" in spec.search_text()
    assert "가장 낮은 충분한 계층을 선택합니다." in spec.search_text()
    assert "No execution authority." in spec.search_text()
