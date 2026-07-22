# Agents Submenu Hardening Review

이 문서는 2026-07-19에 수행한 Console Agents 도메인의 전수검사와 10라운드
하드닝 결과를 기록합니다. 범위는 `Agents`, `Pantheon`, `Agent activity`,
`Handover` 메뉴와 공통 navigation, authenticated agent stream, read API projection,
URL state, accessibility, localization 및 regression test입니다.

> 검사 기준은 고정 15-agent pantheon, read-only console, append-only audit projection,
> stewardship handover 계약입니다. 코드나 브라우저로 반증된 가설은 결함으로 세지
> 않고 아래에 기각 또는 검증 완료로 표시했습니다.

## Design at a glance

네 메뉴는 같은 Agent workspace 안에서 서로 다른 질문에 답합니다. `Agents`는 현재
runtime work와 incident를, `Pantheon`은 고정 조직과 workflow를, `Agent activity`는
audit 기반 행위 이력을, `Handover`는 사람의 accountability와 coverage를 보여줍니다.
모든 화면은 읽기 전용이며 선택과 필터만 URL에 반영합니다.

## Agents critiques

| # | Critique | Disposition |
|---:|----------|-------------|
| 1 | Unknown `agent.state` frame이 16번째 agent를 state에 추가할 수 있었습니다. | Round 1에서 fixed pantheon 외 frame을 무시하도록 수정했습니다. |
| 2 | Ticket보다 먼저 온 conversation turn의 stub incident가 참여 agent를 기록하지 않았습니다. | Round 2에서 알려진 from/to agent를 `involved`에 보존했습니다. |
| 3 | 기존 incident에 새 turn participant가 합류해도 `involved`가 갱신되지 않았습니다. | Round 2에서 참여자를 중복 없이 합쳤습니다. |
| 4 | Turn-only stub이 30개 retention 밖으로 밀려도 `incidents` map에는 남았습니다. | Round 3에서 order와 map을 함께 prune했습니다. |
| 5 | Incident retention 30개 제한이 화면에 명시되지 않습니다. | 후속 UX 개선입니다. 현재 memory bound 자체는 의도된 동작입니다. |
| 6 | Durable incident snapshot은 mount 시 한 번만 load되어 stream reconnect 뒤 재조정되지 않습니다. | 후속 resilience 개선입니다. reconnect 시 snapshot refresh가 필요합니다. |
| 7 | Agent stream의 `lastError`가 hook에는 있지만 Agents 화면에 표시되지 않습니다. | 후속 observability 개선입니다. |
| 8 | Snapshot load 중 roster가 0 incident처럼 보여 loading과 empty를 구분하기 어렵습니다. | 후속 loading-state 개선입니다. |
| 9 | Invalid `?agent=` deep link는 unavailable message를 보이지만 정리 action은 없습니다. | 후속 route recovery 개선입니다. |
| 10 | Invalid `?correlation=` deep link는 retained stream에 없다는 사실만 표시합니다. | Incident 또는 Audit 검색 링크를 추가하는 후속 개선입니다. |
| 11 | Frontend `PANTHEON`과 backend `PANTHEON_SPECS`의 이름 parity를 직접 검사하는 console test가 없습니다. | 후속 cross-layer parity gate입니다. |
| 12 | Incident ticket의 `involved_agents`는 fixed pantheon membership을 검증하지 않습니다. | 후속 stream-boundary hardening입니다. |
| 13 | Conversation turn의 unknown from/to는 incident text에는 남을 수 있습니다. | Round 2는 ownership 연결만 known agent로 제한했습니다. Text provenance 검증은 후속입니다. |
| 14 | Stream timestamp는 string type만 검사하고 RFC 3339 형식을 검사하지 않습니다. | 후속 boundary validation입니다. |
| 15 | Incident severity가 free-form string이라 예상하지 못한 CSS class가 만들어질 수 있습니다. | 후속 severity enum validation입니다. |
| 16 | Agent event 클릭이 URL만 바꾸고 현재 패널에서 반응이 보이지 않았습니다. | 이전 조치에서 선택 강조와 inline workflow를 추가했습니다. |
| 17 | Focus event list의 220px scroll 영역에는 추가 content가 있다는 cue가 약합니다. | 후속 compact-panel UX 개선입니다. |
| 18 | 선택 incident가 Agent focus와 global incident list 양쪽에 중복 렌더됩니다. | 정보 위치를 비교한 뒤 한쪽 summary화할 후속 UX 항목입니다. |
| 19 | Route title, state label 및 empty copy 대부분이 inline English입니다. | 후속 catalog localization입니다. |
| 20 | Agent event inline expansion은 browser 검증이 있으나 component interaction regression test가 없습니다. | Pure selection test는 존재하며 DOM interaction test는 후속입니다. |

