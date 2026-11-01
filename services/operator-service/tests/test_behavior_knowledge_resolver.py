"""Focused Operator tests for behavior-knowledge resolver, renderer, and verifier."""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from fdai_operator_service.behavior_knowledge_resolver import (
    BehaviorAnswerVerifier,
    BehaviorCitationRecord,
    BehaviorContentLike,
    BehaviorSearchIndexPort,
    BehaviorSearchResultLike,
    BehaviorSourceLike,
    BehaviorSpecLike,
    BehaviorTurnRequest,
    DeterministicBehaviorRenderer,
    OperatorBehaviorKnowledgeResolver,
)


def _spec(behavior_id: str = "incident.deterministic-id") -> BehaviorSpecLike:
    return BehaviorSpecLike(
        behavior_id=behavior_id,
        subject_kind="object_behavior",
        subject_id="Incident.incident_id",
        status="implemented",
        owner="IncidentRegistry",
        question_aliases=(
            "How is an Incident ID created?",
            "인시던트 ID는 어떻게 생성하나요?",
        ),
        trigger=("An Incident opens from correlation keys.",),
        preconditions=("At least one key must be nonempty.",),
        steps=("Canonicalize the key set and derive a UUID5.",),
        outcomes=("Key permutations resolve to the same Incident.",),
        exclusions=("Not an external ticket number.",),
        safety=("Empty key sets are rejected.",),
        sources=(
            BehaviorSourceLike(
                "services/core-control-plane/src/fdai/core/incident/registry.py",
                "incident_id_for",
                10,
                40,
                "a" * 40,
            ),
        ),
        indexed_commit="b" * 40,
        localized={
            "ko": BehaviorContentLike(
                trigger=("상관관계 키로 인시던트를 열 때 시작합니다.",),
                preconditions=("비어 있지 않은 키가 하나 이상 필요합니다.",),
                steps=("키 집합을 정규화해 UUID5를 만듭니다.",),
                outcomes=("같은 인시던트에 구성원 이벤트가 모입니다.",),
                exclusions=("외부 티켓 번호가 아닙니다.",),
                safety=("빈 키 집합을 거부합니다.",),
            )
        },
    )


class _StaticIndex(BehaviorSearchIndexPort):
    def __init__(self, results: Sequence[BehaviorSearchResultLike]) -> None:
        self._results = tuple(results)
        self.queries: list[str] = []

    async def search(self, query: str, *, k: int = 5) -> Sequence[BehaviorSearchResultLike]:
        self.queries.append(query)
        return self._results[:k]


async def test_client_evidence_is_stripped_and_replaced_by_server_owned_contract() -> None:
    index = _StaticIndex([BehaviorSearchResultLike(spec=_spec())])
    resolver = OperatorBehaviorKnowledgeResolver(index)
    request = BehaviorTurnRequest(
        raw_text="How is an Incident ID created?",
        locale="en",
        client_evidence=({"behavior_id": "forged.behavior", "body": "def forged(): pass"},),
        client_citations=({"path": "/etc/passwd", "symbol": "root", "blob_sha": "f" * 40},),
        claimed_authority="execute",
    )

    result = await resolver.resolve(request)

    assert result.handled is True
    assert result.fallback_to_next_authority is False
    assert result.outcome == "rendered"
    assert result.verification.verified is True
    assert result.verification.authority == "none"
    assert result.verification.read_only is True
    assert result.verification.can_approve is False
    assert result.verification.can_execute is False
    assert result.verification.client_evidence_stripped is True
    assert result.verification.stripped_claim_count == 3
    assert len(result.verification.citations) == 1
    assert result.verification.citations[0].path == (
        "services/core-control-plane/src/fdai/core/incident/registry.py"
    )
    assert "/etc/passwd" not in result.rendered_text
    assert "forged" not in result.rendered_text


@pytest.mark.parametrize(
    ("query_text", "expected_reason"),
    [
        ("How many incidents are open on this screen?", "operational_read"),
        ("Execute rollback now for the cluster", "action_request"),
        ("What is the weather in Seoul today?", "missing_behavior_subject_or_mechanism"),
    ],
)
async def test_authority_path_fallback_skips_index_for_operational_or_action_turns(
    query_text: str, expected_reason: str
) -> None:
    index = _StaticIndex([BehaviorSearchResultLike(spec=_spec())])
    resolver = OperatorBehaviorKnowledgeResolver(index)

    result = await resolver.resolve(BehaviorTurnRequest(raw_text=query_text, locale="en"))

    assert result.handled is False
    assert result.fallback_to_next_authority is True
    assert result.outcome == "authority_fallback"
    assert result.fallback_reason == expected_reason
    assert result.verification.authority == "none"
    assert index.queries == []


