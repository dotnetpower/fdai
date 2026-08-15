---
title: 콘솔 근거 및 복원력
translation_of: console-evidence-and-resilience.md
translation_source_sha: ed3024c0132b6df8cb799e5b7dfbfbe428716fa7
translation_revised: 2026-08-15
---

# 콘솔 근거 및 복원력

이 문서는 운영자 콘솔의 근거 출처 이력, localization, 스트림 복구, 영속 재생 및 아키텍처 지도 복원력 계약을 소유합니다. 대화형 도구 및 RBAC 계약은 [operator-console-ko.md](operator-console-ko.md)에 유지됩니다.

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|-----------|
| 통제된 온톨로지 보증 출처 이력 | in-progress | `console/tests/live-e2e/ontology-query-assurance*.ts`, `console/tests/live-e2e/assurance-budget.ts`, `console/tests/live-e2e/assurance-checkpoint.ts`, focused Vitest 79개 통과 | 강화된 release gate는 두 locale의 모든 operation에 완전하게 검증된 답변을 요구합니다. 실행은 질문별 및 무진행 deadline을 갖춘 유도된 budget으로 제한되고 provenance에 바인딩된 checkpoint에서 재개하며, 소진된 budget은 ready 아티팩트를 보고하지 않습니다. |
| Exact-release 온톨로지 카탈로그 변환 결과 | 구현됨 | `ontology_console_projection.py`, `materialize-authoritative-catalogs.py`, focused materializer 동등성 테스트, Console 토폴로지 모델 테스트 및 타입 검사 | 하나의 생산자가 릴리스 신원 및 변경 권한 부재와 함께 선언 보기와 카탈로그 토폴로지를 제공합니다. 의미 모델 렌더링과 receipt 기반 컨텍스트 근거는 남아 있습니다. |
| 의미 모델 및 관계 방향 | 구현됨 | `ontology-semantic-model.ts`, `ontology-semantic-map.tsx`, 카탈로그 토폴로지 renderer 및 inspector, focused Vitest 23개 및 Console 타입 검사 통과 | 검토된 네 가지 의미 영역, 다섯 가지 운영 보기, 화살표 및 분리된 들어오는 관계와 나가는 관계를 구현했습니다. 인증된 데스크톱 및 모바일 근거는 남아 있습니다. |
| 에이전트 활동 하트비트 표현 | validated | `console/src/routes/agents.model.ts`, `console/src/routes/agents.model.test.ts`, `docs/baselines/agent-activity-heartbeat-assurance-2026-08-14.json`, focused Vitest 31개 통과 및 인증된 Browser Entra assurance | 두 번 새로고치는 동안 연속된 하트비트 시각 세 개가 증가했고 인증된 self 검사 세 번이 모두 성공했으며 런타임 초기화 행은 0개였습니다. |
| Command Deck JSON 대비 | 구현됨 | `console/src/styles.css`, `console/src/deck/command-deck-workspace-visual.test.ts`, focused Vitest 10개 통과 및 인증된 브라우저 검사 | 구문 강조 JSON은 전역의 밝은 `pre` 스타일과 관계없이 고정된 어두운 코드 표면을 유지합니다. 브라우저 검사는 통제된 런타임 근거로 보존하지 않았습니다. |
| 탭 간 SSE 및 인시던트 복원력 | validated | 탭 간 stream hook, `incidents.milestones.ts`, incident projection, `docs/baselines/console-cross-tab-sse-assurance-2026-08-14.json`, `docs/baselines/incident-rca-report-assurance-2026-08-15.json`, focused Console/Operator 테스트 | 탭 간 leadership와 failover가 통과했고 인증된 Incident 상세가 notification delivery를 주장하지 않으면서 milestone 8개, 같은 스냅샷 분석 및 사용 불가 source와 plan context를 보존했습니다. |
| 선택적 report PDF 컨트롤 | validated | `console/src/routes/reports.tsx`; service-local Operator PDF 어댑터; `docs/baselines/incident-rca-report-assurance-2026-08-15.json`; focused Console 및 Operator 테스트 | Catalog와 runtime registry가 함께 `pdf`를 표시했고 인증된 Browser Entra가 no-RCA 사용 불가 동작을 보존하면서 범위가 제한된 38809-byte PDF를 검증했습니다. |
| 대화 검색 요청 복원력 | implemented | `console/src/routes/conversation-search.tsx`, `console/src/routes/conversation-search.test.tsx`, focused Console 테스트 (`22 passed`) 및 타입 검사 | 검색 generation은 오래된 결과 및 맥락 쓰기를 거부합니다. Generation 범위 in-flight key는 rerender 전 중복 맥락 요청을 억제하고 검색 간 결과를 섞지 않습니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 잔여 작업 |
|------|------|------|------|-----------|
| 2026-08-13 | in-progress | 이전 출처 이력을 재구성하지 않고 구현 ledger를 도입했으며 온톨로지 보증 아티팩트를 정확한 source, configuration, workspace, 인증, request 및 projection 출처 이력에 연결했습니다. | 현재 변경의 `console/tests/live-e2e/ontology-query-assurance*.ts`, focused Vitest 25개 및 Console 타입 검사 통과. | 정확한 중앙 검증 receipt를 얻은 뒤 seeded 영/한 100-case cohort 전에 인증된 probe 하나를 실행합니다. |
| 2026-08-14 | 구현됨 | 현재 상태와 하트비트 최신성을 유지하면서 주기적인 `Runtime agent initialized` 스냅샷이 페이지를 새로고칠 때마다 chronological 활동으로 다시 나타나지 않도록 수정했습니다. | `current change`, `agents.model.test.ts` focused 테스트 31개 통과, 인증된 브라우저에서 두 번 새로고침하는 동안 초기화 행 0개 확인 | 런타임 검증을 주장하기 전에 두 번 새로고침한 Browser Entra 결과를 통제된 아티팩트로 보존합니다. |
| 2026-08-14 | 구현됨 | 전역 `pre` 배경이 덮어쓴 Command Deck JSON 구문 강조 영역 아래에 고정된 어두운 표면을 복원했습니다. | `current change`, 작업 소유 Console CSS 및 시각 계약 테스트, focused Vitest 10개 통과, Console 타입 검사 통과, 인증된 브라우저에서 의도한 어두운 표면과 토큰 색상 계산 확인 | 범위가 제한된 잔여 작업은 없습니다. 향후 테마 변경은 focused 회귀 테스트가 확인합니다. |
| 2026-08-14 | 구현됨 | 각 attention 및 알림 채널에서 탭 간 읽기 담당 하나를 선출하고 검증된 attention 스냅샷을 follower 탭과 공유해 HTTP/1.1에서 일반 Operator API 용량을 확보했습니다. | `current change`, 작업 소유 스트림 훅, focused Vitest 8개 및 Console 타입 검사 통과 | SSE 읽기 담당이 활성화된 상태에서 새 Dashboard 접근 검사가 완료되는 통제된 세 탭 Browser Entra 아티팩트를 보존합니다. |
| 2026-08-14 | 구현됨 | Principal-scoped cross-tab stream leadership를 확장하고 bounded incident milestone, action confirmation projection 및 deterministic resilience baseline을 추가했습니다. | `current change`, focused Console/Operator test 및 Console typecheck | Runtime validation을 주장하기 전에 인증된 multi-tab 및 incident Browser evidence를 보존합니다. |
| 2026-08-14 | validated | 인증된 Browser Entra 복원력 아티팩트를 보존하고 SSE 및 탭 간 경계에서 모호한 local-date timestamp를 거부했습니다. | `current change`, strict stream timestamp 테스트 9개 통과, 인증된 Playwright 복원력 테스트 2개 통과, tracked cross-tab 및 heartbeat 아티팩트가 source revision `848e1021786c2bb7f3fb0a533d9d113c3020d5cf`와 하나의 workspace patch digest에 연결됩니다. | 관리되는 incident-detail 근거를 별도로 보존하고 중앙 검증된 revision에서 semantic-planning capacity를 사용할 수 있을 때 강화된 ontology cohort를 완료합니다. |
| 2026-08-14 | 구현됨 | Operator 온톨로지 레지스트리와 카탈로그 토폴로지를 하나의 exact-release 생산자로 통합하고 InterfaceType 및 FunctionType 노드를 추가했으며 SPA의 생성된 토폴로지 복사본을 제거했습니다. | `current change`, materializer 동등성 테스트 2개, focused Console 테스트 13개 및 Console 타입 검사 통과 | 검토된 의미 모델을 렌더링하고 receipt 기반 컨텍스트 스냅샷과 인증된 Browser 근거를 보존해야 합니다. |
| 2026-08-14 | 구현됨 | 네 영역 의미 모델을 기본 온톨로지 보기로 만들고 dense graph를 카탈로그 토폴로지로 유지했으며 semantic inspector와 topology canvas 모두에 canonical 방향을 렌더링했습니다. | `current change`, focused ontology Vitest 23개, 카탈로그 동등성 및 Console 타입 검사 통과 | 인증된 데스크톱 및 모바일 Browser 근거를 보존하고 런타임 근거를 표시하기 전에 authoritative 컨텍스트 receipt를 연결해야 합니다. |
| 2026-08-14 | 구현됨 | 독립적인 비평 라운드 10개를 완료하고 범위가 제한된 구획에서 검증된 모든 Medium 이상 finding을 수정했습니다. Fail-closed 응답 decoding, canonical 영역, profile 기반 action membership, self-loop, 관계 flag, 키보드 제어, 접근 가능한 landmark 및 focus, topology bound, localized node kind를 포함합니다. | `current change`, focused Python 테스트 7개, ontology Vitest 27개, 카탈로그 동등성, Console 타입 검사 및 Core import 경계 통과 | 남은 구현 finding은 Low입니다. Principal 범위 컨텍스트 전송과 인증된 Browser 근거는 가용성을 추론하지 않고 명시적 검증 작업으로 유지합니다. |
| 2026-08-14 | 구현됨 | 인증된 Browser 검사에서 동작하지 않는 topology 키보드 경로와 390 px intrinsic-width overflow를 찾아 수정했습니다. 이후 의미 모델은 네 영역, 다섯 보기, 하나의 exact release, 명시적 컨텍스트 사용 불가 상태, body overflow 0, node overlap 0 및 잘린 node control 0으로 렌더링됐고 카탈로그 토폴로지 canvas에는 빈 화면이 아닌 pixel이 있었습니다. | 5273 로컬 Browser Entra 및 `current change`, focused 키보드, geometry, decoder, semantic, i18n 및 타입 검사 통과 | Browser 관측은 통제된 아티팩트로 보존하지 않았고 hidden-tab `requestAnimationFrame` 제한 때문에 screenshot 기반 키보드 이동 receipt를 신뢰성 있게 만들지 못했습니다. |
| 2026-08-14 | implemented | Browser authorization 또는 분석 동작을 추가하지 않고 opt-in Incident RCA PDF 다운로드 컨트롤을 추가했습니다. | `current change`; catalog 및 registry 가용성 확인, stale 다운로드 억제, service-local PDF 경로, focused Console 및 Operator 테스트입니다. | 하나의 exact-revision 인증된 roster-to-RCA-to-report/PDF 아티팩트를 보존해야 합니다. |
| 2026-08-14 | implemented | Incident roster, RCA 근거, report 묶음, PDF 응답, no-RCA 상태 및 실제로 unavailable인 source 또는 plan context를 위한 exact-source Browser Entra runner를 추가했습니다. | `current change`; `incident-rca-report-assurance.spec.ts`, Console typecheck 및 focused Playwright discovery입니다. | Source commit의 중앙 receipt가 생긴 뒤에만 runner를 실행하고 redacted 아티팩트를 보존해야 합니다. |
| 2026-08-14 | implemented | 같은 경로의 SPA 문서가 API 근거 대기를 충족할 수 없도록 Incident assurance runner를 JSON Operator 응답에 연결했습니다. | `current change`; `incident-rca-report-assurance.spec.ts`, Console typecheck 및 focused Playwright discovery입니다. | 이 runner revision을 중앙 검증한 뒤 다시 실행해 redacted 아티팩트를 보존해야 합니다. |
| 2026-08-14 | implemented | 일치하지 않는 legacy 경로가 Overview로 fallback하지 않도록 Incident assurance runner를 canonical `/root-cause-analysis` 경로로 이동했습니다. | `current change`; `incident-rca-report-assurance.spec.ts`, Console typecheck 및 focused Playwright discovery입니다. | 이 runner revision을 중앙 검증한 뒤 다시 실행해 redacted 아티팩트를 보존해야 합니다. |
| 2026-08-14 | implemented | 인증된 assurance에서 서버의 최신순 hypothesis 정렬을 거부하는 동작이 드러나 Console RCA decoder를 수정했습니다. | `current change`; `api-operations.ts`, `api.test.ts`, focused decoder 테스트 13개 및 Console typecheck입니다. | 수정 commit을 중앙 검증한 뒤 다시 실행해 redacted 아티팩트를 보존해야 합니다. |
| 2026-08-14 | implemented | 오래되거나 중복된 대화 검색 맥락 응답이 현재 Console 상태를 대체하지 않도록 차단했습니다. | `current change`; focused 경로 및 decoder 테스트 22개, Console 타입 검사 및 catalog parity 검사가 통과했습니다. | 관리되는 Browser 근거는 이 로컬 요청 상태 검사가 아니라 더 넓은 Console 보증 캠페인에서 계속 다룹니다. |
| 2026-08-15 | validated | JSON 응답 연결, canonical 탐색, 최신순 decoding 및 audit-backed report materialization을 hardening한 뒤 인증된 Incident-to-RCA-to-report/PDF 아티팩트 하나를 보존했습니다. | `current change`; `docs/baselines/incident-rca-report-assurance-2026-08-15.json`; source `014974045e70e35c26e489fa238345cf70bc3ca3`는 중앙 검증됐습니다. | Incident 상세 또는 RCA PDF Browser 근거에 남은 작업이 없습니다. |
| 2026-08-15 | implemented | 온톨로지 relationship-direction 컴포넌트를 Console visible-title 인벤토리에 등록했습니다. 이는 해당 컴포넌트가 렌더링하는 `h4` 제목과 일치하며 공유 검증 큐의 차단을 해제합니다. | `current change`; 전체 Console Vitest suite 1782개 통과입니다. | 남은 작업이 없습니다. 인벤토리 계약이 이후 title prop 추가를 계속 소유합니다. |
| 2026-08-15 | implemented | 통제된 온톨로지 assurance 실행기를 유도된 run budget, 질문별 및 무진행 deadline, 적응형 요청 간격, 제한된 transport 재시도, 질문별 진행 출력 및 provenance에 바인딩된 재개 가능 checkpoint로 제한했습니다. | `current change`; focused Vitest live-evidence 79개 및 전체 Console suite 1782개 통과, Console 타입 검사 통과입니다. | Release 경계에서 bounded cohort를 실행하고 그 아티팩트를 보존합니다. |
| 2026-08-15 | implemented | 모든 assurance turn을 남은 실행 예산으로 제한하고, 아티팩트 발행 전에 checkpoint를 회수하며, 통과에 live turn 최소 1회를 요구하고, turn 오류와 deadline 위반을 구분하며, 기본 checkpoint 경로를 cohort별로 분리했습니다. | `current change`; focused Vitest live-evidence 80개 통과, Console 타입 검사 통과, 1차 독립 검토의 Medium 2건 해소입니다. | Release 경계에서 bounded cohort를 실행하고 그 아티팩트를 보존합니다. |

