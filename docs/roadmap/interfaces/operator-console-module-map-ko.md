---
title: Operator Console Module Map and Boundaries
translation_of: operator-console-module-map.md
translation_source_sha: 3387187e2e28acf6e9de8d343389d7b69b564469
translation_revised: 2026-08-06
---
# Operator Console Module Map and Boundaries

이 문서는 Operator Console conversation module, route, channel 및 provider boundary를 매핑합니다.
Main console contract를 확장하지 않고 source ownership을 찾을 수 있게 유지합니다.

## 실행 가능한 기준선

[`operator-console-module-inventory.json`](operator-console-module-inventory.json)은 현재 Operator API
package 책임, route family 분류, 후보 destination 및 import surface 상태를 기록합니다. 이 inventory는
file-count 목표가 아닌 설명 기준이지만, executable completeness gate는 현재 모든 module directory와
route module을 분류된 상태로 유지하도록 요구합니다.
Candidate destination은 package hint입니다. 새 process, identity, transport 또는 data owner의 gate는 [서비스 승격과 데이터 소유권](../architecture/service-graduation-and-ownership-ko.md)입니다.
[`test_operator_api_layout.py`](../../../tests/delivery/operator_api/test_operator_api_layout.py)는 현재 모든
package와 route module이 분류된 상태인지 확인하고, exact 기본 method, path, route-name set 및 대표 HTTP
envelope를 고정합니다. 의도적인 기본 route 추가는 같은 변경에서 검토된 baseline을 갱신합니다.

### Dependency-direction gate

`check-operator-api-boundaries.py`는 application code를 로드하지 않고 import를 파싱합니다. 정리된
core-to-delivery, runtime-to-Operator API, ingestion-to-Operator API 및 shared
delivery-to-application 방향은 enforced check로 유지합니다. 기존 route-to-core policy import와 반대
방향의 Operator API service import는 report-only debt로 유지하므로 이후 migration issue가 이를 줄이는
동안 관련 없는 작업을 차단하지 않습니다.

Gate는 production factory, development factory 및 runtime bootstrap의 unique internal import도
측정합니다. 검토된 limit 이상인 composition root는
`.check-operator-api-boundaries.allowlist`에 exact path, maximum import count 및 바로 앞의
justification comment가 필요합니다. 검토된 maximum을 넘기려면 새 review가 필요합니다. Justification
누락, 검토되지 않은 high-fanout root 또는 stale exception은 check를 실패시킵니다. Report-only rule은
`.check-operator-api-boundaries.debt`를 aggregate non-growth budget으로 사용합니다. Debt는 file 변경 없이
줄어들 수 있지만 증가는 CI를 실패시킵니다. 좁은 package 또는 touched-file check에는 하나 이상의
`--path <repository-relative-path>` argument를 사용합니다. Stale detection도 동일한 선택 범위로
제한되며 CI와 pre-push는 항상 full scan을 실행합니다.

Enforced finding은 dependency를 neutral contract 또는 provider seam으로 이동하고 검토된 composition
root에서 implementation을 bind하여 해결합니다. Reverse service import를 위해 allowlist entry를 추가하지
않습니다. Report-only finding은 migration inventory이며 owning package가 정리된 후에만 enforce 대상으로
전환합니다.

`check-boundary-docstrings.py`는 exact reviewed package module에서 non-empty Responsibility,
Boundary, Authority and state, Dependencies, Deployment section을 검사합니다. Scope는 report
mode로 시작하고 review 후에만 enforce로 이동합니다. Justified exclusion은 missing, out of scope
또는 불필요한 상태가 되면 실패합니다. 이 structural AST check는 semantic truth를 증명하지 않습니다.

### 첫 reversible family migration

Issue 70은 다섯 개의 `routes/audit*.py` module을 첫 migration family로 선택합니다. Executable
inventory는 이미 이 module을 하나의 read-projection family로 분류합니다. 각 module은 family 외부에 한두
개의 direct Python consumer, 한 개에서 세 개의 internal FDAI import 및 측정된 90-day window에 한두 번의 변경이
있습니다. 이 family는 read-only이며 approval, execution, CORS 또는 lifespan behavior를 소유하지 않으므로
chat, workflow 또는 investigation보다 behavioral surface가 작습니다.

