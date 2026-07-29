---
title: Operator Console - Data and Wire Contracts
translation_of: operator-console-wire-contracts.md
translation_source_sha: 792f1046d147b6a81b367d3008e4001c90f4eb87
translation_revised: 2026-07-30
---

# Operator Console - Data and Wire Contracts

> [operator-console-ko.md](operator-console-ko.md) section 13 (13.1-13.3, 13.6-13.9)에서 분리한 focused owner 문서입니다.

## 13. 데이터 + wire 계약

### 13.1 Audit entry - `console.turn` action_kind

```json
{
  "action_kind": "console.turn",
  "session_id": "...",
  "turn_id": "...",
  "principal": {"kind": "user|cli|bot", "id": "...", "role": "Reader|..."},
  "channel": "cli|teams|slack|web",
  "direction": "inbound|outbound|tool_call|tool_result",
  "tier": "T0|T1|T2",
  "escalation_trigger": "...",
  "tool_name": "...",
  "arguments": {...},
  "result_preview": "...",
  "evidence_refs": ["..."],
  "verifier_verdict": "pass|abstain|deny|n/a",
  "model_deployment_id": "...",
  "prompt_tokens": 0,
  "completion_tokens": 0,
  "started_at": "...",
  "finished_at": "..."
}
```

### 13.2 CLI REPL wire 계약

- stdin: 한 줄에 하나의 오퍼레이터 발화.
- stdout: `--json` flag 설정 시 JSON-Lines; 그렇지 않으면 formatted text.
- stderr: coordinator log 라인 (구조화됨; 별개 stream 이므로 formatted
  view는 clean 유지).
- Exit code: clean 세션 종료 시 `0`; 유효하지 않은 config 시 `2`; 복구
  불가능한 채널 error 시 `3`.

### 13.3 Read-API approval callback (Week 1)

- `POST /hil/{approval_id}/decision`
- Body: `{"decision": "approve|reject|defer", "justification": "..."}`
- Header: `X-FDAI-Signature: sha256=<hex>`,
  `X-FDAI-Timestamp: <RFC3339>`.
- Signature 재료: `HMAC-SHA256(secret, timestamp . approval_id . body)`.
  세 부분은 literal `.` separator 로 join. URL path `approval_id` 를
  digest 에 bind 하면, 캡처된 유효 메시지를 다른 pending item 으로 replay
  (URL swap) 할 수 없음. bot은 URL 에 넣은 `approval_id` 를 서명 재료에도
  반드시 동일하게 포함해야 함.
- Response: `200 {"queued": true, "audit_entry_id": "..."}`.

이 경로는 read API의 GET 전용 projection surface에 문서화된 write-route
예외입니다. Invariant test는 이 callback을 명시적으로 allow-list합니다. 이는
[app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md)
의 "console never executes" 규칙을 깨지 **않음**: 이 endpoint는 기존 HIL
큐에 *승인 결정을 기록* (시그널) 할 뿐이며, 별도 executor principal이
나중에 그것을 실행. API 프로세스는 executor Managed Identity를 절대
보유하지 않고 mutation surface를 직접 호출하지 않음; 승인과 실행은
별개 principal 유지.

### 13.6 의미 기반 작업 초안 및 typed confirmation

모든 자연어 turn은 `POST /chat` 또는 `POST /chat/stream`을 사용합니다.
구성된 mini narrator는 서버가 제공한 capability manifest에서 answer, read
tool, agent owner, public-web query, clarification 또는 write draft를 선택한
strict JSON-schema `TurnPlan`을 반환합니다. 브라우저는 action intent를
분류하지 않으며 자연어를 write endpoint에 직접 보내지 않습니다.

- **초안**: `action_draft` 또는 `incident_draft`는 allowlist에 있는
  `action_type`, bounded typed arguments, conversation `session_id`, request-scoped
  idempotency key를 반환합니다. 초안을 만드는 동안 event를 발행하거나
  Incident를 생성하지 않습니다. 브라우저는 확인 및 취소 control을 표시합니다.
- **Typed confirmation**: `POST /chat/action/confirm`은
  `{"action_type": str, "arguments": object, "session_id": str?,
  "idempotency_key": str}`만 받습니다. 서버는 proposal 하나를 발행하기 전에
  ActionType allowlist, argument bounds, 인증된 principal 및 RBAC를 다시
  확인합니다. 알 수 없는 field 및 allowlist에 없는 action은 차단됩니다.