### 잔여 작업

- [ ] 정확한 중앙 검증 receipt와 인증된 probe를 확보한 뒤 seeded 영/한 100-case cohort에서 통과한 통제 아티팩트 하나를 보존합니다.
- [x] 에이전트 스트림 열림, 갱신된 하트비트 시각, 페이지를 두 번 새로고친 뒤 `Runtime agent initialized` 활동 행 0개를 보여 주는 통제된 Browser Entra 아티팩트를 보존합니다.
- [x] 백그라운드 알림과 활성 탭 attention 스트림을 유지하면서 새 Dashboard 접근 검사가 완료되는 통제된 세 탭 Browser Entra 아티팩트를 보존합니다.
- [x] Milestone, 원본, 대응 계획 및 같은 스냅샷 결과 표현을 위한 관리되는 incident-detail Browser 근거를 보존합니다.
- [x] 사용할 수 없는 RCA 사실을 주장하지 않고 하나의 source revision과 workspace digest를 연결하는 인증된 roster-to-RCA-to-report/PDF 근거를 보존합니다.
- [ ] 의미 모델과 카탈로그 토폴로지가 일치하는 하나의 온톨로지 릴리스를 표시하고 보안 receipt가 없으면 컨텍스트가 사용 불가로 유지됨을 보여 주는 인증된 Browser 근거를 보존합니다.
## 탐색 컨텍스트

활동 Bar 영역을 선택하면 Explorer가 열리고 운영자의 로컬 순서 및 표시 설정에 따라 첫 번째 visible 패널로 이동합니다. Command Deck이 닫혀 있거나 floating 상태여도 이 탐색은 동작하며, full-workspace Deck은 경로가 변경되기 전에 닫힙니다.
다른 화면의 cached 대화 선택은 범위가 제한된 exception입니다. Console은 대화 출처로 이동할 때 conversation-owned synchronous 경로 이벤트만 suppress한 뒤 대화 기록을 활성화합니다. Transient default-session 전환 또는 close/reopen focus cycle 없이 Deck을 열린 상태로 유지합니다.
Same-screen 및 에이전트 대화는 탐색 없이 전환합니다.
이미 활성인 same-screen 대화를 다시 선택하면 focus만 복원하며 최신 in-memory 턴 위에 sessionStorage 대화 기록을 다시 로드하지 않습니다.
비활성 대화를 선택하면 browser-local 읽음 확인만 기록하고 활동 시각은 변경하지 않으므로 이력 순서가 유지됩니다. principal 범위로 한정된 `내 대화`, `읽지 않음` 및 `즐겨찾기` 필터는 browser-local 탐색 메타데이터만 사용하며 즐겨찾기 전환은 서버 활동, 근거 또는 정렬을 변경하지 않습니다. 대화 제목은 관찰된 활동이 저장된 읽기 시각보다
최신인 동안에만 굵게 표시됩니다. 선택하면 행을 이동하지 않고 이 표시를 해제하며, 더 새로운 서버
활동만 정렬 시각을 갱신합니다.
에이전트 대화가 아닌 경우 첫 운영자 질문이 제목이 되고 출처 화면은 별도 메타데이터로 유지됩니다.
정규화된 질문은 이력 메타데이터에서 512자로 제한되고 브라우저 및 영속 복원 후에도 보존됩니다.
제목이 시각적으로 잘리면 visible 텍스트는 ellipsis를 유지합니다. 시간 영역을 포함한 selectable
대화 행 어디에서든 포인터 hover하거나 keyboard focus하면 제목 길이와 관계없이 공용 콘솔
툴팁으로 제한된 질문 전체를 표시합니다. 배치 및 닫기 icon 컨트롤도 같은 localized 툴팁 컴포넌트를 사용합니다. 연결된 백엔드 툴팁은 모드, 엔드포인트, 경로 choice 및 후보를 별도 줄로 유지하고 localized 자리 표시자를 모두 채우며 긴 엔드포인트 또는 배포 토큰을 뷰포트 경계 안에서 줄바꿈합니다.
에이전트 카드의 Ask 액션은 항상 unique user-scoped 키를 가진 비어 있는 새 에이전트 대화를 엽니다. 새 요약은 선택한 에이전트를 즉시 보유하므로 첫 제출부터 같은 에이전트 대상을 Operator API에 전달합니다. 기존 에이전트 대화는 별도 이력 항목으로 보존하며 운영자가 명시적으로 선택할 때만 복원합니다.
활성 cached 대화를 제거하면 current-route 기본값(이전 방식 `screen` 키 포함) 또는 current-route 스레드만 선택합니다. 둘 다 없으면 unrelated-route 또는 에이전트 대화 기록을 활성화하지 않고 새 current-route 기본값을 만듭니다. Context-dependent 취소, 런북, knowledge, 기억, learning, ordinal-resource, 모호함, reformatting 및 partial-source 질문에는 검증된 이전 대화 기록이 필요합니다. 서버는 principal 범위로 한정된 `ConversationHistoryStore`의 최신 사용 가능한 assistant 재생에서 활성 조사, 선택된 리소스, 이전 답변 또는 source-failure 증적을 재구성합니다. 브라우저 대화 기록은 이 권한을 만들 수 없으며 fresh 대화는 사용 불가 상태를 유지합니다. 검증된 또는 corrected 이전 턴 이후 `KnowledgeContextChatTools`는 unique trusted 런북 하나를 부하하거나 활성화된 출처의 권한 확인 및 refresh 상태를 보고하거나 해당 principal만 볼 수 있는 explicit-consent 기억을 표시합니다. Exact assistant-turn 검토가 materialized 기억 또는 runtime-skill 제안을 가리킬 때만 learning을 reusable로 보고합니다. 초안과 모호한 런북은 빈으로, 프로바이더 실패는 사용 불가로 유지하며 ordinary chat은 기억 또는 검토 상태를 쓰지 않습니다. 완료된 이어가기는 영속 assistant 턴과 내용 기반 주소를 가진 출처 증적을 인용합니다.
검증된 fresh 인벤토리 답변은 서버가 소유한 재생 메타데이터에 범위가 제한된 `resource_result_context`를 포함할 수 있습니다. Raw 리소스 ID를 포함하지 않고 브라우저 맥락에서는 수락하지 않으며 출처, 스냅샷, 범위, 조회 다이제스트, 최신성, 잘림 및 이후 결정론적 후속 조치에 사용할 최대 40개의 ordered 선택자를 보존합니다.
Ordinal 후속 조치는 선택한 위치를 exact fresh 인벤토리 조건식으로 다시 검증합니다. 모호함 후속 조치는 완전한 이전 결과 집합의 equal-name 후보만 표시합니다. 불완전한 맥락은 사용 불가 상태를 유지하며 current-screen 또는 서술기 출력으로 대체 경로할 수 없습니다.
검증된 source-manifest 답변은 범위가 제한된 사용 불가 또는 알 수 없음 항목을 `source_failure_context`로 보존합니다. Partial-source 이어가기는 해당 증적의 available 사실과 exact 공백을 렌더링하고 사유 및 last 관측이 있으면 함께 표시하며 arbitrary 검증되지 않은 답변을 출처 권한으로 취급하지 않습니다. 검증된 또는 corrected `query_llm_usage` 답변은 domain, 기능, 토큰 measure, 그룹화, `usage_scope` 및 numeric 1-90일 조회 구간이 포함된 범위가 제한된 `analysis_context`를 보존합니다. 기간, 그룹화, 표 또는 chart만 바꾸는 구체화는 이 서버가 소유한 anchor를 재사용하고 metering 근거를 다시 읽습니다. 비교, 내보내기, missing-anchor, client-supplied-anchor 및 명시적인 다른 메트릭 요청은 인벤토리, Resource Health 또는 서술기 출력을 선택하지 않고 context-required 보류를 반환합니다.
Full-workspace Command Deck 세션은 대화 기록만 열린 내용 열로 시작합니다. 비어 있는 대화 기록은 상황별 suggestion을 유지하고 도구 선택이나 권한을 바꾸지 않는 localized 복원력, 변경 안전성 및 비용 거버넌스 quick 시작을 추가합니다. 대화 기록
toolbar는 workspace, docked 및 floating 배치에서 필터 가능한 대화 이력을 제공합니다. 좁은
배치에서는 대화 기록 폭을 줄이지 않고 그 위에 overlay로 엽니다. Workspace에서는 포인터 또는 keyboard 구분자로 대화 이력 폭을 180-360 px 범위에서 조절하고 마지막 폭을 로컬에 저장합니다. 좁은 배치는 구분자를 숨깁니다. 이력 헤더는 검색과 icon-only 새 대화를 간결한한 한 줄에 배치하고 lightweight 필터 tab을 사용하며, 컨트롤 대신 목록만 scroll합니다. 현재 화면 다이제스트는 workspace 컨트롤로 유지됩니다. Deck은 열린 표면마다 composition-owned data-source 매니페스트를 한 번 읽고 대화 기록 위에 인벤토리, Incidents, 감사, Knowledge 및 자동화 준비 상태 링크를 간결한하게 표시합니다. 누락되거나 non-authoritative인 출처는 `unknown`으로 유지합니다. 브라우저는 상태를 추론하거나 raw 프로바이더 상세를 노출하거나 경로 존재로 매니페스트를 대체하지 않습니다. 로딩은 고정된 골격을 사용하고 매니페스트 실패는 대화 이력을 차단하지 않으면서 진단으로 연결합니다.
이력은 고정된 커서 순서를 유지하지만 처음에는 요약 20건만 렌더링합니다. 이력 scroll 경계에 가까워지면 이미 부하된 요약 중 다음 20건을 표시합니다. 로컬 구간을 모두 사용한 뒤에는 같은 경계에서 서버 페이지 20건을 요청하고 기존 행을 교체하지 않고 이어서 표시합니다. 다음 페이지가 있으면 개수를 `20+`로 표시합니다. 대화 기록 본문은 선택할 때만 hydrate합니다. Operator 이미지는 전송된 턴 안에 표시됩니다. 브라우저 캐시 직렬화는 inline 바이트를 제거하고 범위가 제한된 서술자만 유지하며, 영속 복원은 인증된 principal 및 대화 범위 이미지 경로를 통해 binary를 fetch합니다. 브라우저 또는 영속 이력에서 복원된 대화 기록은 새 대화를 시작할 때까지 resumed-session 표시를 표시합니다. Deck 헤더는 경로와 선택적 에이전트 맥락만 담당하며 에이전트 대화가 아닌 질문은 반복 표시하지 않습니다. 다이제스트는 기록 수, 스냅샷 age 및 오래된 맥락 새로고침을 담당하며, 작성기에는 첨부, 질문 입력 및 보내기 또는 중지만 유지합니다.

