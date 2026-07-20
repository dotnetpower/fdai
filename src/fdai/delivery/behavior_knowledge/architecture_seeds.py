"""Grounded architecture behavior contracts beyond the initial object flows."""

# Structured catalog sentences intentionally preserve searchable phrases.
# ruff: noqa: E501

from __future__ import annotations

from collections.abc import Mapping

from fdai.shared.providers.behavior_knowledge import BehaviorSpec

from ._architecture_seed_support import (
    ARCHITECTURE_SOURCE_PATHS,
    EXTRACTOR_VERSION,
)
from ._architecture_seed_support import (
    content as _content,
)
from ._architecture_seed_support import (
    source as _source,
)
from ._architecture_seed_support import (
    spec as _spec,
)


def build_architecture_behavior_specs(
    *,
    indexed_commit: str,
    blob_shas: Mapping[str, str],
) -> tuple[BehaviorSpec, ...]:
    """Build architecture contracts when every required source is tracked."""
    missing = sorted(ARCHITECTURE_SOURCE_PATHS - blob_shas.keys())
    if missing:
        raise ValueError(f"missing architecture behavior source blobs: {', '.join(missing)}")

    return (
        _spec(
            behavior_id="architecture.trust-tier-routing",
            subject_id="TrustRouter.route",
            status="implemented",
            owner="TrustRouter",
            aliases=(
                "이벤트는 언제 T0로 가고 언제 T1로 가?",
                "resource type이 없으면 trust router는 어떻게 해?",
                "How does the trust router select T0 or T1?",
            ),
            trigger=("A validated Event reaches the trust router.",),
            preconditions=("The router receives the loaded deterministic RuleIndex.",),
            steps=(
                "Derive resource_type from payload.resource.type or payload.resource_type.",
                "Route to T0 when matching deterministic rules exist.",
                "Route to T1 when resource_type is known but no rule matches.",
                "Abstain when resource_type cannot be derived instead of guessing.",
            ),
            outcomes=(
                "The result records T0, T1, or abstain plus candidate rule IDs and reason.",
                "The router selects a tier but does not invoke that tier itself.",
            ),
            exclusions=(
                "The current TrustRouter result does not directly return T2.",
                "A missing resource type is not inferred from unrelated event fields.",
            ),
            safety=("Missing routing input produces an explicit abstain decision.",),
            ko=_content(
                trigger=("검증된 Event가 trust router에 도착하면 시작합니다.",),
                preconditions=("router에 deterministic RuleIndex가 로드되어 있어야 합니다.",),
                steps=(
                    "payload.resource.type 또는 payload.resource_type에서 resource type을 구합니다.",
                    "일치하는 deterministic rule이 있으면 T0로 보냅니다.",
                    "resource type은 알지만 rule이 없으면 T1로 보냅니다.",
                    "resource type을 구할 수 없으면 추측하지 않고 abstain합니다.",
                ),
                outcomes=(
                    "T0, T1, abstain과 candidate rule ID 및 reason을 기록합니다.",
                    "router는 tier를 선택할 뿐 tier 자체를 실행하지 않습니다.",
                ),
                exclusions=(
                    "현재 TrustRouter 결과는 T2를 직접 반환하지 않습니다.",
                    "누락된 resource type을 다른 event field에서 임의 추론하지 않습니다.",
                ),
                safety=("라우팅 입력이 부족하면 명시적인 abstain decision을 냅니다.",),
            ),
            sources=(
                _source(
                    blob_shas,
                    "code",
                    "src/fdai/core/trust_router/__init__.py",
                    "TrustRouter.route",
                    53,
                    90,
                ),
                _source(
                    blob_shas,
                    "test",
                    "tests/core/trust_router/test_trust_router.py",
                    "test_routes_to_t0_when_resource_type_matches_a_rule",
                    68,
                    75,
                ),
            ),
            indexed_commit=indexed_commit,
        ),
        _spec(
            behavior_id="architecture.t2-quality-gate",
            subject_id="T2.QualityGate.grounding.cross_check",
            status="implemented",
            owner="QualityGate",
            aliases=(
                "T2 결과는 어떤 검증을 통과해야 해?",
                "모델들이 의견이 다르거나 grounding이 없으면 어떻게 돼?",
                "What checks must a T2 proposal pass?",
            ),
            trigger=("A T2 candidate action reaches the quality gate.",),
            preconditions=(
                "Verifier, grounding source, and cross-check model quorum are configured.",
            ),
            steps=(
                "Run the deterministic verifier first.",
                "Validate cited rules against the grounding source.",
                "Cross-check the action type with the configured model quorum.",
                "Apply confidence and optional rubric thresholds without raising authority.",
            ),
            outcomes=(
                "Only an eligible decision may continue to the risk gate.",
                "Verifier rejection denies; missing grounding abstains; model disagreement disagrees.",
            ),
            exclusions=(
                "A single model response is not execution eligibility.",
                "Optional debate or rubric stages cannot override a deterministic deny.",
            ),
            safety=(
                "Every incomplete or conflicting quality signal fails closed before execution.",
            ),
            ko=_content(
                trigger=("T2 candidate action이 quality gate에 도착하면 시작합니다.",),
                preconditions=(
                    "verifier, grounding source, cross-check model quorum이 설정되어야 합니다.",
                ),
                steps=(
                    "deterministic verifier를 먼저 실행합니다.",
                    "인용 rule이 grounding source에 실제로 있는지 확인합니다.",
                    "설정된 model quorum으로 action type을 교차 검사합니다.",
                    "권한을 높이지 않는 confidence 및 optional rubric threshold를 적용합니다.",
                ),
                outcomes=(
                    "eligible decision만 risk gate로 진행할 수 있습니다.",
                    "verifier reject는 deny, grounding 부재는 abstain, model disagreement는 disagree입니다.",
                ),
                exclusions=(
                    "단일 model 응답만으로 실행 자격을 얻지 않습니다.",
                    "optional debate 또는 rubric은 deterministic deny를 뒤집을 수 없습니다.",
                ),
                safety=("불완전하거나 충돌하는 quality signal은 실행 전에 안전하게 차단됩니다.",),
            ),
            sources=(
                _source(
                    blob_shas,
                    "code",
                    "src/fdai/core/quality_gate/gate.py",
                    "QualityGate.evaluate",
                    318,
                    450,
                ),
                _source(
                    blob_shas,
                    "test",
                    "tests/core/quality_gate/test_gate.py",
                    "test_no_grounded_citation_when_require_grounding_true",
                    241,
                    251,
                ),
                _source(
                    blob_shas,
                    "test",
                    "tests/core/quality_gate/test_gate.py",
                    "test_cross_check_disagreement_below_quorum_becomes_disagree",
                    270,
                    282,
                ),
            ),
            indexed_commit=indexed_commit,
        ),
        _spec(
            behavior_id="architecture.human-approval-separation",
            subject_id="HIL.Var.approval.no_self_approval",
            status="implemented",
            owner="RiskGate / Var",
            aliases=(
                "왜 이 작업은 사람 승인이 필요해?",
                "요청자가 자기 작업을 직접 승인할 수 있어?",
                "Why does this action require human approval?",
            ),
            trigger=("The risk decision requires human approval and Var has a pending ticket.",),
            preconditions=("The ticket records its initiating principal and required quorum.",),
            steps=(
                "Normalize the approver identity and reject blank identities.",
                "Compare the approver with the initiating principal case-insensitively.",
                "Collect distinct approvers until quorum or terminate immediately on rejection.",
            ),
            outcomes=(
                "A satisfied quorum emits an approved object.approval event.",
                "Self-approval, duplicate approval, rejection, or timeout never executes the action.",
            ),
            exclusions=(
                "Holding Owner-like authority does not permit self-approval.",
                "Approval does not grant Var the executor identity held by Thor.",
            ),
            safety=("Initiation, approval, and execution remain distinct principals.",),
            ko=_content(
                trigger=(
                    "risk decision이 사람 승인을 요구하고 Var에 pending ticket이 생기면 시작합니다.",
                ),
                preconditions=(
                    "ticket에 initiator principal과 required quorum이 기록되어야 합니다.",
                ),
                steps=(
                    "approver identity를 정규화하고 빈 identity를 거부합니다.",
                    "approver와 initiator를 대소문자 구분 없이 비교합니다.",
                    "서로 다른 approver가 quorum을 채울 때까지 수집하고 reject면 즉시 종료합니다.",
                ),
                outcomes=(
                    "quorum이 충족되면 approved object.approval event를 발행합니다.",
                    "자기 승인, 중복 승인, 거절, timeout은 action을 실행하지 않습니다.",
                ),
                exclusions=(
                    "Owner 수준 권한이 있어도 자기 승인은 허용되지 않습니다.",
                    "승인했다고 Var가 Thor의 executor identity를 얻는 것은 아닙니다.",
                ),
                safety=("요청, 승인, 실행은 서로 다른 principal로 유지됩니다.",),
            ),
            sources=(
                _source(blob_shas, "code", "src/fdai/agents/var.py", "Var.decide", 103, 163),
                _source(
                    blob_shas,
                    "test",
                    "tests/agents/test_chat_to_pipeline_e2e.py",
                    "test_var_rejects_blank_approver_and_trims_self_approval",
                    275,
                    294,
                ),
            ),
            indexed_commit=indexed_commit,
        ),
        _spec(
            behavior_id="architecture.shadow-promotion",
            subject_id="ActionPromotionRegistry.consider_promotion",
            status="implemented",
            owner="ActionPromotionRegistry",
            aliases=(
                "Shadow에서 enforce로 언제 승격돼?",
                "승격 후 회귀가 생기면 어떻게 돼?",
                "When is an ActionType promoted from shadow to enforce?",
            ),
            trigger=("Measured shadow metrics are submitted for one ActionType.",),
            preconditions=("Metrics name the same ActionType and its promotion gate is loaded.",),
            steps=(
                "Check minimum shadow days and sample count.",
                "Check minimum accuracy and maximum policy escapes.",
                "Record enforce only when every gate passes; otherwise record shadow.",
            ),
            outcomes=(
                "Passing metrics promote only that ActionType to enforce.",
                "Regressing metrics demote a previously enforced ActionType back to shadow.",
            ),
            exclusions=(
                "Promotion does not edit the ActionType YAML.",
                "An unknown ActionType defaults to shadow rather than enforce.",
            ),
            safety=(
                "Any failed promotion condition preserves or restores non-mutating shadow mode.",
            ),
            ko=_content(
                trigger=("한 ActionType의 measured shadow metric이 제출되면 시작합니다.",),
                preconditions=(
                    "metric의 ActionType이 일치하고 promotion gate가 로드되어야 합니다.",
                ),
                steps=(
                    "minimum shadow day와 sample count를 확인합니다.",
                    "minimum accuracy와 maximum policy escape를 확인합니다.",
                    "모든 gate가 통과할 때만 enforce를 기록하고 아니면 shadow를 기록합니다.",
                ),
                outcomes=(
                    "통과한 metric은 해당 ActionType만 enforce로 승격합니다.",
                    "metric이 회귀하면 기존 enforce ActionType을 shadow로 자동 강등합니다.",
                ),
                exclusions=(
                    "promotion은 ActionType YAML을 수정하지 않습니다.",
                    "등록되지 않은 ActionType은 enforce가 아니라 shadow가 기본입니다.",
                ),
                safety=(
                    "promotion 조건 하나라도 실패하면 non-mutating shadow mode를 유지하거나 복구합니다.",
                ),
            ),
            sources=(
                _source(
                    blob_shas,
                    "code",
                    "src/fdai/core/risk_gate/gate.py",
                    "ActionPromotionRegistry.consider_promotion",
                    96,
                    148,
                ),
                _source(
                    blob_shas,
                    "test",
                    "tests/core/risk_gate/test_gate.py",
                    "test_promotion_registry_promotes_when_metrics_pass_gate",
                    325,
                    341,
                ),
                _source(
                    blob_shas,
                    "test",
                    "tests/core/risk_gate/test_gate.py",
                    "test_promotion_registry_demotes_when_metrics_regress",
                    342,
                    365,
                ),
            ),
            indexed_commit=indexed_commit,
        ),
        _spec(
            behavior_id="architecture.executor-safety",
            subject_id="ShadowExecutor.execute",
            status="implemented",
            owner="ShadowExecutor / Thor",
            aliases=(
                "실행 전에 어떤 안전 조건을 확인해?",
                "같은 action이 재전달되면 중복 실행돼?",
                "How does the executor prevent duplicate or unsafe execution?",
            ),
            trigger=("A risk-approved Action and its Rule reach the execution surface.",),
            preconditions=(
                "The action carries mode, safety invariants, idempotency key, and target resource.",
            ),
            steps=(
                "Reject unsupported enforce mode and missing safety invariants before mutation.",
                "Check the idempotency cache before and inside the per-resource lock.",
                "Use the durable idempotency store when configured.",
                "Enforce count and rate blast-radius caps before rendering a remediation PR.",
            ),
            outcomes=(
                "A valid shadow action publishes at most one remediation PR and one audit result.",
                "Invariant, blast-radius, render, or mode failures become audited non-mutations.",
            ),
            exclusions=(
                "The P1 ShadowExecutor does not apply an enforce-mode substrate mutation.",
                "A duplicate idempotency key does not publish a second PR.",
            ),
            safety=(
                "Resource locking, two-level idempotency, blast-radius checks, and audit fail closed.",
            ),
            ko=_content(
                trigger=(
                    "risk gate를 통과한 Action과 Rule이 execution surface에 도착하면 시작합니다.",
                ),
                preconditions=(
                    "action에 mode, safety invariant, idempotency key, target resource가 있어야 합니다.",
                ),
                steps=(
                    "지원하지 않는 enforce mode와 누락된 safety invariant를 mutation 전에 거부합니다.",
                    "per-resource lock 전후에 idempotency cache를 확인합니다.",
                    "설정된 경우 durable idempotency store도 확인합니다.",
                    "remediation PR 렌더 전에 count와 rate blast-radius cap을 적용합니다.",
                ),
                outcomes=(
                    "유효한 shadow action은 remediation PR과 audit result를 최대 한 번 발행합니다.",
                    "invariant, blast-radius, render, mode 실패는 감사된 non-mutation으로 끝납니다.",
                ),
                exclusions=(
                    "P1 ShadowExecutor는 enforce-mode substrate mutation을 적용하지 않습니다.",
                    "같은 idempotency key는 두 번째 PR을 발행하지 않습니다.",
                ),
                safety=(
                    "resource lock, 2단계 idempotency, blast-radius 검사, audit가 fail closed합니다.",
                ),
            ),
            sources=(
                _source(
                    blob_shas,
                    "code",
                    "src/fdai/core/executor/executor.py",
                    "ShadowExecutor.execute",
                    168,
                    280,
                ),
                _source(
                    blob_shas,
                    "test",
                    "tests/core/executor/test_executor.py",
                    "test_second_delivery_of_same_key_is_deduped",
                    317,
                    331,
                ),
            ),
            indexed_commit=indexed_commit,
        ),
        _spec(
            behavior_id="architecture.console-identity-boundary",
            subject_id=(
                "Console.Browser.Principal.Executor.Identity.Thor.Azure."
                "Approval.Button.Substrate.Mutation"
            ),
            status="configured",
            owner="Read API / Thor",
            aliases=(
                "콘솔에서 바로 Azure 리소스를 변경할 수 있어?",
                "콘솔 사용자와 executor identity는 왜 분리돼?",
                "Can the operator console mutate Azure resources directly?",
            ),
            trigger=("An operator reads state or proposes work through the console.",),
            preconditions=(
                "The browser principal is authenticated independently from workload identity.",
            ),
            steps=(
                "The console reads bounded projections through the read API.",
                "Mutation intent re-enters the typed control pipeline rather than calling Azure directly.",
                "Only Thor's allowlisted workload identity reaches privileged delivery adapters.",
            ),
            outcomes=(
                "Console compromise does not automatically expose the executor credential.",
                "Approval and execution remain attributable to different principals.",
            ),
            exclusions=(
                "The console does not execute actions with a UI button.",
                "Browser Entra identity is not Thor's managed workload identity.",
            ),
            safety=(
                "Human identity, approval authority, and execution identity remain separate boundaries.",
            ),
            ko=_content(
                trigger=("operator가 console에서 상태를 읽거나 작업을 제안하면 시작합니다.",),
                preconditions=(
                    "browser principal은 workload identity와 별도로 인증되어야 합니다.",
                ),
                steps=(
                    "console은 read API를 통해 제한된 projection만 읽습니다.",
                    "mutation intent는 Azure를 직접 호출하지 않고 typed control pipeline에 재진입합니다.",
                    "Thor의 allowlist된 workload identity만 privileged delivery adapter에 접근합니다.",
                ),
                outcomes=(
                    "console이 침해되어도 executor credential이 자동 노출되지 않습니다.",
                    "승인과 실행은 서로 다른 principal에 귀속됩니다.",
                ),
                exclusions=(
                    "console 승인 버튼으로 action 또는 substrate mutation을 직접 실행하지 않습니다.",
                    "browser Entra identity는 Thor의 managed workload identity가 아닙니다.",
                ),
                safety=(
                    "사람 identity, 승인 권한, 실행 identity를 서로 다른 boundary로 유지합니다.",
                ),
            ),
            sources=(
                _source(
                    blob_shas,
                    "doc",
                    ".github/instructions/app-shape.instructions.md",
                    "Layer Boundaries (security)",
                    37,
                    51,
                    authority_role="configuration",
                ),
            ),
            indexed_commit=indexed_commit,
        ),
        _spec(
            behavior_id="architecture.event-ingest-dedup",
            subject_id="EventIngest.ingest",
            status="implemented",
            owner="EventIngest / Huginn",
            aliases=(
                "같은 이벤트가 두 번 들어오면 어떻게 처리해?",
                "Event ingest dedupe cache가 넘치면 어떻게 돼?",
                "How does event ingest deduplicate redelivery?",
            ),
            trigger=("A validated or raw event mapping reaches EventIngest.",),
            preconditions=("The event schema supplies a stable idempotency_key.",),
            steps=(
                "Validate and coerce the input into the typed Event contract.",
                "Return None when the idempotency key is already in the bounded FIFO cache.",
                "Record a new key and evict the oldest key when the cache exceeds its bound.",
            ),
            outcomes=(
                "Recent redelivery stops before trust routing.",
                "An evicted old key may pass ingest again, while executor idempotency remains the durable stop.",
            ),
            exclusions=(
                "The in-process FIFO is not a durable all-history dedupe ledger.",
                "Schema-invalid input is not treated as a harmless duplicate.",
            ),
            safety=(
                "Bounded memory and downstream durable idempotency prevent cache growth and double mutation.",
            ),
            ko=_content(
                trigger=(
                    "validated Event 또는 raw event mapping이 EventIngest에 도착하면 시작합니다.",
                ),
                preconditions=("event schema에 stable idempotency_key가 있어야 합니다.",),
                steps=(
                    "입력을 검증하고 typed Event contract로 변환합니다.",
                    "idempotency key가 bounded FIFO cache에 있으면 None을 반환합니다.",
                    "새 key를 기록하고 cache bound를 넘으면 가장 오래된 key를 제거합니다.",
                ),
                outcomes=(
                    "최근 재전달은 trust routing 전에 중단됩니다.",
                    "제거된 오래된 key는 다시 통과할 수 있지만 executor idempotency가 durable stop입니다.",
                ),
                exclusions=(
                    "in-process FIFO는 전체 이력을 보존하는 durable dedupe ledger가 아닙니다.",
                    "schema-invalid input을 정상 duplicate로 취급하지 않습니다.",
                ),
                safety=(
                    "bounded memory와 downstream durable idempotency가 cache 증가와 중복 mutation을 막습니다.",
                ),
            ),
            sources=(
                _source(
                    blob_shas,
                    "code",
                    "src/fdai/core/event_ingest/__init__.py",
                    "EventIngest.ingest",
                    50,
                    92,
                ),
                _source(
                    blob_shas,
                    "test",
                    "tests/core/event_ingest/test_event_ingest.py",
                    "test_duplicate_idempotency_key_returns_none",
                    41,
                    47,
                ),
            ),
            indexed_commit=indexed_commit,
        ),
        _spec(
            behavior_id="architecture.vidar-rollback",
            subject_id="Vidar.rollback",
            status="implemented",
            owner="Vidar",
            aliases=(
                "작업 실행이 실패하면 누가 rollback해?",
                "같은 실패 이벤트가 두 번 오면 rollback도 두 번 해?",
                "How does Vidar handle a failed action run?",
            ),
            trigger=("Vidar receives an object.action-run whose state is failed.",),
            preconditions=("The action run names a correlation ID and rollback contract.",),
            steps=(
                "Ignore non-failed action runs and deduplicate handled correlation IDs.",
                "Select the injected executor for the rollback contract.",
                "Record success only when the executor returns a rollback receipt.",
                "Publish object.rollback with succeeded or failed state.",
            ),
            outcomes=(
                "Thor records rolled back when recovery succeeds.",
                "Missing executor, provider error, or missing receipt produces rollback_failed evidence.",
            ),
            exclusions=(
                "Vidar does not execute the forward action.",
                "A duplicate correlation is not rolled back twice.",
            ),
            safety=("Rollback failure is explicit and the per-resource Thor lock is released.",),
            ko=_content(
                trigger=("Vidar가 state=failed인 object.action-run을 받으면 시작합니다.",),
                preconditions=("action run에 correlation ID와 rollback contract가 있어야 합니다.",),
                steps=(
                    "failed가 아닌 action run을 무시하고 처리한 correlation ID를 중복 제거합니다.",
                    "rollback contract에 맞는 injected executor를 선택합니다.",
                    "executor가 rollback receipt를 반환한 경우에만 성공으로 기록합니다.",
                    "succeeded 또는 failed state의 object.rollback을 발행합니다.",
                ),
                outcomes=(
                    "recovery가 성공하면 Thor가 rolled back 상태를 기록합니다.",
                    "executor 부재, provider error, receipt 부재는 rollback_failed evidence를 만듭니다.",
                ),
                exclusions=(
                    "Vidar는 forward action을 실행하지 않습니다.",
                    "같은 correlation을 두 번 rollback하지 않습니다.",
                ),
                safety=("rollback 실패를 명시하고 Thor의 per-resource lock을 해제합니다.",),
            ),
            sources=(
                _source(blob_shas, "code", "src/fdai/agents/vidar.py", "Vidar.rollback", 35, 129),
                _source(
                    blob_shas,
                    "test",
                    "tests/agents/test_wave3_pipeline.py",
                    "test_thor_triggers_vidar_rollback_on_failure",
                    689,
                    721,
                ),
                _source(
                    blob_shas,
                    "test",
                    "tests/agents/test_wave3_pipeline.py",
                    "test_vidar_rollback_is_idempotent_per_correlation",
                    754,
                    775,
                ),
            ),
            indexed_commit=indexed_commit,
        ),
        _spec(
            behavior_id="architecture.bragi-translator",
            subject_id="Bragi.ask",
            status="implemented",
            owner="Bragi",
            aliases=(
                "Bragi가 직접 작업을 실행할 수 있어?",
                "대화에서 restart 요청을 하면 어떤 경로로 가?",
                "Can Bragi execute an operator command directly?",
            ),
            trigger=("An operator asks a question or issues an action-shaped command.",),
            preconditions=("The conversation session is bound to the authenticated user.",),
            steps=(
                "Route read questions to the owning Pantheon agent.",
                "Translate action intent into a typed ActionProposal when that route is allowed.",
                "Submit the proposal through Huginn so Forseti, Var, Thor, and Saga retain authority.",
            ),
            outcomes=(
                "Read questions return grounded agent-owned state.",
                "Action commands return proposal metadata and typed-pipeline progress, not direct execution.",
            ),
            exclusions=(
                "Bragi never calls an executor directly.",
                "A read-only conversation route does not submit an ActionProposal.",
            ),
            safety=(
                "Unknown domains abstain or hand off instead of inventing an owner or action.",
            ),
            ko=_content(
                trigger=("operator가 질문하거나 action 형태의 command를 입력하면 시작합니다.",),
                preconditions=("conversation session이 authenticated user에 묶여 있어야 합니다.",),
                steps=(
                    "read 질문을 해당 domain을 소유한 Pantheon agent로 라우팅합니다.",
                    "허용된 route에서 action intent를 typed ActionProposal로 번역합니다.",
                    "Forseti, Var, Thor, Saga의 권한을 유지하도록 Huginn을 통해 proposal을 제출합니다.",
                ),
                outcomes=(
                    "read 질문은 agent가 소유한 grounded state로 답합니다.",
                    "action command는 직접 실행이 아니라 proposal metadata와 typed-pipeline progress를 반환합니다.",
                ),
                exclusions=(
                    "Bragi는 executor를 직접 호출하지 않습니다.",
                    "read-only conversation route는 ActionProposal을 제출하지 않습니다.",
                ),
                safety=(
                    "알 수 없는 domain은 owner나 action을 날조하지 않고 abstain 또는 handoff합니다.",
                ),
            ),
            sources=(
                _source(blob_shas, "code", "src/fdai/agents/bragi.py", "Bragi.ask", 214, 252),
                _source(
                    blob_shas,
                    "test",
                    "tests/agents/test_conversational_port.py",
                    "test_ask_refuses_action_intent_and_routes_to_typed_pipeline",
                    110,
                    125,
                ),
            ),
            indexed_commit=indexed_commit,
        ),
        _spec(
            behavior_id="architecture.local-evidence-parity",
            subject_id="LocalAzureTruthContract",
            status="configured",
            owner="Read API composition",
            aliases=(
                "로컬 콘솔에 Azure 근거가 없으면 demo data를 보여줘?",
                "로컬과 배포 환경은 promotion state를 다르게 바꿔?",
                "Does local development synthesize missing Azure runtime evidence?",
            ),
            trigger=("Interactive local starts a read surface or requests runtime evidence.",),
            preconditions=(
                "Browser Entra and configured Azure read adapters define the evidence profile.",
            ),
            steps=(
                "Read repository catalogs only as configuration reference data.",
                "Read runtime claims only from their authoritative Azure-backed providers.",
                "Render unavailable or explicitly empty when the provider is missing or unauthorized.",
                "Use the same promotion, workflow, risk, and approval state as deployment.",
            ),
            outcomes=(
                "Local runtime evidence remains honest and source-attributed.",
                "Test fixtures stay confined to pytest, mocks, and explicit example applications.",
            ),
            exclusions=(
                "Interactive local does not substitute demo Incidents, audit rows, approvals, or inventory.",
                "Local mode does not promote or demote an ActionType independently from deployment state.",
            ),
            safety=(
                "Offline or unauthorized sources fail closed to unavailable rather than synthetic truth.",
            ),
            ko=_content(
                trigger=(
                    "interactive local이 read surface를 시작하거나 runtime evidence를 요청하면 시작합니다.",
                ),
                preconditions=(
                    "Browser Entra와 configured Azure read adapter가 evidence profile을 정합니다.",
                ),
                steps=(
                    "repository catalog는 configuration reference data로만 읽습니다.",
                    "runtime claim은 authoritative Azure-backed provider에서만 읽습니다.",
                    "provider가 없거나 권한이 없으면 unavailable 또는 명시적 empty를 표시합니다.",
                    "배포와 같은 promotion, workflow, risk, approval state를 사용합니다.",
                ),
                outcomes=(
                    "local runtime evidence는 실제 source를 유지합니다.",
                    "test fixture는 pytest, mock, 명시적 example application에만 남습니다.",
                ),
                exclusions=(
                    "interactive local은 demo Incident, audit row, approval, inventory를 대체 표시하지 않습니다.",
                    "local mode가 deployment state와 별도로 ActionType을 승격하거나 강등하지 않습니다.",
                ),
                safety=(
                    "offline 또는 unauthorized source는 synthetic truth 대신 unavailable로 fail closed합니다.",
                ),
            ),
            sources=(
                _source(
                    blob_shas,
                    "doc",
                    ".github/instructions/app-shape.instructions.md",
                    "Local Azure Truth Contract",
                    71,
                    115,
                    authority_role="configuration",
                ),
                _source(
                    blob_shas,
                    "test",
                    "tests/delivery/read_api/test_local.py",
                    "test_local_azure_discovery_rejects_synthetic_opt_out",
                    118,
                    128,
                ),
            ),
            indexed_commit=indexed_commit,
        ),
    )


__all__ = [
    "ARCHITECTURE_SOURCE_PATHS",
    "EXTRACTOR_VERSION",
    "build_architecture_behavior_specs",
]
