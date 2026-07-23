"""Authoritative built-in behavior contracts for Command Deck retrieval."""

# Structured catalog sentences intentionally preserve searchable phrases.
# ruff: noqa: E501

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence

from fdai.shared.providers.behavior_knowledge import (
    BehaviorContent,
    BehaviorSource,
    BehaviorSpec,
)

from .architecture_seeds import (
    ARCHITECTURE_SOURCE_PATHS,
    build_architecture_behavior_specs,
)

EXTRACTOR_VERSION = "behavior-seed-v1"

_BASE_SOURCE_PATHS = frozenset(
    {
        "rule-catalog/vocabulary/object-types/Issue.yaml",
        "src/fdai/agents/_framework/arbitration.py",
        "src/fdai/agents/forseti.py",
        "src/fdai/agents/odin.py",
        "src/fdai/agents/saga.py",
        "src/fdai/core/incident/registry.py",
        "tests/agents/test_arbitration.py",
        "tests/agents/test_wave2_governance.py",
        "tests/core/incident/test_incident_lifecycle.py",
    }
)
SEED_SOURCE_PATHS = _BASE_SOURCE_PATHS | ARCHITECTURE_SOURCE_PATHS


def build_seed_behavior_specs(
    *,
    indexed_commit: str,
    blob_shas: Mapping[str, str],
) -> tuple[BehaviorSpec, ...]:
    """Build built-in contracts when every allowlisted source has a blob."""
    if not indexed_commit:
        raise ValueError("indexed_commit MUST be non-empty")
    missing = sorted(SEED_SOURCE_PATHS - blob_shas.keys())
    if missing:
        raise ValueError(f"missing behavior source blobs: {', '.join(missing)}")

    incident_sources = (
        _source(blob_shas, "code", "src/fdai/core/incident/registry.py", "incident_id_for", 45, 71),
        _source(
            blob_shas,
            "code",
            "src/fdai/core/incident/registry.py",
            "IncidentRegistry.open_with_status",
            103,
            186,
        ),
        _source(
            blob_shas,
            "test",
            "tests/core/incident/test_incident_lifecycle.py",
            "test_incident_id_is_deterministic_over_key_set_permutations",
            27,
            45,
        ),
        _source(
            blob_shas,
            "test",
            "tests/core/incident/test_incident_lifecycle.py",
            "test_open_is_idempotent_and_merges_member_events",
            122,
            158,
        ),
    )
    odin_sources = (
        _source(
            blob_shas,
            "code",
            "src/fdai/agents/forseti.py",
            "Forseti.maybe_request_arbitration",
            113,
            201,
        ),
        _source(blob_shas, "code", "src/fdai/agents/odin.py", "Odin.arbitrate", 127, 174),
        _source(
            blob_shas,
            "code",
            "src/fdai/agents/_framework/arbitration.py",
            "MultiObjectiveArbiter.resolve",
            187,
            277,
        ),
        _source(
            blob_shas,
            "test",
            "tests/agents/test_arbitration.py",
            "test_forseti_requests_arbitration_on_conflicting_advice",
            19,
            35,
        ),
        _source(
            blob_shas,
            "test",
            "tests/agents/test_arbitration.py",
            "test_forseti_no_arbitration_on_unanimous_advice",
            37,
            50,
        ),
        _source(
            blob_shas,
            "test",
            "tests/agents/test_arbitration.py",
            "test_forseti_no_arbitration_on_single_domain",
            52,
            63,
        ),
        _source(
            blob_shas,
            "test",
            "tests/agents/test_arbitration.py",
            "test_close_call_escalates_to_hil",
            257,
            274,
        ),
        _source(
            blob_shas,
            "test",
            "tests/agents/test_arbitration.py",
            "test_unknown_domain_escalates_to_hil",
            276,
            282,
        ),
    )
    issue_sources = (
        _source(
            blob_shas,
            "code",
            "src/fdai/agents/saga.py",
            "Saga.escalate_to_github_issue",
            138,
            205,
        ),
        _source(
            blob_shas,
            "test",
            "tests/agents/test_wave2_governance.py",
            "test_saga_issue_dedup_creates_once_and_appends_comment_on_repeat",
            129,
            164,
        ),
        _source(
            blob_shas,
            "schema",
            "rule-catalog/vocabulary/object-types/Issue.yaml",
            "Issue.lifecycle.deduplication",
            1,
            47,
            authority_role="configuration",
        ),
    )

    base_specs = (
        _spec(
            behavior_id="incident.deterministic-id",
            subject_kind="object_behavior",
            subject_id="Incident.incident_id",
            status="implemented",
            owner="IncidentRegistry",
            aliases=(
                "Incident ID는 어떤 방식으로 생성돼?",
                "Incident ID는 어떻게 생성돼?",
                "How is an Incident ID generated?",
                "같은 이벤트가 왜 같은 Incident로 묶여?",
            ),
            trigger=("An incident is opened from one or more correlation keys.",),
            preconditions=("At least one non-empty correlation key is present.",),
            steps=(
                "Remove empty correlation keys.",
                "Deduplicate and sort the remaining keys.",
                "Join the canonical keys under the fdai.incident:// namespace.",
                "Generate UUID5 with NAMESPACE_URL from that canonical name.",
                "If the Incident already exists, merge new member event IDs "
                "instead of creating it again.",
            ),
            outcomes=(
                "The same key set produces the same Incident ID regardless of "
                "key order or duplicates.",
                "Repeated correlated events grow one existing Incident membership set.",
            ),
            exclusions=(
                "The Incident ID is not an external GitHub or Jira ticket number.",
                "The Incident ID is not the event correlation_id.",
            ),
            safety=(
                "An empty canonical key set is rejected.",
                "Concurrent duplicate opens use the persisted canonical Incident "
                "and fail closed on conflicts.",
            ),
            sources=incident_sources,
            indexed_commit=indexed_commit,
            ko=_content(
                trigger=("하나 이상의 correlation key로 Incident를 열 때 시작합니다.",),
                preconditions=("비어 있지 않은 correlation key가 하나 이상 있어야 합니다.",),
                steps=(
                    "빈 correlation key를 제거합니다.",
                    "남은 key의 중복을 제거하고 정렬합니다.",
                    "정규 key를 fdai.incident:// namespace 아래에서 결합합니다.",
                    "그 canonical name에 NAMESPACE_URL 기반 UUID5를 적용합니다.",
                    "기존 Incident가 있으면 새로 만들지 않고 member event ID를 병합합니다.",
                ),
                outcomes=(
                    "key 순서나 중복 여부와 무관하게 같은 key 집합은 같은 Incident ID를 만듭니다.",
                    "반복된 관련 이벤트는 기존 Incident의 membership을 확장합니다.",
                ),
                exclusions=(
                    "Incident ID는 GitHub 또는 Jira ticket number가 아닙니다.",
                    "Incident ID는 event correlation_id와 다른 식별자입니다.",
                ),
                safety=(
                    "정규화 후 key 집합이 비면 요청을 거부합니다.",
                    "동시 중복 open은 저장된 canonical Incident를 사용하고 충돌 시 안전하게 중단합니다.",
                ),
            ),
        ),
        _spec(
            behavior_id="odin.cross-domain-arbitration",
            subject_kind="agent_behavior",
            subject_id="Odin.arbitration",
            status="implemented",
            owner="Odin",
            aliases=(
                "언제 Odin이 개입해?",
                "Odin이 개입하지 않는 경우는?",
                "When does Odin intervene?",
                "When does Odin not intervene?",
            ),
            trigger=(
                "Two or more domains recommend different actions for the same resource.",
                "Forseti publishes object.arbitration-request for that conflict.",
            ),
            preconditions=(
                "The advice contains at least two distinct domains and conflicting "
                "recommendations.",
            ),
            steps=(
                "Forseti collects the conflicting domain recommendations and measured impacts.",
                "Odin scores each domain as configured weight multiplied by measured impact.",
                "Odin orders scores deterministically and emits an arbitration decision.",
            ),
            outcomes=(
                "A clear winner becomes the selected domain recommendation.",
                "A near tie, unknown domain, or non-finite impact is escalated "
                "to HIL instead of auto-selected.",
            ),
            exclusions=(
                "Odin does not intervene for single-domain advice.",
                "Odin does not intervene when all domain recommendations are unanimous.",
                "Odin does not participate in routine conversational collection.",
                "Portfolio review is designed documentation, not this implemented "
                "runtime arbitration loop.",
                "Temporal fairness is active only when a policy and decision history are injected.",
            ),
            safety=(
                "Ambiguous or corrupt measurements fail toward human review.",
                "Retrieved behavior evidence grants no approval or execution authority.",
            ),
            sources=odin_sources,
            indexed_commit=indexed_commit,
            ko=_content(
                trigger=(
                    "같은 resource에 둘 이상의 domain이 서로 다른 action을 추천할 때 시작합니다.",
                    "Forseti가 그 충돌에 대해 object.arbitration-request를 발행합니다.",
                ),
                preconditions=(
                    "서로 다른 domain이 둘 이상이고 recommendation이 실제로 충돌해야 합니다.",
                ),
                steps=(
                    "Forseti가 충돌 recommendation과 measured impact를 수집합니다.",
                    "Odin이 configured weight와 measured impact를 곱해 각 domain을 점수화합니다.",
                    "점수를 결정적으로 정렬하고 arbitration decision을 발행합니다.",
                ),
                outcomes=(
                    "명확한 승자가 있으면 해당 domain recommendation을 선택합니다.",
                    "near tie, unknown domain, non-finite impact는 자동 선택하지 않고 HIL로 보냅니다.",
                ),
                exclusions=(
                    "single-domain advice에는 Odin이 개입하지 않습니다.",
                    "모든 domain recommendation이 unanimous이면 Odin이 개입하지 않습니다.",
                    "일상적인 대화 수집에는 Odin이 참여하지 않습니다.",
                    "Portfolio review는 설계 문서 상태이며 이 runtime arbitration loop와 다릅니다.",
                    "Temporal fairness는 policy와 decision history가 주입된 경우에만 활성화됩니다.",
                ),
                safety=(
                    "모호하거나 손상된 측정값은 사람 검토로 안전하게 전환합니다.",
                    "검색된 behavior evidence는 승인 또는 실행 권한을 부여하지 않습니다.",
                ),
            ),
        ),
        _spec(
            behavior_id="issue.fingerprint-deduplication",
            subject_kind="object_behavior",
            subject_id="Issue.deduplication",
            status="implemented",
            owner="Saga",
            aliases=(
                "Issue는 어떤 기준으로 생성되고 중복은 어떻게 처리해?",
                "Issue 중복은 어떻게 처리해?",
                "How are duplicate Issues handled?",
            ),
            trigger=(
                "An agent handoff or an unhandled Bragi query asks Saga to materialize an Issue.",
            ),
            preconditions=(
                "The handoff provides the fields required to compute a deterministic fingerprint.",
            ),
            steps=(
                "Compute a fingerprint from intent category, resource type, normalized "
                "selector, primary agent, and failure reason code.",
                "Look up the fingerprint in Saga's Issue index.",
                "Create a new Issue only when the fingerprint is absent.",
                "For a repeat fingerprint, append a correlation-scoped comment and "
                "increment the occurrence count.",
            ),
            outcomes=(
                "Equivalent unresolved handoffs map to one Issue with a history of occurrences.",
                "The first and repeated occurrences retain distinct correlation references.",
            ),
            exclusions=(
                "A repeated fingerprint does not create another backing Issue.",
                "Issue deduplication is separate from Incident ID generation.",
            ),
            safety=(
                "The fingerprint contains normalized behavior fields rather than "
                "customer identifiers.",
                "Closing an Issue requires a separately recorded resolving capability promotion.",
            ),
            sources=issue_sources,
            indexed_commit=indexed_commit,
            ko=_content(
                trigger=(
                    "Agent handoff 또는 Bragi의 미처리 질문이 Saga에 Issue 생성을 요청할 때 시작합니다.",
                ),
                preconditions=("handoff에 deterministic fingerprint 계산 필드가 있어야 합니다.",),
                steps=(
                    "intent category, resource type, normalized selector, primary agent, failure reason code로 fingerprint를 계산합니다.",
                    "Saga의 Issue index에서 fingerprint를 조회합니다.",
                    "fingerprint가 없을 때만 새 Issue를 생성합니다.",
                    "반복 fingerprint면 correlation 범위 comment를 추가하고 occurrence count를 증가시킵니다.",
                ),
                outcomes=(
                    "동일한 미해결 handoff는 발생 이력을 가진 하나의 Issue로 모입니다.",
                    "첫 발생과 반복 발생은 서로 다른 correlation reference를 유지합니다.",
                ),
                exclusions=(
                    "반복 fingerprint는 backing Issue를 새로 만들지 않습니다.",
                    "Issue deduplication은 Incident ID 생성과 다른 동작입니다.",
                ),
                safety=(
                    "fingerprint는 customer identifier가 아니라 normalized behavior field를 사용합니다.",
                    "Issue 종료에는 별도로 기록된 resolving capability promotion이 필요합니다.",
                ),
            ),
        ),
    )
    return (
        *base_specs,
        *build_architecture_behavior_specs(
            indexed_commit=indexed_commit,
            blob_shas=blob_shas,
        ),
    )


