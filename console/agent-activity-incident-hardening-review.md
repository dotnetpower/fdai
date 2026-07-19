# Agent Activity and Incident Hardening Review

이 문서는 2026-07-19에 수행한 Heimdall Agent activity 화면과 monitoring-to-Incident
경로의 비평 및 하드닝 결과를 기록합니다. 범위는 local audit fixture, Agent activity,
Incident projection, `IncidentRegistry`, Heimdall repeated-event detector, runtime wiring,
영한 아키텍처 문서입니다.

> 결론: routine monitoring은 Incident를 만들지 않습니다. Healthy heartbeat, successful
> probe, within-threshold observation은 evidence만 기록합니다. Configured time window 안의
> 반복 signal이 anomaly finding을 만들고, allowlisted agent, stable member-event evidence,
> reason, correlation key를 `IncidentLifecycleWorkflow`가 다시 검증한 경우에만 Incident가
> 열립니다.

## Design at a glance

Correlation은 audit와 agent step을 묶는 investigation key입니다. Correlation이 있다는
사실만으로 Incident lifecycle record가 존재하지는 않습니다. Incident의 생성과 상태는
`IncidentRegistry`가 소유하고, Console의 Incident roster는 그 lifecycle evidence와
운영 audit fallback만 읽습니다. Local UI fixture는 Audit과 Trace 학습에는 남지만
운영 Incident roster에는 들어가지 않습니다.

## Critiques