## Pantheon critiques

| # | Critique | Disposition |
|---:|----------|-------------|
| 1 | `agent_count`가 실제 agent 배열 길이와 달라도 수락했습니다. | Round 4에서 exact count를 검증했습니다. |
| 2 | Fixed pantheon agent가 누락되어도 directory를 부분 렌더할 수 있었습니다. | Round 4에서 exact 15-name set을 검증했습니다. |
| 3 | Duplicate agent name이 card key와 조직 identity를 충돌시킬 수 있었습니다. | Round 4에서 uniqueness를 검증했습니다. |
| 4 | Odin 외 agent가 root가 되어도 ReportingTree가 수락했습니다. | Round 5에서 Odin 단일 root를 강제했습니다. |
| 5 | Self 또는 multi-agent reporting cycle이 recursive renderer를 폭주시킬 수 있었습니다. | Round 5에서 모든 parent chain의 acyclic 조건을 검증했습니다. |
| 6 | Unknown `reports_to`가 orphan branch를 만들 수 있었습니다. | Round 5에서 known-agent parent만 허용했습니다. |
| 7 | Workflow `count`와 배열 길이가 달라도 표시했습니다. | Round 6에서 exact count를 검증했습니다. |
| 8 | Duplicate workflow id가 table identity를 충돌시킬 수 있었습니다. | Round 6에서 id uniqueness를 검증했습니다. |
| 9 | Unknown primary agent가 dead Agents link를 만들 수 있었습니다. | Round 6에서 primary membership을 검증했습니다. |
| 10 | Unknown participant 또는 primary 누락 workflow를 수락했습니다. | Round 6에서 fixed participants와 primary inclusion을 검증했습니다. |
| 11 | `org_edges`는 decode하지만 `reports_to`와 일치하는지 검증하거나 렌더하지 않습니다. | 후속 contract simplification 또는 parity validation입니다. |
| 12 | `mermaid`도 required decode하지만 현재 화면에서 사용하지 않습니다. | 후속 contract simplification입니다. |
| 13 | `hard_dependency_agents`가 agent boolean flag와 일치하는지 검증하지 않습니다. | 후속 projection parity validation입니다. |
| 14 | `hot_path_llm_agents`가 card의 `hot_path_llm` flag와 일치하는지 검증하지 않습니다. | 후속 projection parity validation입니다. |
| 15 | Agent `layer`가 free-form이라 unknown layer는 세 directory section 어디에도 나타나지 않습니다. | 후속 layer enum validation입니다. |
| 16 | `default_mode`가 free-form이라 unknown mode도 shadow badge처럼 보일 수 있습니다. | 후속 workflow mode enum validation입니다. |
| 17 | Directory, organization, legend 및 unavailable copy가 inline English입니다. | 후속 catalog localization입니다. |
| 18 | Optional endpoint가 나중에 복구되어도 자동 retry나 Retry control이 없습니다. | 후속 resilience 개선입니다. |
| 19 | Runtime stream의 closed reason은 source banner에 표시되지 않습니다. | 후속 observability 개선입니다. |
| 20 | Browser back으로 directory view가 복원되지 않는다는 가설은 실제 검사에서 반증됐습니다. | 기각했습니다. URL과 `aria-pressed`가 정상 복원됐습니다. |

## Agent activity critiques