공통 페이지 제목은 영역과 패널 레이블이 다를 때 `전체 현황 / Dashboard`를 포함해 둘을 함께 렌더링합니다. 패널 제목이 영역 레이블을 반복하는 영역 루트와 독립 utility는 단일 제목을 유지합니다.

공통 상단 표시줄은 아이콘 전용 FDAI 마크를 원본 색상으로 렌더링하고 옆에 `FDAI Console`
워드마크를 표시합니다. 콘솔 테마는 브랜드 자산의 채도를 낮추거나 색을 변경하지 않습니다.

실제 운영도 `운영 / 실시간`과 같은 공통 title 계약을 따릅니다. 관찰 컨트롤은 공통 헤더 actions
영역에 유지되고 좁은 뷰포트에서는 제목 아래로 줄바꿈되어 화면 고정, 출처, 구간 및 연결
상태가 계속 표시됩니다.
열린 SSE 응답은 전송 연결만 증명합니다. 실제 운영은 권한 있는 런타임 또는 재생 단계 프레임을
관찰한 뒤에만 출처가 준비되었다고 표시합니다. keepalive만 있는 연결은 `소스 대기`를 렌더링하고
운영 메트릭을 사용 불가 상태로 유지하며, 0을 측정된 상태로 제시하는 대신 Core 런타임과 단계
토픽 준비 상태를 확인하도록 안내합니다. 기본 보기는 제한된 12개 작업 풀의 흐름입니다.
흐름과 큐는 동일한 제목, 대상, 범위, 이유, tier, 모드, 소유자 및 단계 사실을 유지하고 큐는
관찰된 risk, 영향, SLA 및 컨트롤 상태만 추가합니다. 흐름은 값이 있는 작업만 렌더링하고
desktop 한 행에 6개씩 배치하며 attention priority와 최신 관찰 순서로 정렬합니다. 최종 결과는
실제 운영 작업 영역을 차지하지 않고 이력에서 계속 확인할 수 있습니다. Tier, 자율성 및 모드 배지는
포인터와 keyboard에서 같은 툴팁을 사용합니다. 누락된 자율성, risk, 영향 또는 SLA는
`관찰되지 않음`으로 유지되며 브라우저에서 추론하지 않습니다.

에이전트 작업 영역은 `Fleet`, `조직` 및 `활동`의 세 가지 간결한 화면을 사용합니다. Fleet은
실시간 런타임 상태와 고정 레지스트리 소유권 및 안전성 플래그를 에이전트별 상세 공개에 함께
표시합니다. 조직 화면은 keyboard-accessible 보고 체계와 선택된 인시던트 근거를 렌더링합니다.
기존 링크가 계속 동작하도록 고정된 `/pantheon` 경로는 조직 compatibility 경로로 유지하고,
탐색에는 별도의 Pantheon 디렉터리를 두지 않습니다. 에이전트 감독은 운영 담당 체계와
통제된 제안 작업 흐름을 다루는 거버넌스 패널이며 `/agent-oversight`를 사용합니다. 이전
`/handover` 경로는 compatibility 별칭으로 유지합니다.
다섯 화면은 개요, 사람 의존성, 지식 인수인계, 승인 경로, 매핑 검토입니다. 개요와 사람 의존성은
엄격한 `GET /stewardship` 프로젝션을 사용합니다. 매핑 검토는 Owner 게이트가 적용된
`GET /iam/assignments` 프로젝션을 재사용하며 기능과 principal은 `GET /iam`에서만 가져옵니다.
지식 인수인계는 통제된 초안 경계를 사용합니다. 승인 경로는 자체 권위 있는 변환 결과가
연결될 때까지 사용 불가로 명시하며, 브라우저는 소유권 데이터에서 경로를 추론하지 않습니다.
담당 체계 출처가 없으면 개요와 사람 의존성만 차단합니다. 독립적인 지식 인수인계, 승인 경로,
매핑 검토 화면은 숨기지 않습니다.
개요는 `identity_health`에서만 ID 출처 최신성을 표시합니다. Operator API는 stale-finding
스냅샷과 개정 번호가 일치하고 만료되지 않은 last-success 하트비트에서만 `checked_at`을 제공합니다.
완료된 `clean` 또는 `warn` 확인은 이 시각과 병합된 `stale_oid` 커버리지에 맞는 발견 사항 개수가
필요합니다. 불일치는 정상 또는 최신 상태로 표시하지 않고 계약 오류로 처리합니다.
각 에이전트의 `bus_factor`는 커버리지 evaluator와 동일하게 서로 다른 accountable `(kind, id)` 대상
단위 수를 사용합니다. 브라우저는 담당자 변환 결과에서 이 값을 다시 계산하고 다른 headline 값은
백업 커버리지를 과장하지 않도록 거부합니다.

Settings에는 권위 있는 StateStore를 사용하는 런타임 policies 경로가 포함됩니다. 이 경로는
시크릿, 엔드포인트, 테넌트 식별자 또는 워크로드 신원 식별자를 노출하지 않고 정제된
환경, 재정의 및 effective 값을 표시합니다. 읽기 담당 접근은 관찰 전용입니다. Owner 갱신은
개정 번호 검사와 원자적인 상태 및 감사 쓰기를 사용합니다. 브라우저는 startup-bound 값을 재시작
필수로 표시하며 저장된 값을 액션 승격 또는 cloud-resource 변경으로 나타내지 않습니다.
Integrations와 진단은 동일한 변환 결과를 사용합니다. 이 화면은 구성된, 준비된,
불완전한, 모드 및 boolean 런타임 상태만 표시합니다. 엔드포인트, 시크릿, 테넌트, 리소스,
저장소 자격 증명, recipient 또는 managed 신원 값은 렌더링하지 않습니다.
Integrations는 sandboxed iframe으로 incident-open 이메일도 렌더링합니다. 인증된 미리 보기
엔드포인트는 Azure Communication Services 이메일이 사용하는 동일한 운영 렌더러를 호출하고
합성 자리 표시자만 제공합니다. 미리 보기는 런타임 인시던트, 엔드포인트, recipient 또는 신원 값을
노출하지 않으며 전송, 승인 또는 실행 컨트롤을 제공하지 않습니다.

Operations에는 Muninn의 영속 StateSnapshot만 사용하는 감지 준비도 경로가 있습니다.
이 화면은 Heimdall 판정, 6개 근거 차원, 공백, 권한 상한, 원본, 관찰 시각을 표시합니다.
브라우저는 AKS를 탐색하거나 대체 판정을 만들지 않습니다. 각 대상은 아키텍처 리소스로,
승격 관련 개수는 승격 gates로 연결됩니다. 성공한 HTTP 응답이 strict 디코딩을
통과하지 못하면 해당 경로와 Capabilities는 로딩 골격에 머물거나 알 수 없는 자율성 모드를 적용으로 취급하지 않고 오류를 렌더링합니다.

Server-pinned drift 맥락이 있으면 GET-only 구성 기준선 경로가 신원, 수명 주기, drift, Knowledge 인용, topology, 지연 시간, 예약 검토, 네 안전성 counter를 fresh 읽기로 표시합니다.
연결 또는 campaign 부재는 사용 불가이나 `not-configured`로 보고하며 진행 상황을 만들지 않고 malformed 데이터를 strict하게 거부하며 in-scope 변경할 수 없는 버전 비교와 failed-attempt 개수를 읽습니다. SPA는 activation, 재개, 예약 생성, 승인, 완화, 리소스 변경을 노출하지 않고 evidence-run, 재개, 청사진 검토, 구체화는 별도 인증된 경로를 사용합니다.
운영은 mounted JSON/DOCX 쌍, 읽기 전용 Managed Identity, exact resource-group 허용 목록을 시작에서 검증한 뒤 패널을 노출합니다. Operator API는 실행기 신원을 받지 않습니다.

Processes 상세 경로는 동일한 권위 있는 프로세스 journal에서 계획 수립 Room을 조건부로
렌더링합니다. Strict decoder는 모순된 phase 개수, 중복 후보, 잘못된 선택,
non-finite 효과 범위를 거부합니다. 일반 프로세스는 `planning: null`인 기존 화면을 유지합니다.
계획 수립 Room은 읽기 전용이며 액션, 승인, 재시도 컨트롤을 노출하지 않습니다.

활동 화면은 영속 감사 행과 browser-session 런타임 프레임을 하나의 범위가 제한된 chronological 로그로
표시합니다. 각 행은 출처 라벨을 유지하므로 런타임 프레임을 영속 감사 근거로 표시하지
않습니다. 기록된 에이전트 간 턴과 실제 운영 에이전트 간 턴은 전체 범위가 제한된 메시지 텍스트를 포함한 개별
`from -> to` 행으로 렌더링합니다. 로그는 렌더링된 행을 최대 200개 유지하고 실제 운영 tail을 기본으로
활성화합니다. 운영자가 위로 scroll하면 tailing을 일시 중지하며 에이전트 및 키워드 필터를
제공합니다. 시간, 경로, 유형, 상세 및 상관관계 열을 선택할 수 있고 유형은 기본적으로 숨깁니다.
Fullscreen은 표현만 변경합니다. 시간 열은 브라우저의 IANA timezone에 따른 시각만 표시하며
`Asia/Seoul`에서는 `KST`를 사용합니다. 기계가 읽는 행에는 전체 시각을 유지합니다.
Waterfall 화면은 수명 주기, 입력, 출력, 기록된 대화 및 해시를 확인하는 영속 감사
master-detail 표면으로 유지합니다.
주기적인 idle 및 watching 상태 스냅샷은 변경되지 않은 영속 감사 페이지를 다시 로드하지 않고
현재 에이전트 상태와 관측 시간만 갱신합니다. 활성 작업, 완료된 핸들러 transition, 인시던트 및
인계는 계속 감사 근거를 새로 고칩니다. 활동 헤더는 반복되는 passive 스냅샷을 작업
행으로 추가하지 않고 마지막으로 관찰된 하트비트 시각을 표시합니다.
principal 범위 Command Deck 턴과 답변 계획 수립은 대화 이력에 남고 shared 에이전트
활동에 게시되지 않습니다. 대화 Assurance는 답변 본문 대신 제한된 메타데이터와 다이제스트를
표시하는 별도 근거 경로입니다. 세부 정보는 권한이 확인된 대화 저장소에서만 원문을
읽고 유일한 쓰기는 멱등적 추가 전용 이의 제기이며, 브라우저는 정책 변경 권한을
광고하는 페이로드를 거부합니다. Synthetic 준비 상태 증명은 감사에 유지합니다.

콘솔의 모든 data-bearing 카드는 drill-down을 제공합니다. 전체 카드 표면은 해당 datum을 소유하는
가장 좁은 analytical 또는 filtered-evidence 목적지로 이동하는 keyboard-accessible native 링크를
사용합니다. 독립 컨트롤을 포함한 카드는 대신 표시되는 기본 상세 링크를 제공합니다. 대시보드의
운영 상태, 근거 메타데이터, 측정되거나 사용 불가인 성과, 분포 legend, attention 사실, 버티컬
통계 및 접힌 operational 개수에도 같은 규칙을 적용합니다. 섹션 제목과 설명 문구만 비대화형으로
유지합니다. 사용 불가 값도 소유 화면을 열어 누락된 출처 또는 샘플을 확인할 수 있게 합니다.
상세 목적지가 없는 structural 그룹, 양식, editor 및 범위가 제한된 도구는 카드 style이나 이름 대신 패널
또는 섹션 의미 규칙을 사용합니다.
사용 불가 메트릭 카드는 낮은 강조도의 전체 표면 배경, 권한 상승 shadow 없음 및 작고 muted한
값 텍스트를 사용해 측정 결과처럼 보이지 않게 합니다. 이 카드는 focus 가능한 drill-down 링크를
유지하고 complete-border focus 또는 hover cue를 제공하며, 시각 표현에 비활성화된 의미 규칙을
사용하지 않습니다.
Shared KPI 카드는 `not-measured`, `not-connected`, `insufficient-sample` 및 `not-applicable`
근거 상태를 구분합니다. 이 상태들은 neutral copy와 style을 사용하며, 실제 요청 또는 탐색
실패만 오류 컴포넌트를 사용해 시각적으로 구분합니다.
Exact Incident deep link는 두 변환 결과의 analytical snapshot sequence가 같을 때만 기존 roster에
합칩니다. Concurrent snapshot 변경은 서로 다른 근거 revision의 record와 metric을 섞지 않고
사용 불가 상태로 유지합니다.
권위 있는 visible 내용이 제자리에서 변경되는 카드는 공유 `top-edge shimmer`를 사용합니다.
이 효과는 높이 2 px, 길이 1.35초의 neutral blue 일괄 점검 한 번으로 제한합니다. 기본 요소 shared KPI
값은 자동 적용하고 복잡한 실제 운영 카드는 semantic 갱신 키를 제공합니다. 첫 렌더링, 변경되지 않은
상위 rerender, 필터, 선택 및 clock-, age-, timestamp-only 변경에는 적용하지 않습니다. 빠른
갱신은 하나의 일괄 점검이 실행되는 동안 합치며 reduced-motion 선호 설정에서는 animation을
비활성화합니다. Shimmer는 표시 내용이 변경됐다는 사실만 알립니다. 상태, 최신성, 심각도 및
결과는 라벨이 있는 content-local cue로 계속 표시합니다.
Console 카드 계약 테스트는 shared KPI 목적지를 확인하고, 중첩된 whole-card 링크를 차단하며,
nullable KPI 값에 근거 상태를 요구하고, raw 데이터 카드에 링크 또는 명시적 상세 컨트롤을
요구하며, structural 카드 이름을 차단합니다.