| # | Critique | Disposition |
|---:|----------|-------------|
| 1 | Stream source badge가 runtime frame만 설명하면서 아래 audit row의 source까지 설명하는 것처럼 보였습니다. | Audit provenance를 row 단위로 분리했습니다. |
| 2 | Heimdall live card의 `Audit rows 1`이 local sample을 operational evidence처럼 합산했습니다. | Operational audit와 Local samples를 별도 count로 나눴습니다. |
| 3 | Agent group header가 sample row 수를 표시하지 않았습니다. | `local sample` count를 추가했습니다. |
| 4 | Activity row가 synthetic fixture임을 표시하지 않았습니다. | Neutral `local sample` status pill을 추가했습니다. |
| 5 | Waterfall detail에서 evidence source를 확인할 수 없었습니다. | Record section에 Local sample 또는 Operational audit를 표시합니다. |
| 6 | `fixture_source`와 `observation_source`가 generic Other fields로 중복 표시될 수 있었습니다. | Curated provenance field로 분리했습니다. |
| 7 | Bare runtime actor `fdai`가 custom agent chip으로 표시됐습니다. | Explicit principal이 없는 bare actor는 System으로 귀속합니다. |
| 8 | 화면 전체에 sample audit가 있다는 안내가 없었습니다. | Visible sample count와 Incident 비생성 경계를 callout으로 표시합니다. |
| 9 | Narrator context가 sample audit를 operational row처럼 전달했습니다. | 각 activity record에 `provenance`를 추가했습니다. |
| 10 | Narrator facts에 sample과 operational count가 없었습니다. | 두 count를 evidence facts로 발행합니다. |
| 11 | Waterfall이 audit correlation group을 Incident라고 불렀습니다. | Correlation group 용어로 교체했습니다. |
| 12 | Empty state가 `No matching incidents`라고 표시했습니다. | `No matching correlation groups`로 수정했습니다. |
| 13 | Collapse control이 `Expand incident`라고 안내했습니다. | `Expand correlation group`으로 수정했습니다. |
| 14 | Live card가 correlation id만 있어도 `Active incident` 값으로 표시했습니다. | Active correlation과 Active incident를 분리했습니다. |
| 15 | Correlation만 있어도 Incident roster link가 생성됐습니다. | Registry-backed incident match가 있을 때만 Incident link를 표시합니다. |
| 16 | Trace link와 Incident link의 존재 조건이 같았습니다. | Trace는 correlation, Incident는 lifecycle match를 요구합니다. |
| 17 | Agent activity purpose가 `Each incident (correlation id)`라고 정의했습니다. | Hand-off cascade를 correlation group으로 정의했습니다. |
| 18 | Static glossary가 correlation id를 incident key라고 정의했습니다. | Investigation key이며 Incident 증거가 아니라고 수정했습니다. |
| 19 | Local seed audit에 machine-readable provenance가 없었습니다. | `fixture_source=read-api-dev-seed`를 기록합니다. |
| 20 | Local seed audit에 observation source가 없었습니다. | `observation_source=synthetic-dev`를 기록합니다. |
| 21 | Seed trace row에는 provenance가 없어 sample audit 일부만 구분될 수 있었습니다. | Audit와 trace seed 모두 같은 marker를 기록합니다. |
| 22 | 모든 audit correlation이 Incident roster entry로 투영됐습니다. | Exact local fixture marker를 projection에서 제외합니다. |
| 23 | Heimdall `within_threshold` sample도 Incident처럼 보였습니다. | Fixture exclusion과 sample UI로 Incident roster에서 제거했습니다. |
| 24 | 정상 capacity forecast sample도 Incident처럼 보였습니다. | 모든 local fixture correlation을 roster에서 제외했습니다. |
| 25 | Sample audit 자체를 삭제하면 Audit과 Trace 학습 화면이 비게 됩니다. | Audit과 Trace에는 sample을 그대로 보존합니다. |
| 26 | Fixture exclusion이 모든 synthetic signal을 숨길 위험이 있었습니다. | Broad source가 아니라 exact `read-api-dev-seed` marker만 제외합니다. |
| 27 | Operational audit fallback까지 제거하면 migration compatibility가 깨집니다. | Marker 없는 operational correlation projection은 유지합니다. |
| 28 | Explicit lifecycle state보다 inferred audit status가 우선할 위험이 있었습니다. | 기존 lifecycle-authoritative test를 유지하고 통과시켰습니다. |
| 29 | 실제 operator-confirmed Incident가 local roster에서 사라질 위험이 있었습니다. | `ProjectingIncidentStateStore` lifecycle test가 Incident 1건을 보장합니다. |
| 30 | Ambiguous correlation을 임의 Incident에 붙일 위험이 있었습니다. | 기존 fail-closed projection test를 유지했습니다. |
| 31 | Deny 또는 failure만으로 Incident를 resolved 처리할 위험이 있었습니다. | 기존 no-resolution test를 유지했습니다. |
| 32 | Operational HIL correlation은 Incident 대응 대상에서 빠질 수 있습니다. | HIL projection은 유지하고 fixture만 제외했습니다. |
| 33 | `status_source=audit_projection` legacy path의 종료 계획이 없습니다. | 후속으로 lifecycle migration metric과 deprecation 기준이 필요합니다. |
| 34 | Local pending HIL fixture도 sample provenance를 UI 전반에서 일관되게 표시하지 않습니다. | Approvals surface의 sample marker는 후속입니다. |
| 35 | Seed timestamp가 고정 날짜인데 compact row는 시각만 보여 현재 데이터처럼 보일 수 있습니다. | Sample badge로 완화했으며 date 표시 강화는 후속입니다. |
| 36 | Seed resource 이름에 `prod`가 들어가 실제 환경처럼 읽힐 수 있습니다. | Generic fixture이지만 sample label을 필수로 표시합니다. |
| 37 | Heimdall `rate_window` constructor 값이 detector에서 사용되지 않았습니다. | Monotonic timestamp를 저장하고 window 밖 event를 prune합니다. |
| 38 | 하루 간격의 동일 healthy probe도 threshold count에 누적될 수 있었습니다. | Sparse monitoring event는 anomaly와 candidate를 만들지 않습니다. |
| 39 | Configured window 안의 실제 burst는 계속 anomaly를 만들어야 합니다. | Existing threshold-burst test를 유지했습니다. |
| 40 | 서로 다른 event type의 관찰이 anomaly로 합쳐질 수 있었습니다. | Existing mixed-event test가 no anomaly를 보장합니다. |
| 41 | Resource id 없는 monitoring event가 candidate가 될 위험이 있었습니다. | Heimdall은 resource id가 없으면 관찰을 종료합니다. |
| 42 | Evidence key 없는 anomaly가 hook 성공 metric으로 기록될 수 있었습니다. | Hook 호출을 막고 `incident_candidate_missing_evidence`를 기록합니다. |
| 43 | Evidence 없는 anomaly까지 버리면 finding audit가 사라집니다. | Authoritative anomaly publish는 유지하고 Incident handoff만 차단합니다. |
| 44 | Unknown agent가 Incident를 열 수 있었습니다. | `IncidentLifecycleWorkflow` allowlist 검증을 유지했습니다. |
| 45 | Member-event evidence가 비어도 Incident가 열릴 위험이 있었습니다. | Workflow의 non-empty evidence gate를 유지했습니다. |
| 46 | Reason 없는 agent Incident가 열릴 위험이 있었습니다. | Workflow의 nonblank reason gate를 유지했습니다. |
| 47 | 같은 evidence replay가 중복 Incident와 notification을 만들 수 있었습니다. | Registry idempotency 및 notification test를 유지했습니다. |
| 48 | Hook failure가 anomaly path까지 중단할 위험이 있었습니다. | Anomaly는 유지하고 failure counter와 structured log를 기록합니다. |
| 49 | Candidate의 original correlation이 runtime hook에서 버려졌습니다. | Shared helper가 optional correlation key를 포함합니다. |
| 50 | 같은 resource와 signal의 독립 investigation이 과거 Incident에 영구 병합될 수 있었습니다. | 서로 다른 correlation은 서로 다른 Incident anchor를 만듭니다. |
| 51 | Local과 production hook이 evidence UUID와 key 규칙을 중복 구현했습니다. | `workflow_support` pure helper로 단일화했습니다. |
| 52 | Empty evidence key가 deterministic UUID로 조용히 변환될 수 있었습니다. | Helper가 non-empty evidence를 요구합니다. |
| 53 | Correlation이 없는 detector candidate는 resource와 signal만으로 다시 합쳐질 수 있습니다. | Ingress correlation 의무화 또는 window key 추가가 후속입니다. |
| 54 | Missing event type은 `generic` signal로 뭉쳐 false incident를 만들 수 있습니다. | Ingress event-type validation 강화가 후속입니다. |
| 55 | `rate_threshold`와 `rate_window`의 positive validation이 constructor에 없습니다. | Config boundary validation 후속입니다. |
| 56 | Repeated anomaly severity가 composition에서 고정 SEV3으로 매핑됩니다. | 현재 medium anomaly와 일치하지만 severity mapping table은 후속입니다. |
| 57 | Seed Heimdall 문구가 원 security finding과 anomaly finding을 혼동시켰습니다. | Supplementary check이며 anomaly와 Incident가 없었다고 수정했습니다. |
| 58 | 영문 문서가 correlation id를 Incident 존재 증거처럼 정의했습니다. | Operator Console과 detection 문서를 수정했습니다. |
| 59 | 한국어 문서도 같은 의미 혼동을 유지했습니다. | 세 문서의 영한 pair를 함께 갱신했습니다. |
| 60 | Audit과 Trace 화면 자체에는 아직 local sample badge가 없습니다. | Agent activity는 해결했으며 shared evidence badge 확장은 후속입니다. |

