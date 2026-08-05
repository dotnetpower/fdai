---
title: 콘솔 근거 및 복원력
translation_of: console-evidence-and-resilience.md
translation_source_sha: af298eb7a4636742c4f3a5593550482d4b647e08
translation_revised: 2026-08-05
---

# 콘솔 근거 및 복원력

이 문서는 operator console의 evidence provenance, localization, stream recovery, durable replay 및 Architecture map resilience 계약을 소유합니다. 대화형 tool 및 RBAC 계약은
[operator-console-ko.md](operator-console-ko.md)에 유지됩니다.

## 탐색 컨텍스트

Activity Bar 영역을 선택하면 Explorer가 열리고 운영자의 로컬 순서 및 표시 설정에 따라 첫 번째 visible 패널로 이동합니다. Command Deck이 닫혀 있거나 floating 상태여도 이 탐색은 동작하며,
full-workspace Deck은 route가 변경되기 전에 닫힙니다.
다른 화면의 cached conversation 선택은 bounded exception입니다. Console은 conversation origin으로 이동할 때 conversation-owned synchronous route event만 suppress한 뒤 transcript를 활성화합니다.
Transient default-session switch 또는 close/reopen focus cycle 없이 Deck을 열린 상태로 유지합니다.
Same-screen 및 agent conversation은 navigation 없이 전환합니다.
이미 active인 same-screen conversation을 다시 선택하면 focus만 복원하며 최신 in-memory turn 위에 sessionStorage transcript를 다시 로드하지 않습니다.
비활성 conversation을 선택하면 browser-local 읽음 확인만 기록하고 activity timestamp는 변경하지 않으므로 history 순서가 유지됩니다. Principal-scoped `내 대화`, `읽지 않음` 및 `즐겨찾기` filter는 browser-local navigation metadata만 사용하며 즐겨찾기 전환은 server activity, evidence 또는 ordering을 변경하지 않습니다. Conversation 제목은 관찰된 activity가 저장된 read timestamp보다
최신인 동안에만 굵게 표시됩니다. 선택하면 행을 이동하지 않고 이 표시를 해제하며, 더 새로운 server
activity만 ordering timestamp를 갱신합니다.
Agent 대화가 아닌 경우 첫 operator 질문이 제목이 되고 origin screen은 별도 metadata로 유지됩니다.
정규화된 질문은 history metadata에서 512자로 제한되고 browser 및 durable 복원 후에도 보존됩니다.
제목이 시각적으로 잘리면 visible text는 ellipsis를 유지합니다. 시간 영역을 포함한 selectable
conversation row 어디에서든 pointer hover하거나 keyboard focus하면 제목 길이와 관계없이 공용 console
tooltip으로 제한된 질문 전체를 표시합니다. Layout 및 닫기 icon control도 같은 localized tooltip component를
사용합니다. 연결된 backend tooltip은 mode, endpoint, route choice 및 candidate를 별도 줄로 유지하고
localized placeholder를 모두 채우며 긴 endpoint 또는 deployment token을 viewport 경계 안에서
줄바꿈합니다.
Agent card의 Ask action은 항상 unique user-scoped key를 가진 비어 있는 새 agent conversation을 엽니다. 새 summary는 선택한 agent를 즉시 보유하므로 첫 submit부터 같은 agent target을 Operator API에
전달합니다. 기존 agent conversation은 별도 history entry로 보존하며 operator가 명시적으로 선택할
때만 복원합니다.
Active cached conversation을 제거하면 current-route default(legacy `screen` key 포함) 또는 current-route thread만 선택합니다. 둘 다 없으면 unrelated-route 또는 agent transcript를 활성화하지
않고 새 current-route default를 만듭니다.
않고 새 current-route default를 만듭니다. Context-dependent cancellation, runbook, knowledge, memory, learning, ordinal-resource, ambiguity, reformatting 및 partial-source 질문에는 verified prior conversation record가 필요합니다. 서버는 principal-scoped `ConversationHistoryStore`의 최신 사용 가능한 assistant replay에서 active investigation, selected resource, prior answer 또는 source-failure receipt를 재구성합니다. Browser transcript는 이 authority를 만들 수 없으며 fresh conversation은 unavailable 상태를 유지합니다. Verified 또는 corrected prior turn 이후 `KnowledgeContextChatTools`는 unique trusted runbook 하나를 load하거나 enabled source의 authorization 및 refresh state를 보고하거나 해당 principal만 볼 수 있는 explicit-consent memory를 표시합니다. Exact assistant-turn review가 materialized memory 또는 runtime-skill proposal을 가리킬 때만 learning을 reusable로 보고합니다. Draft와 ambiguous runbook은 empty로, provider failure는 unavailable로 유지하며 ordinary chat은 memory 또는 review state를 쓰지 않습니다. 완료된 continuation은 durable assistant turn과 content-addressed source receipt를 인용합니다.
Verified fresh inventory answer는 server-owned replay metadata에 bounded `resource_result_context`를 포함할 수 있습니다. Raw resource ID를 포함하지 않고 browser context에서는 수락하지 않으며 source, snapshot, scope, query digest, freshness, truncation 및 이후 deterministic follow-up에 사용할 최대 40개의 ordered selector를 보존합니다.
Ordinal follow-up은 선택한 위치를 exact fresh inventory predicate로 다시 검증합니다. Ambiguity follow-up은 complete prior result set의 equal-name candidate만 표시합니다. Incomplete context는 unavailable 상태를 유지하며 current-screen 또는 narrator output으로 fallback할 수 없습니다.
Verified source-manifest answer는 bounded unavailable 또는 unknown entry를 `source_failure_context`로 보존합니다. Partial-source continuation은 해당 receipt의 available fact와 exact gap을 렌더링하고 reason 및 last observation이 있으면 함께 표시하며 arbitrary unverified answer를 source authority로 취급하지 않습니다. Verified 또는 corrected `query_llm_usage` answer는 domain, capability, token measure, grouping, `usage_scope` 및 numeric 1-90일 lookback이 포함된 bounded `analysis_context`를 보존합니다. 기간, grouping, table 또는 chart만 바꾸는 refinement는 이 server-owned anchor를 재사용하고 metering evidence를 다시 읽습니다. Comparison, export, missing-anchor, client-supplied-anchor 및 명시적인 다른 metric 요청은 inventory, Resource Health 또는 narrator output을 선택하지 않고 context-required hold를 반환합니다.
Full-workspace Command Deck session은 transcript만 열린 content column으로 시작합니다. 비어 있는 transcript는 상황별 suggestion을 유지하고 tool 선택이나 authority를 바꾸지 않는 localized Resilience, Change Safety 및 Cost Governance quick start를 추가합니다. Transcript
toolbar는 workspace, docked 및 floating layout에서 filter 가능한 대화 이력을 제공합니다. 좁은
layout에서는 transcript 폭을 줄이지 않고 그 위에 overlay로 엽니다. Workspace에서는 pointer 또는 keyboard separator로 대화 이력 폭을 180-360 px 범위에서 조절하고 마지막 폭을 local에 저장합니다. 좁은 layout은 separator를 숨깁니다. History header는 검색과 icon-only 새 대화를 compact한 한 줄에 배치하고 lightweight filter tab을 사용하며, control 대신 list만 scroll합니다. 현재 화면 digest는 workspace control로 유지됩니다. Deck은 열린 surface마다 composition-owned data-source manifest를 한 번 읽고 transcript 위에 Inventory, Incidents, Audit, Knowledge 및 Automation readiness link를 compact하게 표시합니다. 누락되거나 non-authoritative인 source는 `unknown`으로 유지합니다. Browser는 health를 추론하거나 raw provider detail을 노출하거나 route 존재로 manifest를 대체하지 않습니다. Loading은 stable skeleton을 사용하고 manifest failure는 conversation history를 차단하지 않으면서 Diagnostics로 연결합니다.
History는 stable cursor 순서로 durable summary를 한 번에 100건씩 load합니다. 100건에 도달하면 count를
`100+`로 표시하고 history scroll 경계에 가까워지면 다음 100건을 load합니다. Transcript body는 선택할
때만 hydrate합니다. Operator image는 전송된 turn 안에 표시됩니다. Browser cache serialization은
inline byte를 제거하고 bounded descriptor만 유지하며, durable restoration은 인증된 principal 및
conversation 범위 image route를 통해 binary를 fetch합니다. Browser 또는 durable history에서 복원된 transcript는 새 대화를 시작할 때까지
resumed-session marker를 표시합니다. Deck header는 route와 optional agent context만 담당하며 agent
대화가 아닌 질문은 반복 표시하지 않습니다. Digest는 record 수, snapshot age 및 오래된 context
새로고침을 담당하며, Composer에는 attachment, 질문 입력 및 보내기 또는 중지만 유지합니다.

공통 페이지 제목은 영역과 패널 레이블이 다를 때 `전체 현황 / Dashboard`를 포함해 둘을 함께 렌더링합니다. 패널 제목이 영역 레이블을 반복하는 영역 루트와 독립 utility는 단일 제목을 유지합니다.

공통 상단 표시줄은 아이콘 전용 FDAI 마크를 원본 색상으로 렌더링하고 옆에 `FDAI Console`
워드마크를 표시합니다. 콘솔 테마는 브랜드 자산의 채도를 낮추거나 색을 변경하지 않습니다.

Live도 `운영 / 실시간`과 같은 공통 title 계약을 따릅니다. 관찰 control은 공통 header actions
영역에 유지되고 좁은 viewport에서는 제목 아래로 줄바꿈되어 화면 고정, source, window 및 connection
status가 계속 표시됩니다.