Operating Outcomes는 선택한 메트릭, 현재 값, 기준선, 측정 구간, 샘플 크기,
확신도 및 출처 출처 이력을 범위가 제한된 Command Deck 화면 스냅샷으로 발행합니다. 버티컬
기록은 measured breakdown을 실제로 렌더링하는 Auto-resolution 화면에만 포함합니다. Narrator는
렌더링된 근거 사실만 수신하며 사용 불가 값을 추론하거나 경로의 권위 있는 출처를
대체하지 않습니다. 스냅샷 headline은 visible 카드와 같은 메트릭 formatter를 사용하며,
Auto-resolution 값은 ratio 의미를 유지하므로 표시된 비율 점유를 운영자에게 보이는 것과
같은 반올림 정밀도로 대조할 수 있습니다.
감사 기반 변환 결과는 추가 전용 감사의 head 순서를 캡처하고 해당 기준 시점 아래 측정
구간의 모든 행을 순회한 다음 control-loop 및 실행기 생산자만 필터링합니다. 행을
`event_id`로 묶어 정규화된 이벤트마다 한 번만 계산합니다. 기준 시점 이후의 동시 덧붙이기는
스냅샷에 들어오지 않습니다. 요청은 하나의 절대 UTC 하한 시각을 계산하고 모든 페이지에서
같은 head 순서와 함께 재사용하므로 페이지 나누기는 조회 비용만 바꾸고 KPI 구성원은 바꾸지
않습니다. 명시적인 `measurement.action_outcome.v1` 기록이 enforce, 검증된, auto, non-rollback
액션을 finalize하고 완전한 이벤트 근거에 사람 승인, 거부, 실행 실패 또는 롤백 신호가
없을 때만 이벤트를 auto-resolved로 계산합니다. Dispatch-only 이벤트는 pending으로 유지됩니다.
경로는 관찰된, finalized, pending, adverse 및 auto-resolved 개수를 분리해 표시합니다.
Auto-resolution 비율은 정본 합계 observed-event denominator를 유지하므로 pending 및 기타
non-auto 이벤트가 비율에서 사라지지 않습니다. 결과 및 감사 시각은 timezone-aware여야
합니다. 영속 감사 시각보다 5분 넘게 미래인 결과는 malformed 근거이므로 액션을
finalize하지 않습니다.
버티컬 귀속은 먼저 명시적으로 기록된 버티컬을 사용하고, 그다음 강한 복원력 또는
비용 거버넌스 액션/리소스 힌트만 사용합니다. 추측 없이 귀속할 수 없는 근거는
`unattributed` 행에 남고 global denominator에 포함되며 표시되는 귀속 커버리지를 낮춥니다.
이 근거를 변경 안전성으로 대체 경로하지 않습니다. 고정된 3-domain portfolio는 unattributed 행을
제외하지만 Operating Outcomes는 감사 목적지와 함께 계속 표시합니다.

각 Operating Outcomes 경로는 메트릭별 analysis 표면을 유지합니다. Auto-resolution은 관측된
이벤트 및 auto-resolved 기록 수, 영역별 비율 및 guard 맥락을 보여줍니다. Human touchpoints,
MTTR, 변경 lead 시간 및 비용 per resolved 이벤트는 각각 고유한 analysis 및 breakdown 섹션을
유지합니다. 읽기 변환 결과가 touchpoint 타입, 지연 시간 percentile, 전달 단계 또는 비용
조립을 제공하지 않으면 관련 없는 버티컬 표를 재사용하거나 브라우저에서 값을 파생하지
않고 사용 불가로 렌더링합니다. 비용 화면은 표시 금액이 표준 단가를 기준으로 하며 할인, 약정,
credit, 세금, 환율 및 프로바이더 청구 adjustment가 반영된 실제 청구 금액과 다를 수 있다는 점도
안내합니다.

컨트롤 Assurance는 감사 KPI, 자율성 측정 및 승격 레지스트리 변환 결과에서 운영
배너, 근거 메타데이터, 자세 메트릭, 승격 guard, 최종 control-path 분포 및
required-attention 합계를 표시합니다. Guard 행은 현재, 기준선 및 임계값 값을 비교하고
filtered 근거로 연결됩니다. 분포 구간과 attention 행은 가장 좁은 감사, 승인
또는 승격 목적지로 연결됩니다. Synthetic guard는 operational pass 또는 실패를 만들지 않으며,
변환 결과가 누락되면 prototype 값나 추론한 0을 공급하지 않고 사용 불가로 렌더링합니다.

버티컬 Outcomes는 세 개의 selected-detail 경로 대신 하나의 portfolio 개요를 사용합니다. 각
영역 카드는 같은 visual grammar를 사용하지만 서로 다른 기본 결과를 표시하고 owning 근거
표면으로 직접 연결됩니다. 복원력은 Incidents, 변경 안전성은 승격 근거, 비용
거버넌스는 감사로 연결됩니다. 이벤트, auto-resolution, 미해결 위험 및 절감액은 공유 비교
표에서만 영역별로 반복합니다. 변경 실패 비율나 복구 drill 성공 같은 domain 메트릭은
읽기 모델이 귀속 근거를 제공할 때까지 사용 불가로 유지하며 global 확신도와 trend 값을
vertical-specific 점유로 바꾸지 않습니다. 빈 영역에는 해석 비율을 추론하지 않으며
synthetic 근거는 operational 상태 라벨이나 filtered runtime-evidence 점유를 만들지 않습니다.

Trust 라우팅은 T0(결정론적 규칙), T1(경량 유사도 재사용), T2(근거 기반 LLM 추론)를 하나의 측정된
tier 지도로 표시합니다. 라우팅 비율, 이벤트 수 및 목표 범위는 자율성 및 감사 KPI 변환 결과에서
가져오며 각 tier는 고유한 analysis 경로로 연결됩니다. T2 컨트롤 흐름은 실행이 통과했다고 주장하는
상태가 아니라 필수 아키텍처 검사를 설명합니다. Leading indicator는 보고된 현재 및 기준선
값만 비교합니다. 누락된 값은 사용 불가로 유지하고 simulated 값은 operational pass 또는
실패를 만들지 않습니다.

LLM 비용은 측정된 호출, 토큰, chat 비율 및 최근 호출 근거를 먼저 표시합니다. 입력 및 출력 구성,
선택 기간 trend, 모델 및 대화 귀속, 호출 기록은 metering 변환 결과에서만 파생합니다. Price 귀속이
연결되지 않은 경우 경로는 이 경계를 안내하고 토큰 양에서 지출, 예산, fixed infrastructure 비용, 호출당 가격 또는 청구서 금액을 추정하지 않습니다. 범위가 제한된 visible 호출 원장은 고정 허용 목록을 quoted CSV로 내보내기하며 formula-leading cell은 neutralize합니다. 대화, 워크로드, 모드, 일 및 월 상세 rollup은 보조 공개에서 계속
제공하므로 기본 화면의 탐색성을 유지하면서 근거를 숨기지 않습니다. Headline KPI 라벨과 값은
균형 잡힌 4열, 2열 또는 1열 grid에서 왼쪽 정렬을 유지하고, 토큰 구성의 개수와 share는 비교하기 쉽도록
공통 오른쪽 숫자 열을 사용합니다. 하나의 global UTC 선택자는 rolling 24시간, 7일, 30일 및 사용자 지정
1일에서 90일 구간을 제공합니다. Operator API는 timezone이 있는 RFC 3339 `from` 및 `to` 값을
검증하고 모든 합계, 귀속, 버킷 및 호출 기록을 계산하기 전에 동일한 시작 포함 및 종료
제외 기준 시점을 적용합니다. URL은 정확한 기준 시점을 보존합니다. 24시간 화면은 hourly 버킷을 사용하고 더
긴 구간은 daily 버킷을 사용합니다. 사용자 지정 display 종료일은 포함되며 exclusive API 경계로
다음 UTC 자정에 대응됩니다.

## 로딩 표현

모든 경로, 패널 및 범위가 제한된 내용 영역은 첫 로딩 프레임부터 골격을 렌더링합니다. 공통 골격은 spinner-only 및 text-only 대기를 대체하며, 경로는 최종 배치 dimension을 유지하는 고유 형태를 제공할 수 있습니다.
대시보드는 자세 블록 다음에 메트릭, 분포, attention 및 버티컬 자리 표시자를 사용하므로 로딩 중에도 보고가 축소되지 않습니다. 하나의 screen-reader 상태가 로딩을 알리고 decorative 블록은 숨깁니다. Reduced motion에서는 shimmer가 멈추지만 정적 골격은 계속 표시됩니다.
공통 대체 경로는 heading, summary-card 및 body-panel 자리 표시자를 사용합니다. 소유 경로 형태는 더 정확한 최종 배치를 유지할 때만 이 대체 경로를 대체합니다.

HTML 문서가 콘솔 stylesheet를 direct 의존성으로 소유하므로 authentication, 경로, 컴포넌트 및 JavaScript hot 갱신 중에도 mount된 SPA의 배치와 테마가 사라지지 않습니다. Vite는 같은 문서 링크를 fingerprinted 운영 CSS asset으로 변환합니다.
개발에서는 기존 hot-update guard도 CSS 변경을 transform하기 전에 Vite의 race-safe 파일 읽기 담당으로 처리하여 editor의 임시 빈 스냅샷이 전체 stylesheet를 대체하지 못하게 합니다.

## Localization 경계

SPA는 운영자 선호 설정에서 표시 로케일을 결정합니다. 재사용 문자열은 기본 영어 출처
카탈로그 또는 완전한 route-local 영어/한국어 쌍에서 가져오며 영어 대체 경로는 필수입니다. Static
키 커버리지, 카탈로그 동등성, 경로 대체 경로 테스트 및 콘솔 모음이 번역되지 않은 표시 텍스트의
재유입을 막습니다. Grounding trace 라벨과 매니페스트/참조 개수 상세도 reconstructed 근거
메타데이터에 영어를 직접 넣지 않고 같은 카탈로그를 사용합니다.

Localization은 표현 라벨만 바꿉니다. 머신 값, 작업 흐름 id, serialized 기록,
프로바이더 페이로드 및 검증 결과는 변경하지 않습니다.

## 관찰된 대화 트래젝터리

각 Command Deck 질문은 관측된 작업이 뒷받침하는 가장 작은 표현을 선택합니다. 활동,
인계 또는 background 작업이 없는 턴도 접힌 실행 기록을 유지합니다. 성공한 단일 최종 읽기는
간결한 조사 행과 접힌 실행 기록을 함께 사용합니다. 여러 활동, 이정표,
재시도, 실패, 인계, 명령 또는 파일 변경이 있으면 전체 타임라인을 유지하지만 실행 기록은
기본적으로 접어 둡니다. 영속
background 작업은 detached 작업 요약을 사용합니다. 복원된 간결한 턴은 영속 상세에서
관찰된 행을 재구성하고 실제 운영 턴은 인과 순서로 이미 표시한 행을 유지합니다. 완료된 모든 답변은
trajectory 요약을 확인할 수 있게 유지합니다. 범위가 제한된 original 운영자 프롬프트는 실행 기록이
접혀 있는 동안 숨기고 운영자가 펼치면 표시합니다. 내부 AnswerPlan 의도 및
상세 라벨은 답변 위에 표시하지 않습니다. 실행 기록 결정 맥락에는 유지하며 답변은
operator-facing 내용과 검증된 근거로 바로 시작합니다. Model-assisted 계획 수립은 검증된
표현 형태만 변경합니다. 검증된 `presentation_artifact` v1은 서버가 변경할 수 없는 근거에서
compile한 내용을 사용해 요약, 표, chart, 커버리지, callout, 상세 및 근거 블록을 mixed할 수
있습니다. 브라우저는 알 수 없음 블록, 중복 자리, 잘못된 한계, incompatible chart 또는 최종
검증 증적 밖의 근거 참조를 거부한 뒤 정본 답변 텍스트를 렌더링합니다. 부분
근거는 valid 블록을 모두 유지하고 명시적인 한계 블록을 추가합니다. 누락된 출처 하나가
답변의 나머지를 숨기지 않습니다. 이전 방식 검증된 chart는 범위가 제한된 `chart_artifact` v1을 계속 반환할 수
있으며 정본 Markdown 또는 fenced chart 데이터는 compatibility 대체 경로로 유지합니다.

