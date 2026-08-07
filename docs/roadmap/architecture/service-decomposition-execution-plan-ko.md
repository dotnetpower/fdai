---
translation_of: service-decomposition-execution-plan.md
translation_source_sha: 08fb6401f20fe385273e2326c23410e1d696a69e
translation_revised: 2026-08-07
---
# 서비스 분해 실행 계획

이 문서는 FDAI를 독립 배포 가능한 5개 runtime service로 전환하는 구현 진행 상태를 추적합니다.
이 문서를 리팩터링의 지속 가능한 진행 기록으로 사용하며, 상세 설계는 각 architecture 문서에서
관리합니다.

> **목표:** 5개 service가 각각 독립 entry point, health check, identity, typed transport를
> 갖추어야 프로그램을 완료합니다. Executor gate를 충족하지 못하면 목표를 다시 4개로 줄이지 않고
> 전체 완료를 차단합니다.
>
> **안전:** Check된 항목은 exit evidence가 존재한다는 의미입니다. 계획 문구, package 이동 또는
> unit test 통과만으로 process boundary의 authority cutover 준비를 증명할 수 없습니다.

## 설계 개요

FDAI는 이 프로그램을 5개 runtime service로 완료합니다. 처음 4개 role은 이미 존재하지만 내부
package와 deployment boundary를 계속 강화해야 합니다. 다섯 번째 service는 Thor 소유 execution을
Core에서 분리하여 Isolated Executor만 mutation-capable workload identity를 보유하게 합니다.

| # | Runtime service | 목표 responsibility | Ingress | Executor authority |
|---|-----------------|---------------------|---------|--------------------|
| 1 | Core Control Plane | Agent runtime, decisioning, approval join, audit intent, recovery coordination | Internal event bus | Cutover 후 없음 |
| 2 | Operator Service | 인증된 query, conversation, projection, governed request 제출 | External HTTPS와 event bus | 없음 |
| 3 | Document Ingestion API | 인증된 upload intake와 API 소유 document transition | External HTTPS와 event bus | 없음 |
| 4 | Document Processing Worker | Durable inspection, extraction, indexing, claim, reconciliation | Internal event bus와 probe | 없음 |
| 5 | Isolated Executor | Thor 소유 command validation, target lock, provider effect, rollback attempt, execution receipt | Internal event bus와 probe | 유일한 보유자 |

Ontology, Rule Catalog, Rego build pipeline, Console, scheduled job, 15개 agent는 이 프로그램에서
별도 service가 되지 않습니다. 각 소유 runtime service 안에서 contract, package, static client,
job 또는 독립 실행 가능한 event subscriber로 유지합니다.

## 상태 요약

| 상태 | 개수 | 의미 |
|------|------|------|
| 완료 | 8 | SD-00부터 SD-07까지 exit evidence와 focused validation을 기록했습니다. |
| 진행 중 | 1 | SD-08 identity-boundary design 및 topology test를 하나의 serial worktree에서 진행합니다. |
| 계획됨 | 1 | SD-09는 시작하지 않았습니다. |
| 차단됨 | 0 | 현재 차단된 work package가 없습니다. |

마지막 업데이트: 2026-08-07.

## 실행 checklist