에이전트 작업 영역은 `Fleet`, `조직` 및 `활동`의 세 가지 compact view를 사용합니다. Fleet은
실시간 runtime state와 고정 registry ownership 및 safety flag를 에이전트별 상세 disclosure에 함께
표시합니다. 조직 view는 keyboard-accessible 보고 체계와 선택된 incident evidence를 렌더링합니다.
기존 link가 계속 동작하도록 stable `/pantheon` path는 조직 compatibility route로 유지하고,
navigation에는 별도의 Pantheon directory를 두지 않습니다. 에이전트 감독은 운영 담당 체계와
governed proposal workflow를 다루는 Governance panel이며 `/agent-oversight`를 사용합니다. 이전
`/handover` 경로는 compatibility alias로 유지합니다.
다섯 view는 개요, 사람 의존성, 지식 인수인계, 승인 경로, 매핑 검토입니다. 개요와 사람 의존성은
엄격한 `GET /stewardship` 프로젝션을 사용합니다. 매핑 검토는 Owner 게이트가 적용된
`GET /iam/assignments` 프로젝션을 재사용하며 capability와 principal은 `GET /iam`에서만 가져옵니다.
지식 인수인계는 governed draft boundary를 사용합니다. 승인 경로는 자체 authoritative projection이
연결될 때까지 unavailable로 명시하며, browser는 ownership data에서 경로를 추론하지 않습니다.
Stewardship source가 없으면 개요와 사람 의존성만 차단합니다. 독립적인 지식 인수인계, 승인 경로,
매핑 검토 view는 숨기지 않습니다.
개요는 `identity_health`에서만 ID source freshness를 표시합니다. Operator API는 stale-finding
snapshot과 revision이 일치하고 만료되지 않은 last-success heartbeat에서만 `checked_at`을 제공합니다.
완료된 `clean` 또는 `warn` 확인은 이 timestamp와 병합된 `stale_oid` coverage에 맞는 finding count가
필요합니다. 불일치는 정상 또는 최신 상태로 표시하지 않고 contract error로 처리합니다.
각 agent의 `bus_factor`는 coverage evaluator와 동일하게 distinct accountable `(kind, id)` subject
unit 수를 사용합니다. Browser는 steward projection에서 이 값을 다시 계산하고 다른 headline 값은
backup coverage를 과장하지 않도록 거부합니다.

Settings에는 authoritative StateStore를 사용하는 Runtime policies route가 포함됩니다. 이 route는
secret, endpoint, tenant identifier 또는 workload identity identifier를 노출하지 않고 정제된
environment, override 및 effective value를 표시합니다. Reader access는 관찰 전용입니다. Owner update는
revision check와 원자적인 state 및 audit write를 사용합니다. Browser는 startup-bound value를 restart
required로 표시하며 저장된 값을 action promotion 또는 cloud-resource 변경으로 나타내지 않습니다.
Integrations와 Diagnostics는 동일한 projection을 사용합니다. 이 화면은 configured, ready,
incomplete, mode 및 boolean runtime status만 표시합니다. Endpoint, secret, tenant, resource,
repository credential, recipient 또는 managed identity value는 렌더링하지 않습니다.
Integrations는 sandboxed iframe으로 incident-open email도 렌더링합니다. Authenticated preview
endpoint는 Azure Communication Services Email이 사용하는 동일한 production renderer를 호출하고
합성 placeholder만 제공합니다. Preview는 runtime incident, endpoint, recipient 또는 identity value를
노출하지 않으며 send, approval 또는 execution control을 제공하지 않습니다.

Operations에는 Muninn의 durable StateSnapshot만 사용하는 감지 준비도 route가 있습니다.
이 화면은 Heimdall 판정, 6개 근거 차원, 공백, 권한 상한, 원본, 관찰 시각을 표시합니다.
브라우저는 AKS를 probe하거나 대체 판정을 만들지 않습니다. 각 target은 Architecture resource로,
promotion 관련 count는 Promotion gates로 연결됩니다. 성공한 HTTP 응답이 strict decoding을
통과하지 못하면 해당 route와 Capabilities는 loading skeleton에 머물거나 알 수 없는 autonomy mode를 enforcement로 취급하지 않고 error를 렌더링합니다.

Server-pinned drift context가 있으면 GET-only 구성 기준선 route가 identity, lifecycle, drift, Knowledge citation, topology, latency, 예약 검토, 네 safety counter를 fresh read로 표시합니다.
Binding 또는 campaign 부재는 unavailable이나 `not-configured`로 보고하며 progress를 만들지 않고 malformed data를 strict하게 거부하며 in-scope immutable version 비교와 failed-attempt count를 읽습니다. SPA는 activation, resume, schedule 생성, 승인, 완화, resource mutation을 노출하지 않고 evidence-run, resume, blueprint review, materialization은 별도 authenticated route를 사용합니다.
Production은 mounted JSON/DOCX pair, read-only Managed Identity, exact resource-group allowlist를 startup에서 검증한 뒤 panel을 노출합니다. Operator API는 executor identity를 받지 않습니다.

Processes detail route는 동일한 authoritative Process journal에서 Planning Room을 조건부로
렌더링합니다. Strict decoder는 모순된 phase count, duplicate candidate, invalid selection,
non-finite effect range를 거부합니다. 일반 Process는 `planning: null`인 기존 view를 유지합니다.
Planning Room은 read-only이며 action, approval, retry control을 노출하지 않습니다.

활동 view는 durable audit 행과 browser-session runtime frame을 하나의 bounded chronological log로
표시합니다. 각 행은 source label을 유지하므로 runtime frame을 durable audit evidence로 표시하지
않습니다. 기록된 agent 간 turn과 live agent 간 turn은 전체 bounded message text를 포함한 개별
`from -> to` 행으로 렌더링합니다. Log는 렌더링된 행을 최대 200개 유지하고 live tail을 기본으로
활성화합니다. 운영자가 위로 scroll하면 tailing을 일시 중지하며 agent 및 keyword filter를
제공합니다. 시간, 경로, 유형, 상세 및 상관관계 열을 선택할 수 있고 유형은 기본적으로 숨깁니다.
Fullscreen은 presentation만 변경합니다. 시간 열은 browser의 IANA timezone에 따른 시각만 표시하며
`Asia/Seoul`에서는 `KST`를 사용합니다. Machine-readable row에는 전체 timestamp를 유지합니다.
Waterfall view는 lifecycle, input, output, 기록된 conversation 및 hash를 확인하는 durable audit
master-detail surface로 유지합니다.
주기적인 idle 및 watching health snapshot은 변경되지 않은 durable audit page를 다시 로드하지 않고
현재 agent state와 observation time만 갱신합니다. Active work, 완료된 handler transition, Incident 및
handoff는 계속 audit evidence를 새로 고칩니다. Activity header는 반복되는 passive snapshot을 work
row로 추가하지 않고 마지막으로 관찰된 heartbeat 시각을 표시합니다.
Principal 범위 Command Deck turn과 answer planning은 conversation history에 남고 shared Agent
Activity에 게시되지 않습니다. Conversation Assurance는 답변 본문 대신 제한된 metadata와 digest를
표시하는 별도 Evidence route입니다. 세부 정보는 권한이 확인된 conversation store에서만 원문을
읽고 유일한 write는 idempotent append-only 이의 제기이며, 브라우저는 policy mutation 권한을
광고하는 payload를 거부합니다. Synthetic readiness proof는 Audit에 유지합니다.

콘솔의 모든 data-bearing card는 drill-down을 제공합니다. 전체 card surface는 해당 datum을 소유하는
가장 좁은 analytical 또는 filtered-evidence 목적지로 이동하는 keyboard-accessible native link를
사용합니다. 독립 control을 포함한 card는 대신 표시되는 primary detail link를 제공합니다. Dashboard의
운영 상태, evidence metadata, 측정되거나 unavailable인 성과, 분포 legend, attention fact, vertical
통계 및 접힌 operational count에도 같은 규칙을 적용합니다. 섹션 제목과 설명 문구만 비대화형으로
유지합니다. unavailable 값도 소유 view를 열어 누락된 source 또는 sample을 확인할 수 있게 합니다.
상세 목적지가 없는 structural group, form, editor 및 bounded tool은 card style이나 이름 대신 panel
또는 section semantics를 사용합니다.
Unavailable metric 카드는 낮은 강조도의 전체 surface 배경, elevation shadow 없음 및 작고 muted한
값 text를 사용해 측정 결과처럼 보이지 않게 합니다. 이 카드는 focus 가능한 drill-down link를
유지하고 complete-border focus 또는 hover cue를 제공하며, 시각 표현에 disabled semantics를
사용하지 않습니다.
Shared KPI card는 `not-measured`, `not-connected`, `insufficient-sample` 및 `not-applicable`
evidence state를 구분합니다. 이 상태들은 neutral copy와 style을 사용하며, 실제 request 또는 probe
실패만 error component를 사용해 시각적으로 구분합니다.
Authoritative visible content가 제자리에서 변경되는 card는 공유 `top-edge shimmer`를 사용합니다.
이 효과는 높이 2 px, 길이 1.35초의 neutral blue sweep 한 번으로 제한합니다. Primitive shared KPI
value는 자동 적용하고 복잡한 live card는 semantic update key를 제공합니다. 첫 render, 변경되지 않은
parent rerender, filter, selection 및 clock-, age-, timestamp-only 변경에는 적용하지 않습니다. 빠른
update는 하나의 sweep이 실행되는 동안 합치며 reduced-motion preference에서는 animation을
비활성화합니다. Shimmer는 표시 content가 변경됐다는 사실만 알립니다. Status, freshness, severity 및
outcome은 label이 있는 content-local cue로 계속 표시합니다.
Console card contract test는 shared KPI 목적지를 확인하고, 중첩된 whole-card link를 차단하며,
nullable KPI 값에 evidence state를 요구하고, raw data card에 link 또는 명시적 detail control을
요구하며, structural card 이름을 차단합니다.

