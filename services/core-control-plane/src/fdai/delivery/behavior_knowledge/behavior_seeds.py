"""Authoritative, read-only reference behavior declarations.

These describe repository behavior, not observations of a tenant or grants of
authority. Source coordinates and Git blobs are resolved by the seed generator.
"""

# Structured catalog sentences preserve reviewable bilingual meaning.
# ruff: noqa: E501

from __future__ import annotations

from dataclasses import dataclass

from fdai.shared.providers.behavior_knowledge import BehaviorContent, BehaviorStatus

CORE = "services/core-control-plane/src/fdai/"
TEST = "services/core-control-plane/tests/"


@dataclass(frozen=True, slots=True)
class SeedRef:
    kind: str
    path: str
    symbol: str


@dataclass(frozen=True, slots=True)
class Seed:
    behavior_id: str
    subject_id: str
    status: BehaviorStatus
    owner: str
    aliases: tuple[str, ...]
    english: BehaviorContent
    korean: BehaviorContent
    refs: tuple[SeedRef, ...]
    subject_kind: str = "architecture_behavior"


def _text(
    trigger: str, preconditions: str, steps: str, outcomes: str, exclusions: str, safety: str
) -> BehaviorContent:
    return BehaviorContent(
        trigger=(trigger,),
        preconditions=(preconditions,),
        steps=(steps,),
        outcomes=(outcomes,),
        exclusions=(exclusions,),
        safety=(safety,),
    )


def _code(path: str, symbol: str) -> SeedRef:
    return SeedRef("code", CORE + path, symbol)


def _test(path: str, symbol: str) -> SeedRef:
    return SeedRef("test", TEST + path, symbol)


