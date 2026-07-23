---
title: 콘솔 근거 및 복원력
translation_of: console-evidence-and-resilience.md
translation_source_sha: 28c4f6a03a7f63b0561674759dee555af40cf150
translation_revised: 2026-07-23
---

# 콘솔 근거 및 복원력

이 문서는 operator console의 evidence provenance, localization, stream recovery, durable replay
및 Architecture map resilience 계약을 소유합니다. 대화형 tool 및 RBAC 계약은
[operator-console-ko.md](operator-console-ko.md)에 유지됩니다.

## 탐색 컨텍스트

Activity Bar 영역을 선택하면 Explorer가 열리고 운영자의 로컬 순서 및 표시 설정에 따라 첫 번째
visible 패널로 이동합니다. Command Deck이 닫혀 있거나 floating 상태여도 이 탐색은 동작하며,
full-workspace Deck은 route가 변경되기 전에 닫힙니다.

공통 페이지 제목은 영역과 패널 레이블이 다를 때 `전체 현황 / Dashboard`를 포함해 둘을 함께
렌더링합니다. 패널 제목이 영역 레이블을 반복하는 영역 루트와 독립 utility는 단일 제목을 유지합니다.

Live도 `운영 / 실시간`과 같은 공통 title 계약을 따릅니다. 관찰 control은 공통 header actions
영역에 유지되고 좁은 viewport에서는 제목 아래로 줄바꿈되어 화면 고정, source, window 및 connection
status가 계속 표시됩니다.

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
제공하므로 primary view의 탐색성을 유지하면서 근거를 숨기지 않습니다.

## 로딩 표현

모든 route, panel 및 bounded content 영역은 첫 loading frame부터 skeleton을 렌더링합니다. 공통
skeleton은 spinner-only 및 text-only 대기를 대체하며, route는 최종 layout dimension을 유지하는
고유 shape를 제공할 수 있습니다. Dashboard는 posture block 다음에 metric, distribution,
attention 및 vertical placeholder를 사용하므로 loading 중에도 report가 축소되지 않습니다. 하나의
screen-reader status가 loading을 알리고 decorative block은 숨깁니다. Reduced motion에서는 shimmer가
멈추지만 정적 skeleton은 계속 표시됩니다.
공통 fallback은 heading, summary-card 및 body-panel placeholder를 사용합니다. 소유 route shape는 더
정확한 최종 layout을 유지할 때만 이 fallback을 대체합니다.

## Localization 경계

SPA는 operator preference에서 표시 locale을 결정합니다. 재사용 문자열은 기본 영어 source
catalog 또는 완전한 route-local 영어/한국어 쌍에서 가져오며 영어 fallback은 필수입니다. Static
key coverage, catalog parity, route fallback test 및 console suite가 번역되지 않은 표시 text의
재유입을 막습니다.

Localization은 presentation label만 바꿉니다. Machine value, workflow id, serialized record,
provider payload 및 validation result는 변경하지 않습니다.

## Durable request replay

완료된 request는 principal, conversation, idempotency key 및 request content가 모두 일치할 때만
replay됩니다. 저장된 terminal assistant payload를 반환하며 evidence retrieval, narration 또는
post-turn review를 반복하지 않습니다. 같은 key에 다른 content나 conversation이 들어오면
conflict입니다. JSON, SSE 및 cross-transport retry는 같은 terminal payload를 사용합니다.

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
selection을 unavailable로 표시합니다.

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

Production read API는 `GET /stewardship`을 등록하기 전에 operational ownership map을 load하고
validate합니다. Console은 이 source를 read-only로 projection합니다. Handover form은 structured
person 또는 group assignment를 별도 ingestion boundary에 제출할 수 있지만 map을 적용하거나 Git
credential을 보유할 수 없습니다. Draft PR 생성과 signed merge processing은 ingestion/GitOps
boundary에 유지되며 반환된 draft에는 persisted idempotent PR receipt가 포함됩니다.
Browser는 receipt URL이 embedded credential 없는 absolute HTTPS URL일 때만 link로 렌더링하며,
그 외에는 PR reference를 클릭할 수 없는 text로 표시합니다.
Content upload는 same-origin ingestion proxy target에만 API bearer token을 유지합니다.
Cross-origin direct-upload target에는 content header를 보내지만 read API credential은 전달하지
않습니다.

## Stream recovery 및 authentication