Operating Outcomes는 선택한 metric, current value, baseline, measurement window, sample size,
confidence 및 source provenance를 bounded Command Deck view snapshot으로 발행합니다. Vertical
record는 measured breakdown을 실제로 렌더링하는 Auto-resolution view에만 포함합니다. Narrator는
렌더링된 evidence fact만 수신하며 unavailable value를 추론하거나 route의 authoritative source를
대체하지 않습니다. Snapshot headline은 visible card와 같은 metric formatter를 사용하며,
Auto-resolution value는 ratio 의미를 유지하므로 표시된 percentage claim을 operator에게 보이는 것과
같은 반올림 정밀도로 대조할 수 있습니다.
Audit 기반 projection은 append-only audit의 head sequence를 캡처하고 해당 cutoff 아래 measurement
window의 모든 row를 순회한 다음 control-loop 및 executor producer만 필터링합니다. Row를
`event_id`로 묶어 정규화된 event마다 한 번만 계산합니다. Cutoff 이후의 concurrent append는
snapshot에 들어오지 않습니다. Request는 하나의 절대 UTC 하한 timestamp를 계산하고 모든 page에서
같은 head sequence와 함께 재사용하므로 pagination은 query cost만 바꾸고 KPI membership은 바꾸지
않습니다. 명시적인 `measurement.action_outcome.v1` record가 enforce, verified, auto, non-rollback
action을 finalize하고 complete event evidence에 사람 승인, 거부, 실행 실패 또는 rollback 신호가
없을 때만 event를 auto-resolved로 계산합니다. Dispatch-only event는 pending으로 유지됩니다.
Route는 observed, finalized, pending, adverse 및 auto-resolved count를 분리해 표시합니다.
Auto-resolution rate는 canonical total observed-event denominator를 유지하므로 pending 및 기타
non-auto event가 rate에서 사라지지 않습니다. Outcome 및 audit timestamp는 timezone-aware여야
합니다. Durable audit timestamp보다 5분 넘게 미래인 outcome은 malformed evidence이므로 action을
finalize하지 않습니다.
Vertical attribution은 먼저 명시적으로 기록된 vertical을 사용하고, 그다음 강한 Resilience 또는
Cost Governance action/resource hint만 사용합니다. 추측 없이 귀속할 수 없는 evidence는
`unattributed` row에 남고 global denominator에 포함되며 표시되는 attribution coverage를 낮춥니다.
이 evidence를 Change Safety로 fallback하지 않습니다. 고정된 3-domain portfolio는 unattributed row를
제외하지만 Operating Outcomes는 Audit 목적지와 함께 계속 표시합니다.

각 Operating Outcomes route는 metric별 analysis surface를 유지합니다. Auto-resolution은 관측된
event 및 auto-resolved record 수, 영역별 비율 및 guard context를 보여줍니다. Human touchpoints,
MTTR, change lead time 및 cost per resolved event는 각각 고유한 analysis 및 breakdown 섹션을
유지합니다. Read projection이 touchpoint type, latency percentile, delivery stage 또는 cost
composition을 제공하지 않으면 관련 없는 vertical table을 재사용하거나 browser에서 값을 파생하지
않고 unavailable로 렌더링합니다. Cost view는 표시 금액이 표준 단가를 기준으로 하며 할인, 약정,
credit, 세금, 환율 및 provider billing adjustment가 반영된 실제 청구 금액과 다를 수 있다는 점도
안내합니다.

Control Assurance는 audit KPI, autonomy measurement 및 promotion registry projection에서 운영
banner, evidence metadata, posture metric, promotion guard, terminal control-path distribution 및
required-attention total을 표시합니다. Guard row는 current, baseline 및 threshold value를 비교하고
filtered evidence로 연결됩니다. Distribution segment와 attention row는 가장 좁은 audit, approval
또는 promotion 목적지로 연결됩니다. Synthetic guard는 operational pass 또는 failure를 만들지 않으며,
projection이 누락되면 prototype value나 추론한 0을 공급하지 않고 unavailable로 렌더링합니다.

Vertical Outcomes는 세 개의 selected-detail route 대신 하나의 portfolio overview를 사용합니다. 각
영역 카드는 같은 visual grammar를 사용하지만 서로 다른 primary outcome을 표시하고 owning evidence
surface로 직접 연결됩니다. Resilience는 Incidents, Change Safety는 promotion evidence, Cost
Governance는 Audit로 연결됩니다. Events, auto-resolution, 미해결 위험 및 절감액은 공유 comparison
table에서만 영역별로 반복합니다. Change failure rate나 recovery drill success 같은 domain metric은
read model이 귀속 evidence를 제공할 때까지 unavailable로 유지하며 global confidence와 trend value를
vertical-specific claim으로 바꾸지 않습니다. 빈 영역에는 resolution rate를 추론하지 않으며
synthetic evidence는 operational health label이나 filtered runtime-evidence claim을 만들지 않습니다.

Trust Routing은 T0(결정론적 규칙), T1(경량 유사도 재사용), T2(근거 기반 LLM 추론)를 하나의 측정된
tier map으로 표시합니다. Routing 비율, event 수 및 목표 범위는 autonomy 및 audit KPI projection에서
가져오며 각 tier는 고유한 analysis route로 연결됩니다. T2 control flow는 실행이 통과했다고 주장하는
상태가 아니라 필수 architecture check를 설명합니다. Leading indicator는 보고된 current 및 baseline
value만 비교합니다. 누락된 값은 unavailable로 유지하고 simulated value는 operational pass 또는
failure를 만들지 않습니다.

LLM Cost는 측정된 호출, token, chat 비율 및 최근 호출 근거를 먼저 표시합니다. 입력 및 출력 구성,
선택 기간 trend, model 및 conversation 귀속, invocation record는 metering projection에서만 파생합니다. Price attribution이
연결되지 않은 경우 route는 이 경계를 안내하고 token volume에서 지출, budget, fixed infrastructure cost, 호출당 가격 또는 invoice 금액을 추정하지 않습니다. Bounded visible invocation ledger는 고정 allowlist를 quoted CSV로 export하며 formula-leading cell은 neutralize합니다. Conversation, workload, mode, day 및 month 상세 rollup은 secondary disclosure에서 계속
제공하므로 primary view의 탐색성을 유지하면서 근거를 숨기지 않습니다. Headline KPI label과 value는
균형 잡힌 4열, 2열 또는 1열 grid에서 왼쪽 정렬을 유지하고, token 구성의 count와 share는 비교하기 쉽도록
공통 오른쪽 숫자 열을 사용합니다. 하나의 global UTC selector는 rolling 24시간, 7일, 30일 및 사용자 지정
1일에서 90일 window를 제공합니다. Operator API는 timezone이 있는 RFC 3339 `from` 및 `to` 값을
검증하고 모든 total, attribution, bucket 및 invocation record를 계산하기 전에 동일한 시작 포함 및 종료
제외 cutoff를 적용합니다. URL은 정확한 cutoff를 보존합니다. 24시간 view는 hourly bucket을 사용하고 더
긴 window는 daily bucket을 사용합니다. 사용자 지정 display 종료일은 포함되며 exclusive API 경계로
다음 UTC 자정에 mapping됩니다.

## 로딩 표현

모든 route, panel 및 bounded content 영역은 첫 loading frame부터 skeleton을 렌더링합니다. 공통 skeleton은 spinner-only 및 text-only 대기를 대체하며, route는 최종 layout dimension을 유지하는 고유 shape를 제공할 수 있습니다.
Dashboard는 posture block 다음에 metric, distribution, attention 및 vertical placeholder를 사용하므로 loading 중에도 report가 축소되지 않습니다. 하나의 screen-reader status가 loading을 알리고 decorative block은 숨깁니다. Reduced motion에서는 shimmer가 멈추지만 정적 skeleton은 계속 표시됩니다.
공통 fallback은 heading, summary-card 및 body-panel placeholder를 사용합니다. 소유 route shape는 더 정확한 최종 layout을 유지할 때만 이 fallback을 대체합니다.

HTML document가 console stylesheet를 direct dependency로 소유하므로 authentication, route, component 및 JavaScript hot update 중에도 mount된 SPA의 layout과 theme가 사라지지 않습니다. Vite는 같은 document link를 fingerprinted production CSS asset으로 변환합니다.
Development에서는 기존 hot-update guard도 CSS 변경을 transform하기 전에 Vite의 race-safe file reader로 처리하여 editor의 임시 empty snapshot이 전체 stylesheet를 대체하지 못하게 합니다.

## Localization 경계

SPA는 operator preference에서 표시 locale을 결정합니다. 재사용 문자열은 기본 영어 source
catalog 또는 완전한 route-local 영어/한국어 쌍에서 가져오며 영어 fallback은 필수입니다. Static
key coverage, catalog parity, route fallback test 및 console suite가 번역되지 않은 표시 text의
재유입을 막습니다. Grounding trace label과 manifest/reference count detail도 reconstructed evidence
metadata에 영어를 직접 넣지 않고 같은 catalog를 사용합니다.

Localization은 presentation label만 바꿉니다. Machine value, workflow id, serialized record,
provider payload 및 validation result는 변경하지 않습니다.

## 관찰된 대화 트래젝터리

각 Command Deck 질문은 관측된 작업이 뒷받침하는 가장 작은 presentation을 선택합니다. Activity,
handoff 또는 background task가 없는 turn도 접힌 run record를 유지합니다. 성공한 단일 terminal read는
compact investigation row와 접힌 run record를 함께 사용합니다. 여러 activity, milestone,
retry, failure, handoff, command 또는 file change가 있으면 전체 timeline을 유지하지만 run record는
기본적으로 접어 둡니다. Durable
background task는 detached task summary를 사용합니다. 복원된 compact turn은 durable detail에서
observed row를 재구성하고 live turn은 인과 순서로 이미 표시한 row를 유지합니다. 완료된 모든 answer는
trajectory summary를 확인할 수 있게 유지합니다. Bounded original operator prompt는 run record가
접혀 있는 동안 숨기고 operator가 펼치면 표시합니다. Internal AnswerPlan intent 및
detail label은 answer 위에 표시하지 않습니다. Run record decision context에는 유지하며 answer는
operator-facing content와 verified evidence로 바로 시작합니다. Model-assisted format selection은 validation된 presentation shape만 변경합니다. Verified chart는 evidence reference가 포함된 bounded `chart_artifact` v1을 반환하며 transport는 answer text보다 먼저 이를 검증하고 렌더링합니다. Canonical fenced chart data는 compatibility fallback으로 유지합니다.

