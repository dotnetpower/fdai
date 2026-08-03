---
title: 콘솔 근거 및 복원력
translation_of: console-evidence-and-resilience.md
translation_source_sha: 81449ed87a2cd9958528bed51272e5596362ee3f
translation_revised: 2026-08-03
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
비활성 conversation을 선택하면 browser-local 읽음 확인만 기록하고 activity timestamp는 변경하지
않으므로 history 순서가 유지됩니다. Conversation 제목은 관찰된 activity가 저장된 read timestamp보다
최신인 동안에만 굵게 표시됩니다. 선택하면 행을 이동하지 않고 이 표시를 해제하며, 더 새로운 server
activity만 ordering timestamp를 갱신합니다.
Conversation 제목이 시각적으로 잘리면 pointer hover에서 공용 console tooltip으로 전체 label을 표시합니다. 제목이 영역 안에 모두 표시되면 중복 tooltip을 표시하지 않습니다.
Agent card의 Ask action은 항상 unique user-scoped key를 가진 비어 있는 새 agent conversation을 엽니다. 새 summary는 선택한 agent를 즉시 보유하므로 첫 submit부터 같은 agent target을 Operator API에
전달합니다. 기존 agent conversation은 별도 history entry로 보존하며 operator가 명시적으로 선택할
때만 복원합니다.
Active cached conversation을 제거하면 current-route default(legacy `screen` key 포함) 또는 current-route thread만 선택합니다. 둘 다 없으면 unrelated-route 또는 agent transcript를 활성화하지
않고 새 current-route default를 만듭니다.

Full-workspace Command Deck session은 transcript만 열린 content column으로 시작합니다. Operator는 transcript toolbar에서 filter 가능한 대화 이력 또는 현재 화면 digest를 열 수 있습니다. Browser 또는
durable history에서 복원된 transcript는 새 대화를 시작할 때까지 resumed-session marker를 표시합니다.
Digest가 닫혀 있어도 composer는 compact route, 근거 record 수 및 snapshot-age line을 유지합니다.

공통 페이지 제목은 영역과 패널 레이블이 다를 때 `전체 현황 / Dashboard`를 포함해 둘을 함께 렌더링합니다. 패널 제목이 영역 레이블을 반복하는 영역 루트와 독립 utility는 단일 제목을 유지합니다.

공통 상단 표시줄은 Cloud Aperture 마크를 원본의 브랜드 파란색으로 렌더링합니다. 콘솔 테마는
브랜드 마크의 채도를 낮추거나 색을 변경하지 않습니다.

Live도 `운영 / 실시간`과 같은 공통 title 계약을 따릅니다. 관찰 control은 공통 header actions
영역에 유지되고 좁은 viewport에서는 제목 아래로 줄바꿈되어 화면 고정, source, window 및 connection
status가 계속 표시됩니다.

에이전트 작업 영역은 `Fleet`, `조직` 및 `활동`의 세 가지 compact view를 사용합니다. Fleet은
실시간 runtime state와 고정 registry ownership 및 safety flag를 에이전트별 상세 disclosure에 함께
표시합니다. 조직 view는 keyboard-accessible 보고 체계와 선택된 incident evidence를 렌더링합니다.
기존 link가 계속 동작하도록 stable `/pantheon` path는 조직 compatibility route로 유지하고,
navigation에는 별도의 Pantheon directory를 두지 않습니다. 담당자 인수인계는 자체 governed proposal
workflow가 있으므로 별도 Explorer panel로 유지합니다.

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
통과하지 못하면 loading skeleton에 머물지 않고 error를 렌더링합니다.

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
7일 trend, model 귀속 및 invocation record는 metering projection에서만 파생합니다. Price attribution이
연결되지 않은 경우 route는 이 경계를 안내하고 token volume에서 지출, budget, 호출당 가격 또는 invoice
금액을 추정하지 않습니다. Workload, mode, day 및 month 상세 rollup은 secondary disclosure에서 계속
제공하므로 primary view의 탐색성을 유지하면서 근거를 숨기지 않습니다. Headline KPI label과 value는
균형 잡힌 4열, 2열 또는 1열 grid에서 왼쪽 정렬을 유지하고, token 구성의 count와 share는 비교하기 쉽도록
공통 오른쪽 숫자 열을 사용합니다.

## 로딩 표현

모든 route, panel 및 bounded content 영역은 첫 loading frame부터 skeleton을 렌더링합니다. 공통
skeleton은 spinner-only 및 text-only 대기를 대체하며, route는 최종 layout dimension을 유지하는
고유 shape를 제공할 수 있습니다. Dashboard는 posture block 다음에 metric, distribution,
attention 및 vertical placeholder를 사용하므로 loading 중에도 report가 축소되지 않습니다. 하나의
screen-reader status가 loading을 알리고 decorative block은 숨깁니다. Reduced motion에서는 shimmer가
멈추지만 정적 skeleton은 계속 표시됩니다.
공통 fallback은 heading, summary-card 및 body-panel placeholder를 사용합니다. 소유 route shape는 더
정확한 최종 layout을 유지할 때만 이 fallback을 대체합니다.

Vite development server는 CSS hot update를 transform하기 전에 Vite의 race-safe file reader로
처리합니다. Editor가 큰 CSS 파일을 truncate한 후 다시 쓰는 동안 임시 empty snapshot이 전체
stylesheet를 대체하는 문제를 방지합니다. 이 guard는 development에서만 적용되며 production CSS
bundling은 변경하지 않습니다.