상태 개요는 완료, 수정 후 완료, 일부 저하, 실패, 검증 미완료, 진행 중 및 관측되지 않음을 구분하며
기록 존재를 성공으로 표시하지 않습니다. 결과 chip은 내부 이벤트 합계 대신 관측된 조회와
명령 개수, 근거 완료, 참조 및 검증을 표시합니다. Serialized `unverified`
상태는 재생을 위해 그대로 유지합니다. 기본 Console 라벨은 범위가 제한된 사유 코드에 따라 맥락
필요, 출처 사용 불가, 조회 검증 실패 또는 근거 없는 점유로 표시하고 technical 상세에는
정본 상태와 raw 사유 코드를 유지합니다. Run-record 요약은
두 결과 indicator를 10 px 이하의 고정된 점으로 표시하고 출처 버튼 가장자리에서 2 px만 겹칩니다.
출처 버튼은 자체 출처 툴팁을 유지합니다. 점은 별도 포인터 및 keyboard 트리거이며 floating
툴팁 또는 별도 컨테이너 없이 간결한한 조회, 명령 및 근거 pill로 오른쪽에 직접 펼쳐집니다.
전체 요약은 트리거의 accessible 이름에 유지합니다. Absolute positioning을 사용하므로 별도 행을
만들거나 회신 액션 형상을 바꾸지 않고 인접 액션을 가리지 않습니다. 출처 버튼이 없으면
답변 품질 검토에 같은 직접 확장 점을 연결합니다. 펼친 run-record 요약은 완전한 범위가 제한된 운영자 프롬프트를 유지하고
좁은 배치에서는 줄바꿈합니다. 공개를 변경하면 대화 기록만 scroll하고 작성기는
Deck 경계에 계속 표시됩니다. 펼친 화면은 6단계 rail, 펼칠 수 있는 observed-event 타임라인 및 출처 이력 신호를 먼저 표시하고,
timing 구간, 결정 맥락, phase 기록 및 커버리지 공백은 하나의 접힌 execution-details 공개에
유지합니다. Preparing-answer 표면은 관찰된 활동과 근거 가지가 최종 상태에 도달할
때까지 운영자 턴과 관찰된 작업 사이에 유지됩니다. 더 일찍 도착한 답변 토큰은 브라우저 그리기
큐에 유지합니다. 활동 shell을 settled로 바꾸는 렌더링에서 답변을 함께 추가하므로 running
조사 골격과 답변 내용이 동시에 나타나지 않습니다. 이후 관찰된 작업은 실행
mock의 진행 상황 note, 세션, connected 단계 및 dark 명령 상세 계층을 따릅니다. 단독 활동의 starting
note는 수신한 해당 활동에서만 가져옵니다. 이정표를 수신한 경우에는 이정표가 note가 되므로
브라우저가 진행 상황을 중복하거나 만들어내지 않습니다. 현재 단계만 자동으로 펼치고 완료된 단계 shell은
유지하며 raw 출력과 시각은 접습니다. Raw current-screen 기록은 접힌 출처 공개에 유지합니다.
한 운영자 질문의 진행 상황, 관찰된 활동 및 최종 답변은 인과 기록을 각각 유지하지만 하나의
visible 에이전트 헤더와 연결된 흐름 아래에 표시합니다. 최종 답변은 같은 에이전트 또는 두 번째 출처
배지를 반복하지 않습니다. Numbered 진행 상황과 상태 glyph는 shared 버티컬 rail을 이동하지 않고
고정된 circle 표시 안에서 optical center에 맞춥니다. Numbered glyph는 더 어두운 body-text navy가
아니라 진행 상황 라벨과 같은 저채도 blue accent를 사용합니다. 대화 기록은
브라우저 scroll anchoring을 끄고 하단 공간을 추가하며 작업이 스트리밍 중일 때만 최신 간선을
따라갑니다. 최종 완료에서는 첫 관찰된 작업 그룹을 대화 기록 간선 아래에 고정해 최종
답변 배치가 완료되는 동안 실행 결과와 답변 시작을 함께 표시합니다. Timing이 없는 계획과 collaboration 메타데이터는 결정 맥락에 두고, 관측된 입력, 근거
및 도구, 모델 호출, 검증 및 전달만 타임라인에 표시합니다.
모든 waterfall 레인은 라벨이 있는 하나의 start-to-completion 규모와 quarter-window tick을 사용합니다.
내부 causal rail은 행을 연결하고 dashed 구간은 설명되지 않은 빈 공간 대신 기록된 간격
사이의 측정된 시간을 표시합니다. 완전한 시각이 있는 실행 활동은 연결된 범용
근거 가지를 대체하며 관찰된 라벨, 도구, 권한 및 상세를 유지합니다. Phase 묶음은
저채도 blue, 근거 작업은 green, 모델 작업은 plum, point-in-time 턴 기록은 neutral gray circle로
표시합니다. 입력 표시는 해당 턴에서 관측된 가장 이른 시각에 고정하고 최종 답변은
마지막 기록된 timing 완료보다 앞에 배치하지 않습니다. 따라서 브라우저와 서버의 시계
skew가 근거를 입력 앞에 두거나 세대와 검증을 전달 뒤에 두지 못합니다. 레인
기준선과 tick은 완료 진행 상황 bar와 구분됩니다.
답변 텍스트는 15 px을 사용하고 main 공개 높이는 44 px이며, 200% 텍스트 resize와 320 CSS pixel에서 내용 loss 없이 reflow합니다.
Trajectory heading은 13 px, 이벤트 라벨은 12 px, 간결한 trajectory 메타데이터는 11 px을 사용합니다.
최종 검증된 답변에 서버가 정확한 영어 또는 한국어 형식으로 렌더링한 recorded-agent-activity 블록이 있으면 해당 행을 하나의 간결한 버티컬 타임라인으로 표시합니다. 각 행은 에이전트, 정본 이벤트 토큰, 정확한 ISO 시각 및 로케일에 맞춘 읽기 쉬운 시간을 유지합니다. Malformed 또는 알 수 없는 산문은 관찰된 활동으로 승격하지 않고 일반 답변 내용으로 유지합니다.
게시된 화면 스냅샷은 5분 후 visibly stale 상태가 되고
명시적인 페이지 refresh를 제공합니다. Bare 시계는 현재 근거를 의미하지 않습니다. Markdown
표는 점진적으로 렌더링합니다. 완성된 헤더와 구분자가 첫 본문 행보다 먼저 표 shell을 만들고,
완성된 각 행은 표를 교체하지 않고 누적됩니다. 완성되지 않은 헤더, 구분자 및 행 구문은 raw
Markdown으로 표시하지 않습니다. 모든 범위가 제한된 답변 행은 대화 기록 흐름에 유지하며 내부 버티컬
scroll 지역이나 행 expansion 컨트롤을 사용하지 않습니다. Foreground의 terminal-only 결정론적
답변도 같은 visual 그리기 큐를 사용하므로 정본 표 행이 0건에서 전체 건수까지 단조롭게
증가합니다. Background tab은 동기적으로 완료합니다. Narrow 화면에서는 대화 기록 폭을 늘리지 않고
cell을 줄바꿈합니다.

상세 화면은 범위가 제한된 기록된 메타데이터를 표시하지만 답변 본문을 반복하지 않습니다. 펼친 각 타임라인
이벤트는 근거 요약과 참조, 계획 의도와 format, 답변 출처와 model-call 개수,
검증 권한과 검사 또는 모델 요청과 응답 메타데이터처럼 출처 기록에 있는
상세를 표시합니다. 적용 가능한 각 레인에는 recorded-payload 블록이 표시됩니다. 여기에는 운영자
입력, IQL 또는 명령과 관찰된 출력, AnswerPlan, 민감정보가 제거된 모델 요청과 응답,
검증 증적 및 최종 전달 증적이 포함됩니다. 해당 페이로드 타입이 없는 레인도 빈
패널 대신 상태, 시작, 완료 및 사용 가능한 사실을 표시합니다. 답변 레인은 전달
메타데이터를 기록하며 답변 본문을 반복하지 않습니다.
인벤토리 실행은 정본 턴 조회를 `IQL` 활동으로 표시합니다. 이어지는 별도 활동은 exact 범위가 제한된 Azure CLI 또는 ARG 증적을 같은 최종 icon으로 표시합니다. 인증된 구독 id,
범용 argv, 측정된 명령 소요 시간, 개수 및 허용 목록된 미리 보기 행 최대 10개는 표시하지만 페이지 나누기 토큰, 자격 증명,
raw 리소스 id 및 프로바이더 오류는 민감정보 제거합니다. IQL 출처와 결과는 각각 토글되며 행은 스냅샷 refresh를 설명하지만 명령 재실행을 주장하지 않습니다. 브라우저는 IQL 또는 출처 이름에서 명령을 파생하지 않습니다. 프로바이더 메시지, 액션 인자, 명령 및 출력의 유효한 객체 또는 array JSON은 indentation, 구문 highlighting 및
copy를 제공하며 malformed 또는 plain 텍스트는 변경하지 않습니다. Terminal-only visual 노출은 최대 30개 조각으로 제한하고 답변 레인은 그리기 완료가 아닌 서버 완료 시각을 사용하므로 표현 pacing을 실행 공백으로 표시하지 않습니다. 최종 재생 페이로드는 ID별 최종
가지, 활동, 이정표 및 민감정보가 제거된 실행 상세를 총 64 KiB 이하로 보존하고 이력 출력을
항목당 32 KiB에서 truncate하며 잘림 및 omission 개수를 표시합니다. 따라서 영속 이력과
실제 운영 턴이 같은 strict 파서 및 trajectory 화면을 사용합니다. 사용 불가 또는
시간이 초과된 근거는 시도이지 완료된 근거가 아니며 검증되지 않은 작업에는 완료 styling을 적용하지
않습니다. 누락된 활동은 관측 커버리지 공개에 두며 작업 부재를 증명하지 않습니다.
Exact-answer 영속 재생에는 같은 범위가 제한된 브라우저 파서를 사용합니다. 서버는 프로바이더의 최종 content-policy 결정이 확인될 때까지 모델 토큰을 buffering합니다. 블록은 부분 토큰 또는 assistant 답변을 노출하지 않고 내용이 없는 증적만 기록하며 SSE와 JSON `422`에 같은 결정론적 대체 경로를 사용하고, 로그에는 단계와 집계 개수만 남깁니다. 명시적인 프로바이더 거절, 잘린 완료, malformed 스트림 프레임 또는 검증된 최종 신호 없이 끝난 스트림은 assistant 답변이 되지 않습니다.

최종 timing은 최대 8개의 허용 목록에 있는 semantic-plan, 근거, 세대, quality-review 및
검증 phase를 포함합니다. 하나의 UTC anchor와 단조 증가 경과 시간으로 관측된 상태, 시작,
완료 및 소요 시간을 만듭니다. Interrupt는 timing을 저장하지 않고 strict 파서는 불일치를 거부합니다.

모델 프로바이더 tracing은 기본값이 꺼진 browser-local Settings 명시적 선택입니다. 활성화하면 request-local
수집기가 턴 계획 수립, rerun, 답변 세대 및 quality 검토를 포함하여 해당 질문의 실제 모델
호출을 최대 8개 기록합니다. Waterfall은 provider-call timing을 사용합니다. 기록된 호출이 0건이면
결정론적 경로에서 프로바이더 레인이 필요하지 않았음을 Waterfall 안에 표시합니다. Trace가 캡처되지
않은 턴은 명시적인 사용 불가 상태를 표시합니다. 캡처 설정이 꺼져 있어도 패널은 Settings 명시적 선택
안내와 함께 표시하지만 저장된 trace 데이터는 계속 숨깁니다. 각 공개는 역할 순서의
기록된 메시지 array와 요청 SHA를 보존하면서 연속 system 계층을 하나의 `SYSTEM` heading으로 묶습니다.
JSON 본문은 pretty-print하고 범위가 제한된 요청 및 응답 블록에는 테마에 맞는 scrollbar를 적용합니다. 공개는 assistant 내용, 토큰 사용량, exact-content SHA-256 및 민감정보 제거 개수도 표시합니다. 자격 증명, 테넌트 또는 리소스 식별자, URL, 이메일, IP 주소, inline 이미지,
hidden reasoning, 헤더 및 프로바이더 내부 정보는 저장하지 않습니다. 설정을 끄면 캡처를 중지하고
저장된 trace 데이터를 숨기며 프로바이더 호출을 반복하지 않고 멱등적 재생 응답에서 trace를 제거합니다.