인증된 live, agent 및 provisioning SSE reader는 keepalive comment를 포함해 45초 동안 byte가 없으면
cancel하고 bounded reconnect를 사용합니다. Provisioning은 event 전달 실패 시 reader도 cancel합니다.
Agent stream의 `401`은 전체 화면 login recovery를 기다리고, `403`은 새 App Role을 page reload 없이
반영할 수 있도록 reconnect합니다.

Command Deck의 web research turn은 작업 진행 중 실제 상태를 나타내는 `status` frame을 stream합니다.
Server는 semantic search intent가 narrator model을 호출할 때만 `web_search_classifying`을 emit하고,
public-web provider 호출 직전에만 `web_search_searching`을 emit하며, retrieval 후에는 정제된 source
수와 preview를 포함한 `web_search_grounded`를 emit합니다. 답변 준비 trace는 이 단계를 즉시
렌더링합니다. 실행하지 않은 단계는 해당 turn의 진행 상태로 표시하지 않습니다.

Interactive Live route는 tab이 hidden 상태일 때 SSE reader를 pause합니다. Operator가 활성화한
browser notification consumer만 bounded exception으로 background에서 authenticated live reader를
유지하고, 기존 capped backoff로 authentication failure를 retry하며, notification permission 또는
principal-scoped opt-in이 제거되면 즉시 중지합니다. Replay가 아닌 frame의 사람 승인, 거부, 실패
결과만 emit합니다. Shared browser ledger는 여러 tab에서 같은 event tag를 5분 동안 억제하고 system
notification delivery를 분당 5건으로 제한하지만 audit 또는 Incident evidence는 제거하지 않습니다.

Agent stream은 local 및 deployed profile에서 같은 shared stage transport를 통해 실제 health에서
파생한 `agent.runtime-state` heartbeat를 수신합니다. Heartbeat는 live agent의 현재 runtime 관찰을
증명하지만 work로 분류되지 않습니다. 누락되거나 malformed인 health frame은 선언된 subscriber
binding을 observed state로 승격하지 않습니다. 각 read API replica는 instance-scoped consumer
group을 사용하므로 연결된 모든 console이 완전한 heartbeat set을 수신합니다.

Command Deck은 complete 또는 pending SSE frame이 256 KiB를 넘으면 `data:` line 누적이나 JSON parse
전에 거부하고 deterministic interrupted-stream fallback을 사용합니다. Correlation-filtered action
progress는 terminal audit frame을 완료로 처리하고 120초 deadline을 timeout으로 보고하며, 그 밖의
authentication 또는 transport failure는 전달합니다.

Console data를 열기 전에 bootstrap은 인증된 `GET /iam/self`로 principal을 확인합니다. Transport
failure는 data를 닫힌 상태로 유지하고 access-check retry 및 sign-in을 제공합니다. Read API가
unreachable일 때 redirect loop가 생기므로 자동 redirect는 시작하지 않습니다.

## Architecture map resilience

Architecture route는 inventory provenance와 factual count를 먼저 표시합니다. 기본 isometric map은
containment와 resource shape을 보여 주며 top 및 front view는 optional입니다. 단순 projection은 세 개
이상의 resource group을 최대 2열로 reflow하고, authored nested layout은 supplied geometry를
유지합니다. Selection은 inventory를 reload하지 않고 canonical deep link를 갱신하며 technical
identifier보다 directional relationship을 먼저 표시합니다.

Label은 collision을 피하고 긴 이름을 맞추며 zoom에 따라 13 px에서 20 px까지 커집니다. 선택된
label은 22 px까지 커질 수 있습니다. Zoom step은 reciprocal이고 색상은 console theme을 따르며,
keyboard-accessible resource 및 relationship index는 filtered canvas와 동등합니다. Pointer target은
containment boundary를 포함해 최소 44 px입니다. Truncated snapshot은 partial-inventory notice를
명시합니다.

Subscription-scoped cached snapshot은 즉시 렌더링됩니다. Expired 또는 change-invalidated snapshot은
background refresh 동안 stale로 표시됩니다. Browser는 read API가 완료된 refresh를 원자적으로
promote할 때까지만 polling하고 server freshness verdict를 높이지 않으며, stale graph를 유지한 채
transient failure를 bounded 2-30초 backoff로 재시도합니다.

## 검증

- Catalog parity 및 route-local fallback test가 localization을 검증합니다.
- Replay test가 JSON, SSE 및 cross-transport idempotency를 검증합니다.
- Provenance test가 unavailable, unknown, malformed 및 route-owner 상태를 검증합니다.
- Stream test가 inactivity, authentication 분류, frame limit 및 action timeout을 검증합니다.
- Architecture test가 layout, selection, accessibility, cache freshness 및 bounded polling을 검증합니다.