| # | Critique | Disposition |
|---:|----------|-------------|
| 1 | Timeline과 Waterfall이 route filter parser를 복제했습니다. | Round 7에서 shared `activityFiltersFromSearch`로 통합했습니다. |
| 2 | Permanent 401/403 뒤 visibility change가 direct reconnect를 우회 호출했습니다. | Round 8에서 resume 조건에 permanent failure를 포함했습니다. |
| 3 | 1.5초 refresh throttle은 burst의 마지막 event 뒤 trailing refresh를 보장하지 않습니다. | 후속 data-freshness hardening입니다. |
| 4 | 각 accepted stream refresh가 audit 최신 200개를 다시 가져옵니다. | 후속 incremental projection 또는 coalescing 개선입니다. |
| 5 | SSE read loop에 application-level inactivity timeout이 없습니다. | 후속 stale-connection detection입니다. |
| 6 | Hook `lastError`가 Activity toolbar에 노출되지 않습니다. | 후속 observability 개선입니다. |
| 7 | Time window는 현재 시간이 아니라 가장 최신 audit row를 anchor로 사용합니다. | Historical fixtures에는 유리하지만 stale dataset이 recent처럼 보일 수 있어 의미 재검토가 필요합니다. |
| 8 | Timeline은 200개에서 잘리고 older data는 Audit 링크 없이 문장으로만 안내됩니다. | 후속 evidence navigation 개선입니다. |
| 9 | Deep-linked step이 현재 filter 밖이어도 waterfall에 삽입되지만 예외 표시가 없습니다. | 후속 filter-context disclosure입니다. |
| 10 | Search query 길이에 client-side bound가 없습니다. | 후속 URL and rendering bound입니다. |
| 11 | Toolbar, empty state, view toggle 및 detail copy가 inline English입니다. | 후속 catalog localization입니다. |
| 12 | Waterfall collapse state는 URL이나 session에 보존되지 않습니다. | 새 data render에는 유지되지만 navigation 복원은 되지 않습니다. |
| 13 | Detail pane은 Escape shortcut을 제공하지 않습니다. | Modal은 아니지만 keyboard efficiency 후속 개선입니다. |
| 14 | Detail pane에 독립 region label이 없어 screen reader landmark가 약합니다. | 후속 accessibility 개선입니다. |
| 15 | Minimum 2.5 percent bar width가 매우 짧은 실제 duration을 시각적으로 과장합니다. | Tooltip은 실제 값을 제공하며 legend 보강이 필요합니다. |
| 16 | Invalid timestamp는 0ms로 정규화되어 unrelated event가 같은 위치에 모일 수 있습니다. | 후속 timestamp boundary validation입니다. |
| 17 | `activityVerb`의 substring heuristic은 `auto`가 포함된 unrelated text를 execute로 분류할 수 있습니다. | 후속 token-based classifier입니다. |
| 18 | Custom service producer는 System layer가 되며 전용 layer filter가 없습니다. | 후속 system filter UX입니다. |
| 19 | Agent chip count의 숫자에 screen-reader용 records label이 없습니다. | 후속 accessibility 개선입니다. |
| 20 | Group collapse가 stream refresh마다 초기화된다는 가설은 component identity상 반증됐습니다. | 기각했습니다. 동일 mount의 state는 re-render에서 유지됩니다. |

## Ownership handover critiques