## Localization 경계

SPA는 operator preference에서 표시 locale을 결정합니다. 재사용 문자열은 기본 영어 source
catalog 또는 완전한 route-local 영어/한국어 쌍에서 가져오며 영어 fallback은 필수입니다. Static
key coverage, catalog parity, route fallback test 및 console suite가 번역되지 않은 표시 text의
재유입을 막습니다. Grounding trace label과 manifest/reference count detail도 reconstructed evidence
metadata에 영어를 직접 넣지 않고 같은 catalog를 사용합니다.

Localization은 presentation label만 바꿉니다. Machine value, workflow id, serialized record,
provider payload 및 validation result는 변경하지 않습니다.

## 관찰된 대화 트래젝터리

완료된 각 Command Deck 질문은 접힌 observed trajectory를 표시합니다. 상태 개요는 완료, 수정 후 완료,
일부 저하, 실패, 검증 미완료, 진행 중 및 관측되지 않음을 구분하며 record 존재를 성공으로 표시하지
않습니다. 기록된 event, evidence, reference 및 verification count는 compact result chip으로 표시합니다.
펼친 view는 6단계 rail, 펼칠 수 있는 observed-event timeline 및 provenance signal을 먼저 표시하고,
timing window, decision context, phase record 및 coverage gap은 하나의 접힌 execution-details disclosure에
유지합니다. Preparing-answer surface는 final answer streaming이 시작될 때까지 operator turn과 observed
work 사이에 유지됩니다. Transcript는 browser scroll anchoring을 끄고 하단 공간을 추가하며 latest edge만
고정해 streaming layout 변경이 현재 읽기 위치를 움직이지 않게 합니다. Timing이 없는 plan과 collaboration metadata는 decision context에 두고, 관측된 input, evidence
및 tool, model call, verification 및 delivery만 timeline에 표시합니다. Answer text는 14 px 이상이고,
main disclosure 높이는 44 px이며, 200% text resize와 320 CSS pixel에서 content loss 없이 reflow합니다.
Transcript text는 15 px, trajectory heading은 13 px, event label은 12 px, control은 13 px을 사용하며
compact trajectory metadata는 11 px 아래로 내려가지 않습니다. 게시된 screen snapshot은 5분 후 visibly stale 상태가 되고
명시적인 page refresh를 제공합니다. Bare clock은 current evidence를 의미하지 않습니다. Markdown
table은 bounded answer row를 transcript flow에 모두 렌더링하며 내부 vertical scroll region이나 row
expansion control을 사용하지 않습니다. Narrow screen에서는 transcript 폭을 늘리지 않고 cell을 줄바꿈합니다.

상세 화면은 bounded recorded metadata를 표시하지만 answer body를 반복하지 않습니다. Provider message,
action argument, command 및 output의 유효한 object 또는 array JSON은 indentation, syntax highlighting 및
copy를 제공하며 malformed 또는 plain text는 변경하지 않습니다. Terminal replay payload는 ID별 최종
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
call을 최대 8개 기록합니다. Waterfall은 provider-call timing을 사용하며, 각 disclosure는 role 순서의
redacted message copy, assistant content, token usage, exact-content SHA-256 및 redaction count를
표시합니다. Credential, tenant 또는 resource identifier, URL, email, IP address, inline image,
hidden reasoning, header 및 provider 내부 정보는 저장하지 않습니다. 설정을 끄면 캡처를 중지하고
저장된 trace를 숨기며 provider call을 반복하지 않고 idempotent replay response에서 trace를 제거합니다.

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
않은 source는 `reachable=null`을 사용합니다.
`latest`, `recent`, `최신` 같은 generic recency 단어만으로는 incident authority를 만들지 않습니다.
Operational lookup에는 incident, issue, outage, failure, problem 또는 cause 의미가 명시적으로 함께
있어야 합니다. 따라서 public software version 또는 release 질문은 deterministic "no matching incident"
답변 대신 bounded public-web path 대상으로 유지됩니다.
Current-screen data scope는 inventory, incident, agent 및 web enrichment보다 우선합니다. Trace
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
Citation이 있는 grounded RCA가 없으면 deterministic verification은 해당 audit evidence에 기록된
failure 또는 escalation reason을 인용할 수 있지만, 완전한 root-cause 결론이 아니라 observation으로
표시합니다.

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
검증합니다. Compact branch summary를 표시하고 observed execution detail은 기본적으로 접어 둡니다.
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
또는 `QUERY` badge, tool label, authority 및 완료 상태를 표시합니다. Command output 또는 query result와
timestamp는 기본적으로 접힌 상태를 유지합니다. Intermediate progress detail과 milestone은 parsed
resource name 대신 opaque resource placeholder를 사용합니다. Input은 16 KiB, result preview는 64 KiB로 제한되며 잘림 여부를
명시합니다. Activity 및 retrieval label은 512자, detail 및 milestone text는 16 KiB로 제한되며
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

Turn이 검증된 inline image attachment를 carry하면 streaming route는 narrator가 작성하기 전에
read-only `vision_analyzing`을, 답변 전에 `vision_grounded`를 emit하며, 각 frame은 image source
preview(name, media type, size)를 포함하되 base64 payload는 절대 포함하지 않습니다. 해당 turn은
vision 지원 narrator로 escalate되고, 답변 준비 trace는 이 단계를 web-search grounding과 동일하게
렌더링합니다.

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