## Implemented hardening

| Area | Result |
|------|--------|
| Fixture provenance | Local audit와 trace seed에 stable sample marker를 기록합니다. |
| Incident projection | Local fixture는 제외하고 operational/lifecycle projection은 보존합니다. |
| Agent activity | Live, operational audit, local sample, correlation, Incident를 분리합니다. |
| Heimdall | Configured rate window 안의 repeated signal만 anomaly candidate가 됩니다. |
| Evidence gate | Stable evidence가 없는 anomaly는 Incident handoff를 하지 않습니다. |
| Incident identity | Original correlation을 anchor에 포함해 follow-on investigation을 분리합니다. |
| Documentation | Detection, pantheon, operator-console 영한 계약을 동기화했습니다. |

## Remaining work

- Correlation이 없는 detector candidate를 거부하거나 stable window key를 추가합니다.
- `rate_threshold`와 `rate_window`를 config boundary에서 positive integer로 검증합니다.
- Audit, Trace, Approvals에도 shared local-sample provenance badge를 적용합니다.
- Incident severity를 anomaly severity mapping table에서 파생합니다.
- Legacy `audit_projection` Incident의 lifecycle migration metric과 종료 기준을 정합니다.
- Local sample timestamp에 date와 timezone을 표시합니다.

## Verification

전체 pantheon agent suite 523 tests와 Incident lifecycle/read projection focused suite
32 tests가 통과했습니다. Heimdall behavior와 introspection focused suite 7 tests,
Ruff lint, Ruff format, strict mypy도 통과했습니다.

Console 전체 suite는 97 files, 771 tests가 통과했습니다. TypeScript typecheck와
production build가 통과했고 entry bundle gate는
`498775 raw / 140912 gzip / 37 lazy imports`였습니다. Translation 101 English docs와
102 translations, punctuation, documentation link gate도 통과했습니다.

Fresh local read API 8012와 isolated Console 5274에서 Playwright로 확인한 결과,
Heimdall 화면은 Operational audit 0, Local samples 1, Live incidents 0, sample badge 1,
`fdai` chip 0, System chip 1을 표시했습니다. Incident roster는 seed entry 0건이었고,
1440 x 900 및 390 x 844 모두 alert와 page-level horizontal overflow가 없었습니다.

## Related docs

| To learn about | Read |
|----------------|------|
| Detection and finding rules | [Observability and detection](../docs/roadmap/rules-and-detection/observability-and-detection.md) |
| Heimdall role and incident hook | [Agent pantheon](../docs/roadmap/agents/agent-pantheon.md) |
| Incident roster contract | [Operator console](../docs/roadmap/interfaces/operator-console.md) |
| Control-loop safety | [Architecture instructions](../.github/instructions/architecture.instructions.md) |