상태 개요는 완료, 수정 후 완료, 일부 저하, 실패, 검증 미완료, 진행 중 및 관측되지 않음을 구분하며
record 존재를 성공으로 표시하지 않습니다. Result chip은 내부 event total 대신 관측된 query와
command count, evidence completion, reference 및 verification을 표시합니다. Serialized `unverified`
status는 replay를 위해 그대로 유지합니다. Primary Console label은 bounded reason code에 따라 Context
필요, Source 사용 불가, Query 검증 실패 또는 근거 없는 claim으로 표시하고 technical detail에는
canonical status와 raw reason code를 유지합니다. Run-record summary는
두 result indicator를 10 px 이하의 고정된 점으로 표시하고 source button 가장자리에서 2 px만 겹칩니다.
Source button은 자체 source tooltip을 유지합니다. 점은 별도 pointer 및 keyboard trigger이며 floating
tooltip 또는 별도 container 없이 compact한 query, command 및 evidence pill로 오른쪽에 직접 펼쳐집니다.
전체 summary는 trigger의 accessible name에 유지합니다. Absolute positioning을 사용하므로 별도 행을
만들거나 reply action geometry를 바꾸지 않고 인접 action을 가리지 않습니다. Source button이 없으면
답변 품질 검토에 같은 직접 확장 점을 연결합니다. 펼친 run-record summary는 complete bounded operator prompt를 유지하고
좁은 layout에서는 줄바꿈합니다. Disclosure를 변경하면 transcript만 scroll하고 composer는
Deck 경계에 계속 표시됩니다. 펼친 view는 6단계 rail, 펼칠 수 있는 observed-event timeline 및 provenance signal을 먼저 표시하고,
timing window, decision context, phase record 및 coverage gap은 하나의 접힌 execution-details disclosure에
유지합니다. Preparing-answer surface는 observed activity와 evidence branch가 terminal state에 도달할
때까지 operator turn과 observed work 사이에 유지됩니다. 더 일찍 도착한 answer token은 browser paint
queue에 유지합니다. Activity shell을 settled로 바꾸는 render에서 answer를 함께 추가하므로 running
investigation skeleton과 answer content가 동시에 나타나지 않습니다. 이후 observed work는 execution
mock의 progress note, session, connected step 및 dark command detail 계층을 따릅니다. 단독 activity의 starting
note는 수신한 해당 activity에서만 가져옵니다. Milestone을 수신한 경우에는 milestone이 note가 되므로
browser가 progress를 중복하거나 만들어내지 않습니다. 현재 step만 자동으로 펼치고 완료된 step shell은
유지하며 raw output과 timestamp는 접습니다. Raw current-screen record는 접힌 source disclosure에 유지합니다.
한 operator 질문의 progress, observed activity 및 terminal answer는 인과 record를 각각 유지하지만 하나의
visible agent header와 연결된 flow 아래에 표시합니다. Terminal answer는 같은 agent 또는 두 번째 source
badge를 반복하지 않습니다. Numbered progress와 status glyph는 shared vertical rail을 이동하지 않고
고정된 circle marker 안에서 optical center에 맞춥니다. Numbered glyph는 더 어두운 body-text navy가
아니라 progress label과 같은 저채도 blue accent를 사용합니다. Transcript는
browser scroll anchoring을 끄고 하단 공간을 추가하며 work가 streaming 중일 때만 latest edge를
따라갑니다. Terminal completion에서는 첫 observed work group을 transcript edge 아래에 고정해 final
answer layout이 완료되는 동안 execution outcome과 answer 시작을 함께 표시합니다. Timing이 없는 plan과 collaboration metadata는 decision context에 두고, 관측된 input, evidence
및 tool, model call, verification 및 delivery만 timeline에 표시합니다.
모든 waterfall lane은 label이 있는 하나의 start-to-completion scale과 quarter-window tick을 사용합니다.
내부 causal rail은 row를 연결하고 dashed segment는 설명되지 않은 빈 공간 대신 recorded interval
사이의 측정된 시간을 표시합니다. Complete timestamp가 있는 execution activity는 연결된 generic
evidence branch를 대체하며 observed label, tool, authority 및 detail을 유지합니다. Phase envelope은
저채도 blue, evidence work는 green, model work는 plum, point-in-time turn record는 neutral gray circle로
표시합니다. Input marker는 해당 turn에서 관측된 가장 이른 timestamp에 고정하고 terminal answer는
마지막 recorded timing completion보다 앞에 배치하지 않습니다. 따라서 browser와 server의 clock
skew가 evidence를 input 앞에 두거나 generation과 verification을 delivery 뒤에 두지 못합니다. Lane
baseline과 tick은 completion progress bar와 구분됩니다.
Answer text는 15 px을 사용하고 main disclosure 높이는 44 px이며, 200% text resize와 320 CSS pixel에서 content loss 없이 reflow합니다.
Trajectory heading은 13 px, event label은 12 px, compact trajectory metadata는 11 px을 사용합니다.
Terminal verified answer에 server가 정확한 영어 또는 한국어 형식으로 렌더링한 recorded-agent-activity block이 있으면 해당 row를 하나의 compact vertical timeline으로 표시합니다. 각 row는 agent, canonical event token, 정확한 ISO timestamp 및 locale에 맞춘 읽기 쉬운 시간을 유지합니다. Malformed 또는 알 수 없는 prose는 observed activity로 승격하지 않고 일반 answer content로 유지합니다.
게시된 screen snapshot은 5분 후 visibly stale 상태가 되고
명시적인 page refresh를 제공합니다. Bare clock은 current evidence를 의미하지 않습니다. Markdown
table은 점진적으로 렌더링합니다. 완성된 header와 separator가 첫 body row보다 먼저 table shell을 만들고,
완성된 각 row는 table을 교체하지 않고 누적됩니다. 완성되지 않은 header, separator 및 row syntax는 raw
Markdown으로 표시하지 않습니다. 모든 bounded answer row는 transcript flow에 유지하며 내부 vertical
scroll region이나 row expansion control을 사용하지 않습니다. Foreground의 terminal-only deterministic
answer도 같은 visual paint queue를 사용하므로 canonical table row가 0건에서 전체 건수까지 단조롭게
증가합니다. Background tab은 동기적으로 완료합니다. Narrow screen에서는 transcript 폭을 늘리지 않고
cell을 줄바꿈합니다.

상세 화면은 bounded recorded metadata를 표시하지만 answer body를 반복하지 않습니다. 펼친 각 timeline
event는 evidence summary와 reference, plan intent와 format, answer source와 model-call count,
verification authority와 check 또는 model request와 response metadata처럼 source record에 있는
상세를 표시합니다. 적용 가능한 각 lane에는 recorded-payload block이 표시됩니다. 여기에는 operator
input, IQL 또는 command와 observed output, AnswerPlan, redacted model request와 response,
verification receipt 및 terminal delivery receipt가 포함됩니다. 해당 payload type이 없는 lane도 빈
panel 대신 status, start, completion 및 사용 가능한 fact를 표시합니다. Answer lane은 delivery
metadata를 기록하며 answer body를 반복하지 않습니다.
Inventory execution은 canonical turn query를 `IQL` activity로 표시합니다. 이어지는 별도 activity는
exact bounded Azure CLI 또는 ARG receipt를 같은 terminal icon으로 표시합니다. 인증된 subscription id,
generic argv, 측정된 command duration, count 및 allowlist된 preview row 최대 10개는 표시하지만 pagination token, credential,
raw resource id 및 provider error는 redaction합니다. IQL source와 result는 각각 토글되며 row는 snapshot refresh를 설명하지만 command 재실행을 주장하지 않습니다. Browser는 IQL 또는 source name에서 command를 파생하지 않습니다. Provider message, action argument, command 및 output의 유효한 object 또는 array JSON은 indentation, syntax highlighting 및
copy를 제공하며 malformed 또는 plain text는 변경하지 않습니다. Terminal-only visual reveal은 최대 30개 chunk로 제한하고 answer lane은 paint 완료가 아닌 server 완료 시각을 사용하므로 presentation pacing을 execution gap으로 표시하지 않습니다. Terminal replay payload는 ID별 최종
branch, activity, milestone 및 redacted execution detail을 총 64 KiB 이하로 보존하고 history output을
항목당 32 KiB에서 truncate하며 truncation 및 omission count를 표시합니다. 따라서 durable history와
live turn이 같은 strict parser 및 trajectory view를 사용합니다. Unavailable 또는
timed-out evidence는 시도이지 완료된 evidence가 아니며 unverified 작업에는 완료 styling을 적용하지
않습니다. 누락된 activity는 observation coverage disclosure에 두며 작업 부재를 증명하지 않습니다.
Exact-answer durable replay에는 같은 bounded browser parser를 사용합니다. Server는 provider의 terminal content-policy 결정이 확인될 때까지 model token을 buffering합니다. Block은 partial token 또는 assistant answer를 노출하지 않고 content-free receipt만 기록하며 SSE와 JSON `422`에 같은 deterministic fallback을 사용하고, log에는 stage와 aggregate count만 남깁니다. 명시적인 provider refusal, truncated completion, malformed stream frame 또는 검증된 terminal signal 없이 끝난 stream은 assistant answer가 되지 않습니다.

Terminal timing은 최대 8개의 allowlisted semantic-plan, evidence, generation, quality-review 및
verification phase를 포함합니다. 하나의 UTC anchor와 monotonic elapsed time으로 관측된 status, start,
completion 및 duration을 만듭니다. Interrupt는 timing을 저장하지 않고 strict parser는 불일치를 거부합니다.