- **호환 endpoint**: `POST /chat/action`, body `{"prompt": str, "session_id": str?,
  "idempotency_key": str?}`. `ReadApiConfig.console_action` 이
  `ConsoleActionSubmitter`
  (`src/fdai/delivery/read_api/routes/console_action.py`)를 wire할 때만
  등록됩니다. 이 raw-prompt route는 호환 API client를 위해 남아 있으며 브라우저
  Command Deck은 사용하지 않습니다. 오퍼레이터 제공 값은
  bound된다(prompt <= 4000, question <= 2000, resource id / session id /
  idempotency key <= 200자) - 하나의 큰 값이 파이프라인/audit 을 bloat 하지
  못하게. 클라이언트 `idempotency_key` 는 proposal 의 dedup 키가 되어(initiator 로
  namespace 되므로 한 operator 가 다른 operator 의 키를 재사용해 그의 action 을
  suppress 할 수 없다), 재시도/중복 제출이 두 번째 action 을 enqueue 하지 않고
  Huginn 에서 collapse 된다; Thor 는 correlation 단위로 추가 멱등이므로
  at-least-once 재전달이 double-execute 되지 않는다.
- **서버 파생 RBAC**. 오퍼레이터 role은 검증된 bearer token(`Principal.roles`)
  에서 오며, 클라이언트 JSON이 아니다. 제출은 `author-draft-pr` capability
  (Contributor 이상)를 요구; Reader는 아무것도 발행되기 전에
  `403 {"submitted": false, "reason": "rbac_capability"}` 로 거부. Forseti가
  downstream에서 initiator principal을 재확인(deny + `SecurityEvent`) -
  defense in depth.
- **두 진입 게이트는 role rank가 아니라 capability로 일치한다**. 대화형 진입
  게이트(`Bragi.submit_action_proposal`)는 세션의 Entra role을 **동일한** canonical
  capability 매트릭스(`fdai.core.rbac.roles`)로 매핑하고 마찬가지로
  `author-draft-pr` 를 요구하므로, HTTP와 대화형 표면이 절대 어긋나지 않는다.
  특히 `BreakGlass` 는 하드 격리(Owner의 superset 아님)이고 `author-draft-pr` 를
  갖지 않으므로, 어느 표면에서도 일반 액션을 제출할 수 없다.
- **거부는 관측 가능하다**. 파이프라인 진입 전의 모든 거부(`invalid_principal` /
  `rbac_capability` / `deny_override_forbidden`)는 로깅되고 선택적으로 주입된
  `RefusalObserver`(`ConsoleActionSubmitter.refusal_observer`)에 전달되어, 한
  actor에 대한 반복 거부 - 요청이 파이프라인에 들어가지 않아 Forseti가 못 보는
  권한 프로빙 신호 - 를 탐지 가능하게 한다(audit / metric / security event). seam이
  없으면 구조화 로그 라인만 방출된다.
- **Legacy translation**. 호환 endpoint의
  `fdai.agents.bragi.translate_action_intent`는 먼저 정확한 ActionType
  id 또는 load된 ActionType catalog의 모호하지 않은 전체 suffix를 매칭합니다.
  예를 들어 `flush cache`는 `ops.flush-cache`로 매핑됩니다. 그다음 보수적인
  built-in verb fallback을 사용합니다. 모호하거나 매핑되지 않은 명령은 추측하지
  않고 `200 {"submitted": false, "reason": "unmapped_action_intent"}`를
  반환합니다. 이 함수는 pantheon 내부 경로와 공유하는 단일 진실원으로 유지됩니다.
- **Deny-override 차단 (Scenario B)**. `prior_outcome_lookup` seam이 wire되면,
  submitter는 publish 전에 이 정확한 `(initiator, resource, action_type)` 에
  대한 파이프라인의 마지막 terminal 결론을 확인한다. 직전 **deny**(안전하지
  않다고 판정됨)는 authoritative하다: 반복 콘솔 요청으로 이를 lift할 수 없어
  submitter는 `403 {"submitted": false, "reason": "deny_override_forbidden"}`
  로 거부하고 아무것도 publish하지 않는다 - deny는 오직 governed rule / policy
  / override 변경으로만 lift되며, 반복 요청으로는 절대 안 된다. 직전 **no-op**
  (대상이 이미 충족되어 액션이 불필요했던 경우)은 재요청을 막지 **않는다**:
  조건은 drift하므로 요청은 파이프라인에 재진입해 새로 judged된다. 이 규칙은
  하나의 순수 함수(`fdai.core.console_request.evaluate_operator_rerequest`)에
  산다. seam이 없으면 모든 요청은 fresh로 취급된다(deny-override 확인 없음).
- **응답**(제출됨): `200 {"submitted": true, "correlation_id": ...,
  "action_type": ..., "resource_id": ...}`. 오퍼레이터는 `correlation_id`
  (Trace 패널 / audit)로 진행을 추적; 파이프라인 결과(auto shadow-exec,
  HIL 대기, deny)는 비동기.
