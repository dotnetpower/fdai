---
title: Operator Console Module Map and Boundaries
translation_of: operator-console-module-map.md
translation_source_sha: a353782aa8b16e2814fe56a2da315c1ce7a03fb9
translation_revised: 2026-08-08
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
[`test_operator_api_layout.py`](../../../services/operator-service/tests/)는 현재 모든
package와 route module이 분류된 상태인지 확인하고, exact 기본 method, path, route-name set 및 대표 HTTP
envelope를 고정합니다. 의도적인 기본 route 추가는 같은 변경에서 검토된 baseline을 갱신합니다.

### Dependency-direction gate

`check-operator-api-boundaries.py`는 application code를 로드하지 않고 import를 파싱합니다. 정리된
core-to-delivery, runtime-to-Operator API, ingestion-to-Operator API, shared
delivery-to-application, application-to-provider-adapter 및 route-to-provider-adapter 방향은 enforced
check로 유지합니다. 기존 route-to-core policy import와 반대
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

### Conversation claims application boundary

SD-01 claims slice는 `fdai.delivery.operator_api.application.conversation.claims` 아래에서
deterministic answer-claim verification을 소유합니다. Extraction, evidence collection, matching,
manifest construction 및 frozen-corpus evaluation은 process 안에서 실행되며 request-local state만
유지합니다. Route adapter는 authentication, HTTP status mapping, JSON envelope, SSE sequencing,
cancellation 및 terminal rendering을 계속 소유합니다.

소유된 terminal verifier는 explicit claims package facade를 import합니다. 기존
`routes.chat_claim*` module의 repository-wide consumer는 internal implementation 또는 test import였고
같은 slice에서 이동했으므로 claim compatibility shim은 남기지 않습니다. Rollback은 implementation
module과 facade를 `routes/` 아래에 복원한 다음 claims package facade가 복원된 owner를 가리키게 합니다.
이 과정에서 JSON 또는 SSE wire contract는 변경하지 않습니다.

### Conversation verification application boundary

SD-01 verification slice는 `fdai.delivery.operator_api.application.conversation.verification`
아래에서 terminal answer verification을 소유합니다. 이 package는 canonical result, text-integrity
check, deterministic claim/evidence coordination, bounded incident/agent-activity rendering,
tool/operational verification handler를 포함합니다. Request-local이며 HTTP status mapping, JSON
envelope, SSE sequencing, authentication, cancellation 및 terminal frame assembly는 route에 유지합니다.

Internal route와 test consumer는 explicit package facade를 import합니다. Capability catalog는 해당
owned package를 직접 사용하므로 `routes/` 아래에 verification compatibility module이 남지 않습니다.
Rollback은 이동한 module을 `routes/` 아래에 복원하고 package facade가 복원된 owner를 가리키게 합니다.
JSON, SSE, authentication 또는 conversation-history behavior는 변경하지 않습니다.

### Conversation presentation projection boundary

SD-01 presentation slice는
`fdai.delivery.operator_api.projections.conversation.presentation` 아래에서 value-free layout
selection과 검증된 evidence artifact compilation을 소유합니다. 이 package에는 presentation contract,
shape profile, bounded planner, deterministic inventory 및 subscription-health artifact compiler가
포함됩니다. Read-only이며 request-local입니다.

JSON 및 SSE route는 explicit presentation facade를 import하며 authentication, HTTP status mapping,
JSON envelope, SSE sequence와 revision, cancellation, terminal assembly 및 conversation history를
계속 소유합니다. 기존 `routes.chat_presentation*` module은 internal import path였으므로 compatibility
shim을 남기지 않습니다. 이 이동은 canonical text fallback, artifact schema, localized label,
evidence reference, byte bound 및 planner degradation을 정확히 보존합니다. Rollback은 route
implementation module을 복원하고 wire contract를 변경하지 않은 채 presentation facade가 복원된
owner를 가리키게 합니다.

### Conversation inventory application 및 projection boundary

SD-01 inventory slice는 typed query, deterministic compilation, follow-up scope,
catalog-backed language/resource semantic, ontology function, semantic retrieval 및 provider-read
coordination을 `fdai.delivery.operator_api.application.conversation.capabilities.inventory`
아래에서 소유합니다. 이 capability는 read-only이고 request-local입니다. HTTP, SSE,
authentication, cancellation, history 또는 inventory write는 소유하지 않습니다.