Implementation owner는 `fdai.delivery.operator_api.projections.audit`로 이동하며 filename과 public
symbol은 변경하지 않습니다. App-side audit query use와 production panel composition은 새 package facade를
import합니다. Development composition은 shared production panel builder를 통해 같은 facade에 도달합니다.
기존의 모든 `routes.audit_*` module은 explicit per-module compatibility shim으로 유지합니다. Method,
path, route name, authorization, response payload, provenance 및 database ownership은 변경하지 않습니다.

Rollback에서도 두 import surface를 안정적으로 유지합니다. Implementation file을 `routes/` 아래에
복원하고 새 `projections.audit` module 각각을 복원된 route module의 forwarding shim으로 변경하며
composition import는 package facade에 유지합니다. 이 절차는 API 또는 wire rollback 없이 physical
ownership을 되돌리고 broad wildcard facade를 만들지 않습니다.

### Conversation turn application boundary

Issue 71은 JSON 및 SSE chat route가 공유하는 process-local application-service boundary로
`fdai.delivery.operator_api.application.conversation_turn`을 도입합니다. Authentication과 bounded
transport parsing 이후 각 route는 immutable `ConversationTurnInput`을 만들고 하나의 typed lifecycle을
시작합니다. 기존 evidence, planning, narration, verification, history, busy-input, progress 및 cancellation
implementation은 in-process로 유지되고 해당 lifecycle을 통해 완료됩니다. Network hop 또는 별도 배포
service는 추가하지 않습니다.

Input은 server-derived principal, conversation, request, correlation, prompt, locale, target-agent,
evidence-reference, history-count 및 transport-mode value만 포함합니다. Provider scope, credential,
approval, role, executor identity 또는 mutable context field는 없습니다. Immutable result는 terminal
status, verified answer, verification summary, evidence ref, presentation artifact, delegation metadata 및
explicit failure detail을 기록합니다. Frozen wire snapshot은 field 추가 없이 기존 JSON payload 또는 SSE
terminal frame으로 round-trip합니다.

Service는 non-authoritative이며 call 사이에 state를 유지하지 않습니다. Approval, execution, promotion,
provider scope 선택을 수행할 수 없고 Thor identity를 받을 수 없습니다. HTTP status mapping, SSE
sequence/revision, header, route name, authorization 및 cancellation transport는 route가 계속 소유합니다.
Bragi는 presentation translator로 유지되고 authority-bearing agent work는 typed pub/sub을 계속 사용합니다.

### Immutable app composition

Issue 72는 `OperatorApiConfig(**kwargs)`를 bounded compatibility constructor로 유지하고 route를 등록하기
전에 `split()`으로 projection합니다. `OperatorApiValues`에는 inert environment-derived value만 포함됩니다.
`OperatorApiRuntimeBindings`는 process-local dependency를 stream, projection, lifecycle, read-view,
conversation, governed-route 및 fixed-HTTP record로 그룹화합니다. 각 registration function은 legacy
aggregate 대신 자신이 소유한 capability record만 받습니다.

모든 record는 frozen입니다. Mapping input은 read-only view로 복사되며, 의도적으로 공유하는 provider는
consumer 전체에서 같은 object를 참조해야 합니다. `OperatorApiComposition.validate()`는 route를 추가하거나
lifecycle callback을 시작하기 전에 shared reference와 필수 cross-group pair를 검사합니다. Record에는 raw
provider credential 또는 Thor executor identity가 없습니다. Production과 interactive local composition은
계속 같은 legacy constructor를 만들고 동일한 split 및 validation boundary로 진입하므로 synthetic
production fallback이나 venue-specific route model을 추가하지 않습니다.

Route method, path, name, registration order, authorization, CORS, response payload 및 availability default는
변경하지 않습니다. Rollback은 immutable record definition과 validation을 `app/config.py`로 다시 옮기고
`app/composition.py`를 제거하며 legacy constructor, `split()` mapping, public `main` facade 및 registration
signature를 그대로 유지합니다. 이 절차는 wire 또는 caller migration 없이 physical ownership을 되돌립니다.

