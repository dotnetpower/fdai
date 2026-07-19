# Governance and Evidence Hardening Review

이 문서는 2026-07-19에 수행한 Console Web의 Governance와 Evidence 전수검사와
10라운드 하드닝 결과를 기록합니다. 범위는 Governance 8개 메뉴와 Evidence 5개
메뉴, 공통 route, read API decoder, URL state, accessibility, document ingestion,
production build 및 regression test입니다.

> 판정 기준은 read-only console, 실제 Azure evidence, append-only audit,
> provenance, shadow-before-enforce 및 clean History API URL 계약입니다. 코드나
> 테스트로 반증된 가설은 결함으로 세지 않았습니다.

## Design at a glance

Governance는 배포 구조, ontology, rules, workflow, capability, blast radius,
promotion readiness 및 effective scope를 설명합니다. Evidence는 audit, reports,
trace, root-cause analysis (RCA) 및 document ingestion의 관찰 근거를 제공합니다.
화면은 상태를 읽고 draft를 만들 수 있지만 managed resource를 직접 변경하지
않습니다.

## Governance critiques

| # | Menu | Critique | Disposition |
|---:|------|----------|-------------|
| 1 | Architecture | Canonical `/architecture` route가 registry에 포함되는지 검사했습니다. | `panels.test.ts`와 `router.test.ts`로 검증했습니다. |
| 2 | Architecture | Unknown named view가 stale graph를 authoritative하게 보일 수 있는지 검사했습니다. | Named-view 404 뒤 default graph fallback을 `architecture.test.ts`로 검증했습니다. |
| 3 | Architecture | Explicit resource가 graph 밖인데 선택될 수 있는지 검사했습니다. | Unknown resource rejection을 검증했습니다. |
| 4 | Architecture | Snapshot age가 wall clock에 고정되어 재현 불가능한지 검사했습니다. | Explicit clock 기반 age 계산을 검증했습니다. |
| 5 | Ontology | Canonical `/ontology` route와 object/action selection을 검사했습니다. | Route registry와 selection tests가 통과했습니다. |
| 6 | Ontology | Invalid ActionType이 다른 항목으로 자동 대체되는지 검사했습니다. | Invalid selection을 보존하고 대체하지 않음을 검증했습니다. |
| 7 | Ontology | ActionType filter가 deep link에서 유실되는지 검사했습니다. | Selection URL round-trip을 검증했습니다. |
| 8 | Ontology | Unsupported view가 renderer를 깨뜨리는지 검사했습니다. | `objects` view로 안전하게 normalize됨을 검증했습니다. |
| 9 | Rules | Canonical `/rules` route와 server-side paging state를 검사했습니다. | Registry와 list-state tests가 통과했습니다. |
| 10 | Rules | Search debounce 중 stale rows가 interactive하게 남는지 검사했습니다. | Updating lock contract를 `rule-catalog.model.test.ts`로 검증했습니다. |
| 11 | Rules | Active와 collected tier의 detail provenance가 섞이는지 검사했습니다. | `rule_origin`이 list origin과 독립적으로 유지됨을 검증했습니다. |
| 12 | Rules | Missing historical rule과 operational outage가 같은 상태인지 검사했습니다. | 404는 unavailable, 그 외 실패는 error로 유지됨을 검증했습니다. |
| 13 | Workflow builder | Canonical `/workflow-builder` route를 검사했습니다. | Route registry가 통과했습니다. |
| 14 | Workflow builder | Catalog clone에서 step parameter가 유실되는지 검사했습니다. | Clone과 draft assembly round-trip을 검증했습니다. |
| 15 | Workflow builder | Unknown workflow deep link가 임의 default로 바뀌는지 검사했습니다. | Unknown selection을 보존함을 검증했습니다. |
| 16 | Workflow builder | Negated operator 문장이 mutation draft로 바뀌는지 검사했습니다. | Negated action abstention을 검증했습니다. |
| 17 | Capabilities | Canonical `/capabilities` route를 검사했습니다. | Route registry가 통과했습니다. |
| 18 | Capabilities | Row click이 URL만 바꾸고 detail state를 갱신하지 않는 결함을 확인했습니다. | Round 9에서 route event와 local state를 동기화했습니다. |
| 19 | Capabilities | Back/forward 뒤 query, category, effect, role이 stale한 결함을 확인했습니다. | Round 9에서 단일 parser로 복원하고 테스트했습니다. |
| 20 | Capabilities | Response count와 item 수가 달라도 표시하는 결함을 확인했습니다. | Round 9에서 exact count를 검증했습니다. |
| 21 | Capabilities | Duplicate 또는 empty capability id가 row identity를 충돌시키는 결함을 확인했습니다. | Round 9에서 non-empty와 uniqueness를 검증했습니다. |
| 22 | Blast radius | Canonical `/blast-radius` route를 검사했습니다. | Route registry가 통과했습니다. |
| 23 | Blast radius | Depth가 1에서 5 밖으로 벗어나는지 검사했습니다. | Invalid depth를 default로 제한함을 검증했습니다. |
| 24 | Blast radius | Unsupported link가 simulation query에 남는지 검사했습니다. | Supported links만 유지됨을 검증했습니다. |
| 25 | Blast radius | 늦은 이전 response가 최신 draft를 덮는지 검사했습니다. | Request generation guard를 검증했습니다. |
| 26 | Promotion gates | Canonical `/promotion-gates` route를 검사했습니다. | Route registry가 통과했습니다. |
| 27 | Promotion gates | Empty ActionType, 음수 count, 범위 밖 accuracy를 수락하는 결함을 확인했습니다. | Round 3에서 boundary decoder를 강화했습니다. |
| 28 | Promotion gates | Duplicate gap이 unstable key와 중복 표시를 만드는 결함을 확인했습니다. | Round 3에서 deduplicate 후 sort했습니다. |
| 29 | Promotion gates | `agreed_count`가 `reviewed_count`보다 커도 표시하는 결함을 확인했습니다. | Round 4에서 관계 검증을 추가했습니다. |
| 30 | Promotion gates | Summary count가 실제 row와 모순되어도 KPI로 표시하는 결함을 확인했습니다. | Round 4에서 ready와 blocked count parity를 검증했습니다. |
| 31 | Scope | Canonical `/scope` route와 policy exclusion 계산을 검사했습니다. | Registry와 `scope.test.ts`가 통과했습니다. |
| 32 | Scope | Clipboard 실패를 copied로 오인하는지 검사했습니다. | Success 뒤에만 copied 상태가 되며 reject는 failed임을 검증했습니다. |