Sanitization, current/activity result projection, scheduled-shutdown projection 및 deterministic
answer rendering은 `fdai.delivery.operator_api.projections.conversation.inventory` 아래에 있습니다.
Route와 terminal verification은 책임에 따라 explicit application 또는 projection facade를 import합니다.
기존 `routes.chat_inventory*` consumer는 모두 internal implementation 또는 test code였으므로
compatibility shim을 남기지 않습니다. JSON, SSE sequence/revision, authorization, provider scope 및
conversation history behavior는 변경되지 않습니다.

Rollback은 inventory implementation module을 `routes/` 아래에 복원하고 두 inventory package
facade가 복원된 owner를 가리키게 합니다. Wire contract와 authoritative inventory provider는
변경하지 않습니다.

### Conversation backend application 및 adapter boundary

SD-01 backend slice는 `fdai.delivery.operator_api.application.conversation.backend` 아래에서
provider-neutral contract와 request-local latency routing을 소유합니다. Application package는 injected
backend 중 하나를 선택하고 bounded failover와 multimodal dispatch를 보존하며 credential이 없는 endpoint
metadata만 노출합니다. Azure 또는 OpenAI implementation은 import하지 않습니다.

Concrete Azure workload-identity 및 OpenAI-compatible HTTP implementation, shared response validation,
metering transport, resolved-model loading 및 startup construction은
`fdai.delivery.operator_api.adapters.conversation` 아래에 있습니다. JSON 및 SSE route는 authentication,
HTTP status mapping, sequence와 revision, cancellation, terminal delivery 및 conversation history를 계속
소유합니다. 기존 `routes.chat_backend_*` module의 repository consumer는 모두 internal implementation 또는
test import였으므로 compatibility shim을 남기지 않습니다.

Rollback은 다섯 backend module을 `routes/` 아래에 복원한 다음 application 및 adapter facade가 복원된
owner를 가리키게 합니다. Auth, provider scope, JSON 또는 SSE는 변경하지 않습니다.

### Conversation evidence application boundary

SD-01 evidence slice는
`fdai.delivery.operator_api.application.conversation.evidence` 아래에서 read-only operational
evidence resolution, provenance projection, bounded branch lifecycle 및 authority-preserving result
merge를 소유합니다. Operational lookup은 authorized server read model을 계속 읽으며 정확한
`matched`, `summary`, `ambiguous`, `none`, `unavailable` outcome을 유지합니다. Evidence가 없거나
충돌하거나 선택되지 않은 경우 unsupported answer로 넘어가지 않고 명시적으로 유지합니다.

독립 branch는 계속 concurrent하게 완료되며 canonical specification order로 반환됩니다. Merge는 기존
tool, operational, agent 및 public-web authority precedence를 유지합니다. JSON 및 SSE route는
authentication, request parsing, HTTP status mapping, frame sequence와 revision, cancellation,
terminal assembly 및 conversation history를 계속 소유합니다. 기존 `routes.chat_evidence*` consumer는
모두 internal source 또는 test import였고 이 slice에서 이동했으므로 compatibility shim은 남기지
않습니다. Rollback은 다섯 route implementation을 복원하고 JSON, SSE, authentication, evidence
authority 또는 history를 변경하지 않은 채 evidence facade가 복원된 owner를 가리키게 합니다.

### Conversation progress metric projection boundary

SD-01 streaming metric slice는
`fdai.delivery.operator_api.projections.conversation.stream_metrics` 아래에서 queue에 수락된
progress의 pure reduction을 소유합니다. First-progress latency, terminal branch outcome과 duration,
output truncation의 aggregate만 기록합니다. Prompt, answer, branch id, channel id, principal id 또는
resource identifier는 보관하지 않습니다.

SSE route는 frame sequencing, queue admission, cancellation 및 transport delivery를 계속 소유합니다.
기존 `routes.chat_stream_metrics` module에는 external compatibility consumer가 없었으므로 shim을
남기지 않습니다. Rollback은 reducer를 `routes/` 아래에 복원하고 metric name, SSE frame 또는
cancellation behavior를 변경하지 않은 채 stream route import를 되돌립니다.

### Conversation terminal projection boundary