- **Investigation Incident**. 명시적 `tool.run-investigation <kind> <resource>` 명령 자체를
  확인으로 간주하여 session, target, resource kind에 대한 deterministic Incident를 만들거나
  재사용합니다. Proposal은 Incident ID를 correlation으로 사용하고 typed parameter에
  `incident_id`를 전달합니다. 일반 질문과 discovery 작업은 Incident를 만들지 않습니다.
- **Live stage turn**. 제출 성공 후 web deck은 인증된 correlation-filtered `/live/stream`
  reader를 열고 하나의 transcript turn을 Huginn ingest, Forseti route/verify/gate, Thor
  execute, Saga audit 순서로 갱신합니다. Audit가 terminal이며 timeout 또는 stream 실패 시
  durable Trace correlation이 recovery source로 남습니다.
- **이것은 13.3 approval callback과 나란한 두 번째 문서화된 write route**;
  둘 다 시그널을 기록할 뿐 executor Managed Identity를 갖지 않는다.

### 13.7 Python VM task workbench

Workflow Builder 는
[`python_tasks.py`](../../../src/fdai/delivery/read_api/routes/python_tasks.py) 의 여섯
mutation route 와 read-only `GET /python-tasks/capabilities` route 를 사용하는
multi-file Python task workbench 를 포함합니다.
Operator 는 source file 을 편집하고 entrypoint 를 선택하며 module 및 host
capability 를 선언한 뒤 validate, immutable artifact stage, inventory Resource 대상
shadow plan 을 수행할 수 있습니다.

Capability response 는 optional operation 별 가용성을 따로 보고합니다. Console 은 route 가
없으면 workbench 를 열지 않으며 adapter, submitter 또는 schedule store 가 연결되지 않은
operation 을 비활성화합니다. 따라서 unavailable path 가 generic `404` 로 실패하는 실행 가능한
control 처럼 표시되지 않습니다.

Workbench 는 console identity boundary 를 유지합니다.

- **Validate** 는 pure AST 및 manifest validation 입니다.
- **Generate editable draft** 는 operator intent, target capability, allowlisted
  module 로 injected `PythonTaskAuthor` 를 호출합니다. Draft 는 request control 이
  enable 되기 전에 계속 validate 및 stage 되어야 합니다.
- **Stage artifact** 는 VM 이 아니라 content-addressed artifact store 에 씁니다.
- **Test shadow plan** 은 `PlanningVmTaskRunner` 를 사용합니다. Read API 에는 Run
  Command 를 만들 수 있는 Managed Identity 가 없습니다.
- **Request governed run** 은 typed `ActionProposal` 을 publish 합니다. Console
  process 에서 `VmTaskRunner` 를 호출하거나 file 을 copy 하거나 Python 을 실행하지
  않습니다.
- **Create schedule** 은 선택한 catalog Workflow, artifact, inventory target 의
  strict cron binding 을 저장합니다. 이후 scheduler tick 이 typed event 를
  publish 합니다.

Background task, busy input, skill의 read API composition helper는 `routes/`에 두며 result panel은 validation issue, artifact reference, planned file 및 byte count,
target capability 또는 submitted correlation id 를 표시합니다. Control loop 가
proposal 을 수락한 후 runtime status 는 Processes 및 audit surface 에 이어집니다.

### 13.8 채팅 답변의 그라운딩된 코드

Command Deck 의 최종 답변에 fenced code block 이 있으면 read API 는 이를 크기가
제한된 `GroundedCodeArtifact` 로 추출합니다. Artifact 는 code, language, SHA-256
reference, static validation 결과를 포함합니다. Python block 은 import 하거나
실행하지 않고 parse 및 compile 합니다. 다른 언어는 검증되었다고 표시하지 않고
`not_checked` 로 표시합니다.

Console 은 기본적으로 code 를 **코드 근거** 아래에 접어서 표시합니다. Disclosure
를 펼치면 그라운딩된 정확한 content, artifact reference, syntax validation 통과
여부를 볼 수 있습니다. 최종 artifact 는 완료되지 않은 streaming token 이 아니라
검증된 최종 답변에서 생성됩니다. Tab 은 transcript 와 함께 artifact 를
`sessionStorage` 에 보존할 수 있으며, 방어적 parser 는 malformed 또는 oversized
entry 를 제거합니다.

이 표시 계약은 실행 권한을 부여하지 않습니다.

- **Runtime write 없음**: chat route 는 생성된 code 를 FDAI source tree, 설치된
  package, container filesystem 또는 active Git checkout 에 쓰지 않습니다.