## Evidence critiques

| # | Menu | Critique | Disposition |
|---:|------|----------|-------------|
| 33 | Audit | Canonical `/audit` route를 검사했습니다. | Route registry가 통과했습니다. |
| 34 | Audit | Exact entry link가 mutable page cursor로만 처리되는지 검사했습니다. | Immutable sequence bounds로 변환됨을 검증했습니다. |
| 35 | Audit | Replayed page가 duplicate audit row를 만드는지 검사했습니다. | Sequence 기반 deduplication을 검증했습니다. |
| 36 | Audit | 늦은 이전 cursor response가 최신 page를 append하는지 검사했습니다. | Current cursor response만 수락함을 검증했습니다. |
| 37 | Reports | Canonical `/reports` route를 검사했습니다. | Route registry가 통과했습니다. |
| 38 | Reports | RFC 3339 offset이 다른 source를 문자열 순서로 비교하는 결함을 확인했습니다. | Round 1에서 epoch 순서로 수정했습니다. |
| 39 | Reports | Date-only 또는 timezone 없는 provenance가 evidence time으로 수락되는 결함을 확인했습니다. | Round 2에서 strict RFC 3339 판별을 공통화했습니다. |
| 40 | Reports | Source 하나라도 `as_of`가 없는데 aggregate time을 추론하는지 검사했습니다. | Unknown source time이 있으면 null로 abstain함을 검증했습니다. |
| 41 | Reports | Variable 변경 뒤 이전 rendered evidence가 남는지 검사했습니다. | Variable 변경 시 rendered state와 operation error를 무효화함을 검증했습니다. |
| 42 | Trace | Canonical `/trace` route와 correlation URL encoding을 검사했습니다. | Registry와 slash-containing correlation round-trip을 검증했습니다. |
| 43 | Trace | `step_count`와 steps 길이가 달라도 reconstruction을 표시하는 결함을 확인했습니다. | Round 6에서 exact count를 검증했습니다. |
| 44 | Trace | Duplicate 또는 unordered seq가 timeline으로 표시되는 결함을 확인했습니다. | Round 6에서 unique ascending sequence를 강제했습니다. |
| 45 | Trace | Empty correlation과 malformed recorded time을 수락하는 결함을 확인했습니다. | Round 6에서 non-empty와 RFC 3339를 검증했습니다. |
| 46 | RCA | Canonical `/root-cause-analysis` route와 correlation URL encoding을 검사했습니다. | Registry와 deep-link test가 통과했습니다. |
| 47 | RCA | Empty correlation을 authoritative RCA로 표시하는 결함을 확인했습니다. | Round 7에서 non-empty correlation을 강제했습니다. |
| 48 | RCA | Duplicate 또는 unordered hypothesis seq를 수락하는 결함을 확인했습니다. | Round 7에서 unique ascending sequence를 강제했습니다. |
| 49 | RCA | Hypothesis와 response의 malformed recorded time을 수락하는 결함을 확인했습니다. | Round 7에서 strict RFC 3339를 적용했습니다. |
| 50 | Documents | Canonical `/documents` route와 optional capability 상태를 검사했습니다. | Registry와 404/501 unavailable 분류를 검증했습니다. |
| 51 | Documents | Capability 전에 drag-and-drop 파일이 queued 되는 결함을 확인했습니다. | Round 5에서 authoritative limits 전에는 selection을 거부했습니다. |
| 52 | Documents | Status poll 한 번의 5xx가 전체 upload를 실패시키는 결함을 확인했습니다. | Round 5에서 transient failure만 최대 3회 재시도합니다. |
| 53 | Documents | 4xx status failure도 재시도해 불필요한 요청을 만드는지 검사했습니다. | 4xx는 첫 실패에서 즉시 중단함을 검증했습니다. |
| 54 | Documents | Drop zone과 capability error가 assistive technology에 노출되는지 검사했습니다. | Round 5에서 heading label과 `role=alert`를 연결했습니다. |