SD-01 terminal slice는 `fdai.delivery.operator_api.projections.conversation.terminal` 아래에서 pure
verification-frame assembly, terminal payload compilation, 측정된 LLM usage rendering, durable inventory
result context 및 source-failure replay context를 소유합니다. 이 package는 terminal response에 사용되는
bounded public intent-graph 및 conversation-policy summary도 소유합니다. 이 경계는 read-only이며
request-local입니다.

JSON 및 SSE route는 계속 authentication, request parsing, HTTP status mapping, frame sequence와 revision,
cancellation, terminal delivery 및 conversation history를 소유합니다. 이전 route 모듈 4개의 모든 repository
consumer는 explicit terminal facade로 이동했고 package는 `fdai.delivery.operator_api.routes` 모듈을 import하지
않으므로 compatibility shim이 남지 않습니다. Rollback은 route 구현 4개를 복원하고 terminal facade를
redirect하며 두 wire contract는 변경하지 않습니다.

### Conversation post-generation application boundary

SD-01 post-generation slice는
`fdai.delivery.operator_api.application.conversation.post_generation` 아래에서 streamed turn
completion을 소유합니다. Answer generation 이후 이 package는 기존 순서대로 bounded quality review,
deterministic verification, terminal payload validation, principal 범위 assistant-turn persistence 및
off-path post-turn review를 조정합니다. Pure payload compilation은
`projections.conversation.terminal`에 위임하고 durable history는 injected persister를 통해서만 씁니다.

SSE route는 authorization, request parsing, heartbeat framing, connection 및 busy-input cancellation,
request sequence와 revision, trajectory projection 및 최종 transport delivery를 계속 소유합니다. 이
package는 `fdai.delivery.operator_api.routes` module을 import하지 않습니다. 기존
`routes.chat_stream_post_generation` path는 internal이었으므로 compatibility shim을 남기지 않습니다.
Rollback은 해당 route module을 복원하고 stream-route import를 변경하며 frame order, JSON 또는 SSE
terminal payload, verification, history 및 post-turn review behavior는 변경하지 않습니다.

### Conversation request preparation application boundary

SD-01 request-preparation 슬라이스는
`fdai.delivery.operator_api.application.conversation.request_preparation` 아래에서 content-policy
validation과 replay, 사용자 preference, document-reference resolution, complete-history 조립,
verified prior context, resource와 freshness context, follow-up scope, answer planning,
target-agent 파생을 소유합니다. 이 package는 server-authenticated, byte-bounded JSON object 하나를
받고 typed prepared request 또는 replay outcome을 반환합니다. Process-local이고 authority가
없으며 `operator_api.routes` module을 import하지 않습니다.

`routes/chat_stream_request.py`는 `authorize(request)`, Content-Length preflight, raw body 읽기,
byte 제한, JSON-object parsing, Starlette `HTTPException` mapping 및 SSE adapter 호출을 유지합니다.
JSON chat은 기존 transport 순서를 유지하면서 같은 preparation contract와 helper를 import합니다.
기존 route-owned history module은 전체 이동했고 document, replay, resource-context, identity helper는
혼합 route module에서 분리했습니다. 모든 consumer가 internal source 또는 test import였으므로
compatibility shim은 남기지 않았습니다.

Document resolver 실패는 JSON과 SSE 모두 application boundary에서 하나의 고정된 unavailable
detail로 변환됩니다. Exception chaining은 내부 진단을 보존하지만 provider URL, token 및 error
text는 HTTP boundary를 넘지 않습니다.

Rollback은 history와 preparation helper를 `routes/` 아래에 복원하고 `chat_stream_setup.py`를
복원한 뒤 JSON과 SSE import를 되돌립니다. Authentication, status code, body bound,
content-policy replay, history, document access, answer plan 및 두 wire contract는 변경하지 않습니다.

### Conversation lifecycle application boundary

SD-01 lifecycle slice는 shadow answer-planning task coordination을
`application.conversation.planning`으로, Korean narrator review를
`application.conversation.post_generation.quality`로, input content-policy recovery를
`application.conversation.request_preparation.content_policy`로, request-local steer 및 active
narrator interruption coordination을 `application.conversation.busy_input`으로 이동합니다. 이 module들은
bounded process-local state만 유지하며 `operator_api.routes` module을 import하지 않습니다.