이 principal 범위로 한정된 화면은 authorization-first offline 검토 산출물인
[관리형 trajectory 데이터셋](governed-trajectory-datasets-ko.md)과 구분됩니다. Hidden reasoning, raw
unredacted 프롬프트, 자격 증명, unrestricted 페이로드 및 해당 턴에 기록되지 않은 데이터는 표시하지 않습니다.

## 영속 요청 재생

완료된 요청은 principal, 대화, 멱등성 키 및 요청 내용이 모두 일치할 때만
재생됩니다. 저장된 최종 assistant 페이로드를 반환하며 근거 수집, 서술 또는
post-turn 검토를 반복하지 않습니다. 같은 키에 다른 내용나 대화가 들어오면
conflict입니다. JSON, SSE 및 cross-transport 재시도는 같은 최종 페이로드를 사용합니다.
Content-policy 증적에도 같은 신원 검사를 적용합니다. 일치하는 재시도는 선호 설정 해석,
문서 수집, 이력 compaction, 계획 수립 또는 프로바이더 작업 전에 정책 결과를 재생합니다.
같은 요청 키에서 프롬프트 또는 대화가 바뀌면 conflict입니다.

선택적 인시던트 대화 연결은 범위가 제한된 인시던트 id, 상관관계 id 및 허용 목록에 있는
Pantheon 에이전트를 전달합니다. 브라우저와 서버는 같은 한계를 강제합니다. 잘못 저장된 연결은
대화를 삭제하지 않고 폐기합니다. 에이전트 활동은 범위가 제한된 historical 감사 근거를
설명하며 활동 부재가 에이전트의 현재 작업 부재를 증명하지 않습니다.
새 일시적인 대화는 첫 운영자 턴이 서버 기록을 만들기 전에 영속 이력을
조회하지 않으므로, 정상적인 first-open 상태를 missing-history 오류로 보고하지 않습니다.

## 검증된 근거

Read-source 출처 이력, 온톨로지 browse, 화면 간 operational 및 인벤토리 답변은 타입이 지정된
근거에서 결정론적으로 렌더링됩니다. 온톨로지 browse는 대상과 browse verb를 요구하고,
허용 목록에 있는 신원 필드와 256자 이하 프롬프트 값만 전달하며, 중복되거나 malformed인 개수와
선택을 사용 불가로 표시합니다. 온톨로지 변환 결과와 결정론적 browse 답변은 일반 프롬프트
assembly와 분리된 자체 프롬프트 모듈에 위치합니다.
Reader-gated `/ontology/graph` 변환 결과는 스키마 버전, 변환 결과 개정, 릴리스 다이제스트,
선언 기록, 의미 맵 프로필 및 카탈로그 토폴로지를 포함하는 하나의 exact 카탈로그 릴리스를
제공합니다. 배포 인스턴스 속성은 반환하지 않습니다. 런타임 객체와 상태 사실은 기준 시각,
freshness, 완전성, 충돌, 잘림 및 근거 참조를 보존하는 별도 권한 확인 컨텍스트 스냅샷을
통해서만 Console에 들어옵니다.
일반 delegated 답변은 Bragi를 서술기로 유지하면서 검증된 specialist를 응답 소유자로
표시합니다. Dedicated 대상 세션은 명시적 인계가 서술을 Bragi로 돌려보낼 때까지 해당
specialist의 검증된 voice를 사용합니다.
Agent-targeted Web 턴은 첫 provisional 토큰부터 선택한 specialist를 표시하고 최종 위임이
소유자를 확인하거나 인계를 표시할 때까지 라벨을 안정적으로 유지합니다.
명시적 인계로 턴이 Bragi에 돌아오면 Web은 회신 헤더와 answer-plan 행에
`specialist -> Bragi`로 소유권 흐름을 표시합니다. 인계에 specialist 답변이 없으면 결정론적
검증은 근거를 사용할 수 없다는 응답을 반환하고, 관련 없는 current-screen 사실로 서술기
문장을 검증하지 않습니다.
선택한 에이전트와 서버가 소유한 operational 근거가 모두 해석되면 조정기는 둘 다 유지하며,
인시던트 요약, absence 점유 및 cause는 계속 결정론적 검증이 소유합니다.
Bragi가 T0/T1 소유자 경로를 한 번 완료한 뒤, 일반 답변 경로는 그 소유자에서 점수가 유일하게
가장 높은 읽기 도구 하나를 선택합니다. 완료된 도구 결과가 기본 specialist 답변이 되고,
범위 한정 사실은 기존 agent-evidence 매니페스트로 들어갑니다. 동점이거나 일치 항목이 없으면 소유자의
일반 응답을 유지합니다. 선택된 읽기가 abstain, 시간 초과, 민감도 보류 또는 부분 완료
상태이면 범용 또는 기여자 대체 경로 없이 명시적으로 인계합니다. 계획 수립과 전달은
깊이 1단계를 유지하며 하나의 범위가 제한된 gather 예산을 공유합니다. 이 일반 경로는 lexical이며 에이전트
경로에 임베딩 호출을 추가하지 않습니다.
어떤 에이전트도 소유하지 않는 질문은 tool-answer 경로에 들어가지 않습니다.
Charter 버전, 해시 및 도구 id는 hidden 출처 이력으로 유지합니다. Exact 정책 일치일 때 모델은
Bragi global 안전성 프롬프트 뒤에서 서버가 소유한 charter를 받으며, charter는 역할과 voice를 제한하지만
근거 또는 권한이 되지 않습니다. 런타임 grounding은 제공된
근거 참조 또는 정규화된 에이전트 사실의 내용 기반 주소를 가진 해시를 사용하며 static 에이전트 spec을 사용하지 않습니다.
에이전트 서술 자체는 근거 출처가 아닙니다. Atomic 점유는 별도로 귀속된 기여자
사실을 포함한 에이전트 사실 leaf를 런타임 제공 참조에 rooted된 고유 JSON 포인터에 연결합니다.

인시던트 title도 서버 소유 근거입니다. 읽기 변환 결과는 기록된 title, 요약 또는 룰
필드를 우선 사용한 뒤 길이가 제한된 신호 및 리소스 상관관계 키를 사용합니다. 빈 값,
`None`, `null` 상관관계 표시는 결측으로 처리하며 브라우저는 인시던트 대상을 만들지 않습니다.

선택한 인시던트 상세 화면은 수명 주기 요약과 불러온 감사 이력에서만 파생한 운영자용 현재
상황을 가장 먼저 표시합니다. Raw `pending`, `unknown`, `shadow` 값을 하나의 상태처럼 보여주지 않고
수명 주기 상태, 응답 결정, 변경 권한 및 운영자 attention을 분리합니다. 활성 인시던트에
notification-delivery 에스컬레이션이 있으면 이를 우선 표시하고 필요한 후속 작업을 설명합니다. 기록이
있으면 감사 및 technical 활동을 사용할 수 있습니다. Root-cause analysis와 dossier는 `rca.*`
기록이 생긴 뒤에만 링크가 되며, 그 전에는 근거가 있는 가설이 기록되지 않았다고 표시합니다. RCA
경로도 가설이 없으면 범용 감사 대체 경로 응답을 숨겨 `incident.members`를 응답 계획
또는 cause로 표시하지 않습니다. Trace 경로는 raw ordered 표보다 먼저 notification 에스컬레이션,
response-decision 근거, RCA 근거 및 named 파이프라인 단계를 분리한 interpretation 요약을
표시합니다. 범용 correlated 활동은 cause 점유가 아니라 technical 이력으로 유지합니다.

Operational 근거는 `matched`, `summary`, `ambiguous`, `none`, `unavailable` 중 하나입니다.
Collection 요약 요청에서 `summary`는 인시던트 하나를 선택하도록 요구하지 않고 범위가 제한된 matching
집합을 즉시 렌더링합니다. 모델 산문은 선택된 인시던트, 검색 범위, 지원되는 cause, collection
구성원 또는 absence 점유를 바꿀 수 없습니다.
`availability=unavailable`인 출처는 `reachable=true`를 보고하지 않으며 구성되지 않았거나 탐색하지
않은 출처는 `reachable=null`을 사용합니다. 명시적인 latest-incident 요약은 collection을 반환하지 않고 서버 읽기 모델에서 가장 최근 인시던트 하나를 선택합니다. 루트 cause, 타임라인, 가설, similar 인시던트, 영향, next 액션, consumed 근거, uncertainty 및 deep 조사 질문에는 인시던트 하나가 필요합니다. 한계 인시던트가 없으면 범용 analysis 표현은 운영자가 선택할 범위가 제한된 후보를 반환하며 current-screen, 저장소, 에이전트 또는 공개 웹 근거를 빌리지 않습니다.
`ambiguous` 최종 답변은 최대 5개의 server-validated 인시던트 후보를 포함한 versioned
산출물도 전달합니다. Web 클라이언트는 후보별로 title, 심각도, 상태, last-updated 시간 및
인시던트 id가 표시된 버튼을 렌더링하므로 중복 title도 구분할 수 있습니다. 버튼을 선택하면
exact incident-bound 대화를 열고 localized 읽기 전용 조사 질문을 즉시
제출합니다. 명시적인 click이 운영자 요청이며 managed 리소스를 변경하지 않습니다. 누락되거나
malformed, oversized 또는 검증되지 않은인 후보 산출물은 버튼을 렌더링하지 않으며 연결을
만들 수 없습니다.
`latest`, `recent`, `최신` 같은 범용 recency 단어만으로는 인시던트 권한을 만들지 않습니다.
Operational 조회에는 인시던트, issue, 장애, 실패, problem 또는 cause 의미가 명시적으로 함께
있어야 합니다. 따라서 공개 software 버전 또는 release 질문은 결정론적 "no matching 인시던트"
답변 대신 범위가 제한된 공개 웹 경로 대상으로 유지됩니다.
Current-screen 데이터 범위는 인벤토리, 인시던트, 에이전트 및 web enrichment보다 우선합니다. Topology, 종단 간 도달 가능성, 인바운드 네트워크 정책, 피어링 및 실패 impact-scope 질문에는 exact 출처/대상 리소스 이름 또는 server-validated 선택된 네트워크 리소스 하나가 필요합니다. Context-free 참조는 인벤토리 프로바이더 실행 전에 결정론적 명확화를 반환합니다. Current-screen 링크, resource-group 구성원 또는 인시던트 근거는 connectivity나 영향 범위의 근거가 되지 않습니다. Trace
상관관계는 질문에 인시던트, 실패, problem 또는 cause 의미가 명시된 경우에만 인시던트 선택
힌트로 사용하며 일반 단계 및 행위자 필드는 화면 사실로 유지합니다.
지원되는 current-screen 값과 명시적 absence 답변은 모델 호출 없이 Bragi T0가 렌더링합니다.
명시적으로 빈 사실 또는 records 변환 결과는 화면 커버리지 근거이며 모델 기억 대체 경로
권한이 아닙니다. 이 답변도 최종이 되기 전에 atomic-claim 검증기를 통과합니다.
Current-time 질문은 injected timezone-aware 서버 시계와 principal의 IANA timezone 선호 설정을
사용합니다. 최종 답변은 exact 시각과 timezone으로 결정론적으로 렌더링합니다. 선호 설정이
없으면 명시적으로 표시한 UTC로 대체 경로하며 서술기와 브라우저 시계는 시간 권한이 아닙니다.

예측 Learning 경로는 서버가 소유한 PostgreSQL 변환 결과만 읽습니다. Closure 완전성은
due episode를 denominator로 사용하고 게시 상태는 미래 scheduled 작업을 due debt, 실패한
시도 및 dead letter와 구분합니다. 집단이 없으면 0이 아니라 사용 불가로 표시하며 브라우저는
관련 없는 개수에서 모델 miss, 파이프라인 miss 또는 보존 상태를 도출하지 않습니다.