## Shared critiques

| # | Surface | Critique | Disposition |
|---:|---------|----------|-------------|
| 55 | Navigation | Governance 8개와 Evidence 5개가 stable group order를 유지하는지 검사했습니다. | `panels.test.ts`에서 exact order를 검증했습니다. |
| 56 | Routing | 모든 path가 lowercase kebab-case이고 collision이 없는지 검사했습니다. | Registry validation tests가 통과했습니다. |
| 57 | Routing | Malformed percent encoding이 broken route로 남는지 검사했습니다. | Dashboard fallback contract를 검증했습니다. |
| 58 | Accessibility | Responsive table에서 omitted `mobileLabel`이 빈 cell label을 만드는 결함을 확인했습니다. | Round 8에서 header 또는 stable key fallback을 추가했습니다. |
| 59 | Accessibility | Empty table 결과가 screen reader에 announce되지 않는 결함을 확인했습니다. | Round 8에서 polite status region으로 변경했습니다. |
| 60 | Visual boundary | Colored top 또는 left edge가 Governance와 Evidence container에 재도입되는지 검사했습니다. | `visual-boundary.test.ts`가 통과했습니다. |

## Ten hardening rounds

| Round | Surface | Hardening | Focused verification |
|------:|---------|-----------|----------------------|
| 1 | Reports | Offset-aware evidence time ordering | `reports.test.ts` |
| 2 | Reports and API | Shared strict RFC 3339 validation | `time-format.test.ts`, `reports.test.ts`, `api.test.ts` |
| 3 | Promotion gates | Identifier, metric and gap decoding | `promotion-gates.test.ts`, `panel-decode.test.ts` |
| 4 | Promotion gates | Row relationship and summary parity | `promotion-gates.test.ts` |
| 5 | Documents | Capability gating and transient poll retry | `document-ingestion.view.test.ts` |
| 6 | Trace | Strict reconstruction decoder | `rule-trace.test.ts`, `correlation-lookup.test.ts` |
| 7 | RCA | Correlation, sequence and timestamp validation | `api.test.ts` |
| 8 | Shared tables | Responsive labels and empty-state announcement | `ui.test.ts`, `visual-boundary.test.ts` |
| 9 | Capabilities | URL state synchronization and catalog parity | `capabilities.test.ts`, `router.test.ts` |
| 10 | All menus | Full regression, typecheck, build and bundle gate | 98 test files, 784 tests |

## Verification

각 round는 다음 round 전에 focused Vitest를 통과했습니다. 최종 Console suite는
98 files, 784 tests가 통과했습니다. Strict TypeScript typecheck, production Vite
build, editor diagnostics 및 entry bundle gate도 통과했습니다. Entry bundle은
`499777 raw / 141351 gzip / 37 lazy imports`입니다.

Unauthenticated Playwright sweep에서는 13개 canonical path가 모두 SPA HTTP 200을
반환했고 page error, console error 및 page-level horizontal overflow가 없었습니다.
새 browser context는 Entra sign-in boundary에서 멈추므로 authenticated 내부 화면의
interaction 증명에는 사용하지 않았습니다. 내부 기능은 decoder, model, URL state,
component contract 및 full regression tests로 검증했습니다.

## Related docs

| To learn about | Read |
|----------------|------|
| Read-only console and local Azure truth | [App shape](../.github/instructions/app-shape.instructions.md) |
| Rule lifecycle and GitOps control | [Rule governance](../docs/roadmap/rules-and-detection/rule-governance.md) |
| Audit and RCA evidence collection | [RCA evidence collection](../docs/runbooks/rca-evidence-collection.md) |
| Operator console contracts | [Operator console](../docs/roadmap/interfaces/operator-console.md) |