| 완료 | ID | Work package | Dependency | 병렬 lane | Exit evidence |
|------|----|--------------|------------|-----------|---------------|
| [x] | SD-00 | Canonical 문서와 machine manifest에서 5개 service topology, owner, contract, writer, identity, baseline test, rollback unit을 고정합니다. | 없음 | 직렬 | 검토된 topology와 ownership record, baseline check receipt |
| [x] | SD-01 | JSON, SSE, authentication, history behavior를 변경하지 않고 Operator route family를 transport, application, projection, adapter, streaming, persistence package로 분해합니다. | SD-00 | A | 고정된 route contract와 package-boundary check |
| [x] | SD-02 | Core composition, Thor execution, Saga audit intent와 closure, Vidar recovery를 명시적으로 주입된 port 뒤로 분리합니다. | SD-00 | A | Authority regression과 import-boundary receipt |
| [x] | SD-03 | Ingestion API와 Worker identity, database grant, claim, duplicate/reorder behavior, restart recovery, probe, co-host rollback을 강화합니다. | SD-00 | A | Role test와 15분 이내 rollback rehearsal |
| [x] | SD-04 | Canonical ontology release 배포, exact reference pinning, N/N-1 compatibility, projection-writer ownership, mismatch rejection, replay, rollback을 추가합니다. | SD-00 | B | Cross-service ontology compatibility와 semantic regression receipt |
| [x] | SD-05 | Canonical AST analysis부터 catalog build, semantic validation, ontology/vector generation, incremental parity, exact applicability, evaluation, governed feedback까지 Rego knowledge path를 구축합니다. | SD-04 | B | Query-to-exact-Rego contract test와 generation rollback receipt |
| [x] | SD-06 | Canonical Change lineage, provider adapter, decision trace, delivery/outcome join, resilience coverage, candidate-only learning, read-only Operator projection을 추가합니다. | SD-02, SD-04, SD-05 | C | Replay 가능한 lineage와 authority non-escalation receipt |
| [x] | SD-07 | Effect authority 없이 Isolated Executor command와 receipt contract, durable attempt mechanics, shadow consumer, health, telemetry, identity, Container App을 구현합니다. | SD-02, SD-04 | C | Duplicate, reorder, restart, deadline, lock, shadow receipt |
| [ ] | SD-08 | Mutation authority를 Isolated Executor로 cutover하고 Core에서 executor role을 제거하며 independent effect를 검증하고 in-process topology 복귀를 rehearsal합니다. | SD-07 | 직렬 | Effective-access proof, exact-topology smoke, timed rollback receipt |
| [ ] | SD-09 | 만료된 compatibility path를 제거하고 boundary를 enforce하며 canonical 문서를 업데이트하고 centralized stable-batch validation을 실행한 뒤 residual work를 종료합니다. | SD-01부터 SD-08 | 직렬 | Exact commit range의 green validation receipt |

## 병렬 실행 규칙

- **Lane A:** SD-00 후 owned path가 겹치지 않으면 Operator, Core boundary, ingestion 작업을
  별도 worktree에서 실행할 수 있습니다.
- **Lane B:** Ontology boundary hardening은 package 작업과 겹쳐 실행할 수 있습니다. Rego
  generation은 canonical ontology release와 semantic validation을 기다립니다.
- **Lane C:** Change lineage와 Executor shadow 구현은 shared contract, pantheon role file,
  composition, infrastructure identity file을 하나의 serial integration owner가 관리할 때만
  겹쳐 실행할 수 있습니다.
- **Serial join:** Shared contract, writer cutover, production composition, identity cutover,
  rollback rehearsal, stable-batch validation은 경쟁 session에서 실행하지 않습니다.

## 병렬 session 충돌 방지

각 session은 편집 전에 work package, branch 또는 worktree, owned path, 해제 조건을
예약합니다. 두 번째 session은 현재 예약과 대상 worktree의 dirty 및 미병합 path를 먼저
확인합니다. 서로 다른 branch를 사용하더라도 owned path가 하나라도 겹치면 handoff를
기다립니다.

- **독점 path:** Session은 예약한 path만 편집합니다. 다른 session 예약에 포함된 dirty,
  untracked, renamed 또는 미병합 파일은 정리, format, conflict resolution 또는 부수적인
  refactoring 대상으로 사용하지 않습니다.
- **Integration owner:** 한 명의 serial integration owner가 이 계획 문서 쌍,
  `config/service-decomposition.json`, package 간 shared contract, pantheon role 파일,
  production composition, identity cutover를 관리합니다. Package 전용 infrastructure는
  handoff 전까지 해당 package owner가 관리합니다.
- **Handoff:** Owner는 focused commit, validation receipt, residual work를 기록한 후에만 path
  예약을 해제합니다. Integration owner가 cherry-pick, merge, 상태 변경, dependency 해제를
  수행하며 worker session은 이 join과 경쟁하지 않습니다.
- **Validation 격리:** Worker는 자신이 commit한 diff 또는 예약한 worktree만 검증합니다.
  다른 session의 dirty tree에서 changed-file selector를 실행하지 않습니다.
- **Persistent worktree:** 모든 active worker는 `/home/moonchoi/dev/fdai-worktrees/` 아래의
  경로를 사용합니다. Host 재시작이나 cleanup으로 handoff evidence 통합 전에 worktree가 제거될 수
  있으므로 새 예약에 `/tmp`를 사용할 수 없습니다.