Model provider tracing은 기본값이 꺼진 browser-local Settings opt-in입니다. 활성화하면 request-local
collector가 turn planning, rerun, answer generation 및 quality review를 포함하여 해당 질문의 실제 model
call을 최대 8개 기록합니다. Waterfall은 provider-call timing을 사용합니다. 기록된 call이 0건이면
deterministic path에서 provider lane이 필요하지 않았음을 Waterfall 안에 표시합니다. Trace가 캡처되지
않은 turn은 명시적인 unavailable state를 표시합니다. 캡처 설정이 꺼져 있어도 panel은 Settings opt-in
안내와 함께 표시하지만 저장된 trace data는 계속 숨깁니다. 각 disclosure는 role 순서의
기록된 message array와 request SHA를 보존하면서 연속 system layer를 하나의 `SYSTEM` heading으로 묶습니다.
JSON body는 pretty-print하고 bounded request 및 response block에는 theme에 맞는 scrollbar를 적용합니다. Disclosure는 assistant content, token usage, exact-content SHA-256 및 redaction count도 표시합니다. Credential, tenant 또는 resource identifier, URL, email, IP address, inline image,
hidden reasoning, header 및 provider 내부 정보는 저장하지 않습니다. 설정을 끄면 캡처를 중지하고
저장된 trace data를 숨기며 provider call을 반복하지 않고 idempotent replay response에서 trace를 제거합니다.

이 principal-scoped view는 authorization-first offline review artifact인
[관리형 trajectory dataset](governed-trajectory-datasets-ko.md)과 구분됩니다. Hidden reasoning, raw
unredacted prompt, credential, unrestricted payload 및 해당 turn에 기록되지 않은 data는 표시하지 않습니다.

## Durable request replay

완료된 request는 principal, conversation, idempotency key 및 request content가 모두 일치할 때만
replay됩니다. 저장된 terminal assistant payload를 반환하며 evidence retrieval, narration 또는
post-turn review를 반복하지 않습니다. 같은 key에 다른 content나 conversation이 들어오면
conflict입니다. JSON, SSE 및 cross-transport retry는 같은 terminal payload를 사용합니다.
Content-policy receipt에도 같은 identity check를 적용합니다. 일치하는 retry는 preference resolution,
document retrieval, history compaction, planning 또는 provider 작업 전에 policy result를 replay합니다.
같은 request key에서 prompt 또는 conversation이 바뀌면 conflict입니다.

Optional incident conversation binding은 bounded incident id, correlation id 및 allowlisted
Pantheon agent를 전달합니다. Browser와 server는 같은 bound를 강제합니다. 잘못 저장된 binding은
conversation을 삭제하지 않고 폐기합니다. Agent activity는 bounded historical audit evidence를
설명하며 activity 부재가 agent의 현재 task 부재를 증명하지 않습니다.
새 ephemeral conversation은 첫 operator turn이 server record를 만들기 전에 durable history를
조회하지 않으므로, 정상적인 first-open 상태를 missing-history error로 보고하지 않습니다.

## 검증된 근거

Read-source provenance, ontology browse, cross-screen operational 및 inventory answer는 typed
evidence에서 결정론적으로 렌더링됩니다. Ontology browse는 target과 browse verb를 요구하고,
allowlisted identity field와 256자 이하 prompt value만 전달하며, 중복되거나 malformed인 count와
selection을 unavailable로 표시합니다. Ontology projection과 결정론적 browse answer는 일반 prompt
assembly와 분리된 자체 prompt module에 위치합니다.
Reader-gated `/ontology/graph` projection은 operating-model status, source revision, aggregate
object 및 link count만 포함합니다. Deployment instance property는 반환하지 않습니다.
일반 delegated answer는 Bragi를 narrator로 유지하면서 verified specialist를 response owner로
표시합니다. Dedicated target session은 명시적 handoff가 narration을 Bragi로 돌려보낼 때까지 해당
specialist의 검증된 voice를 사용합니다.
Agent-targeted Web turn은 첫 provisional token부터 선택한 specialist를 표시하고 terminal delegation이
owner를 확인하거나 handoff를 표시할 때까지 label을 안정적으로 유지합니다.
명시적 handoff로 turn이 Bragi에 돌아오면 Web은 reply header와 answer-plan row에
`specialist -> Bragi`로 소유권 흐름을 표시합니다. Handoff에 specialist answer가 없으면 결정론적
verification은 근거를 사용할 수 없다는 응답을 반환하고, 관련 없는 current-screen fact로 narrator
문장을 검증하지 않습니다.
선택한 agent와 server-owned operational evidence가 모두 resolve되면 coordinator는 둘 다 유지하며,
incident summary, absence claim 및 cause는 계속 결정론적 verification이 소유합니다.
Bragi가 T0/T1 owner route를 한 번 완료한 뒤, 일반 answer path는 그 owner에서 점수가 유일하게
가장 높은 read tool 하나를 선택합니다. 완료된 tool result가 primary specialist answer가 되고,
범위 한정 fact는 기존 agent-evidence manifest로 들어갑니다. 동점이거나 일치 항목이 없으면 owner의
일반 response를 유지합니다. 선택된 read가 abstain, timeout, sensitivity hold 또는 partial completion
상태이면 generic 또는 contributor fallback 없이 명시적으로 handoff합니다. Planning과 dispatch는
깊이 1단계를 유지하며 하나의 bounded gather budget을 공유합니다. 이 일반 path는 lexical이며 agent
route에 embedding 호출을 추가하지 않습니다.
어떤 에이전트도 소유하지 않는 질문은 tool-answer path에 들어가지 않습니다.
Charter version, hash 및 tool id는 hidden provenance로 유지합니다. Exact policy match일 때 model은
Bragi global safety prompt 뒤에서 server-owned charter를 받으며, charter는 role과 voice를 제한하지만
evidence 또는 authority가 되지 않습니다. Runtime grounding은 제공된
evidence ref 또는 normalized agent fact의 content-addressed hash를 사용하며 static agent spec을 사용하지 않습니다.
Agent narration 자체는 evidence source가 아닙니다. Atomic claim은 별도로 귀속된 contributor
fact를 포함한 agent fact leaf를 runtime 제공 ref에 rooted된 고유 JSON pointer에 연결합니다.

Incident title도 서버 소유 evidence입니다. Read projection은 기록된 title, summary 또는 rule
field를 우선 사용한 뒤 길이가 제한된 signal 및 resource correlation key를 사용합니다. 빈 값,
`None`, `null` correlation marker는 결측으로 처리하며 browser는 incident subject를 만들지 않습니다.

선택한 Incident 상세 화면은 lifecycle summary와 불러온 audit history에서만 파생한 운영자용 현재
상황을 가장 먼저 표시합니다. Raw `pending`, `unknown`, `shadow` 값을 하나의 상태처럼 보여주지 않고
lifecycle state, response decision, change authority 및 operator attention을 분리합니다. 활성 incident에
notification-delivery escalation이 있으면 이를 우선 표시하고 필요한 후속 작업을 설명합니다. 기록이
있으면 audit 및 technical activity를 사용할 수 있습니다. Root-cause analysis와 dossier는 `rca.*`
record가 생긴 뒤에만 link가 되며, 그 전에는 근거가 있는 가설이 기록되지 않았다고 표시합니다. RCA
route도 hypothesis가 없으면 generic audit fallback response를 숨겨 `incident.members`를 response plan
또는 cause로 표시하지 않습니다. Trace route는 raw ordered table보다 먼저 notification escalation,
response-decision evidence, RCA evidence 및 named pipeline stage를 분리한 interpretation summary를
표시합니다. Generic correlated activity는 cause claim이 아니라 technical history로 유지합니다.

Operational evidence는 `matched`, `summary`, `ambiguous`, `none`, `unavailable` 중 하나입니다.
Collection summary 요청에서 `summary`는 incident 하나를 선택하도록 요구하지 않고 bounded matching
set을 즉시 렌더링합니다. Model prose는 선택된 incident, search scope, 지원되는 cause, collection
membership 또는 absence claim을 바꿀 수 없습니다.
`availability=unavailable`인 source는 `reachable=true`를 보고하지 않으며 구성되지 않았거나 probe하지
않은 source는 `reachable=null`을 사용합니다. 명시적인 latest-incident summary는 collection을 반환하지 않고 server read model에서 가장 최근 incident 하나를 선택합니다. Root cause, timeline, hypothesis, similar incident, impact, next action, consumed evidence, uncertainty 및 deep investigation 질문에는 incident 하나가 필요합니다. Bound incident가 없으면 generic analysis wording은 operator가 선택할 bounded candidate를 반환하며 current-screen, repository, agent 또는 public-web evidence를 빌리지 않습니다.
`ambiguous` terminal answer는 최대 5개의 server-validated incident candidate를 포함한 versioned
artifact도 전달합니다. Web client는 candidate별로 title, severity, status, last-updated time 및
incident id가 표시된 button을 렌더링하므로 중복 title도 구분할 수 있습니다. Button을 선택하면
exact incident-bound conversation을 열고 localized read-only investigation question을 즉시
제출합니다. 명시적인 click이 operator 요청이며 managed resource를 변경하지 않습니다. 누락되거나
malformed, oversized 또는 unverified인 candidate artifact는 button을 렌더링하지 않으며 binding을
만들 수 없습니다.
`latest`, `recent`, `최신` 같은 generic recency 단어만으로는 incident authority를 만들지 않습니다.
Operational lookup에는 incident, issue, outage, failure, problem 또는 cause 의미가 명시적으로 함께
있어야 합니다. 따라서 public software version 또는 release 질문은 deterministic "no matching incident"
답변 대신 bounded public-web path 대상으로 유지됩니다.
Current-screen data scope는 inventory, incident, agent 및 web enrichment보다 우선합니다. Topology, end-to-end reachability, inbound network policy, peering 및 failure impact-scope 질문에는 exact source/target resource name 또는 server-validated selected network resource 하나가 필요합니다. Context-free reference는 inventory provider 실행 전에 deterministic clarification을 반환합니다. Current-screen link, resource-group membership 또는 incident evidence는 connectivity나 impact scope의 근거가 되지 않습니다. Trace
correlation은 질문에 incident, failure, problem 또는 cause 의미가 명시된 경우에만 incident selection
hint로 사용하며 일반 stage 및 actor field는 screen fact로 유지합니다.
지원되는 current-screen value와 명시적 absence answer는 model 호출 없이 Bragi T0가 렌더링합니다.
명시적으로 빈 facts 또는 records projection은 screen coverage 근거이며 model memory fallback
권한이 아닙니다. 이 answer도 terminal이 되기 전에 atomic-claim verifier를 통과합니다.
Current-time 질문은 injected timezone-aware server clock과 principal의 IANA timezone preference를
사용합니다. Terminal answer는 exact timestamp와 timezone으로 결정론적으로 렌더링합니다. Preference가
없으면 명시적으로 표시한 UTC로 fallback하며 narrator와 browser clock은 time authority가 아닙니다.