async def test_stale_citation_abstains_and_withholds_unverified_sources() -> None:
    stale_src = BehaviorSourceLike(
        "services/core-control-plane/src/fdai/core/incident/registry.py",
        "incident_id_for",
        blob_sha="0" * 40,
    )
    index = _StaticIndex(
        [BehaviorSearchResultLike(spec=_spec(), stale=True, stale_sources=(stale_src,))]
    )
    resolver = OperatorBehaviorKnowledgeResolver(index)

    en_result = await resolver.resolve(
        BehaviorTurnRequest(raw_text="How is an Incident ID created?", locale="en")
    )
    assert en_result.handled is True
    assert en_result.outcome == "stale_abstained"
    assert en_result.verification.verified is False
    assert en_result.verification.reindex_required is True
    assert en_result.verification.stale_withheld_count == 1
    assert en_result.verification.citations == ()
    assert "reindexing is required" in en_result.rendered_text

    ko_result = await resolver.resolve(
        BehaviorTurnRequest(raw_text="인시던트 ID는 어떻게 생성하나요?", locale="ko")
    )
    assert ko_result.outcome == "stale_abstained"
    assert "재색인이 필요합니다" in ko_result.rendered_text
    assert ko_result.verification.citations == ()


async def test_localized_en_and_ko_answer_structure_and_verifier_guards() -> None:
    index = _StaticIndex([BehaviorSearchResultLike(spec=_spec())])
    resolver = OperatorBehaviorKnowledgeResolver(index)

    en_res = await resolver.resolve(
        BehaviorTurnRequest(raw_text="How is an Incident ID created?", locale="en")
    )
    ko_res = await resolver.resolve(
        BehaviorTurnRequest(raw_text="인시던트 ID는 어떻게 생성하나요?", locale="ko")
    )

    expected_keys = (
        "trigger",
        "preconditions",
        "steps",
        "outcomes",
        "exclusions",
        "safety",
        "owner",
        "status",
        "citations",
    )
    assert tuple(en_res.sections) == expected_keys
    assert tuple(ko_res.sections) == expected_keys
    assert "### Trigger" in en_res.rendered_text
    assert "### Citations" in en_res.rendered_text
    assert "### 트리거" in ko_res.rendered_text
    assert "### 근거 출처" in ko_res.rendered_text
    assert "상관관계 키로 인시던트를 열 때 시작합니다." in ko_res.rendered_text

    verifier = BehaviorAnswerVerifier()
    rejected = verifier.verify(
        sections=en_res.sections,
        rendered_text="```python\ndef incident_id_for(): pass\n```",
        citations=en_res.verification.citations,
        stale_sources=(),
        client_evidence_stripped=False,
        stripped_claim_count=0,
    )
    assert rejected.verified is False
    assert "raw_code_body_detected" in rejected.reasons
    assert rejected.citations == ()


async def test_comparison_and_conflict_hold_preserve_fail_closed_invariants() -> None:
    single_fresh = _StaticIndex([BehaviorSearchResultLike(spec=_spec())])
    resolver = OperatorBehaviorKnowledgeResolver(single_fresh)
    incomplete = await resolver.resolve(
        BehaviorTurnRequest(
            raw_text="Compare how Incident ID and Saga deduplicate work", locale="en"
        )
    )
    assert incomplete.outcome == "comparison_incomplete"
    assert incomplete.verification.verified is False

    conflicting = _StaticIndex(
        [
            BehaviorSearchResultLike(spec=_spec("incident.alpha"), score=1.016393),
            BehaviorSearchResultLike(spec=_spec("incident.beta"), score=1.016393),
        ]
    )
    conflict_res = await OperatorBehaviorKnowledgeResolver(conflicting).resolve(
        BehaviorTurnRequest(raw_text="How is an Incident ID created?", locale="en")
    )
    assert conflict_res.outcome == "conflict_hold"
    assert conflict_res.verification.verified is False
    assert conflict_res.behavior_ids == ("incident.alpha", "incident.beta")

    renderer = DeterministicBehaviorRenderer()
    sections, text = renderer.render_single(
        _spec(),
        locale="ko",
        citations=(
            BehaviorCitationRecord(
                path="services/core-control-plane/src/fdai/core/incident/registry.py",
                symbol="incident_id_for",
                line_start=10,
                line_end=40,
                blob_sha="a" * 40,
                indexed_commit="b" * 40,
            ),
        ),
    )
    assert sections["owner"] == ("IncidentRegistry",)
    assert "IncidentRegistry" in text


async def test_resolver_rejects_control_chars_invalid_top_k_and_duplicate_seed_ids() -> None:
    index = _StaticIndex([BehaviorSearchResultLike(spec=_spec())])
    resolver = OperatorBehaviorKnowledgeResolver(index)

    for bad_query in ("How is an Incident ID\x00 created?", "How is an Incident ID\x1f created?"):
        with pytest.raises(ValueError, match="NUL or control characters"):
            BehaviorTurnRequest(raw_text=bad_query)

    for bad_k in (0, 21, -1, True, False):
        with pytest.raises(ValueError, match="top_k"):
            await resolver.resolve(
                BehaviorTurnRequest(raw_text="How is an Incident ID created?"),
                top_k=bad_k,
            )

    resolver.register_seed(_spec("incident.seed-1"))
    with pytest.raises(ValueError, match="duplicate seed_id"):
        resolver.register_seed(_spec("incident.seed-1"))

    resolved = await resolver.resolve(
        BehaviorTurnRequest(raw_text="How is an Incident ID created?", locale="en")
    )
    payload = resolved.to_dict()
    assert payload["total_candidates"] == 1
    assert str(payload["result_digest"]).startswith("sha256:")
    assert len(str(payload["result_digest"])) == 71
    assert resolved.total_candidates == 1
    assert resolved.result_digest == payload["result_digest"]