| 예약 | 현재 owner | 예약 path | 해제 조건 |
|------|------------|-----------|-----------|
| SD-01 completed route closure | `main`의 integration owner가 관리하며 handoff된 worker는 `/home/moonchoi/dev/fdai-worktrees/sd01-turn-execution`에 read-only로 유지합니다. | 예약된 source path가 없습니다. 이전 `/home/moonchoi/dev/fdai-worktrees/sd01-route-closure` worktree는 read-only이며 예약되지 않은 상태로 유지합니다. 이 worktree의 untracked worker-local `chat_route_common.py` artifact를 부수적으로 merge하거나 정리하지 않습니다. | Transport-only route ownership, application lifecycle ownership, 변경되지 않은 wire behavior, reverse import 0이 focused validation과 독립 review를 통과한 후 완료하고 해제했습니다. |
| SD-03 completed effective access와 rollback | `main`의 integration owner가 관리하며 이전 worker는 `/home/moonchoi/dev/fdai-worktrees/sd03-effective-access`에 read-only로 유지합니다. | 예약된 source path가 없습니다. | Live effective-access proof와 2초 rollback rehearsal을 수락하고 구현 예약을 해제했습니다. |
| SD-06 completed lineage | `main`의 integration owner. 이전 core, projection, hardening worker는 read-only로 유지합니다. | `d4e430d60` 후 모든 SD-06 구현 path를 해제했습니다. | Canonical lineage, provider compatibility, decision/resilience trace, candidate-only learning, bounded Operator projection 및 critique round 14회가 focused validation을 통과하고 Medium 이상 residual이 없음을 증명합니다. Execution 및 promotion authority는 0을 유지합니다. |
| SD-07 completed shadow Executor | `main`의 integration owner가 관리하며 이전 shadow 및 health-recovery worker는 read-only로 유지합니다. | `aa89b0bf1` 후 모든 SD-07 구현 및 image-admission path를 해제했습니다. | Exact protected apply, healthy shadow revision, canary, immutable receipt, digest-bound image admission, critique round 11회 및 focused validation이 통과했고 effect authority는 0을 유지합니다. |
| SD-08 authority cutover design | `/home/moonchoi/dev/fdai-worktrees/sd08-authority-cutover`의 persistent serial worker | Architecture/deployment doc pair의 Core transport-versus-effect identity design, `infra/main.tf`, `infra/variables.tf`, compute Container App identity input 및 해당 isolated-executor/topology test만 소유합니다. | Tested opt-in topology가 필요한 transport/read access를 제거하지 않으면서 Core에서 모든 mutation-capable identity를 제거합니다. 기본값은 SD-07 shadow topology를 유지하며 exact plan, smoke 및 timed rollback evidence 전에는 live authority를 이동하지 않습니다. |
| Serial integration | Integration owner | 이 계획 문서 쌍, machine status manifest, package 간 contract, production composition, pantheon role, executor identity cutover | Focused package handoff를 수락하고 dependency 상태를 업데이트 |

## 진행 상태 업데이트 contract

Work package의 상태를 바꾸는 focused commit에서 이 문서를 함께 업데이트합니다. 각 상태 전환에서
다음을 수행합니다.

1. 상태 요약 개수와 `마지막 업데이트` 날짜를 변경합니다.
2. Exit evidence가 존재할 때만 항목을 check합니다.
3. Evidence log에 commit과 focused check receipt를 추가합니다.
4. Blocker를 소유 gate와 다음 disconfirming check와 함께 기록합니다.
5. Dependency 또는 residual authority cutover가 열려 있으면 parent 항목을 완료하지 않습니다.

## Evidence log