Trace 경로는 오류 렌더링 중에도 `correlation_id`, `load_status` 및 값이 있을 때 actionable
`load_error`를 게시합니다. 서버는 이 상관관계를 선택 힌트로만 사용하고 operational
근거를 반환하기 전에 권한이 적용된 읽기 모델에서 다시 확인합니다.
Trace는 연관된 감사 행을 순서대로 유지하고 파이프라인 단계가 없는 활동을 `stage: null`로
표현하며 마지막으로 이름이 기록된 단계에서 `terminal_stage`를 도출합니다.
인용이 있는 근거에 기반한 RCA가 없으면 결정론적 검증은 영속 `incident.open` 기록의
범위가 제한된 detection 사실을 먼저 렌더링합니다. 여기에는 신호, 대상 리소스 및 연관된 member-event
개수가 포함됩니다. 이 사실은 관찰된 상태를 확인하지만 원인을 증명하지 않습니다. 워크로드 실패
사유는 별도 섹션에 유지합니다. `notification.*` 실패는 notification 전달 아래에만 표시하며
워크로드 실패 또는 root-cause 근거가 되지 않습니다. Notification이 주제인 인시던트는 전달
실패를 먼저 표시할 수 있습니다. 모든 경로는 기록된 실패를 완전한 root-cause 결론이 아니라
관측으로 표시합니다.

각 매니페스트 경로에는 소유자가 하나만 있습니다. SPA는 조회와 fragment를 제거하고 path-segment
경계에서 exact 경로 또는 descendant를 일치한 뒤 가장 긴 소유자를 선택합니다. 비슷한 접두사는
소유권을 상속하지 않습니다. Owned 경로가 매니페스트에 하나라도 없으면 패널은 `unknown`이고,
명시적으로 source-independent인 패널만 출처 상태를 생략합니다.

운영 Operator API는 `GET /stewardship`을 등록하기 전에 operational 소유권 지도를 부하하고
validate합니다. Console은 이 출처를 읽기 전용으로 변환 결과합니다. 인계 양식은 구조화된
person 또는 그룹 배정을 별도 인제스트 경계에 제출할 수 있지만 지도를 적용하거나 Git
자격 증명을 보유할 수 없습니다. 초안 PR 생성과 signed 병합 처리는 인제스트/GitOps
경계에 유지되며 반환된 초안에는 저장된 멱등적 PR 증적이 포함됩니다.
브라우저는 증적 URL이 embedded 자격 증명 없는 absolute HTTPS URL일 때만 링크로 렌더링하며,
그 외에는 PR 참조를 클릭할 수 없는 텍스트로 표시합니다.
내용 업로드는 same-origin 인제스트 proxy 대상에만 API bearer 토큰을 유지합니다.
Cross-origin direct-upload 대상에는 내용 헤더를 보내지만 Operator API 자격 증명은 전달하지
않습니다.

## 점진적 병렬 대화

가지 수명 주기, ordered reduction, confirmed 개정 번호, 취소, 재생 및 메트릭은
[Operator Console Progressive Conversations](operator-console-progressive-conversations-ko.md)가 소유합니다.

## 스트림 복구 및 authentication

인증된 실제 운영, 에이전트 및 프로비저닝 SSE 읽기 담당은 keepalive comment를 포함해 45초 동안 바이트가 없으면
취소하고 범위가 제한된 reconnect를 사용합니다. 프로비저닝은 이벤트 전달 실패 시 읽기 담당도 취소합니다.
에이전트 스트림의 `401`은 전체 화면 login 복구를 기다리고, `403`은 새 App 역할을 페이지 reload 없이
반영할 수 있도록 reconnect합니다.

Command Deck 조사 활동에는 선택적인 관찰된 실행 근거가 포함될 수 있습니다. 서버는 발행 전에 자격 증명과 민감한 식별자를 제거하고 `redacted=true`를 설정하며, 브라우저는 이 확인이
없는 입력 근거를 폐기합니다. `input_kind=command`는 기록된 프로세스 호출이 필요하며 exit
코드를 포함할 수 있습니다. `input_kind=query`는 정본 타입이 지정된 서버 조회를 전달하고 reconstructed
프로바이더 명령을 만들지 않으며 exit 코드를 포함할 수 없습니다. 허용된 활동은 일치하는 `TOOL`
또는 `QUERY` 배지, 도구 라벨, 권한 및 완료 상태를 표시합니다. Command 출력, 조회 결과 및 시각은 기본적으로 접힌 상태를 유지합니다. 유효한 객체 또는 array JSON은 테마에 맞는 scrollbar가 적용된 범위가 제한된 고정된 어두운 코드 표면에서 pretty-print됩니다.
인벤토리 결과는 일치한 리소스, 개수, 커버리지 및 스냅샷 출처 이력을 포함하는 verifier-accepted detailed 변환 결과를 유지합니다. 입력은 16 KiB, 결과 미리 보기는 64 KiB로 제한됩니다. 크기를 초과하는 collection tail은 omission 개수와 함께 제거해 출력을 유효한 JSON으로 유지합니다. 활동 및 수집 라벨은 512자, 상세 및 이정표 텍스트는 16 KiB로 제한되며
completed/합계 진행 상황이 모순되면 거부합니다. 브라우저는
표시된 명령 또는 조회를 복사할 수 있지만 실행하거나 다시 시도할 수 없습니다. 이 근거는 권한 있는
런타임이 수행한 작업을 읽기 전용으로 관찰한 것이며, 콘솔이 실행기 신원 또는 임시 권한을
보유한다는 증거가 아닙니다.

Command Deck의 web research 턴은 작업 진행 중 실제 상태를 나타내는 `status` 프레임을 스트림합니다.
서버는 semantic 검색 의도가 서술기 모델을 호출할 때만 `web_search_classifying`을 발행하고,
공개 웹 프로바이더 호출 직전에만 `web_search_searching`을 발행하며, 수집 후에는 정제된 출처
수와 미리 보기를 포함한 `web_search_grounded`를 발행합니다. 답변 준비 trace는 이 단계를 즉시
렌더링합니다. 실행하지 않은 단계는 해당 턴의 진행 상태로 표시하지 않습니다.

완료된 각 model-backed 턴은 선택된 모델과 해당 턴의 기록된 메타데이터로 확인되는 단계인 근거
수집, 모델 reasoning, specialist consultation, 근거 연결 및 검증을 LLM 에스컬레이션
공개에 계속 표시합니다. 새 인용이 없는 후속 조치 턴도 모델 reasoning 단계를 표시하고
별도 출처가 첨부되지 않았음을 명시합니다. 이전 인용을 새로 조회한 것처럼 재사용하지 않습니다.
근거 값과 경로는 잘리지 않고 줄바꿈되며, 출처 상세는 별도로 펼쳐 확인할 수 있습니다. 완료된
검증 단계는 검사가 수행되었음을 나타내며, 검증되지 않은 결과는 성공 검사 대신 attention mark를
사용합니다.

완료된 결정론적 턴은 LLM 라벨 없이 동일한 처리 공개를 사용합니다. 공개는
결정론적 응답기를 식별하고 사용할 수 없는 백엔드 또는 content-policy 블록 같은 기록된 대체 경로
사유를 유지하므로 모델 장애가 공개되지 않은 모델 응답처럼 보이지 않습니다.

브라우저는 기록된 모델 식별자와 선택적 지연 시간 또는 토큰 메트릭이 범위가 제한된 source-descriptor
계약과 일치할 때만 LLM 공개를 표시합니다. 빈, oversized, control-character,
duplicate-metric 및 free-form 메트릭 값은 LLM 에스컬레이션 점유를 만들지 않습니다. Raw 출처
배지는 너비가 제한되므로 malformed 메타데이터가 회신 헤더를 밀어내지 않습니다. 브라우저가 토큰
사용량을 표시하려면 토큰 합계와 프롬프트 및 완료 컴포넌트가 각각 finite nonnegative 값여야
합니다.

검증 메타데이터는 검사 counter가 nonnegative integer이고 completed 검사가 합계 검사보다
크지 않을 때만 허용됩니다. Atomic 점유 구간은 순서가 맞는 nonnegative integer이고 매니페스트 스키마
버전 1을 명시하며 점유, failed-claim 및 used-evidence 참조에는 중복 또는 dangling
식별자가 없어야 합니다. `unverified`가 아닌 최종 상태는 선언된 검사를 모두 완료하며,
부분 근거는 표시하되 최종 검증은 `unverified`로 유지합니다. 잘못된 조합은
검증되지 않은 malformed 산출물이 됩니다. Failed-claim 식별자는 지원하지 않는 또는 모호한 점유와
정확히 일치하며 매니페스트는 검증 묶음과 동일한 권한을 사용합니다.
브라우저는 생산자 상한인 점유 64개, 근거 항목 512개 및 추가 문서 참조 8개를 동일하게
적용합니다. 산출물 식별자는 1 KiB, rendered 값은 16 KiB, anchor 또는 별칭 목록은 64개로
제한됩니다. 실제 운영 회신과 세션 재생은 동일한 파서를 사용하므로 reload 후 HTTP 경계가
거부할 메타데이터를 복원하거나 다르게 해석하지 않습니다.

세션 재생은 4 MiB JSON 묶음 안에 최신 턴을 최대 40개 유지합니다. Turn 하나에는 텍스트
256 KiB, 범위가 제한된 인용 512개, 범위가 제한된 후속 조치 8개 및 범위가 제한된 활동 기록 64개까지 포함할 수
있습니다. 직렬화가 묶음을 초과하면 브라우저는 가장 오래된 턴부터 제거합니다. Oversized
또는 내부 정합성이 없는 선택적 collection은 렌더러로 복원하지 않습니다. Answer-plan 섹션 및
재정의 라벨은 64자와 128자, 코드 검증 상세는 4 KiB, 이정표 에이전트 신원은 64자로
제한합니다.

Web 작성기는 선택, 폐기 및 clipboard paste raster를 동일한 범위가 제한된 첨부 tray와 검증 경로로 전달합니다. 단계 전에 브라우저는 upscaling 없이 longest 간선을 2048 px 안에 맞추고 이미지당 4 MiB 아래로 re-encode합니다. Clipboard 텍스트와 HTML은 textarea의 native paste 동작을 유지하며 첨부가 되지 않습니다.
Turn이 검증된 inline 이미지 첨부를 carry하면 스트리밍 경로는 서술기가 작성하기 전에 읽기 전용 `vision_analyzing`을, 답변 전에 `vision_grounded`를 발행하며, 각 프레임은 이미지 출처 미리 보기(이름, media 타입, 크기)를 포함하되 base64 페이로드는 절대 포함하지 않습니다.
해당 턴은 vision 지원 서술기로 escalate되고, 답변 준비 trace는 이 단계를 웹 검색 grounding과 동일하게 렌더링합니다.

Interactive 실제 운영 경로는 tab이 hidden 상태일 때 SSE 읽기 담당을 pause합니다. Shell의 인시던트,
액세스 권한 및 Operator가 활성화한 브라우저 notification 소비자는 Web Locks를 사용해 same-origin 탭의
각 채널에서 principal 범위로 한정된 읽기 담당 하나를 선출합니다. 인시던트 및 액세스 권한 leader는
검증된 스냅샷을 `BroadcastChannel`을 통해 follower 탭으로 보내므로 각 shell은 중복 SSE 연결을 열지
않고 attention 상태를 유지합니다. Notification leader는 background에서 인증된 실제 운영 읽기 담당을
유지합니다. 이 고정 연결 예산은 HTTP/1.1에서 일반 Operator API 요청에 필요한 용량을 남깁니다.
Notification leader는 기존 capped 재시도 대기로 authentication 실패를 재시도하며, notification 권한
또는 principal 범위로 한정된 명시적 선택이 제거되면 즉시 중지합니다. 재생이 아닌 프레임의 사람 승인,
거부, 실패 결과만 발행합니다. Shared 브라우저 원장은 여러 tab에서 같은 이벤트 tag를 5분 동안 억제하고
system notification 전달을 분당 5건으로 제한하지만 감사 또는 인시던트 근거는 제거하지 않습니다.

에이전트 활동 경로는 shared 에이전트 스트림을 열기 전에 범위가 제한된 영속 인벤토리 검사,
온톨로지 변환 및 현재 상태 읽기 기록을 불러옵니다. 정확한 activity id로 재생과 실제 운영 전달을
중복 제거합니다. Journal은 routine 작업 유형을 별도 필터 lane에 유지하고 인시던트로 만들지 않습니다.
Health-derived `agent.runtime-state` 하트비트는 현재 관찰을 증명하지만 작업이 아닙니다. 누락,
malformed, 미래 또는 권한을 가진 프레임은 선언된 연결을 관찰 상태로 승격하지 않습니다. 각 Operator
API 복제본은 instance-scoped 소비자 그룹을 사용하므로 모든 Console이 완전한 하트비트 집합을
수신합니다. Give up 또는 halt된 소비자는 형제를 유지한 채 health-derived 하트비트에서 빠지고 Saga
또는 Vidar 실패는 sticky shadow를 계속 강제합니다. 이 기록은 액션 감사 근거의 복사본이 아닌 운영
활동입니다.