SEEDS: tuple[Seed, ...] = (
    Seed(
        "incident.deterministic-id",
        "Incident.incident_id",
        "implemented",
        "IncidentRegistry",
        ("How is an Incident ID created?", "인시던트 ID는 어떻게 생성하나요?"),
        _text(
            "An Incident opens from correlation keys.",
            "At least one key must be nonempty.",
            "Canonicalize the key set and derive a UUID5; merge members on repeated opens.",
            "Key permutations resolve to the same Incident and accumulate member events.",
            "The Incident ID is neither an external ticket number nor an event correlation ID.",
            "Empty key sets are rejected; persisted duplicate opens do not create a second Incident.",
        ),
        _text(
            "상관관계 키로 인시던트를 열 때 시작합니다.",
            "비어 있지 않은 키가 하나 이상 필요합니다.",
            "키 집합을 정규화해 UUID5를 만들고 다시 열면 구성원 이벤트를 병합합니다.",
            "키 순서와 중복에 관계없이 같은 인시던트에 구성원 이벤트가 모입니다.",
            "인시던트 ID는 외부 티켓 번호나 이벤트 상관관계 ID가 아닙니다.",
            "빈 키 집합을 거부하고 중복 요청으로 두 번째 인시던트를 만들지 않습니다.",
        ),
        (
            _code("core/incident/registry.py", "incident_id_for"),
            _code("core/incident/registry.py", "IncidentRegistry.open_with_status"),
            _test(
                "core/incident/test_incident_lifecycle.py",
                "test_incident_id_is_deterministic_over_key_set_permutations",
            ),
            _test(
                "core/incident/test_incident_lifecycle.py",
                "test_open_is_idempotent_and_merges_member_events",
            ),
        ),
        subject_kind="object_behavior",
    ),
    Seed(
        "odin.cross-domain-arbitration",
        "Odin.arbitration",
        "implemented",
        "Odin",
        ("When does Odin intervene?", "Odin이 개입하지 않는 경우는 언제인가요?"),
        _text(
            "Forseti requests arbitration for a cross-domain conflict.",
            "Conflicting grounded objective effects, or conflicting advice without that evidence, are required.",
            "Forseti publishes a request; Odin weighs eligible options and checks for close calls.",
            "A clear eligible recommendation is selected; ambiguous or unknown domains go to human review.",
            "Single-domain and unanimous advice do not trigger arbitration; portfolio review is not established here.",
            "Arbitration evidence never approves or executes an action.",
        ),
        _text(
            "영역 간 충돌이 있으면 Forseti가 중재를 요청합니다.",
            "근거가 있는 목표 효과가 충돌하거나, 그 근거가 없을 때 권고가 충돌해야 합니다.",
            "Forseti가 요청을 발행하고 Odin이 적격 선택지와 박빙 여부를 검토합니다.",
            "명확한 적격 권고를 선택하고 모호하거나 알 수 없는 영역은 사람에게 검토를 맡깁니다.",
            "단일 영역이나 만장일치 권고는 중재하지 않으며 이 항목은 포트폴리오 검토를 입증하지 않습니다.",
            "중재 근거는 액션의 승인이나 실행 권한을 부여하지 않습니다.",
        ),
        (
            _code(
                "agents/_framework/forseti_arbitration.py",
                "ForsetiArbitrationMixin.maybe_request_arbitration",
            ),
            _code("agents/odin.py", "Odin.arbitrate"),
            _code("agents/_framework/arbitration.py", "MultiObjectiveArbiter.resolve"),
            _test(
                "agents/test_arbitration.py",
                "test_forseti_requests_arbitration_on_conflicting_advice",
            ),
            _test("agents/test_arbitration.py", "test_forseti_no_arbitration_on_single_domain"),
            _test("agents/test_arbitration.py", "test_close_call_escalates_to_hil"),
        ),
        subject_kind="agent_behavior",
    ),
    Seed(
        "issue.fingerprint-deduplication",
        "Issue.deduplication",
        "implemented",
        "Saga",
        ("How are repeated Issues handled?", "Issue 중복은 어떻게 처리하나요?"),
        _text(
            "An unresolved agent handoff reaches Saga.",
            "A normalized handoff fingerprint is available.",
            "Find an open matching Issue; create once or append a correlation-scoped occurrence.",
            "Repeated handoffs share the Issue while retaining separate occurrence references.",
            "An Issue fingerprint is not an Incident ID or a license to close an Issue.",
            "Closure requires a separate resolving promotion and regression window.",
        ),
        _text(
            "해결되지 않은 에이전트 인계가 Saga에 도착하면 시작합니다.",
            "정규화된 인계 지문이 필요합니다.",
            "열린 Issue의 지문을 비교하고 처음에만 만들며 재발 시 상관관계별 기록을 추가합니다.",
            "반복 인계는 Issue를 공유하지만 각 발생의 참조는 따로 보존합니다.",
            "Issue 지문은 인시던트 ID가 아니며 Issue를 닫는 권한도 아닙니다.",
            "종료에는 별도 해결 기능 승격과 회귀 검증 구간이 필요합니다.",
        ),
        (
            _code("agents/saga.py", "Saga.escalate_to_github_issue"),
            _test(
                "agents/test_wave2_governance.py",
                "test_saga_issue_dedup_creates_once_and_appends_comment_on_repeat",
            ),
            SeedRef(
                "schema",
                "rule-catalog/vocabulary/object-types/Issue.yaml",
                "lifecycle.deduplication",
            ),
        ),
        subject_kind="object_behavior",
    ),
    Seed(
        "architecture.trust-tier-routing",
        "TrustRouter.route",
        "implemented",
        "TrustRouter",
        ("How does the trust router choose a tier?", "신뢰 라우터는 계층을 어떻게 선택하나요?"),
        _text(
            "A validated Event reaches the trust router.",
            "The deterministic RuleIndex is loaded.",
            "Derive the resource type; select T0 for a rule match, T1 for no match, or abstain.",
            "Return a tier or abstention with the reason and candidate rule IDs.",
            "This router does not invoke a tier or directly return T2.",
            "A missing resource type leads to abstention rather than inference.",
        ),
        _text(
            "검증된 Event가 신뢰 라우터에 도착하면 시작합니다.",
            "결정적 RuleIndex가 로드되어야 합니다.",
            "리소스 유형을 구해 규칙이 맞으면 T0, 없으면 T1, 유형이 없으면 기권합니다.",
            "이유와 후보 규칙 ID를 포함한 계층 또는 기권 결과를 반환합니다.",
            "이 라우터는 계층을 실행하거나 T2를 직접 반환하지 않습니다.",
            "리소스 유형이 없으면 추측하지 않고 기권합니다.",
        ),
        (
            _code("core/trust_router/__init__.py", "TrustRouter.route"),
            _test(
                "core/trust_router/test_trust_router.py",
                "test_routes_to_t0_when_resource_type_matches_a_rule",
            ),
        ),
    ),
    Seed(
        "architecture.t2-quality-gate",
        "T2.QualityGate.grounding.cross_check",
        "implemented",
        "QualityGate",
        ("What checks does a T2 proposal pass?", "T2 제안은 어떤 검증을 통과해야 하나요?"),
        _text(
            "A T2 proposal reaches the quality gate.",
            "Verifier and grounding are required.",
            "Verify deterministically, check cited grounding, then cross-check model agreement.",
            "Only an eligible result may proceed to the risk gate.",
            "One model response cannot authorize execution.",
            "Missing grounding abstains and disagreement fails closed.",
        ),
        _text(
            "T2 제안이 품질 검증기에 도착하면 시작합니다.",
            "검증기와 인용할 근거가 필요합니다.",
            "결정적으로 검증하고 인용 근거를 확인한 다음 모델 간 합의를 교차 검사합니다.",
            "적격 결과만 위험 관문으로 진행할 수 있습니다.",
            "모델 응답 하나로 실행을 승인할 수 없습니다.",
            "근거가 없으면 기권하고 의견이 다르면 안전하게 중단합니다.",
        ),
        (
            _code("core/quality_gate/gate.py", "QualityGate.evaluate"),
            _test(
                "core/quality_gate/test_gate.py",
                "test_no_grounded_citation_when_require_grounding_true",
            ),
            _test(
                "core/quality_gate/test_gate.py",
                "test_cross_check_disagreement_below_quorum_becomes_disagree",
            ),
        ),
    ),
    Seed(
        "architecture.human-approval-separation",
        "HIL.Var.approval.no_self_approval",
        "implemented",
        "RiskGate / Var",
        ("Can an approver approve their own action?", "자기 액션을 스스로 승인할 수 있나요?"),
        _text(
            "A risk decision calls for human approval.",
            "Var has a pending approval ticket.",
            "Verify distinct approver identity and quorum before emitting an approval event.",
            "Valid human approval permits the separately gated action path to continue.",
            "An approver cannot execute with Thor's identity or self-approve.",
            "Rejection, duplicate approval, or missing quorum grants no execution authority.",
        ),
        _text(
            "위험 판단에 사람 승인이 필요하면 시작합니다.",
            "Var에 보류 중인 승인 티켓이 있어야 합니다.",
            "승인자 신원과 정족수를 확인한 뒤 승인 이벤트를 발행합니다.",
            "유효한 사람 승인 후에도 별도의 관문을 통과해야 액션이 진행됩니다.",
            "승인자는 Thor 신원으로 실행하거나 자기 액션을 승인할 수 없습니다.",
            "거부, 중복 승인 또는 정족수 부족은 실행 권한을 부여하지 않습니다.",
        ),
        (
            _code("agents/var.py", "Var.decide"),
            _test(
                "agents/test_chat_to_pipeline_e2e.py",
                "test_var_rejects_blank_approver_and_trims_self_approval",
            ),
        ),
    ),
    Seed(
        "architecture.shadow-promotion",
        "ActionPromotionRegistry.consider_promotion",
        "implemented",
        "ActionPromotionRegistry",
        (
            "When can an ActionType leave shadow mode?",
            "ActionType은 언제 shadow-mode를 벗어나나요?",
        ),
        _text(
            "Measured shadow evidence is submitted for an ActionType.",
            "The promotion registry has the action and its governing checks.",
            "Evaluate the promotion conditions; demote when measured conditions regress.",
            "Only the eligible ActionType may enter enforce mode.",
            "Promotion does not edit its ActionType definition.",
            "Unknown or regressing actions remain in, or return to, shadow mode.",
        ),
        _text(
            "ActionType의 shadow 측정 근거가 제출되면 시작합니다.",
            "승격 레지스트리에 액션과 적용할 검사 조건이 있어야 합니다.",
            "승격 조건을 평가하고 측정 조건이 악화되면 강등합니다.",
            "적격 ActionType만 enforce 모드로 전환할 수 있습니다.",
            "승격은 ActionType 정의를 수정하지 않습니다.",
            "알 수 없거나 조건이 악화된 액션은 shadow 모드에 머물거나 되돌아갑니다.",
        ),
        (
            _code("core/risk_gate/gate.py", "ActionPromotionRegistry.consider_promotion"),
            _test(
                "core/risk_gate/test_gate.py",
                "test_promotion_registry_promotes_when_metrics_pass_gate",
            ),
            _test(
                "core/risk_gate/test_gate.py",
                "test_promotion_registry_demotes_when_metrics_regress",
            ),
        ),
    ),
    Seed(
        "architecture.executor-safety",
        "ShadowExecutor.execute",
        "implemented",
        "ShadowExecutor / Thor",
        (
            "How does the shadow executor avoid duplicate actions?",
            "shadow 실행기는 중복 액션을 어떻게 막나요?",
        ),
        _text(
            "A gated Action and Rule reach the shadow executor.",
            "The request must satisfy its declared scope and safeguards.",
            "Check idempotency, lock, blast radius, and renderability before publication.",
            "An eligible shadow delivery publishes a bounded proposal and audit result.",
            "The shadow executor does not apply an enforce-mode substrate mutation.",
            "Duplicate keys and failed invariants do not create a second mutation.",
        ),
        _text(
            "관문을 통과한 액션과 규칙이 shadow 실행기에 도착하면 시작합니다.",
            "요청은 선언된 범위와 안전장치를 충족해야 합니다.",
            "발행 전에 멱등성, 잠금, 영향 범위 및 렌더링 가능 여부를 검사합니다.",
            "적격 shadow 전달은 범위가 제한된 제안과 감사 결과를 발행합니다.",
            "shadow 실행기는 enforce 모드의 기반 리소스를 변경하지 않습니다.",
            "중복 키와 안전장치 실패는 두 번째 변경을 만들지 않습니다.",
        ),
        (
            _code("core/executor/executor.py", "ShadowExecutor.execute"),
            _test("core/executor/test_executor.py", "test_second_delivery_of_same_key_is_deduped"),
        ),
    ),
    Seed(
        "architecture.console-identity-boundary",
        "Console.Browser.Principal.Executor.Identity.Thor.Azure.Approval.Button.Substrate.Mutation",
        "designed",
        "Operator API / Thor",
        ("Does the browser hold the executor identity?", "브라우저가 실행기 신원을 갖나요?"),
        _text(
            "An operator reads or proposes work through Console.",
            "Human and workload identities are distinct by design.",
            "Operator API checks its own principal; execution belongs to the isolated executor.",
            "The design keeps a console compromise from automatically obtaining executor credentials.",
            "A browser button is not a substrate execution path.",
            "The instruction describes the boundary, not a current runtime attestation.",
        ),
        _text(
            "운영자가 Console에서 조회하거나 작업을 제안하면 시작합니다.",
            "설계상 사람 신원과 워크로드 신원을 분리해야 합니다.",
            "Operator API는 자체 주체를 확인하고 실행은 격리된 실행기가 맡습니다.",
            "설계는 Console 침해로 실행기 자격 증명이 자동 노출되지 않도록 구분합니다.",
            "브라우저 버튼은 기반 리소스의 실행 경로가 아닙니다.",
            "이 지침은 경계를 설명할 뿐 현재 런타임 검증을 입증하지 않습니다.",
        ),
        (
            SeedRef(
                "doc",
                ".github/instructions/app-shape.instructions.md",
                "Layer Boundaries (security)",
            ),
        ),
    ),
    Seed(
        "architecture.event-ingest-dedup",
        "EventIngest.ingest",
        "implemented",
        "EventIngest / Huginn",
        ("What happens to duplicate events?", "중복 이벤트는 어떻게 처리하나요?"),
        _text(
            "A raw or validated event reaches EventIngest.",
            "An idempotency key is present in the bounded deduplication window.",
            "Normalize and validate; suppress keys already in the in-process window.",
            "Recent redelivery stops before routing.",
            "This bounded cache is not an all-history durable ledger.",
            "Downstream executor idempotency remains a distinct safety boundary.",
        ),
        _text(
            "원시 또는 검증된 이벤트가 EventIngest에 도착하면 시작합니다.",
            "멱등성 키와 범위가 제한된 중복 제거 구간이 필요합니다.",
            "정규화하고 검증한 뒤 메모리 구간에 이미 있는 키를 억제합니다.",
            "최근에 다시 전달된 이벤트는 라우팅 전에 멈춥니다.",
            "이 메모리 캐시는 모든 이력을 보관하는 영속 원장이 아닙니다.",
            "후속 실행기의 멱등성은 별개의 안전 경계로 유지됩니다.",
        ),
        (
            _code("core/event_ingest/__init__.py", "EventIngest.ingest"),
            _test(
                "core/event_ingest/test_event_ingest.py",
                "test_duplicate_idempotency_key_returns_none",
            ),
        ),
    ),
    Seed(
        "architecture.vidar-rollback",
        "Vidar.rollback",
        "implemented",
        "Vidar",
        ("How does Vidar handle rollback?", "Vidar는 롤백을 어떻게 처리하나요?"),
        _text(
            "Vidar receives a failed ActionRun.",
            "A corresponding recovery path is available.",
            "Attempt a bounded rollback and report the result to the action lifecycle.",
            "Success records rolled_back; unavailable recovery produces explicit failure evidence.",
            "Vidar does not perform the forward action.",
            "A duplicate correlation does not roll back twice.",
        ),
        _text(
            "실패한 ActionRun을 Vidar가 받으면 시작합니다.",
            "대응하는 복구 경로가 있어야 합니다.",
            "범위가 제한된 롤백을 시도하고 결과를 액션 수명 주기에 보고합니다.",
            "성공 시 rolled_back을 기록하고 복구할 수 없으면 실패 근거를 명시합니다.",
            "Vidar는 정방향 액션을 실행하지 않습니다.",
            "같은 상관관계에 대해 롤백을 두 번 실행하지 않습니다.",
        ),
        (
            _code("agents/vidar.py", "Vidar.rollback"),
            _test("agents/test_wave3_pipeline.py", "test_thor_triggers_vidar_rollback_on_failure"),
            _test(
                "agents/test_wave3_pipeline.py", "test_vidar_rollback_is_idempotent_per_correlation"
            ),
        ),
    ),
    Seed(
        "architecture.bragi-translator",
        "Bragi.ask",
        "implemented",
        "Bragi",
        ("Can Bragi execute a command?", "Bragi는 명령을 직접 실행하나요?"),
        _text(
            "An operator asks a question or gives an action-shaped request.",
            "The request must pass the typed conversation boundary.",
            "Render read evidence or return proposal metadata to the typed action pipeline.",
            "A read answer or a separately governed action proposal results.",
            "Bragi does not directly call an executor.",
            "Unknown ownership abstains instead of manufacturing authority.",
        ),
        _text(
            "운영자가 질문하거나 액션 형태의 요청을 하면 시작합니다.",
            "요청은 타입이 정해진 대화 경계를 통과해야 합니다.",
            "읽기 근거를 표현하거나 제안 메타데이터를 타입이 정해진 액션 경로로 전달합니다.",
            "읽기 답변이나 별도 관리되는 액션 제안을 반환합니다.",
            "Bragi는 실행기를 직접 호출하지 않습니다.",
            "소유자가 불분명하면 권한을 만들지 않고 기권합니다.",
        ),
        (
            _code("agents/bragi.py", "Bragi.ask"),
            _test(
                "agents/test_conversational_port.py",
                "test_ask_refuses_action_intent_and_routes_to_typed_pipeline",
            ),
        ),
    ),
    Seed(
        "architecture.local-evidence-parity",
        "LocalAzureTruthContract",
        "designed",
        "Operator API composition",
        (
            "Can local Console use synthetic operational evidence?",
            "로컬 Console이 합성 운영 근거를 써도 되나요?",
        ),
        _text(
            "An interactive local session requests operational evidence.",
            "The corresponding authoritative source must be available.",
            "Read the real source or explicitly mark its absence as unavailable.",
            "The design preserves attribution without claiming live readiness from a fixture.",
            "Pytest examples and catalog definitions are not observed tenant state.",
            "This documented contract is not a current operational receipt.",
        ),
        _text(
            "대화형 로컬 세션이 운영 근거를 요청하면 시작합니다.",
            "해당하는 권위 있는 출처를 사용할 수 있어야 합니다.",
            "실제 출처를 조회하고 없으면 사용할 수 없다고 명시합니다.",
            "설계는 시험 자료로 실제 준비 상태를 주장하지 않고 출처를 보존합니다.",
            "pytest 예제와 카탈로그 정의는 관측된 테넌트 상태가 아닙니다.",
            "이 문서화된 계약은 현재 운영 증적이 아닙니다.",
        ),
        (
            SeedRef(
                "doc",
                ".github/instructions/app-shape.instructions.md",
                "Local Azure Truth Contract (MUST)",
            ),
        ),
    ),
)