`BusyInputCoordinator`는 active-turn registration과 arbitration을 담당하는 core authority로 유지됩니다.
Application helper는 safe-boundary와 cancel-event contract만 사용하며 conversation cancellation을 Thor,
ActionType 또는 managed-resource state에 연결하지 않습니다. JSON 및 SSE route는 authentication, HTTP/SSE
status mapping, frame sequence와 revision, connection cancellation, history transport 및 최종 delivery를
계속 소유합니다.

이전 route module consumer는 모두 internal source 또는 test code였으므로 compatibility shim은 남기지
않습니다. Rollback은 네 route implementation을 복원하고 internal import를 되돌리며 planning bound,
quality verification, policy recovery, steering, interruption, JSON 또는 SSE behavior는 변경하지 않습니다.

### Conversation terminal support projection 경계

SD-01 terminal support slice는 bounded trajectory-detail replay, deterministic current-screen T0
answer, opt-in redacted model-call trace, verified resource-follow-up response context를
`fdai.delivery.operator_api.projections.conversation` 아래에서 소유합니다. 이 projection은 read-only이고
request-local입니다. `operator_api.routes` module을 import하지 않고 durable write, model call 또는 provider
call을 수행하지 않습니다.

Request resource parsing 및 follow-up contextualization은
`application.conversation.request_preparation.resource_context`에 유지됩니다. Azure 및 OpenAI-compatible
adapter는 이미 수행된 model request와 response를 tracing projection에 기록하고 provider call은 계속
adapter가 소유합니다. JSON 및 SSE route는 authentication, body parsing, status mapping, frame sequence와
revision, cancellation, terminal delivery, conversation history를 유지합니다. 이전 route consumer는 모두
internal이므로 compatibility shim은 남기지 않습니다. Rollback은 네 route implementation을 복원하고
internal consumer를 redirect하며 wire contract는 변경하지 않습니다.

### Conversation persistence 및 document evidence 경계

SD-01 persistence slice는 principal 범위 transcript write, content-free policy receipt, replay
metadata 및 conversation-image lifecycle을
`fdai.delivery.operator_api.persistence.conversation` 아래에서 소유합니다. Explicit facade는 stable
operator/assistant idempotency key, ordered turn allocation 및 bounded ontology projection을
보존합니다. Assistant projection timeout 또는 실패는 durable answer write 이후 logged degradation으로
유지되며 저장된 answer 또는 terminal response를 변경하지 않습니다.

Validated image는 기존 pending create, exact-attempt compensation 및 durable finalization 순서를
유지합니다. Turn metadata에는 image id, display name 및 검증된 media type만 포함됩니다. Image byte는
principal과 conversation 범위 image repository에 유지됩니다. Pure governed document context 및
verification merge는 `projections.conversation.document_evidence`에 있으며 exact citation value와
duplicate ref 제거 시 stable first-occurrence order를 보존합니다.

JSON 및 SSE route는 authentication, request parsing, HTTP status mapping, frame sequence와 revision,
cancellation 및 transport delivery를 유지합니다. 이전 route-module consumer는 모두 internal source 또는
test code였으므로 compatibility shim은 남기지 않습니다. Rollback은 세 implementation을 `routes/` 아래에
복원하고 internal import를 되돌리며 transcript identity, image expiry, document ref, JSON 또는 SSE behavior는
변경하지 않습니다.

### Conversation capability application 경계

SD-01 capability slice는 bounded Pantheon delegation, runtime-skill disclosure,
configuration-baseline read, public-web evidence resolution, request-time capability visibility 및 strict
topology intent를 `fdai.delivery.operator_api.application.conversation` 아래에서 소유합니다. Agent
delegation은 기존 runtime 및 bridge contract를 사용하는 read-only adapter로 유지됩니다. Action proposal과
handoff materialization을 비활성화하며 Pantheon의 judgment, approval, execution, recovery 또는 audit authority를
Operator API로 옮기지 않습니다.

Provider-neutral web-search resolver는 deterministic 및 semantic intent precedence, sanitization, bounded
timeout, availability, progress 및 fail-closed provider error를
`application.conversation.capabilities.web_search` 아래에서 소유합니다. Azure candidate construction과
environment loading은 `adapters.conversation.web_search`에 둡니다. Caller text는 provider scope, allowed
domain, endpoint, deployment 또는 credential을 제공하지 않습니다. Configuration drift는 정확한 server-pinned
document route를 action-context phrase보다 먼저 유지하고, topology intent는 계속 exact server-owned
selector를 요구합니다.

