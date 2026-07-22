---
title: 콘솔 근거 및 복원력
translation_of: console-evidence-and-resilience.md
translation_source_sha: 79e8da01f71652754a2a76cb9263ac3ce6628520
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

Dashboard의 모든 데이터 항목은 drill-down을 제공합니다. 운영 상태, evidence metadata, 측정되거나
unavailable인 성과, 분포 legend, attention fact, vertical 통계 및 접힌 operational count는 해당
datum을 소유하는 가장 좁은 analytical 또는 filtered-evidence 목적지로 연결됩니다. 섹션 제목과 설명
문구만 비대화형으로 유지합니다. unavailable 값도 소유 view를 열어 누락된 source 또는 sample을
확인할 수 있게 합니다.
Unavailable metric 카드는 낮은 강조도의 전체 surface 배경, elevation shadow 없음 및 작고 muted한
값 text를 사용해 측정 결과처럼 보이지 않게 합니다. 이 카드는 focus 가능한 drill-down link를
유지하고 complete-border focus 또는 hover cue를 제공하며, 시각 표현에 disabled semantics를
사용하지 않습니다.

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

## Stream recovery 및 authentication

인증된 live, agent 및 provisioning SSE reader는 keepalive comment를 포함해 45초 동안 byte가 없으면
cancel하고 bounded reconnect를 사용합니다. Provisioning은 event 전달 실패 시 reader도 cancel합니다.
Agent stream의 `401`은 전체 화면 login recovery를 기다리고, `403`은 새 App Role을 page reload 없이
반영할 수 있도록 reconnect합니다.

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