Forecast Learning route는 server-owned PostgreSQL projection만 읽습니다. Closure completeness는
due episode를 denominator로 사용하고 publication health는 미래 scheduled work를 due debt, failed
attempt 및 dead letter와 구분합니다. Cohort가 없으면 0이 아니라 unavailable로 표시하며 browser는
관련 없는 count에서 model miss, pipeline miss 또는 retention status를 도출하지 않습니다.

Trace route는 error render 중에도 `correlation_id`, `load_status` 및 값이 있을 때 actionable
`load_error`를 게시합니다. Server는 이 correlation을 selection hint로만 사용하고 operational
evidence를 반환하기 전에 권한이 적용된 read model에서 다시 확인합니다.
Trace는 연관된 감사 행을 순서대로 유지하고 파이프라인 단계가 없는 활동을 `stage: null`로
표현하며 마지막으로 이름이 기록된 단계에서 `terminal_stage`를 도출합니다.
Citation이 있는 grounded RCA가 없으면 deterministic verification은 durable `incident.open` record의
bounded detection fact를 먼저 렌더링합니다. 여기에는 signal, target resource 및 연관된 member-event
count가 포함됩니다. 이 fact는 관찰된 상태를 확인하지만 원인을 증명하지 않습니다. Workload failure
reason은 별도 section에 유지합니다. `notification.*` failure는 notification delivery 아래에만 표시하며
workload failure 또는 root-cause evidence가 되지 않습니다. Notification이 주제인 incident는 delivery
failure를 먼저 표시할 수 있습니다. 모든 path는 기록된 failure를 완전한 root-cause 결론이 아니라
observation으로 표시합니다.

각 manifest route에는 owner가 하나만 있습니다. SPA는 query와 fragment를 제거하고 path-segment
경계에서 exact path 또는 descendant를 match한 뒤 가장 긴 owner를 선택합니다. 비슷한 prefix는
ownership을 상속하지 않습니다. Owned route가 manifest에 하나라도 없으면 panel은 `unknown`이고,
명시적으로 source-independent인 panel만 source status를 생략합니다.

Production Operator API는 `GET /stewardship`을 등록하기 전에 operational ownership map을 load하고
validate합니다. Console은 이 source를 read-only로 projection합니다. Handover form은 structured
person 또는 group assignment를 별도 ingestion boundary에 제출할 수 있지만 map을 적용하거나 Git
credential을 보유할 수 없습니다. Draft PR 생성과 signed merge processing은 ingestion/GitOps
boundary에 유지되며 반환된 draft에는 persisted idempotent PR receipt가 포함됩니다.
Browser는 receipt URL이 embedded credential 없는 absolute HTTPS URL일 때만 link로 렌더링하며,
그 외에는 PR reference를 클릭할 수 없는 text로 표시합니다.
Content upload는 same-origin ingestion proxy target에만 API bearer token을 유지합니다.
Cross-origin direct-upload target에는 content header를 보내지만 Operator API credential은 전달하지
않습니다.

## 점진적 병렬 대화

Command Deck과 pull-direction ChatOps는 하나의 channel-neutral 점진적 대화 모델을 사용합니다.
결정론적 scope 및 authority routing 이후 coordinator는 조건을 충족한 독립 read branch를 동시에
시작할 수 있습니다. Branch는 immutable evidence operation이며 nested narrator session이나 direct
agent call이 아닙니다. Active conversational identity가 presentation translator로 유지됩니다. 책임
tool 또는 agent가 branch
evidence를 소유하고, 결정론적 verification이 확인된 모든 answer segment를 소유합니다.

각 branch event는 다음 bounded field를 전달합니다.

| Field | Contract |
|-------|----------|
| `branch_id` | Request 안에서 안정적이며 request id와 canonical branch kind에서 파생됩니다. |
| `branch_kind` | `tool`, `operational`, `agent`, `public_web`과 같은 allowlisted read source 하나입니다. |
| `parent_branch_id` | Optional dependency reference입니다. 독립 top-level branch는 `null`을 사용합니다. |
| `status` | Monotonic `pending`, `running` 이후 `completed`, `unavailable`, `failed`, `timed_out`, `cancelled` 중 하나입니다. |
| `summary` | Bounded 및 redacted operator-facing progress 또는 terminal summary이며 evidence authority가 아닙니다. |
| `started_at`, `completed_at`, `duration_ms` | Optional observed timing입니다. Completed time은 started time보다 앞설 수 없습니다. |
| `evidence_refs` | Terminal branch state에서만 내보내는 bounded canonical reference입니다. |

Server는 request `seq` 순서로 branch lifecycle frame을 내보냅니다. Branch completion 순서는 달라질 수
있지만 join은 항상 immutable result를 canonical branch-kind 순서로 병합합니다. 신뢰할 수 없는 input을
`ValueError`로 수락하지 않는 branch는 `unavailable`로 기록하고 traceback 없이 구조화된 info를
내보냅니다. 예상하지 못한 exception은 `failed`와 traceback 포함 warning을 유지합니다. 성공한 sibling
evidence는 계속 사용할 수 있습니다. Authoritative fact conflict는 양쪽 evidence set을 보존하고 answer를
unverified로 표시하며 Bragi가 한쪽을 선택하지 못하게 합니다. Concurrent branch는 shared context를 변경하지 않습니다.

구현된 first wave는 조건을 충족한 tool, operational, 명시적으로 선택된 agent, read-investigation agent
및 deterministic public-web read에 bounded task group 하나를 사용합니다. 이전 authority result에 따라
eligibility가 달라지는 agent 또는 web 작업은 bounded follow-up wave에서 실행됩니다. 따라서 기존
authority order가 억제할 agent 또는 external web provider를 speculative하게 호출하지 않으면서 독립
I/O를 겹쳐 실행합니다. JSON 및 SSE chat은 동일한 merge helper를 사용합니다.

Draft `token` frame은 provisional narration으로 유지됩니다. `confirmed` frame에는 결정론적 verifier를
이미 통과한 evidence에서 렌더링한 complete segment만 포함됩니다. Monotonic segment index, answer
revision, evidence reference와 이후 verified result가 앞선 segment를 수정할 때의 replacement range를
포함합니다. Confirmed segment는 running branch를 인용하지 않습니다. Terminal `done` frame은 계속
canonical이며 conversation history에 저장되는 유일한 answer입니다. Client는 terminal frame 없이
중단된 stream을 partial로 표시하며 draft text를 confirmed content로 승격하지 않습니다.

Web reducer는 rendering 전에 branch kind, monotonic status, timing, evidence-reference 및 text bound를
검증합니다. 각 branch를 번호가 있는 investigation stage로 표시합니다. 완료된 operational, agent,
tool 및 public-web stage는 각각 펼쳐 status, timing, summary 및 해당 branch가 소유한 bounded evidence
reference를 확인할 수 있습니다. Observed command와 output detail은 기본적으로 접어 둡니다.
Queued token paint와 correction revision이 모두 drain된 후에만 confirmed segment를 적용합니다.
Token 및 confirmed frame은 현재 canonical revision과 일치해야 합니다. Superseded 또는 공지되지 않은
revision의 frame은 sequence position만 소비하고 text append, canonical content 교체, confirmation
callback 호출 또는 confirmation metric 증가를 수행할 수 없습니다. Confirmed revision도 strictly
advance하므로 현재 revision의 duplicate는 stale replay입니다. Frame 사이에
`seq` 값이 누락되면 이후 `done`이 도착해도 turn을 partial로 표시하므로 incomplete stream이 terminal
verification을 상속하지 않습니다.

Web, Teams 및 Slack은 동일한 ordered event reduction을 사용합니다.

- **Web**은 in-progress answer 옆에 compact branch summary를 유지합니다. 상세 정보와 canonical
	redacted command 또는 output evidence는 operator가 펼칠 때까지 접어 둡니다.
- **Teams 및 Slack**은 originating thread에 response 하나를 게시하고 monotonic edit를 적용합니다.
	Final edit에는 canonical verified answer와 bounded folded branch summary가 포함됩니다.
- **Capability fallback**은 vendor가 edit을 지원하지 않을 때 complete terminal response 하나를
	전송합니다. Precomputed text chunk를 streaming이라고 부르지 않으며 answer authority를 바꾸지 않습니다.

Stream close, operator interruption 또는 request deadline은 모든 child branch를 cancel하고 await합니다.
Optional progress observer가 실패해도 cancellation이 authoritative 상태를 유지합니다. Observer error는
cancelled branch를 failed stream으로 바꾸지 않고 log됩니다.
Per-branch deadline, queue capacity, branch count, event size, activity count, text byte 및 vendor payload는
bounded 상태를 유지합니다. Command 및 output evidence에는 `redacted=true`가 필요합니다. Branch
summary는 credential, tenant identifier, customer resource identifier 또는 raw untrusted web content를
노출하지 않습니다. Durable replay는 canonical terminal answer와 revision state를 저장하며 completed
read를 다시 실행하거나 provider message를 중복 전송하지 않습니다.

Progress metric은 aggregate count와 latency만 유지합니다. Time to first progress 및 confirmed
content, branch kind/outcome/duration, correction, truncation, terminal completion, replay, queue
saturation, sequence gap, suppressed branch retry, ambiguous channel update를 기록합니다. Prompt,
answer, branch id, channel id, principal id 또는 resource identifier는 보관하지 않습니다. Failed 및
timed-out read branch는 turn 안에서 retry하지 않으며 operator가 fresh scope로 새 turn을 시작할 수
있습니다. Server는 client frame 누락을 관찰할 수 없으므로 browser가 sequence gap과 partial terminal을
local에서 계산합니다.
Progress, branch outcome 및 truncation metric은 bounded stream queue가 event를 accept한 후에만
기록합니다. Cancellation-only lifecycle frame은 first evidence progress로 계산하지 않습니다.
Idempotent terminal replay는 observed time-to-first-confirmed latency와 replay count에 포함되지만
evidence retrieval, narration 및 post-turn review는 계속 건너뜁니다.