JSON 및 SSE route는 authentication, request parsing, HTTP status mapping, frame sequence와 revision,
cancellation, terminal delivery 및 conversation history를 유지합니다. 이전 route module 6개의 consumer는
모두 internal source 또는 test import였으므로 compatibility shim을 남기지 않습니다. Rollback은 해당
implementation을 `routes/` 아래에 복원하고 internal import를 되돌리며 authority classification, provider
scope, intent precedence 또는 wire contract는 변경하지 않습니다.

### 최종 conversation route closure

Commit `e141ab07e`은 여섯 file의 structural inventory를 확립하고 compiled user policy,
assurance policy 및 one-shot response completion을 explicit application owner 뒤로 이동했습니다. Pure
terminal summary와 payload value는 `projections.conversation.terminal`에 유지하며 conversation
application, projection 및 persistence package는 route module을 import하지 않습니다.

JSON 및 streamed turn lifecycle은 이제 `application/conversation/turn_execution` 아래에 있습니다.
Typed service는 Starlette, provider adapter 또는 route module을 import하지 않고 request preparation,
planning, evidence, generation과 stream collection, busy input, verification, response completion,
persistence, metering 및 user-context projection을 조정합니다. `chat.py`는 authentication, bounded
JSON parsing, application error-to-status mapping, `JSONResponse` delivery, route binding 및 검토된
compatibility import를 유지합니다.

`chat_stream.py`는 이제 authentication과 bounded request transport delegation, stream 시작 전
application error-to-status mapping, `StreamingResponse` construction, SSE encoding, heartbeat byte,
sequence와 revision field, async iterator teardown을 통한 connection-close cancellation만 유지합니다.
Application event가 canonical answer `revision`을 소유하고 route는 wire-frame order용 별도 monotonic
`seq`를 추가하며 revision을 변경하지 않고 보존합니다. `chat_registration.py`는 registration,
`chat_stream_protocol.py`는 SSE protocol,
`chat_stream_request.py`는 request transport를 소유합니다. Chat family는 SSE frame order, replay,
interruption, cancellation, history 및 terminal payload를 보존하면서 structural transport-only 상태가
되었습니다.

### Change lineage projection 경계