| Package | 현재 책임 | Migration 규칙 |
|---------|-----------|----------------|
| Root | Public facade 및 foundational contract | 분류된 replacement가 준비될 때까지 유지합니다. |
| `app/` | Shared ASGI assembly, middleware, registration 및 lifespan | HTTP composition boundary로 유지합니다. |
| `application/` | Typed process-local, non-authoritative application coordination | Service-graduation evidence가 process boundary를 정당화할 때까지 유지합니다. |
| `dev/` | Interactive local 및 test-only provider composition | Production import에서 사용할 수 없게 유지합니다. |
| `dev/fixtures/` | Synthetic pytest-only fixture | Production composition 밖에 유지합니다. |
| `persistence/` | Operator API read-model implementation 및 projection | 소유된 read contract 뒤에 유지합니다. |
| `projections/` | HTTP route 밖의 read-only projection ownership | Migrated family의 owner로 유지합니다. |
| `projections/audit/` | Audit query 및 autonomy/FinOps measurement projection | Explicit facade를 통해 import하고 기존 route module은 shim으로 유지합니다. |
| `production/` | Production provider construction 및 binding | Wire behavior를 변경하지 않고 fanout을 점진적으로 줄입니다. |
| `routes/` | HTTP adapter, coordination, projection 및 policy helper가 혼재 | 측정된 family 하나씩 이동하며 typed service boundary 전에 chat을 일괄 이동하지 않습니다. |
| `streaming/` | Read-only SSE transport, redaction, fanout 및 runtime projection | Versioned relay 및 replay contract가 준비될 때까지 유지합니다. |

`fdai.delivery.operator_api.main`은 public app facade입니다. `read_model`은 검토된 replacement가 준비될
때까지 public delivery contract로 유지합니다. `fdai.delivery.auth`는 framework-neutral bearer 및 Entra
verification을 소유하고 `operator_api.auth`와 `operator_api.entra_verifier`는 compatibility facade로만
유지됩니다.
`main` facade의 `busy_input_runtime` re-export는 새 runtime ownership claim이 아닌 transitional public
seam입니다.
현재 fork 및 reporting guide가 직접 import하므로 `routes.panels`와 `routes.reporting`은 transitional
public extension seam으로 유지합니다. 그 외 개별 `routes.*` module은 internal implementation path입니다.
Migration에서는 분류된 compatibility 필요가 있을 때만 module별 forwarding shim을 사용합니다.
Runtime-owned agent-state record 및 event-bus publication은 `fdai.delivery.agent_activity`에 있으므로
headless runtime은 Operator API streaming implementation을 import하지 않습니다. Provisioning의
`streaming.provision_stream` compatibility는 별도로 분류합니다. Issue 71은 baseline에 기록된 chat wire
debt를 해소합니다. Version 1 semantic frame에는 server-owned request id와 integer sequence가 필요하고,
known HTTP failure는 bounded status와 reason을 유지하며, producer는 browser의 256 KiB limit를 넘는
frame을 거부합니다.

이 이동 동안 PostgreSQL과 Alembic은 shared migration authority로 유지됩니다. Module 또는 route migration은
두 번째 schema owner를 만들지 않습니다. Service-owned schema 및 migration lane에는 별도 검토된 boundary가
필요합니다.

## Core 및 delivery map

- [`src/fdai/core/conversation/`](../../../src/fdai/core/conversation)
  - `coordinator.py`는 Layer 2 `ConversationCoordinator` orchestration을 소유합니다.
  - `tool_arguments.py`는 pure canonical-verb argument parsing을 소유하며 tool authority를 부여하지 않습니다.
  - `read_plan.py`는 bounded-plan validation, serial read execution, result aggregation 및
    identity-scoped high-signal conflict detection을 소유합니다.
  - `contextual_translation.py`는 current/prior turn text의 scalar argument provenance를 소유합니다.
  - `grounded_answer_validation.py`는 narration과 immutable tool authority 사이의 conservative
    canonical-ID, numeric, timestamp, freshness 및 exact-reference check를 소유합니다.
  - `tools.py`는 `SystemConsoleTool`과 Layer 1 module에 delegate하는 implementation을 정의합니다.
  - `narrator.py`는 synchronous intent, contextual, proposal-only read-plan, zero-execution
    clarification 및 presentation-only grounded-answer protocol을 정의합니다.
  - `session.py`는 disposable core/CLI `ConversationSession` projection을 제공합니다. Production
    transcript는 principal-scoped `ConversationHistoryStore`가 소유합니다.