## Stream recovery 및 authentication

인증된 live, agent 및 provisioning SSE reader는 keepalive comment를 포함해 45초 동안 byte가 없으면
cancel하고 bounded reconnect를 사용합니다. Provisioning은 event 전달 실패 시 reader도 cancel합니다.
Agent stream의 `401`은 전체 화면 login recovery를 기다리고, `403`은 새 App Role을 page reload 없이
반영할 수 있도록 reconnect합니다.

Command Deck 조사 activity에는 선택적인 observed execution evidence가 포함될 수 있습니다. Server는
emit 전에 credential과 민감한 identifier를 제거하고 `redacted=true`를 설정하며, browser는 이 확인이
없는 input evidence를 폐기합니다. `input_kind=command`는 기록된 process invocation이 필요하며 exit
code를 포함할 수 있습니다. `input_kind=query`는 canonical typed server query를 전달하고 reconstructed
provider command를 만들지 않으며 exit code를 포함할 수 없습니다. 허용된 activity는 일치하는 `TOOL`
또는 `QUERY` badge, tool label, authority 및 완료 상태를 표시합니다. Command output, query result 및 timestamp는 기본적으로 접힌 상태를 유지합니다. 유효한 object 또는 array JSON은 theme에 맞는 scrollbar가 적용된 bounded code surface에서 pretty-print됩니다.
Inventory result는 일치한 resource, count, coverage 및 snapshot provenance를 포함하는 verifier-accepted detailed projection을 유지합니다. Input은 16 KiB, result preview는 64 KiB로 제한됩니다. 크기를 초과하는 collection tail은 omission count와 함께 제거해 output을 유효한 JSON으로 유지합니다. Activity 및 retrieval label은 512자, detail 및 milestone text는 16 KiB로 제한되며
completed/total progress가 모순되면 거부합니다. Browser는
표시된 command 또는 query를 복사할 수 있지만 실행하거나 다시 시도할 수 없습니다. 이 evidence는 권한 있는
runtime이 수행한 work를 read-only로 관찰한 것이며, console이 executor identity 또는 임시 권한을
보유한다는 증거가 아닙니다.

Command Deck의 web research turn은 작업 진행 중 실제 상태를 나타내는 `status` frame을 stream합니다.
Server는 semantic search intent가 narrator model을 호출할 때만 `web_search_classifying`을 emit하고,
public-web provider 호출 직전에만 `web_search_searching`을 emit하며, retrieval 후에는 정제된 source
수와 preview를 포함한 `web_search_grounded`를 emit합니다. 답변 준비 trace는 이 단계를 즉시
렌더링합니다. 실행하지 않은 단계는 해당 turn의 진행 상태로 표시하지 않습니다.

완료된 각 model-backed turn은 선택된 model과 해당 turn의 기록된 metadata로 확인되는 단계인 evidence
retrieval, model reasoning, specialist consultation, evidence binding 및 verification을 LLM escalation
disclosure에 계속 표시합니다. 새 citation이 없는 follow-up turn도 model reasoning 단계를 표시하고
별도 source가 첨부되지 않았음을 명시합니다. 이전 citation을 새로 조회한 것처럼 재사용하지 않습니다.
Evidence value와 path는 잘리지 않고 줄바꿈되며, source detail은 별도로 펼쳐 확인할 수 있습니다. 완료된
verification stage는 검사가 수행되었음을 나타내며, unverified result는 성공 check 대신 attention mark를
사용합니다.

완료된 deterministic turn은 LLM label 없이 동일한 processing disclosure를 사용합니다. Disclosure는
결정론적 응답기를 식별하고 사용할 수 없는 backend 또는 content-policy block 같은 기록된 fallback
reason을 유지하므로 model outage가 공개되지 않은 model response처럼 보이지 않습니다.

Browser는 기록된 model identifier와 optional latency 또는 token metric이 bounded source-descriptor
contract와 일치할 때만 LLM disclosure를 표시합니다. Empty, oversized, control-character,
duplicate-metric 및 free-form metric value는 LLM escalation claim을 만들지 않습니다. Raw source
badge는 width가 제한되므로 malformed metadata가 reply header를 밀어내지 않습니다. Browser가 token
usage를 표시하려면 token total과 prompt 및 completion component가 각각 finite nonnegative value여야
합니다.

Verification metadata는 check counter가 nonnegative integer이고 completed check가 total check보다
크지 않을 때만 허용됩니다. Atomic claim span은 순서가 맞는 nonnegative integer이고 manifest schema
version 1을 명시하며 claim, failed-claim 및 used-evidence reference에는 duplicate 또는 dangling
identifier가 없어야 합니다. `unverified`가 아닌 terminal status는 선언된 check를 모두 완료하며,
partial evidence는 표시하되 terminal verification은 `unverified`로 유지합니다. 잘못된 조합은
unverified malformed artifact가 됩니다. Failed-claim identifier는 unsupported 또는 ambiguous claim과
정확히 일치하며 manifest는 verification envelope과 동일한 authority를 사용합니다.
Browser는 producer cap인 claim 64개, evidence entry 512개 및 추가 document reference 8개를 동일하게
적용합니다. Artifact identifier는 1 KiB, rendered value는 16 KiB, anchor 또는 alias list는 64개로
제한됩니다. Live reply와 session replay는 동일한 parser를 사용하므로 reload 후 HTTP boundary가
거부할 metadata를 복원하거나 다르게 해석하지 않습니다.

Session replay는 4 MiB JSON envelope 안에 최신 turn을 최대 40개 유지합니다. Turn 하나에는 text
256 KiB, bounded citation 512개, bounded follow-up 8개 및 bounded activity record 64개까지 포함할 수
있습니다. Serialization이 envelope을 초과하면 browser는 가장 오래된 turn부터 제거합니다. Oversized
또는 내부 정합성이 없는 optional collection은 renderer로 복원하지 않습니다. Answer-plan section 및
override label은 64자와 128자, code validation detail은 4 KiB, milestone agent identity는 64자로
제한합니다.

Web composer는 선택, drop 및 clipboard paste raster를 동일한 bounded attachment tray와 validation path로 전달합니다. Stage 전에 browser는 upscaling 없이 longest edge를 2048 px 안에 맞추고 image당 4 MiB 아래로 re-encode합니다. Clipboard text와 HTML은 textarea의 native paste 동작을 유지하며 attachment가 되지 않습니다.
Turn이 검증된 inline image attachment를 carry하면 streaming route는 narrator가 작성하기 전에 read-only `vision_analyzing`을, 답변 전에 `vision_grounded`를 emit하며, 각 frame은 image source preview(name, media type, size)를 포함하되 base64 payload는 절대 포함하지 않습니다.
해당 turn은 vision 지원 narrator로 escalate되고, 답변 준비 trace는 이 단계를 web-search grounding과 동일하게 렌더링합니다.

Interactive Live route는 tab이 hidden 상태일 때 SSE reader를 pause합니다. Operator가 활성화한
browser notification consumer만 bounded exception으로 background에서 authenticated live reader를
유지하고, 기존 capped backoff로 authentication failure를 retry하며, notification permission 또는
principal-scoped opt-in이 제거되면 즉시 중지합니다. Replay가 아닌 frame의 사람 승인, 거부, 실패
결과만 emit합니다. Shared browser ledger는 여러 tab에서 같은 event tag를 5분 동안 억제하고 system
notification delivery를 분당 5건으로 제한하지만 audit 또는 Incident evidence는 제거하지 않습니다.

Agent stream은 local 및 deployed profile에서 같은 shared stage transport를 통해 실제 health에서
파생한 `agent.runtime-state` heartbeat를 수신합니다. Heartbeat는 live agent의 현재 runtime 관찰을
증명하지만 work로 분류되지 않습니다. 누락되거나 malformed인 health frame은 선언된 subscriber
binding을 observed state로 승격하지 않습니다. 각 Operator API replica는 instance-scoped consumer
group을 사용하므로 연결된 모든 console이 완전한 heartbeat set을 수신합니다. Deployed Pantheon도
handler `started`, `completed`, `failed` transition을 이 transport로 게시합니다. Give up 또는 halt된
consumer는 sibling을 유지한 채 health-derived heartbeat에서 빠지고 terminal agent/topic은 runtime
health에 남습니다. Saga 또는 Vidar failure는 sticky shadow를 강제합니다. 이 transition은 runtime
activity이며 durable audit evidence가 아닙니다.

Command Deck은 complete 또는 pending SSE frame이 256 KiB를 넘으면 `data:` line 누적이나 JSON parse
전에 거부하고 deterministic interrupted-stream fallback을 사용합니다. Correlation-filtered action
progress는 terminal audit frame을 완료로 처리하고 120초 deadline을 timeout으로 보고하며, 그 밖의
authentication 또는 transport failure는 전달합니다. Investigation row는 pending에서 running을 거쳐
terminal state 하나로 진행합니다. Stale backward frame과 terminal replacement는 무시하므로 completed,
failed 또는 unavailable operation이 spinner로 돌아가지 않습니다.

Console data를 열기 전에 bootstrap은 인증된 `GET /iam/self`로 principal을 확인합니다. Transport
failure는 data를 닫힌 상태로 유지하고 access-check retry 및 sign-in을 제공합니다. Operator API가
unreachable일 때 redirect loop가 생기므로 자동 redirect는 시작하지 않습니다.

## Architecture map resilience