def _source(
    blob_shas: Mapping[str, str],
    source_kind: str,
    path: str,
    symbol: str,
    line_start: int,
    line_end: int,
    *,
    authority_role: str | None = None,
) -> BehaviorSource:
    return BehaviorSource(
        source_kind=source_kind,  # type: ignore[arg-type]
        path=path,
        symbol=symbol,
        line_start=line_start,
        line_end=line_end,
        blob_sha=blob_shas[path],
        authority_role=authority_role
        or ("verification" if source_kind == "test" else "implementation"),  # type: ignore[arg-type]
    )


def _spec(
    *,
    behavior_id: str,
    subject_kind: str,
    subject_id: str,
    status: str,
    owner: str,
    aliases: tuple[str, ...],
    trigger: tuple[str, ...],
    preconditions: tuple[str, ...],
    steps: tuple[str, ...],
    outcomes: tuple[str, ...],
    exclusions: tuple[str, ...],
    safety: tuple[str, ...],
    sources: tuple[BehaviorSource, ...],
    indexed_commit: str,
    ko: BehaviorContent | None = None,
) -> BehaviorSpec:
    return BehaviorSpec(
        behavior_id=behavior_id,
        subject_kind=subject_kind,
        subject_id=subject_id,
        status=status,  # type: ignore[arg-type]
        owner=owner,
        question_aliases=aliases,
        trigger=trigger,
        preconditions=preconditions,
        steps=steps,
        outcomes=outcomes,
        exclusions=exclusions,
        safety=safety,
        sources=sources,
        indexed_commit=indexed_commit,
        extractor_version=EXTRACTOR_VERSION,
        source_manifest_hash=_manifest_hash(sources),
        localized={"ko": ko} if ko is not None else {},
    )


def _content(
    *,
    trigger: tuple[str, ...],
    preconditions: tuple[str, ...],
    steps: tuple[str, ...],
    outcomes: tuple[str, ...],
    exclusions: tuple[str, ...],
    safety: tuple[str, ...],
) -> BehaviorContent:
    return BehaviorContent(
        trigger=trigger,
        preconditions=preconditions,
        steps=steps,
        outcomes=outcomes,
        exclusions=exclusions,
        safety=safety,
    )


def _manifest_hash(sources: Sequence[BehaviorSource]) -> str:
    payload = [source.manifest_record() for source in sources]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


__all__ = ["EXTRACTOR_VERSION", "SEED_SOURCE_PATHS", "build_seed_behavior_specs"]