- [`cli/`](../../../cli)
  - `src/repl.ts`는 shared `POST /chat` coordinator용 IME-safe stdin/stdout channel입니다.
  - `src/cockpit.ts`는 self-describing screen snapshot을 같은 coordinator에 publish하는 live SSE
    presentation입니다.
- [`src/fdai/core/conversation/channel_gateway.py`](../../../src/fdai/core/conversation/channel_gateway.py)는
  sender를 인증하고 message idempotency key를 claim하며 coordinator를 호출합니다. Durable delivery가
  구성되면 provider send 전에 complete response를 저장합니다.
- [`src/fdai/delivery/channels/`](../../../src/fdai/delivery/channels)
  - `teams.py`는 bearer-token verification 이후 Bot Framework activity를 normalize하고 injected reply
    publisher를 사용합니다. Payload-supplied reply URL을 신뢰하지 않습니다.
  - `slack.py`는 timestamped signature를 검증하고 replay 또는 bot-authored event를 차단하며 message를
    normalize하고 injected reply publisher를 사용합니다.
  - Slack, Teams 및 web attachment contract는
    [conversation attachment](conversation-attachments-ko.md)를 통해 수렴합니다. Dedicated WebSocket
    adapter는 optional입니다.
- [`chat_current_time.py`](../../../src/fdai/delivery/operator_api/routes/chat_current_time.py)는 injected
  aware clock과 principal IANA timezone에서 current-time 질문을 resolve합니다.

## Operator API route ownership

- `chat_stream_setup.py`는 authenticated request, evidence, history 및 answer-plan validation을 소유합니다.
- `chat_stream_terminal.py`는 pure terminal verification-frame 및 replay-payload assembly를 소유합니다.
- `chat_trajectory_detail.py`는 durable trajectory replay용 bounded final progress projection을 소유합니다.
- `chat_knowledge_context.py`는 state write 없이 exact prior-turn runbook, source freshness, consented
  memory 및 materialized learning을 읽습니다.
- `chat_vision_prompt.py`는 validated image를 projection합니다.
- `chat_verification_text.py`와 `chat_verification_rendering.py`는 terminal integrity와 prose를 소유합니다.
- `read_investigation_responder.py`는 registered Heimdall read intent를 typed evidence에서 렌더링합니다.
  Evidence가 없으면 explicit unavailable answer를 반환합니다. `read_investigation_catalog.py`는 catalog
  ID, ownership 또는 plan binding drift 시 startup을 차단합니다.

영어 및 한국어 presentation literal은 NFC UTF-8을 사용합니다. Escaped Hangul은 정확한 rationale이 있는
code-point behavior에만 허용됩니다. 이 표현은 machine value, evidence authority, locale selection 또는
typed-pipeline decision을 변경하지 않습니다.

Scheduler Runs, Automation Blueprints, Scheduled Continuations,
[관리형 trajectory dataset](governed-trajectory-datasets-ko.md),
[execution backend status](execution-backends-ko.md)는 read-only metadata를 제공합니다. 이 view에는 enable,
submit, retry, cancel, cleanup, execute 또는 approval control이 없습니다. Credential 및 Thor identity를
제외하고 command를 SPA 밖에 유지합니다.

[`tools/chat.py`](../../../tools/chat.py)는 core coordinator용 headless JSONL development harness이며 별도
policy implementation이 아닙니다.

## Boundary invariant

`core/conversation/`은 protocol만 import합니다. Azure SDK, HTTP, Bot Framework 및 provider call은
`delivery/` 아래에 있습니다. Conversation presentation은 execution authority가 되지 않습니다.

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| Console framing, tool, RBAC 및 safety | [Operator Console](operator-console-ko.md) |
| Runtime model 및 DI seam | [Operator Console runtime model](operator-console-runtime-model-ko.md) |
| Durable channel delivery | [Durable conversation delivery](durable-conversation-delivery-ko.md) |