- **Chat execution 없음**: read API 에서는 static parsing 만 수행합니다. 생성된
  module 을 import 하거나 subprocess 를 시작하거나 virtual environment 를 만들거나
  `VmTaskRunner` 를 호출하지 않습니다.
- **Governed execution 분리**: code 실행이 필요한 operator 는 `PythonTask` 를 만들고
  stage 한 후 section 13.7 flow 를 통해 typed `ActionProposal` 을 publish 합니다.
  Risk gate, approval ceiling, executor identity, audit path 가 계속 권위입니다.
- **Temporary storage 는 sandbox 자체가 아님**: runner 는 writable file 을 위해
  `/tmp/fdai-code/<run-id>` 와 같은 per-run directory 를 사용할 수 있습니다. 실제
  isolation 은 separate principal, read-only runtime filesystem, path 및 symlink 검사,
  resource limit, network policy, cleanup 에서 나옵니다. Path convention 만으로는
  security boundary 가 되지 않습니다.

### 13.9 온톨로지 레지스트리 projection

`GET /ontology/graph` 는 웹 콘솔의 세 가지 온톨로지 뷰를 위한 read-only
레지스트리 projection 입니다.

온톨로지 화면에는 `GET /inventory/graph`를 독립적으로 사용하는 네 번째 **온톨로지 맵**
뷰도 있습니다. 이 뷰는 런타임 리소스 projection이며 선언 카탈로그 또는 범용 온톨로지
인스턴스 테이블의 별도 복사본이 아닙니다. 이 분리를 통해 런타임 인벤토리를 사용할 수
없어도 레지스트리 뷰는 계속 사용할 수 있습니다.

저장 위치 질문은 요청한 경로를 누락된 화면 필드로 취급하지 않고 결정적 catalog contract를
사용합니다. 기본 ObjectType과 LinkType 정의는 `rule-catalog/vocabulary/object-types/` 및
`rule-catalog/vocabulary/link-types/`에서, ActionType 정의는 `rule-catalog/action-types/`에서
가져옵니다. Downstream composition은 검증된 추가 root를 주입할 수 있습니다. Read API는 시작할
때 합성된 정의를 immutable in-memory catalog로 로드하고 `/ontology/graph`가 그 catalog를
read-only projection으로 제공합니다. 운영 ontology instance는 PostgreSQL의
`ontology_resource`와 `ontology_link`에 저장됩니다. ObjectType과 LinkType metadata도 FK 검증용
reference로 PostgreSQL에 동기화될 수 있지만, 해당 row는 정의의 authoring source 또는 source of
truth가 아닙니다. SPA는 별도 복사본을 저장하지 않습니다. JSON 및 SSE chat은 narrator를 호출하지
않고 동일한 contract 답변을 반환합니다.

- **Objects**: ObjectType 과 LinkType edge 를 선택된 하나의 결정적 one-hop
  neighborhood 로 렌더링합니다. Inspector 는 기록된 property 와 incoming 및
  outgoing relationship 을 표시합니다.
- **Links**: LinkType 을 선택하면 기록된 모든 `from_type -> to_type` endpoint pair,
  cardinality, causal, transitive, temporal flag 를 표시합니다. 콘솔은 카탈로그에
  없는 relationship semantics 를 추론하지 않습니다.
- **Actions**: 응답은 로드된 ActionType 카탈로그를 완전한 safety-contract record 로
  포함합니다. Catalog 뷰는 category, trigger, execution path, rollback contract,
  default mode, precondition, stop condition, blast-radius declaration, tier ceiling,
  promotion gate 를 표시합니다.
- **온톨로지 맵**: operator가 루트 리소스 id를 입력하기 전에는 콘솔이 인벤토리 요청을
  보내지 않습니다. 입력 후에는 `depth=2`, `limit=200`,
  `contains,attached_to,depends_on`으로 제한된 인접 관계만 요청합니다. 인접 리소스를
  선택해 쿼리 루트를 변경할 수 있습니다. 이 뷰는 provider의 원본, 최신 상태, 스냅샷
  시각, 안정적인 잘림 사유를 유지하고, 인벤토리 라우트를 사용할 수 없어도 세 가지
  레지스트리 뷰를 비활성화하지 않습니다.

ActionType projection 은 additive 입니다. 이전 deployment 에서는
`action_type_count` 와 `action_types` 가 없거나 0일 수 있지만 ObjectType 과
LinkType 탐색은 계속 동작합니다. 큰 action catalog 가 resource relationship 을
가리지 않도록 ActionType 은 ObjectType graph 에 넣지 않습니다. 네 뷰는 모두
GET-only 이며 action 또는 approval 호출을 실행하지 않습니다.