Command Deck은 완전한 또는 pending SSE 프레임이 256 KiB를 넘으면 `data:` 줄 누적이나 JSON parse
전에 거부하고 결정론적 interrupted-stream 대체 경로를 사용합니다. Correlation-filtered 액션
진행 상황은 최종 감사 프레임을 완료로 처리하고 120초 기한을 시간 초과로 보고하며, 그 밖의
authentication 또는 전송 계층 실패는 전달합니다. 조사 행은 pending에서 running을 거쳐
최종 상태 하나로 진행합니다. Stale backward 프레임과 최종 replacement는 무시하므로 completed,
실패한 또는 사용 불가 연산이 spinner로 돌아가지 않습니다.

Console 데이터를 열기 전에 초기화는 인증된 `GET /iam/self`로 principal을 확인합니다. 전송 계층
실패는 데이터를 닫힌 상태로 유지하고 access-check 재시도 및 sign-in을 제공합니다. Operator API가
unreachable일 때 redirect 루프가 생기므로 자동 redirect는 시작하지 않습니다.

## 아키텍처 지도 복원력

아키텍처 경로는 지도 오른쪽 위에 떠 있는 간결한 패널에 범위 선택만 배치합니다. 인벤토리
개수, 설명문 및 계층 필터는 표시하지 않습니다. 잘린 그래프는 짧은 상태 배지 하나로
알립니다. Resource-color legend는 floating 또는 bottom 패널이 아니라 구독 경계 옆 세계
하한에 직접 그립니다. Camera fit은 범례가 들어갈 하한 공간을 예약합니다. 고정된 legend box, title
또는 color swatch 없이 리소스 타입 이름을 해당 하한에 직접 표시합니다. 타입 이름은 pan과 함께
이동하고 읽을 수 있는 범위 안에서 지도 zoom에 비례해 조정됩니다.
Resource glyph는 Microsoft Cloud Adoption Framework의
[Azure 리소스 abbreviations](https://learn.microsoft.com/azure/cloud-adoption-framework/ready/azure-best-practices/resource-abbreviations)를
사용합니다. 알려진 모든 정본 타입은 명시적인 lowercase abbreviation을 가집니다. 일대일 CAF
항목이 없는 abstract 타입은 자동 initialism 대신 문서화된 고정된 확장을 사용합니다.
관계 legend는 간결한 캔버스 컨트롤로 유지합니다. 기본 isometric 지도는 Reflections와
Connections가 활성화된 상태로 시작합니다. Containment는 흐린 dashed 링크로,
첨부 및 의존성은 각각의 directional style로 표시하고 리소스 형태를 렌더링합니다.
Top 및 front 화면은 선택적입니다. 단순 변환 결과는 선택된 단일 범위를 포함한 모든
resource-group 패널의 크기를 관찰된 하위 수에 따라 정하고 균형 잡힌 세계에 패널을 배치합니다.
Focused 서비스 및 resource-group 화면은 full 구독 프레임이 아니라 repacked 내용에
맞춰 표시합니다. Resource 노드는 표준 Event Grid 토픽
블록보다 작게 렌더링되지 않습니다. 인벤토리에 맞춰 세계와 캔버스가 커지며 authored 중첩된
배치는 supplied 형상을 유지합니다. 지도는 workspace 전체 너비를 사용하고 점검 상세는
아래에 배치합니다. 좁은 뷰포트에서는 box를 읽을 수 없게 줄이는 대신 노드 크기를 유지하고 지도
panning을 사용합니다. 선택은 인벤토리를 reload하지 않고 정본 deep 링크를 갱신하며
technical 식별자보다 directional 관계를 먼저 표시합니다. 선택 중에는 모든 공통
리소스 coordinate를 유지하면서 auxiliary neighbor만 표시합니다. 관련 없는 리소스는 흐리게
처리하지 않으며 선택된 outline과 점검 상세만 사용해 선택을 나타냅니다. Virtual
머신을 포함한 모든 리소스 선택은 현재 camera 규모와 position을 유지합니다. Zoom, fit,
pan 및 camera-view 컨트롤은 운영자가 명시적으로 조작할 때만 변경됩니다.

Factual 개수와 점검 인덱스는 계속 완전한 권위 있는 인벤토리를 사용합니다. Isometric
개요는 네트워크 인터페이스와 managed disk를 표시하고 진단, certificate 및 프로바이더 보조 로직
리소스를 접는 presentation-only 변환 결과를 적용합니다. 표시된 각 소유자는 접힌 neighbor
수에 해당하는 `+N` 배지를 표시합니다. Resource를 선택하면 새 인벤토리를 요청하거나 만들어 내지
않고 direct auxiliary 하위와 semantic neighbor를 표시합니다. 개요는 표시된 리소스만 packing하고
하위를 계층 및 타입 순서로 정렬하며 접힌 소유자 옆에 최대 두 개의 satellite 자리를 예약합니다. 큰
resource-group 패널을 wide 행에 먼저 배치하므로 숨겨진 auxiliary가 빈 grid hole을 만들거나 세계를
부풀리지 않습니다. Virtual Network와 subnet은 낮은 하한
레인으로 렌더링하므로 compute, 데이터 및 게이트웨이 노드를 네트워크 plane 위에서 읽을 수 있습니다. 하한
레인은 reflection을 렌더링하지 않습니다. Azure 인벤토리는 VNet 페이로드 안에서 관찰된 subnet만
`network.subnet` 기록으로 승격하고 관찰된 VNet-to-subnet containment 간선을 생성합니다. Console은
등록된 `attached_to` 링크가 범위가 제한된 resource-to-interface-to-subnet 체인 안에서 하나의 subnet에만
도달하거나 disk가 범위가 제한된 disk-to-workload-to-interface-to-subnet 체인으로 도달할 때 리소스를 해당
subnet에 배치합니다. 구성원이 없거나 모호하면 resource-group의 neutral
하한에 유지하며 이름과 프로바이더 식별자를 topology 근거로 사용하지 않습니다.

Isometric 렌더러는 VNet을 outer 하한으로, subnet을 visible 구성원 수에 따라 크기가 정해지는 inset
하한 plane으로 그립니다. Evidence-derived 구성원 rail과 direct `attached_to` 링크는 하한에
유지하고 `depends_on` arrow는 리소스 top 위에 유지합니다. Plane 이름은 floating 라벨 카드 없이
세계 축을 따릅니다. Plane을 선택하면 동일한 리소스 inspector를 사용하며 가장 작은 containing
plane이 포인터 대상으로 유지됩니다. Focused 서비스 또는 resource-group 화면은 공간이 허용될 때
3개의 네트워크 하한을 한 행에 배치하는 wide packing 대상을 사용합니다. 완전한 인벤토리 화면보다
작은 desktop legend reserve와 캔버스 높이를 사용합니다. 좁은 뷰포트에서는 동일한 노드 크기를
유지하고 캔버스를 520 px로 제한하며 더 넓어진 하한을 panning으로 탐색합니다.

Subnet 안의 visible 경로 participant는 관찰된 `attached_to` connected 컴포넌트별로 묶은 다음 네트워크
간선에서 저장소 순서로 배치합니다. 공개 IP 및 네트워크 security 리소스, 네트워크 인터페이스,
compute 및 서비스 리소스, disk 및 데이터 리소스 순서입니다. 여러 워크로드 경로는 타입 또는 이름으로
서로 섞이지 않고 연속으로 유지됩니다. 이는 배치 순서이며 추론한 트래픽 direction이 아닙니다.
각 컴포넌트는 독립적인 depth-oriented 레인을 사용합니다. 공개 IP는 camera에 가장 가깝고 security,
인터페이스, 워크로드 및 저장소 단계가 순서대로 뒤로 물러납니다. 렌더러는 겹치는 intra-subnet 간선을
하나의 shared 하한 spine과 짧은 단계 가지로 대체하며 cross-plane 첨부만 direct 경로를
유지합니다. 워크로드는 supporting 네트워크 리소스보다 크게 렌더링됩니다. 경로 리소스는 기본적으로
glyph를 사용하고 워크로드는 기본 라벨을 유지하며 어떤 리소스든 선택하면 full 이름과 타입을
복원합니다. 읽을 수 있는 라벨 임계값보다 낮은 dense 개요 규모에서는 선택하지 않은 노드 이름과
subnet 이름이 glyph, VNet 이름, 지역 이름 및 하한 legend에 자리를 양보하며 focused 화면은 일반
워크로드 및 subnet 라벨 정책을 복원합니다. Perspective는 범위가 제한된 깊이
범위에서 projected 지점을 조정해 가까운 리소스를 먼 리소스보다 크게 표시하고 picking과
containment도 동일한 변환 결과를 사용합니다. Zoom은 512x 규모까지 상세 탐색을 지원하고 포인터를
중심으로 확대하며, content-driven 세계는 고정 canvas-height 상한 없이 확장됩니다. Fit은 완전한
프레임을 복원하는 명시적 컨트롤로 유지됩니다. 기본 isometric camera는 경로 레인을 좌우로 읽고 깊이가
뒤로 물러나도록 낮은 oblique angle을 사용합니다. Fit은 간결한 세계 위쪽에 visual 깊이를 남기기
위해 화면 중심보다 약간 아래에 배치합니다. Content-driven 캔버스가 projected 세계보다 크게 높은
경우에는 세계를 접기 아래에 중앙 정렬하지 않고 첫 visible 프레임에 upper 한계를 고정합니다.
왼쪽 버튼 끌기는 projected 세계를 pan합니다. 가운데 버튼 끌기는 정규화된 continuous yaw로
세계 center 주위에서 camera를 좌우로 orbit하며 세로 이동은 pitch를 변경하지 않습니다. 오른쪽 버튼은
브라우저 행동을 유지합니다. Orbit 입력은 동일한 animation-frame coalescing을 사용하고 라벨만
지연하며 하한, 경로 및 reflection은 계속 표시합니다.

라벨은 충돌을 피하고 긴 이름을 맞추며 각 리소스 이름과 읽기 쉬운 리소스 타입을 함께
표시합니다. 블록의 간결한 acronym은 보조 cue이며 리소스를 식별하는 유일한 방법이 아닙니다.
라벨은 zoom에 따라 13 px에서 20 px까지 커지고 선택된 라벨은 22 px까지 커질 수 있습니다. Zoom
단계는 reciprocal이고 색상은 콘솔 테마를 따르며, keyboard-accessible 리소스 및 관계
인덱스는 filtered 캔버스와 동등합니다. 포인터 대상은 containment 경계를 포함해 최소 44 px입니다.
선택된 라벨은 마지막 캔버스 overlay이므로 블록 glyph, 관계 또는 인접 라벨이 가릴 수
없습니다. 잘린 스냅샷은 partial-inventory notice를 명시합니다.
캔버스는 containment를 subdued dashed center-to-center 간선으로 렌더링합니다. Semantic 관계는
연결된 블록 top보다 높은 directional node-to-node arrow를 사용하며 resource-group 지역을 operational
엔드포인트로 연결하지 않습니다. 끌기 입력은 animation 프레임마다 한 번만 draw하고 포인터가 이동하는
동안에도 reflection을 계속 표시하며 라벨만 생략합니다. 포인터 release는 라벨을 복원합니다.
로컬 변환 결과는 선택된 엔드포인트 id와 리소스 타입이 일치하는 등록된 관계 타입만
표시합니다. Malformed 또는 over-limit 벤더 관계는 폐기하고 스냅샷을 잘린으로 표시하며,
신뢰할 수 없는 간선을 렌더링하지 않고 마지막 완전한 리소스 그래프를 유지합니다.

Subscription-scoped cached 스냅샷은 즉시 렌더링됩니다. 만료된 또는 change-invalidated 스냅샷은
background refresh 동안 stale로 표시됩니다. 브라우저는 Operator API가 완료된 refresh를 원자적으로
promote할 때까지만 polling하고 서버 최신성 판정을 높이지 않으며, stale 그래프를 유지한 채
transient 실패를 범위가 제한된 2-30초 재시도 대기로 재시도합니다.

## 검증

- 카탈로그 동등성 및 route-local 대체 경로 테스트가 localization을 검증합니다.
- 재생 테스트가 JSON, SSE 및 cross-transport 멱등성을 검증합니다.
- 출처 이력 테스트가 사용 불가, 알 수 없음, malformed 및 route-owner 상태를 검증합니다.
- 스트림 테스트가 inactivity, authentication 분류, 프레임 한도 및 액션 시간 초과를 검증합니다.
- 아키텍처 테스트가 배치, 선택, accessibility, 캐시 최신성 및 범위가 제한된 polling을 검증합니다.