Architecture route는 map 오른쪽 위에 떠 있는 compact panel에 scope selection만 배치합니다. Inventory
count, 설명문 및 layer filter는 표시하지 않습니다. Truncated graph는 짧은 status badge 하나로
알립니다. Resource-color legend는 floating 또는 bottom panel이 아니라 subscription boundary 옆 world
floor에 직접 그립니다. Camera fit은 범례가 들어갈 floor 공간을 예약합니다. 고정된 legend box, title
또는 color swatch 없이 resource type name을 해당 floor에 직접 표시합니다. Type name은 pan과 함께
이동하고 읽을 수 있는 범위 안에서 map zoom에 비례해 조정됩니다.
Resource glyph는 Microsoft Cloud Adoption Framework의
[Azure resource abbreviations](https://learn.microsoft.com/azure/cloud-adoption-framework/ready/azure-best-practices/resource-abbreviations)를
사용합니다. 알려진 모든 canonical type은 명시적인 lowercase abbreviation을 가집니다. 일대일 CAF
항목이 없는 abstract type은 자동 initialism 대신 문서화된 stable extension을 사용합니다.
Relationship legend는 compact canvas control로 유지합니다. 기본 isometric map은 Reflections와
Connections가 활성화된 상태로 시작합니다. Containment는 흐린 dashed link로,
attachment 및 dependency는 각각의 directional style로 표시하고 resource shape을 렌더링합니다.
Top 및 front view는 optional입니다. 단순 projection은 선택된 단일 scope를 포함한 모든
resource-group panel의 크기를 관찰된 child 수에 따라 정하고 균형 잡힌 world에 panel을 배치합니다.
Focused service 및 resource-group view는 full subscription frame이 아니라 repacked content에
맞춰 표시합니다. Resource node는 표준 Event Grid topic
block보다 작게 렌더링되지 않습니다. Inventory에 맞춰 world와 canvas가 커지며 authored nested
layout은 supplied geometry를 유지합니다. Map은 workspace 전체 너비를 사용하고 inspection detail은
아래에 배치합니다. 좁은 viewport에서는 box를 읽을 수 없게 줄이는 대신 node 크기를 유지하고 map
panning을 사용합니다. Selection은 inventory를 reload하지 않고 canonical deep link를 갱신하며
technical identifier보다 directional relationship을 먼저 표시합니다. Selection 중에는 모든 공통
resource coordinate를 유지하면서 auxiliary neighbor만 표시합니다. 관련 없는 resource는 흐리게
처리하지 않으며 선택된 outline과 inspection detail만 사용해 selection을 나타냅니다. Virtual
machine을 포함한 모든 resource selection은 현재 camera scale과 position을 유지합니다. Zoom, fit,
pan 및 camera-view control은 운영자가 명시적으로 조작할 때만 변경됩니다.

Factual count와 inspection index는 계속 complete authoritative inventory를 사용합니다. Isometric
overview는 network interface와 managed disk를 표시하고 diagnostic, certificate 및 provider helper
resource를 접는 presentation-only projection을 적용합니다. 표시된 각 owner는 접힌 neighbor
수에 해당하는 `+N` badge를 표시합니다. Resource를 선택하면 새 inventory를 요청하거나 만들어 내지
않고 direct auxiliary child와 semantic neighbor를 표시합니다. Overview는 표시된 resource만 packing하고
child를 layer 및 type 순서로 정렬하며 접힌 owner 옆에 최대 두 개의 satellite slot을 예약합니다. 큰
resource-group panel을 wide row에 먼저 배치하므로 숨겨진 auxiliary가 빈 grid hole을 만들거나 world를
부풀리지 않습니다. Virtual network와 subnet은 낮은 floor
lane으로 렌더링하므로 compute, data 및 gateway node를 network plane 위에서 읽을 수 있습니다. Floor
lane은 reflection을 렌더링하지 않습니다. Azure inventory는 VNet payload 안에서 관찰된 subnet만
`network.subnet` record로 승격하고 관찰된 VNet-to-subnet containment edge를 생성합니다. Console은
등록된 `attached_to` link가 bounded resource-to-interface-to-subnet chain 안에서 하나의 subnet에만
도달하거나 disk가 bounded disk-to-workload-to-interface-to-subnet chain으로 도달할 때 resource를 해당
subnet에 배치합니다. Membership이 없거나 모호하면 resource-group의 neutral
floor에 유지하며 name과 provider identifier를 topology evidence로 사용하지 않습니다.

Isometric renderer는 VNet을 outer floor로, subnet을 visible member 수에 따라 크기가 정해지는 inset
floor plane으로 그립니다. Evidence-derived membership rail과 direct `attached_to` link는 floor에
유지하고 `depends_on` arrow는 resource top 위에 유지합니다. Plane name은 floating label card 없이
world axis를 따릅니다. Plane을 선택하면 동일한 resource inspector를 사용하며 가장 작은 containing
plane이 pointer target으로 유지됩니다. Focused service 또는 resource-group view는 공간이 허용될 때
3개의 network floor를 한 행에 배치하는 wide packing target을 사용합니다. Complete inventory view보다
작은 desktop legend reserve와 canvas height를 사용합니다. 좁은 viewport에서는 동일한 node 크기를
유지하고 canvas를 520 px로 제한하며 더 넓어진 floor를 panning으로 탐색합니다.

Subnet 안의 visible path participant는 관찰된 `attached_to` connected component별로 묶은 다음 network
edge에서 storage 순서로 배치합니다. Public IP 및 network security resource, network interface,
compute 및 service resource, disk 및 data resource 순서입니다. 여러 workload path는 type 또는 name으로
서로 섞이지 않고 연속으로 유지됩니다. 이는 layout 순서이며 추론한 traffic direction이 아닙니다.
각 component는 독립적인 depth-oriented lane을 사용합니다. Public IP는 camera에 가장 가깝고 security,
interface, workload 및 storage stage가 순서대로 뒤로 물러납니다. Renderer는 겹치는 intra-subnet edge를
하나의 shared floor spine과 짧은 stage branch로 대체하며 cross-plane attachment만 direct route를
유지합니다. Workload는 supporting network resource보다 크게 렌더링됩니다. Path resource는 기본적으로
glyph를 사용하고 workload는 primary label을 유지하며 어떤 resource든 선택하면 full name과 type을
복원합니다. 읽을 수 있는 label threshold보다 낮은 dense overview scale에서는 선택하지 않은 node name과
subnet name이 glyph, VNet name, region name 및 floor legend에 자리를 양보하며 focused view는 일반
workload 및 subnet label 정책을 복원합니다. Perspective는 bounded depth
범위에서 projected point를 조정해 가까운 resource를 먼 resource보다 크게 표시하고 picking과
containment도 동일한 projection을 사용합니다. Zoom은 512x scale까지 상세 탐색을 지원하고 pointer를
중심으로 확대하며, content-driven world는 고정 canvas-height ceiling 없이 확장됩니다. Fit은 complete
frame을 복원하는 명시적 control로 유지됩니다. 기본 isometric camera는 path lane을 좌우로 읽고 depth가
뒤로 물러나도록 낮은 oblique angle을 사용합니다. Fit은 compact world 위쪽에 visual depth를 남기기
위해 화면 중심보다 약간 아래에 배치합니다. Content-driven canvas가 projected world보다 크게 높은
경우에는 world를 fold 아래에 중앙 정렬하지 않고 첫 visible frame에 upper bound를 고정합니다.
왼쪽 button drag는 projected world를 pan합니다. 가운데 button drag는 normalized continuous yaw로
world center 주위에서 camera를 좌우로 orbit하며 세로 이동은 pitch를 변경하지 않습니다. 오른쪽 button은
browser behavior를 유지합니다. Orbit input은 동일한 animation-frame coalescing을 사용하고 label만
지연하며 floor, path 및 reflection은 계속 표시합니다.

Label은 collision을 피하고 긴 이름을 맞추며 각 resource name과 읽기 쉬운 resource type을 함께
표시합니다. Block의 compact acronym은 보조 cue이며 resource를 식별하는 유일한 방법이 아닙니다.
Label은 zoom에 따라 13 px에서 20 px까지 커지고 선택된 label은 22 px까지 커질 수 있습니다. Zoom
step은 reciprocal이고 색상은 console theme을 따르며, keyboard-accessible resource 및 relationship
index는 filtered canvas와 동등합니다. Pointer target은 containment boundary를 포함해 최소 44 px입니다.
선택된 label은 마지막 canvas overlay이므로 block glyph, relationship 또는 인접 label이 가릴 수
없습니다. Truncated snapshot은 partial-inventory notice를 명시합니다.
Canvas는 containment를 subdued dashed center-to-center edge로 렌더링합니다. Semantic relationship은
연결된 block top보다 높은 directional node-to-node arrow를 사용하며 resource-group region을 operational
endpoint로 연결하지 않습니다. Drag input은 animation frame마다 한 번만 draw하고 pointer가 이동하는
동안에도 reflection을 계속 표시하며 label만 생략합니다. Pointer release는 label을 복원합니다.
Local projection은 선택된 endpoint id와 resource type이 일치하는 registered relationship type만
표시합니다. Malformed 또는 over-limit vendor relationship은 drop하고 snapshot을 truncated로 표시하며,
신뢰할 수 없는 edge를 렌더링하지 않고 마지막 complete resource graph를 유지합니다.

Subscription-scoped cached snapshot은 즉시 렌더링됩니다. Expired 또는 change-invalidated snapshot은
background refresh 동안 stale로 표시됩니다. Browser는 Operator API가 완료된 refresh를 원자적으로
promote할 때까지만 polling하고 server freshness verdict를 높이지 않으며, stale graph를 유지한 채
transient failure를 bounded 2-30초 backoff로 재시도합니다.

## 검증

- Catalog parity 및 route-local fallback test가 localization을 검증합니다.
- Replay test가 JSON, SSE 및 cross-transport idempotency를 검증합니다.
- Provenance test가 unavailable, unknown, malformed 및 route-owner 상태를 검증합니다.
- Stream test가 inactivity, authentication 분류, frame limit 및 action timeout을 검증합니다.
- Architecture test가 layout, selection, accessibility, cache freshness 및 bounded polling을 검증합니다.
