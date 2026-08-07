---
translation_of: service-decomposition-execution-plan.md
translation_source_sha: 730b748e7a8f262e24621a6c1cb39d18c7124b36
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
| 완료 | 4 | Exit evidence와 focused validation을 기록했습니다. |
| 진행 중 | 3 | SD-01, SD-03, SD-06은 persistent isolated worktree에서 실행 중입니다. |
| 계획됨 | 2 | 작업을 시작하지 않았거나 ownership handoff가 대기 중입니다. |
| 차단됨 | 1 | SD-07은 live dispatch 전에 centralized validation receipt와 push 가능한 remote commit을 기다립니다. |

마지막 업데이트: 2026-08-07.

## 실행 checklist

| 완료 | ID | Work package | Dependency | 병렬 lane | Exit evidence |
|------|----|--------------|------------|-----------|---------------|
| [x] | SD-00 | Canonical 문서와 machine manifest에서 5개 service topology, owner, contract, writer, identity, baseline test, rollback unit을 고정합니다. | 없음 | 직렬 | 검토된 topology와 ownership record, baseline check receipt |
| [ ] | SD-01 | JSON, SSE, authentication, history behavior를 변경하지 않고 Operator route family를 transport, application, projection, adapter, streaming, persistence package로 분해합니다. | SD-00 | A | 고정된 route contract와 package-boundary check |
| [x] | SD-02 | Core composition, Thor execution, Saga audit intent와 closure, Vidar recovery를 명시적으로 주입된 port 뒤로 분리합니다. | SD-00 | A | Authority regression과 import-boundary receipt |
| [ ] | SD-03 | Ingestion API와 Worker identity, database grant, claim, duplicate/reorder behavior, restart recovery, probe, co-host rollback을 강화합니다. | SD-00 | A | Role test와 15분 이내 rollback rehearsal |
| [x] | SD-04 | Canonical ontology release 배포, exact reference pinning, N/N-1 compatibility, projection-writer ownership, mismatch rejection, replay, rollback을 추가합니다. | SD-00 | B | Cross-service ontology compatibility와 semantic regression receipt |
| [x] | SD-05 | Canonical AST analysis부터 catalog build, semantic validation, ontology/vector generation, incremental parity, exact applicability, evaluation, governed feedback까지 Rego knowledge path를 구축합니다. | SD-04 | B | Query-to-exact-Rego contract test와 generation rollback receipt |
| [ ] | SD-06 | Canonical Change lineage, provider adapter, decision trace, delivery/outcome join, resilience coverage, candidate-only learning, read-only Operator projection을 추가합니다. | SD-02, SD-04, SD-05 | C | Replay 가능한 lineage와 authority non-escalation receipt |
| [ ] | SD-07 | Effect authority 없이 Isolated Executor command와 receipt contract, durable attempt mechanics, shadow consumer, health, telemetry, identity, Container App을 구현합니다. | SD-02, SD-04 | C | Duplicate, reorder, restart, deadline, lock, shadow receipt |
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
| SD-01 capability route | `/home/moonchoi/dev/fdai-worktrees/sd01-capability-routes`의 persistent worker | `chat_agent_delegate.py`, `chat_skills.py`, `chat_configuration_drift.py`, `chat_web_search.py`, `chat_capability_registry.py`, `chat_topology_intent.py`, destination application package, 해당 test와 module-map 업데이트 | Capability handoff가 read-only provider boundary와 deterministic intent precedence를 보존하고 application-to-route import가 0임을 증명합니다. |
| SD-03 effective access와 rollback | `/home/moonchoi/dev/fdai-worktrees/sd03-effective-access`의 기존 SD-03 isolated session | Ingestion runtime, ingestion 전용 Terraform, access probe와 해당 test | Effective-access proof와 rollback evidence를 integration owner에게 handoff |
| SD-06 canonical Change lineage | `/home/moonchoi/dev/fdai-worktrees/sd06-change-lineage`의 persistent worker | `src/fdai/core/change_lineage/**`와 `tests/core/change_lineage/**`만 소유 | Immutable replay-stable Change -> assessment -> decision -> action -> outcome lineage focused test와 execution 또는 promotion authority 0을 증명합니다. Shared contract, agent, composition, Operator API, ingestion, infra 및 이 plan은 read-only입니다. |
| SD-07 serial finish | `main`의 integration owner. 이전 worker는 `/home/moonchoi/dev/fdai-worktrees/sd07-shadow-executor`에 유지합니다. | `infra/modules/isolated-executor/**`, `infra/main.tf`/`infra/variables.tf`/`infra/outputs.tf`의 SD-07 전용 block, `.github/workflows/deploy-dev.yml`의 `deploy_isolated_executor` block, 해당 Terraform/workflow test, production composition 및 paired docs | Effect authority 없이 shadow deployment evidence를 기록하고 ingestion module과 모든 SD-03 소유 Terraform hunk를 피하며 handoff 후 해제된 worker는 read-only로 유지합니다. |
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
| 2026-08-07 | SD-01 | 진행 중 | `f220eb06f`, `2739e2be6`, `7c18ed513`, `0ab723835`, `64955ba87` | Stream metric, terminal projection, post-generation orchestration, application capability ownership, authenticated request preparation을 explicit application 또는 projection package 뒤로 이동했습니다. 최신 request-preparation union test 192개가 통과했고 application/projection reverse import count는 0이며 scoped boundary gate는 green입니다. JSON, SSE, authentication, cancellation, history wire behavior는 route가 계속 소유합니다. Remaining route family와 최종 compatibility 분류가 남아 있어 SD-01은 계속 진행 중입니다. |
| 2026-08-07 | SD-01 | 진행 중 | `2111617b8` | Trajectory detail, deterministic screen answer, redacted model tracing, response resource context를 compatibility shim 없이 pure conversation projection으로 이동했습니다. Main integration union test 258개가 통과했고 application/projection-to-route import는 0을 유지했으며 scoped boundary와 translation gate가 통과했습니다. |
| 2026-08-07 | SD-01 | 진행 중 | `bbb5ac552` | Answer planning, terminal quality review, content-policy recovery, busy-input steer 또는 interrupt coordination을 compatibility shim 없이 explicit application package로 이동했습니다. Main lifecycle union test 131개가 통과했고 application/projection-to-route import는 0을 유지했으며 chat route file은 25개에서 17개로 줄었습니다. |
| 2026-08-07 | 병렬 session | 진행 중 | Persistent worktree migration | Active SD-03과 retained SD-07 worker를 `/home/moonchoi/dev/fdai-worktrees/`로 이동했습니다. 모든 새 worker는 이 persistent root를 사용하며 temporary worktree path는 더 이상 유효한 예약이 아닙니다. |
| 2026-08-07 | SD-07 | 진행 중 | `work/sd07-shadow-executor`의 Start `03f6ef265` | `/tmp/fdai-sd07`에서 command/receipt transport와 durable shadow-attempt mechanics를 시작했습니다. Effect authority, production composition, pantheon role, identity cutover는 serial integration 예약으로 유지합니다. |
| 2026-08-07 | SD-07 | 진행 중 | `3b84ee15a`, `800eee04b` | Versioned command/receipt schema, durable duplicate/reorder/restart/deadline closure, poison-record DLQ, at-least-once receipt publish, supervised health 및 effect 없는 telemetry가 `main`의 focused union test 55개를 통과했습니다. Logical-target lock evidence, production composition, workload identity, Container App 배포는 남아 있으며 effect authority는 SD-08 전까지 사용할 수 없습니다. |
| 2026-08-07 | SD-07 | 진행 중 | `9ff088aec` | 기존 `ResourceLock` seam이 같은 target의 shadow command를 직렬화하고 다른 target은 겹쳐 처리하며 exact target identity를 사용하고 handler 실패 후 lock을 해제합니다. Worker에서 focused union test 59개가 통과했고 lock handoff를 통합했습니다. Production composition, workload identity, Container App 배포 및 live shadow smoke는 남아 있습니다. |
| 2026-08-07 | SD-07 | 진행 중 | Serial start `b813a227f` | Package된 shadow entrypoint와 명시적 deployed-process marker를 통합했습니다. Serial IaC는 예약된 isolated-Executor module과 SD-07 전용 root block만 소유하며 SD-03 ingestion Terraform은 변경하지 않습니다. |
| 2026-08-07 | SD-07 | 진행 중 | `0c52be49d` | Opt-in internal Container App IaC, effect 권한이 없는 전용 UAMI, operational command/DLQ/receipt entity, Key Vault-backed durable state, distributed lock DSN 및 internal probe를 구현했습니다. Root Terraform validate, module shadow-boundary test 1/1, authority test 3/3이 통과했고 SD-03 path 변경은 없습니다. Live runner plan/apply, exact-topology smoke 및 timed rollback은 남아 있습니다. |
| 2026-08-07 | SD-07 | 차단됨 | `f3eb25593`, live gate | Private-runner workflow가 `deploy_isolated_executor`를 노출하고 plan-only 기본값과 design-mocks exclusivity를 보존하며 apply 후 app revision을 검증합니다. Workflow test 24개가 통과했습니다. 상태 commit 직전 측정에서 shared queue pending commit 575개와 `origin/main`보다 50 commit 앞선 local `main`을 기록했으므로 live dispatch는 Integration Validator를 기다립니다. 다음 반증 check는 SD-07 commit의 exact validation receipt와 성공한 push이며 그 후에만 plan-only workflow를 실행합니다. |

## 관련 문서

| 알아볼 내용 | 문서 |
|-------------|------|
| 승격, ownership, rollback gate | [서비스 승격과 데이터 소유권](service-graduation-and-ownership-ko.md) |
| Repository package boundary | [프로젝트 구조](project-structure-ko.md) |
| Azure runtime과 identity deployment | [배포 및 온보딩](../deployment/deploy-and-onboard-ko.md) |
| Operating ontology release boundary | [운영 온톨로지 플랫폼](operating-ontology-platform-ko.md) |
| Operator package ownership | [Operator Console Module Map](../interfaces/operator-console-module-map-ko.md) |