SD-06 Operator projection은 `fdai.delivery.operator_api.projections.change_lineage` 아래에서
canonical immutable Change lineage의 bounded summary 및 detail view를 소유합니다. Read-only이고
request-local이며 candidate-only learning과 execution/promotion authority 0을 보존하고 provider I/O나
persistence를 수행하지 않습니다.

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
| `adapters/` | HTTP route 밖의 concrete Operator API provider implementation | Provider I/O를 application contract 뒤에 유지합니다. |
| `adapters/conversation/` | Azure 및 OpenAI-compatible narrator transport와 web-search startup construction | Explicit module로 import하고 credential, endpoint, deployment selection 및 transport는 application과 route 밖에 유지합니다. |
| `app/` | Shared ASGI assembly, middleware, registration 및 lifespan | HTTP composition boundary로 유지합니다. |
| `application/` | Typed process-local, non-authoritative application coordination | Service-graduation evidence가 process boundary를 정당화할 때까지 유지합니다. |
| `application/conversation/` | HTTP transport 밖의 process-local conversation planning, server policy resolution, one-shot JSON execution, response completion, capability visibility, strict intent classification, busy-input steering, interruption 및 capability | Service-graduation evidence가 준비될 때까지 process 안에 유지하고 HTTP 및 SSE transport 책임은 route에 둡니다. |
| `application/conversation/turn_execution/` | Typed, Starlette-free JSON 및 streamed turn request preparation, planning, evidence, generation, verification, persistence, metering 및 completion coordination | Explicit facade로 import하고 authentication, body parsing, status mapping, JSON/SSE encoding, heartbeat, sequence, revision 및 response delivery는 route에 유지합니다. |
| `application/conversation/capabilities/` | Domain별 typed process-local agent delegation, runtime-skill, configuration-drift, web-search 및 read-model capability | Non-authoritative capability owner로 유지하고 injected read-only runtime과 provider contract를 사용합니다. |
| `application/conversation/capabilities/inventory/` | Typed inventory query, deterministic compilation, semantic grounding 및 provider-read coordination | Explicit package facade로 import하고 JSON, SSE, authentication 및 history는 route에 유지합니다. |
| `application/conversation/backend/` | Provider-neutral backend contract 및 request-local latency routing | Explicit facade로 import하고 provider implementation은 adapter에 유지합니다. |
| `application/conversation/claims/` | Deterministic answer-claim extraction 및 bounded evidence verification | Explicit package facade로 import하고 JSON, SSE 및 authentication은 route에 유지합니다. |
| `application/conversation/verification/` | Deterministic terminal answer verification 및 bounded evidence rendering | Explicit package facade로 import하고 wire behavior와 authentication은 route에 유지합니다. |
| `application/conversation/evidence/` | Operational evidence resolution, provenance, branch lifecycle 및 authority-preserving merge | Explicit package facade로 import하고 JSON, SSE, authentication, cancellation 및 history는 route에 유지합니다. |
| `application/conversation/post_generation/` | Quality review, verification, history persistence coordination, terminal payload validation 및 post-turn review | Explicit package facade로 import하고 authorization, request parsing, heartbeat framing, sequencing, cancellation 및 SSE delivery는 route에 유지합니다. |
| `application/conversation/request_preparation/` | Content policy와 replay, preference, document ref, history, prior context, resource와 freshness context, follow-up scope, answer plan 및 target-agent 파생 | Explicit package facade로 import하고 authorization, bounded body parsing, HTTP mapping, SSE sequencing 및 transport delivery는 route에 유지합니다. |
| `dev/` | Interactive local 및 test-only provider composition | Production import에서 사용할 수 없게 유지합니다. |
| `dev/fixtures/` | Synthetic pytest-only fixture | Production composition 밖에 유지합니다. |
| `persistence/` | Operator API read-model 및 conversation-state persistence implementation | 소유된 store contract 뒤에 유지합니다. |
| `persistence/conversation/` | Principal 범위 transcript, policy receipt, replay metadata 및 conversation-image lifecycle persistence | Explicit facade로 import하고 HTTP, SSE, authentication, status mapping 및 transport는 route에 유지합니다. |
| `projections/` | HTTP route 밖의 read-only projection ownership | Migrated family의 owner로 유지합니다. |
| `projections/audit/` | Audit query 및 autonomy/FinOps measurement projection | Explicit facade를 통해 import하고 기존 route module은 shim으로 유지합니다. |
| `projections/change_lineage/` | Bounded canonical Change-lineage summary 및 detail view | Explicit facade로 import하고 HTTP, provider I/O, persistence, execution 및 promotion은 package 밖에 유지합니다. |
| `projections/conversation/` | Screen data, exact document evidence, model trace, trajectory detail, resource response context 및 queue에 수락된 progress metric reduction을 포함하는 request-local conversation read projection | Service-graduation evidence가 준비될 때까지 process 안에 유지합니다. |
| `projections/conversation/presentation/` | Value-free layout selection 및 검증된 evidence artifact compilation | Explicit facade로 import하고 JSON 및 SSE behavior는 route에 유지합니다. |
| `projections/conversation/inventory/` | Inventory evidence sanitization, result projection 및 deterministic rendering | Explicit facade로 import하고 query compilation과 provider coordination은 application package에 유지합니다. |
| `projections/conversation/terminal/` | Terminal payload, LLM usage, resource-result 및 source-failure projection | Explicit facade로 import하고 JSON, SSE, authentication, cancellation 및 history는 route에 유지합니다. |
| `production/` | Production provider construction 및 binding | Wire behavior를 변경하지 않고 fanout을 점진적으로 줄입니다. |
| `routes/` | HTTP/SSE transport, route registration, domain request adapter 및 분류된 compatibility facade | Transport 및 검토된 facade boundary로 유지하고 conversation lifecycle orchestration은 typed application facade 뒤에 둡니다. |
| `streaming/` | Read-only SSE transport, redaction, fanout 및 runtime projection | Versioned relay 및 replay contract가 준비될 때까지 유지합니다. |