| # | Critique | Disposition |
|---:|----------|-------------|
| 1 | Fixed pantheon agent 누락을 수락했습니다. | Round 9에서 exact 15-name set을 검증했습니다. |
| 2 | Duplicate agent name이 handover identity를 충돌시킬 수 있었습니다. | Round 9에서 uniqueness를 검증했습니다. |
| 3 | `maintainer_count`와 maintainer 배열 길이가 달라도 표시했습니다. | Round 9에서 count parity를 검증했습니다. |
| 4 | Duplicate maintainer identity는 실제 환경에서 bus-factor를 과장할 수 있습니다. | Upstream placeholder map은 동일 all-zero id를 허용하므로 frontend에서는 거부하지 않습니다. Fork validation 후속 항목입니다. |
| 5 | Coverage `total_agents`가 map과 달라도 표시했습니다. | Round 9에서 map parity를 검증했습니다. |
| 6 | Coverage `autonomous_agents`가 실제 mode와 달라도 표시했습니다. | Round 9에서 derived count parity를 검증했습니다. |
| 7 | Coverage maintainer 수가 map과 달라도 표시했습니다. | Round 9에서 cross-section parity를 검증했습니다. |
| 8 | Steward `kind`가 free-form string이었습니다. | Round 10에서 `user|group`만 허용했습니다. |
| 9 | Steward `responsibility`가 free-form string이었습니다. | Round 10에서 `accountable|informed`만 허용했습니다. |
| 10 | Finding `severity`가 free-form string이었습니다. | Round 10에서 `warn|info`만 허용했습니다. |
| 11 | Map `version`은 decode하지만 지원 version을 검증하지 않습니다. | 후속 schema-version hardening입니다. |
| 12 | `hop_timeout_seconds`는 decode하지만 화면에 표시하지 않습니다. | 후속 escalation SLA visibility입니다. |
| 13 | `over_assigned_max`는 decode하지만 finding threshold context로 표시하지 않습니다. | 후속 coverage context visibility입니다. |
| 14 | Subtitle, KPI label, banner, table 및 callout copy가 inline English입니다. | 후속 catalog localization입니다. |
| 15 | Handover data는 mount 시 한 번만 읽고 refresh control이 없습니다. | 후속 stale-data recovery입니다. |
| 16 | Last updated timestamp가 없어 operator가 map freshness를 판단할 수 없습니다. | Backend provenance 확장과 함께 처리할 후속 항목입니다. |
| 17 | Stewardship change audit로 가는 evidence link가 없습니다. | 후속 Audit filtered link입니다. |
| 18 | Steward row가 실제 id 또는 resolved display name 없이 `user / accountable`만 표시합니다. | 높은 우선순위 후속 UX입니다. 현재 누가 steward인지 식별할 수 없습니다. |
| 19 | Steward display order가 escalation tier 순서를 명시적으로 정렬하지 않습니다. | 후속 accountable-first ordering입니다. |
| 20 | Autonomous mode와 reason, steward 배열의 상호 일관성을 frontend가 재검증하지 않습니다. | 후속 fail-closed contract validation입니다. |

## Ten hardening rounds

| Round | Menu | Hardening | Focused verification |
|------:|------|-----------|----------------------|
| 1 | Agents | Unknown state frame rejection | `agents.model.test.ts` |
| 2 | Agents | Turn-first participant retention | `agents.model.test.ts` |
| 3 | Agents | Turn-first stub pruning | `agents.model.test.ts` |
| 4 | Pantheon | Exact count and fixed names | `pantheon.test.ts` |
| 5 | Pantheon | Reporting root and acyclic parent chains | `pantheon.test.ts` |
| 6 | Pantheon | Workflow count, id and agent references | `pantheon.test.ts` |
| 7 | Agent activity | Shared route-filter parser | `agent-activity-groups.test.ts` plus typecheck |
| 8 | Agent activity | Permanent auth failure visibility guard | `use-agent-stream.test.ts` |
| 9 | Handover | Fixed names and count parity | `handover.test.ts` |
| 10 | Handover | Stewardship enum validation | `handover.test.ts` plus typecheck |

## Verification

각 라운드는 다음 라운드로 넘어가기 전에 focused Vitest를 통과했습니다. 최종 관련
suite는 7 files, 65 tests가 통과했고 Console 전체 suite도 97 files, 766 tests가
통과했습니다. Strict TypeScript typecheck와 editor diagnostics, `git diff --check`도
통과했습니다. Production Vite build와 entry bundle gate는
`498557 raw / 140831 gzip / 37 lazy imports`로 통과했습니다.

Playwright는 1440 x 900과 390 x 844에서 네 canonical route의 active navigation,
alert absence, page-level horizontal overflow를 검사했습니다. Agents event는 inline
workflow 1개, Pantheon은 org chart 1개, Agent activity는 waterfall 11 groups,
Handover는 15 map rows와 2 tables를 확인했습니다. Mobile Handover table은 자체
scroll container 안에 머물렀고 main page overflow는 없었습니다.

## Related docs

| To learn about | Read |
|----------------|------|
| Fixed agent roles and organization | [Agent pantheon](../docs/roadmap/agents/agent-pantheon.md) |
| Cross-agent workflow contracts | [Agent workflows](../docs/roadmap/agents/agent-workflows.md) |
| Human accountability mapping | [Agent stewardship and handover](../docs/roadmap/interfaces/agent-stewardship-and-handover.md) |
| Read-only console boundary | [App shape](../.github/instructions/app-shape.instructions.md) |