| 날짜 | Work package | 상태 | Commit 또는 receipt | Evidence와 residual work |
|------|--------------|------|-------------------|--------------------------|
| 2026-08-07 | SD-00 | 완료 | `config/service-decomposition.json` at `95bd58718` | 5개 service 목표와 work-package DAG를 승인했습니다. Baseline pack은 918 passed와 PostgreSQL 전용 skip 2건을 기록했으며 live check는 SD-03과 SD-05가 소유합니다. |
| 2026-08-07 | SD-01 | 진행 중 | Start `ccfa3c3dd` | 첫 Operator slice로 claims-family package 이동을 시작했습니다. |
| 2026-08-07 | SD-02 | 진행 중 | Start `ccfa3c3dd` | Thor execution port와 receipt contract 분리를 시작했습니다. |
| 2026-08-07 | SD-03 | 진행 중 | Start `ccfa3c3dd` | Ingestion identity와 storage-role 검증을 시작했습니다. |
| 2026-08-07 | SD-04 | 진행 중 | Start `ccfa3c3dd` | Cross-service ontology release compatibility gate를 시작했습니다. |
| 2026-08-07 | SD-02 | 완료 | `2a82507cb`, `7e15ba084`, `7a48288cb` | Shared execution instance, durable Saga audit readiness, Vidar recovery readiness, normal dispatch, HIL resume를 명시적 composition evidence로 고정했고 union test 122개가 통과했습니다. |
| 2026-08-07 | SD-04 | 완료 | `f5cf51e3a`, `91c88f2a3`, `a5350296e`, `b24c2d90d`, `07161a96c` | Exact release ref, additive N/N-1 compatibility, revision-fenced projection writer, provider I/O 전 mismatch rejection, replay-stable atomic generation rollback이 focused union test 142개를 통과했습니다. `FDAI_DATABASE_URL`이 설정되지 않아 PostgreSQL live case 8개는 skip 상태이며, baseline은 이 live generation receipt를 SD-05에 할당합니다. |
| 2026-08-07 | SD-05 | 완료 | `1c9ce4e94`부터 `d211570c6`, `b24c2d90d`, `4f01a02e8` | Canonical AST manifest, promoted surface, held-out evaluation, concept-first exact Rule ref, atomic generation, rollback 및 governed feedback을 완료했습니다. Focused route test 105개와 lifecycle test 43개가 통과했고 PostgreSQL generation 및 parity test 12개가 skip 없이 실행됐습니다. Retrieval은 `execution_authority: false`를 유지하며 SD-06 dependency를 시작할 수 있습니다. |
| 2026-08-07 | SD-06 | 진행 중 | Start `74694b6ca` | Persistent core-only worker가 immutable canonical Change lineage slice를 소유합니다. Shared contract를 추가하거나 Operator, ingestion, executor, composition, infrastructure path를 변경하지 않고 기존 `ChangeRecord`, `ChangeAssessment`, `DecisionCase`, `ResponseOutcome` identity를 재사용합니다. |
| 2026-08-07 | SD-06 | 진행 중 | `3fcf91880` | 첫 canonical lineage slice가 `ChangeRecord`, `ChangeAssessment`, 선택한 `DecisionCase` option, `Action`, `ResponseOutcome`을 하나의 변경 불가능하고 replay-stable한 record로 연결합니다. Correlation, target, ActionType, digest, identity, causal-order 불일치를 차단하고 evidence reference를 canonicalize하며 execution 및 promotion authority를 0으로 고정합니다. Ruff, strict mypy 및 focused test 7개가 worker와 `main`에서 각각 통과했습니다. Provider, resilience, candidate-learning, read-only Operator join은 남아 있습니다. |
| 2026-08-07 | SD-06 | 진행 중 | `9f1c3be30`, `b2fd7401b`, `bcf9c701f` | 변경 불가능한 resilience 및 decision trace가 execution mode, impact scope, rollback contract, effect timing, recovery result, objective score, protected objective, constraint, approval requirement, selected effect, reasoning receipt를 lineage identity에 결합합니다. 잘못된 observation window와 ambiguous score identity는 fail closed합니다. Trace value와 boundary test를 책임별로 분리했으며 source file은 260줄과 196줄입니다. Ruff, strict mypy 및 focused package test 11개가 worker와 `main`에서 통과했습니다. Provider, candidate-learning, read-only Operator join은 남아 있습니다. |
| 2026-08-07 | SD-06 | 진행 중 | `c64834b3a`, `52dbb2ba3` | Deterministic lineage learning projection은 inert하며 별도로 sealed된 operational case를 요구하고 `operational_reuse_eligible: false`를 보고하며 execution 및 promotion authority를 0으로 고정합니다. Public GitHub 및 Azure DevOps `ChangeFeed.recent()` output이 mock transport를 통해 canonical lineage와 candidate extraction을 모두 통과했으므로 중복 core adapter를 추가하지 않았습니다. Ruff, strict mypy 및 focused package test 16개가 `main`에서 통과했습니다. Core-only 예약은 해제했으며 read-only Operator projection은 SD-01 route handoff를 기다립니다. |
| 2026-08-07 | SD-06 | 진행 중 | Projection start `2ecd7a36c` | SD-01 capability package가 통합됐습니다. 새 persistent worker는 pure `projections/change_lineage` package와 focused test만 소유합니다. HTTP route를 register하거나 app, persistence, composition, core, SD-01 route 예약을 변경할 수 없습니다. Projected candidate가 sealed case 없이 reusable해지거나 0이 아닌 authority를 노출하거나 unbounded source data를 유출하거나 Starlette/routes를 import하면 이 slice를 반증합니다. |
| 2026-08-07 | SD-06 | 진행 중 | `e76874409`, projection handoff | Frozen summary 및 detail view가 canonical lineage를 candidate sealing과 authority 0에 결합하고 oversized identity를 거부하며 display reason과 evidence를 명시적으로 제한하고 raw provider content를 생략합니다. Projection test 4개, Operator boundary gate, Ruff, strict mypy가 통과했습니다. 결합된 lineage/projection union test 20개가 통과했습니다. 구현 예약은 해제했습니다. 다음 반증 check는 SD-01 conversation-persistence handoff 후 충돌 없는 module-map ownership 및 HTTP registration 검토입니다. |
| 2026-08-07 | SD-06 | 진행 중 | Hardening start `96c959429` | Persistent isolated worker가 해제된 SD-06 source와 focused-test path만 소유하고 critique round를 10회 이상 수행합니다. 재현 가능한 각 Medium 이상 defect는 focused fix, test, commit 하나로 처리하며 검증된 false positive round는 production edit 없이 기록합니다. 최종 완료는 독립 Low-only residual review를 요구합니다. |
| 2026-08-07 | SD-06 | 진행 중 | Hardening round 9 scope | GitHub `ChangeFeed.recent()`는 aware normalized deployment timestamp와 naive query bound를 비교할 때 `TypeError`를 발생시켰고 Azure DevOps peer는 같은 bound를 UTC로 정규화합니다. 소유되지 않은 GitHub adapter file을 재현된 parity fix에 한해 이 worker에 추가하며 다른 provider path는 read-only로 유지합니다. |
| 2026-08-07 | SD-06 | 완료 | `f83c82f62`부터 `d4e430d60`, Low-only review | Critique round 14회에서 재현 가능한 lineage/candidate digest 위조, causal timestamp 누락, assessment evidence 손실, outcome-effect 불일치, selected-option 충돌, resilience timing 우회, projection identity/count/reason metadata gap 및 GitHub naive-window failure를 수정했습니다. Impossible-state 또는 의도된 never-raising authority claim 2건은 false positive로 기각했습니다. 최종 독립 review는 Medium 이상 residual이 없음을 확인했습니다. Exact `main`에서 Ruff, strict mypy, Operator boundary gate 및 focused lineage/projection/provider test 43개가 통과했습니다. Low residual은 malformed GitHub timestamp의 fail-closed silent skip, authorized detail projection의 content digest 노출 및 400줄 advisory를 1줄 넘는 lineage model입니다. |
| 2026-08-07 | SD-01 | 진행 중 | `f220eb06f`, `2739e2be6`, `7c18ed513`, `0ab723835`, `64955ba87` | Stream metric, terminal projection, post-generation orchestration, application capability ownership, authenticated request preparation을 explicit application 또는 projection package 뒤로 이동했습니다. 최신 request-preparation union test 192개가 통과했고 application/projection reverse import count는 0이며 scoped boundary gate는 green입니다. JSON, SSE, authentication, cancellation, history wire behavior는 route가 계속 소유합니다. Remaining route family와 최종 compatibility 분류가 남아 있어 SD-01은 계속 진행 중입니다. |
| 2026-08-07 | SD-01 | 진행 중 | `2111617b8` | Trajectory detail, deterministic screen answer, redacted model tracing, response resource context를 compatibility shim 없이 pure conversation projection으로 이동했습니다. Main integration union test 258개가 통과했고 application/projection-to-route import는 0을 유지했으며 scoped boundary와 translation gate가 통과했습니다. |
| 2026-08-07 | SD-01 | 진행 중 | `bbb5ac552` | Answer planning, terminal quality review, content-policy recovery, busy-input steer 또는 interrupt coordination을 compatibility shim 없이 explicit application package로 이동했습니다. Main lifecycle union test 131개가 통과했고 application/projection-to-route import는 0을 유지했으며 chat route file은 25개에서 17개로 줄었습니다. |
| 2026-08-07 | SD-01 | 진행 중 | `2ecd7a36c` | Agent delegation, runtime-skill disclosure, configuration drift, public-web evidence, request-time capability visibility, topology intent를 application 또는 adapter boundary 뒤로 이동했습니다. Main capability union test 110개가 통과했고 reverse import는 0을 유지했으며 provider scope는 server-owned 상태를 유지하고 chat route file은 17개에서 11개로 줄었습니다. |
| 2026-08-07 | SD-01 | 진행 중 | `10d7ae266` | Principal 범위 transcript와 image lifecycle persistence를 `persistence.conversation` 뒤로 이동했고 exact document evidence는 pure conversation projection으로 이동했습니다. Worker handoff의 focused test 438개가 통과했습니다. Main persistence union test 155개, reverse import 0, scoped boundary 및 translation gate가 통과했고 chat route file 8개가 남았습니다. Final response-tail과 route-common coordination 및 route-family 분류가 남아 있어 SD-01은 계속 진행 중입니다. |
| 2026-08-07 | SD-01 | 진행 중 | `e141ab07e` | Policy와 response completion을 explicit application owner 뒤로 이동했고 chat family는 여섯 file의 structural inventory에 도달했습니다. Main union test 235개, Ruff, strict mypy, structural boundary gate 및 translation gate가 통과했고 reverse import는 0을 유지했습니다. 독립 review에서는 `chat.py`와 `chat_stream.py`가 여전히 planning, evidence, persistence 및 metering을 조정하므로 High residual이 남았다고 확인했습니다. 이는 partial structural closure이며 SD-01 완료가 아닙니다. |
| 2026-08-07 | SD-01 | 진행 중 | Reservation handoff | Active reservation을 `/home/moonchoi/dev/fdai-worktrees/sd01-turn-execution`으로 이동했습니다. 이전 `/home/moonchoi/dev/fdai-worktrees/sd01-route-closure` worktree에는 삭제된 historical blob과 내용이 다른 untracked worker-local `chat_route_common.py` artifact가 있으므로 read-only로 유지합니다. 이 worktree는 active reservation이 아니며 부수적으로 정리하거나 merge해서는 안 됩니다. |
| 2026-08-07 | SD-06 | 진행 중 | `226e1058a` | Canonical module inventory가 `projections/change_lineage`를 execution, promotion, provider I/O 또는 persistence authority가 없는 bounded read-only request-local projection으로 소유합니다. Exact Operator package 및 route inventory test 10개와 bilingual map, translation, punctuation gate가 통과했습니다. SD-06에는 예약된 critique campaign과 이후 상태 종료만 남아 있습니다. |
| 2026-08-07 | 병렬 session | 진행 중 | Persistent worktree migration | Active SD-03과 retained SD-07 worker를 `/home/moonchoi/dev/fdai-worktrees/`로 이동했습니다. 모든 새 worker는 이 persistent root를 사용하며 temporary worktree path는 더 이상 유효한 예약이 아닙니다. |
| 2026-08-07 | SD-07 | 진행 중 | `work/sd07-shadow-executor`의 Start `03f6ef265` | `/tmp/fdai-sd07`에서 command/receipt transport와 durable shadow-attempt mechanics를 시작했습니다. Effect authority, production composition, pantheon role, identity cutover는 serial integration 예약으로 유지합니다. |
| 2026-08-07 | SD-07 | 진행 중 | `3b84ee15a`, `800eee04b` | Versioned command/receipt schema, durable duplicate/reorder/restart/deadline closure, poison-record DLQ, at-least-once receipt publish, supervised health 및 effect 없는 telemetry가 `main`의 focused union test 55개를 통과했습니다. Logical-target lock evidence, production composition, workload identity, Container App 배포는 남아 있으며 effect authority는 SD-08 전까지 사용할 수 없습니다. |
| 2026-08-07 | SD-07 | 진행 중 | `9ff088aec` | 기존 `ResourceLock` seam이 같은 target의 shadow command를 직렬화하고 다른 target은 겹쳐 처리하며 exact target identity를 사용하고 handler 실패 후 lock을 해제합니다. Worker에서 focused union test 59개가 통과했고 lock handoff를 통합했습니다. Production composition, workload identity, Container App 배포 및 live shadow smoke는 남아 있습니다. |
| 2026-08-07 | SD-07 | 진행 중 | Serial start `b813a227f` | Package된 shadow entrypoint와 명시적 deployed-process marker를 통합했습니다. Serial IaC는 예약된 isolated-Executor module과 SD-07 전용 root block만 소유하며 SD-03 ingestion Terraform은 변경하지 않습니다. |
| 2026-08-07 | SD-07 | 진행 중 | `0c52be49d` | Opt-in internal Container App IaC, effect 권한이 없는 전용 UAMI, operational command/DLQ/receipt entity, Key Vault-backed durable state, distributed lock DSN 및 internal probe를 구현했습니다. Root Terraform validate, module shadow-boundary test 1/1, authority test 3/3이 통과했고 SD-03 path 변경은 없습니다. Live runner plan/apply, exact-topology smoke 및 timed rollback은 남아 있습니다. |
| 2026-08-07 | SD-07 | 차단됨 | `f3eb25593`, live gate | Private-runner workflow가 `deploy_isolated_executor`를 노출하고 plan-only 기본값과 design-mocks exclusivity를 보존하며 apply 후 app revision을 검증합니다. Workflow test 24개가 통과했습니다. 상태 commit 직전 측정에서 shared queue pending commit 575개와 `origin/main`보다 50 commit 앞선 local `main`을 기록했으므로 live dispatch는 Integration Validator를 기다립니다. 다음 반증 check는 SD-07 commit의 exact validation receipt와 성공한 push이며 그 후에만 plan-only workflow를 실행합니다. |
| 2026-08-07 | SD-06 | 완료 | `3d601afbe`, Low residual 후속 조치 | 잘못된 GitHub deployment timestamp는 계속 fail closed하며 이제 provider, record type, reason field만 포함하는 redacted structured warning 하나를 기록합니다. Provider row value, repository identity 및 commit ref는 log에 남기지 않습니다. GitHub change-feed test 9개, Ruff 및 strict mypy가 통과했습니다. 남은 Low residual은 authorized detail projection의 content digest와 400줄 advisory를 1줄 넘는 lineage model입니다. |
| 2026-08-07 | SD-06 | 완료 | `7dca0e720`, `fe1664664`, `e70273d45`, 최종 Low-only 후속 조치 | Canonical identity serialization을 focused module로 이동하고 exact digest snapshot을 추가해 aggregate lineage model을 401줄에서 340줄로 줄였습니다. Summary/detail direct construction은 forged lineage, candidate, assessment 및 target digest shape를 차단하며 bounded evidence는 canonical assessment reference를 항상 보존합니다. Exact `main`에서 focused lineage/projection/GitHub test 46개, Ruff, strict mypy, Operator boundary gate, signed framework integrity 및 editor diagnostics가 통과했습니다. 독립 review는 Medium 이상 또는 재현 가능한 Low defect가 없음을 확인했습니다. Coarse clock을 위한 non-decreasing equal timestamp는 계속 유효하고 긴 provider identity는 core에서 유효하지만 Operator projection은 display bound를 넘으면 거부하며 authorized content-digest visibility는 HTTP, persistence, provider I/O, execution 또는 promotion path가 없는 의도된 Low replay reference로 유지합니다. |
| 2026-08-07 | SD-01 | 완료 | `e141ab07e`, `d741d40e4`, `2de2c15f1`, `2c9bbd89f`, 최종 독립 review | `e141ab07e`에서 partial structural closure를 수립하고 `d741d40e4`에서 typed JSON execution, `2de2c15f1`에서 typed SSE execution, `2c9bbd89f`에서 structural boundary와 문서를 고정했습니다. SSE 통합 후 main union test 283개와 focused structural closure test 114개가 통과했습니다. 정확한 route inventory는 `chat.py`, `chat_registration.py`, `chat_stream.py`, `chat_stream_protocol.py`, `chat_stream_request.py`, `chat_verification.py`이며 `chat.py`는 259 LOC, `chat_stream.py`는 211 LOC입니다. Application, projection, persistence의 routes reverse import는 0이고 `turn_execution`의 Starlette, routes, concrete adapter import도 0입니다. Ruff와 strict mypy가 green이며 translation은 175/175를 통과했습니다. JSON/SSE transport, authentication, request parsing, status mapping, frame sequencing, cancellation은 route가 소유하고 planning, evidence, generation, verification, persistence, metering lifecycle coordination은 application이 소유합니다. Wire, replay, interruption, history behavior를 보존했습니다. 최종 독립 review는 Medium 이상 finding 0건과 Low residual 1건을 확인했습니다. 구현이 없는 `routes/chat_verification.py` compatibility facade는 catalog/source-path compatibility를 위해 남아 있으며 SD-09 cleanup candidate이고 완료 blocker가 아닙니다. |
| 2026-08-07 | SD-01 | 완료 | Hardening round 1-13, Low-only review | 독립 critique round 12회에서 JSON/SSE transport parity, route inventory, lifecycle ordering과 cancellation, persistence와 replay, principal isolation, identity boundary, redaction 및 provenance를 검토했습니다. 재현 가능한 Medium finding 1건은 임의 document-resolver `RuntimeError` detail이 JSON과 SSE HTTP response에 모두 노출되는 문제였습니다. Shared request-preparation 및 JSON lifecycle boundary는 이제 원래 exception을 내부 cause로 보존하면서 고정된 unavailable detail만 제공합니다. 전체 chat-route test 82개, exact redaction regression 2개, Ruff, formatting 및 production slice strict mypy가 통과했습니다. Round 13 독립 review는 current call path를 기준으로 불완전한 SSE status map, double cleanup, persistence 전 completion 및 duplicate planning finding을 반증했습니다. Medium 이상 residual은 없습니다. 구현이 없는 `routes/chat_verification.py` facade는 의도된 Low SD-09 cleanup candidate로 유지합니다. |
| 2026-08-07 | SD-07 | 진행 중 | Live run `31177967045`, image admission recovery 시작 | Terraform apply와 convergence는 성공했지만 reused ACR `v0.1.163` image에 configured `fdai-isolated-executor` command가 없어 isolated Executor revision이 unhealthy 상태에 머물렀습니다. Log Analytics는 process 시작 전 반복된 OCI `ContainerCreateFailure`를 증명했고 image pull, Core health 및 Operator API health는 성공했습니다. Persistent recovery worker는 image-admission slice만 소유합니다. 다음 반증 check는 Terraform 전에 isolated entry point를 통과하는 exact current image와 healthy에 도달한 배포 revision입니다. |
| 2026-08-07 | SD-03 | 완료 | `480d11686`, `5c034fc65`, live effective-access receipt | Focused Terraform case 7개가 통과했고 split-to-cohost-to-split rehearsal은 900초 budget 중 2초에 완료됐습니다. VNet runner는 inherited Azure RBAC의 exact 일치와 non-privileged PostgreSQL runtime role을 확인했습니다. Live ingestion API와 worker revision도 healthy입니다. |
| 2026-08-07 | SD-07 | 진행 중 | Plan `31179749690`, apply `31180087754` | Exact protected plan은 `0 add / 9 in-place change / 0 destroy`였고 apply는 exact-plan verification, convergence, migration 2개, healthy runtime revision 5개, API health, canary 및 immutable receipt를 완료했습니다. Isolated identity는 ACR pull, command receive, receipt/DLQ send 및 state-secret read role만 가지며 effect authority는 0입니다. 기존 in-process Core path는 SD-08 rollback artifact로 유지합니다. Image-admission critique handoff와 SD-08 timed authority-cutover rollback은 계속 열려 있습니다. |
| 2026-08-07 | SD-07 | 완료 | `c8a32ae77`부터 `aa89b0bf1`, round 1-11 | Final image는 uid 65532에서 isolated entry point를 검증합니다. Protected plan은 ACR digest가 일치하는 attested GHCR subject만 수락하고 explicit authorized promotion을 요구하며 strict runtime-image metadata를 보존하고 모든 external image operation에 bound를 적용합니다. Exact main union에서 verifier, workflow, image, transport 및 CLI test 72개와 Ruff, strict mypy, YAML, translation, punctuation, whitespace check가 통과했습니다. 독립 review에서 재현 가능한 Medium 이상 residual은 없었고 malformed registry response와 unavailable pre-promoted image는 fail closed합니다. Live run `31180087754`는 effect authority 0을 유지하며 health, canary 및 immutable apply receipt를 완료했습니다. SD-08은 dependency-ready이며 serial 상태를 유지합니다. |
| 2026-08-07 | SD-08 | 진행 중 | Identity-boundary discovery 시작 | 하나의 Event Hubs role만 단순히 이동할 수 있다는 첫 가설은 반증됐습니다. Current aggregate identity는 Core transport와 startup dependency도 소유하며 Core는 aggregate identity와 vertical identity 3개를 직접 attach합니다. Serial worker는 먼저 design 및 topology test에서 필요한 Core transport/read identity를 mutation-capable executor identity와 분리합니다. 이후 exact cutover plan과 rollback receipt 전까지 effect authority는 0을 유지합니다. |

## 관련 문서

| 알아볼 내용 | 문서 |
|-------------|------|
| 승격, ownership, rollback gate | [서비스 승격과 데이터 소유권](service-graduation-and-ownership-ko.md) |
| Repository package boundary | [프로젝트 구조](project-structure-ko.md) |
| Azure runtime과 identity deployment | [배포 및 온보딩](../deployment/deploy-and-onboard-ko.md) |
| Operating ontology release boundary | [운영 온톨로지 플랫폼](operating-ontology-platform-ko.md) |
| Operator package ownership | [Operator Console Module Map](../interfaces/operator-console-module-map-ko.md) |