`fdai.delivery.operator_api.main`은 public app facade입니다. `read_model`은 검토된 replacement가 준비될
때까지 public delivery contract로 유지합니다. `fdai.delivery.auth`는 framework-neutral bearer 및 Entra
verification을 소유하고 `operator_api.auth`와 `operator_api.entra_verifier`는 compatibility facade로만
유지됩니다.
`main` facade의 `busy_input_runtime` re-export는 새 runtime ownership claim이 아닌 transitional public
seam입니다.
현재 fork 및 reporting guide가 직접 import하므로 `routes.panels`와 `routes.reporting`은 transitional
public extension seam으로 유지합니다. 그 외 개별 `routes.*` module은 internal implementation path이며,
분류된 compatibility 필요가 있을 때만 module별 forwarding shim을 사용합니다.
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

- [`services/core-control-plane/src/fdai/core/conversation/`](../../../services/core-control-plane/src/fdai/core/conversation)
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
- [`services/core-control-plane/src/fdai/core/conversation/channel_gateway.py`](../../../services/core-control-plane/src/fdai/core/conversation/channel_gateway.py)는
  sender를 인증하고 message idempotency key를 claim하며 coordinator를 호출합니다. Durable delivery가
  구성되면 provider send 전에 complete response를 저장합니다.
- [`services/operator-service/src/fdai_operator_service//`](../../../services/operator-service/src/fdai_operator_service/)
  - `teams.py`는 bearer-token verification 이후 Bot Framework activity를 normalize하고 injected reply
    publisher를 사용합니다. Payload-supplied reply URL을 신뢰하지 않습니다.
  - `slack.py`는 timestamped signature를 검증하고 replay 또는 bot-authored event를 차단하며 message를
    normalize하고 injected reply publisher를 사용합니다.
  - Slack, Teams 및 web attachment contract는
    [conversation attachment](conversation-attachments-ko.md)를 통해 수렴합니다. Dedicated WebSocket
    adapter는 optional입니다.
- [`current_time.py`](../../../services/operator-service/src/fdai_operator_service/)는 injected
  aware clock과 principal IANA timezone에서 current-time 질문을 resolve합니다.

## Operator API route ownership

- `application/conversation/backend/`는 provider-neutral backend contract, prompt-policy error, bounded
  latency routing, failover 및 multimodal dispatch를 소유합니다. Provider I/O, HTTP, SSE, authentication 또는
  durable state는 소유하지 않습니다.
- `adapters/conversation/`은 Azure workload-identity 및 OpenAI-compatible provider call, response validation,
  metering transport, resolved-model loading 및 backend construction을 소유합니다. Route authorization, JSON
  또는 SSE delivery, conversation history는 소유하지 않습니다.
- `application/conversation/claims/`는 deterministic claim extraction, evidence matching 및 evidence
  manifest를 소유합니다. HTTP, SSE, authentication 또는 durable state는 소유하지 않습니다.
- `application/conversation/verification/`은 terminal answer integrity, deterministic evidence
  verification 및 bounded verification prose를 소유합니다. HTTP, SSE, authentication, cancellation
  또는 durable state는 소유하지 않습니다.
- `application/conversation/capabilities/inventory/`는 typed inventory query, compilation,
  semantic grounding 및 provider-read coordination을 소유합니다. HTTP, SSE, authentication,
  history, rendering 또는 inventory write는 소유하지 않습니다.
- `application/conversation/evidence/`는 read-only operational evidence resolution, provenance,
  canonical branch ordering 및 authority-preserving merge를 소유합니다. HTTP, SSE, authentication,
  cancellation, history 또는 durable state는 소유하지 않습니다.
- `application/conversation/post_generation/`은 ordered quality review, verification, terminal
  validation, history persistence coordination 및 post-turn review를 소유합니다. HTTP,
  authentication, request parsing, heartbeat framing, SSE sequencing, connection cancellation 또는
  transport delivery는 소유하지 않습니다.
- `application/conversation/request_preparation/`은 content-policy validation과 replay,
  preference, document ref, history 조립, verified prior context, resource와 freshness context,
  follow-up scope, answer planning 및 target-agent 파생을 소유합니다. Request, HTTP status mapping,
  authorization, SSE sequencing, cancellation 또는 transport delivery는 소유하지 않습니다.
- `application/conversation/planning.py`는 bounded shadow planning task start, metadata 및 drain을
  소유합니다. `application/conversation/busy_input.py`는 safe-boundary steering과 active narrator
  interruption만 소유합니다. 두 module 모두 connection cancellation, core busy-input authority,
  action state 또는 durable state를 소유하지 않습니다.
- `application/conversation/capabilities/`는 action, prior-context, current-time, source,
  readiness, knowledge, metering, log, network, subscription-health, T2 recovery, behavior 및
  read-model helper를 소유합니다. `application/conversation/`은 turn/intent-graph planning, prompt
  assembly, public-web intent 및 vision validation을 소유합니다. 두 package 모두 `routes`를 import하지
  않습니다.
- `projections/conversation/presentation/`은 value-free presentation plan, 검증된 evidence artifact
  compilation, bound 및 localized label을 소유합니다. HTTP, SSE, authentication, cancellation,
  terminal delivery 또는 durable state는 소유하지 않습니다.
- `projections/conversation/inventory/`는 inventory evidence sanitization, result projection 및
  deterministic rendering을 소유합니다. Provider selection, query compilation, HTTP, SSE,
  authentication, history 또는 durable state는 소유하지 않습니다.
- `projections/conversation/terminal/`은 terminal verification-frame 및 payload assembly, 측정된 LLM
  usage rendering, durable result context 및 bounded public terminal summary를 소유합니다. HTTP, SSE
  sequencing, authentication, cancellation, history 또는 durable state는 소유하지 않습니다.
- `projections/conversation/stream_metrics.py`는 queue에 수락된 aggregate progress reduction을
  소유합니다. Frame sequencing, queue admission, cancellation, transport 또는 durable state는
  소유하지 않습니다.
- `projections/conversation/`은 incident-dossier와 RCA rendering, bounded execution-output
  projection, provider-receipt projection, tool-progress reduction, current-screen T0 rendering,
  redacted model trace, trajectory-detail replay 및 resource-follow-up response projection을 소유합니다.
  이동된 internal helper에는 compatibility shim이 없습니다.
- `routes/chat_stream_request.py`는 authorization, Content-Length와 raw-body bound, JSON-object
  parsing, application error의 HTTP mapping 및 SSE preparation adapter를 소유합니다.
- `application/conversation/turn_execution/`은 typed dependency와 result를 통해 one-shot JSON
  request preparation, planning, evidence, generation, verification, persistence, metering 및 terminal
  completion을 소유합니다. Starlette, route 또는 provider-adapter module을 import하지 않습니다.
- 다섯 file의 `chat*.py` structural inventory에는 `chat.py`, `chat_registration.py`,
  `chat_stream.py`, `chat_stream_protocol.py` 및 `chat_stream_request.py`가 포함됩니다. `chat.py`는 이제
  JSON HTTP transport와 compatibility binding만 소유합니다. `chat_stream.py`는 SSE transport만 소유하고
  application revision을 transport sequence가 있는 frame으로 매핑합니다. 나머지 세 file은 각각
  registration, SSE protocol 및 request-transport owner로 유지됩니다.
- `application/conversation/capabilities/knowledge_context.py`는 state write 없이 exact prior-turn
  runbook, source freshness, consented
  memory 및 materialized learning을 읽습니다.
- `application/conversation/vision_prompt.py`는 validated image를 projection합니다.
- `routes/`는 JSON/SSE envelope, authentication, HTTP/SSE status mapping, frame sequencing,
  connection cancellation, route registration과 graph, data-source, readiness projection의 HTTP
  handler를 유지합니다.
- `read_investigation_responder.py`는 registered Heimdall read intent를 typed evidence에서 렌더링합니다.
  Evidence가 없으면 explicit unavailable answer를 반환합니다. `read_investigation_catalog.py`는 catalog
  ID, ownership 또는 plan binding drift 시 startup을 차단합니다.
- `routes/rule_catalog.py`는 read-only active/discovery Rule reference projection을 제공합니다.
  Catalog와 일치하는 active generation에서만 semantic ranking을 사용하고, 그 외에는 명시적인
  degraded state와 함께 lexical result를 반환합니다. Reader-gated `POST /rules/search`는 exact
  `catalog.search_rules` ontology function을 invoke하고 evaluation 또는 execution authority 없이
  retrieval 및 function receipt를 반환합니다. Generation publishing은 API startup 밖에 유지합니다.

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
