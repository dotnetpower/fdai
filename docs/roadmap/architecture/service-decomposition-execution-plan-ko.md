---
translation_of: service-decomposition-execution-plan.md
translation_source_sha: 15d7f2486a6ea5cebda906ff66ce07d9317849c1
translation_revised: 2026-08-11
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
| 완료 | 10 | SD-00부터 SD-09까지 exit evidence와 focused validation을 기록했습니다. |
| 진행 중 | 0 | 활성 service-decomposition work package가 없습니다. |
| 계획됨 | 0 | 계획 상태의 service-decomposition work package가 없습니다. |
| 차단됨 | 0 | 현재 차단된 work package가 없습니다. |

마지막 업데이트: 2026-08-10.

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
| [x] | SD-08 | Mutation authority를 Isolated Executor로 cutover하고 Core에서 executor role을 제거하며 independent effect를 검증하고 in-process topology 복귀를 rehearsal합니다. | SD-07 | 직렬 | Effective-access proof, exact-topology smoke, timed rollback receipt |
| [x] | SD-09 | 만료된 compatibility path를 제거하고 boundary를 enforce하며 canonical 문서를 업데이트하고 centralized stable-batch validation을 실행한 뒤 residual work를 종료합니다. | SD-01부터 SD-08 | 직렬 | Exact commit range의 green validation receipt |

## 독립 service 추출

완료한 SD program은 배포된 process 5개와 health, transport, identity boundary를 증명합니다. 이제 IS
program은 이 5개 role을 독립적으로 build하고 release할 수 있게 만듭니다. 완료하려면 Python
distribution, image, Terraform root, migration branch 및 독립 upgrade/rollback proof가 각각 5개여야
합니다. Service는 다른 distribution에서 versioned shared contract, provider Protocol 및 telemetry
primitive만 import할 수 있으며 다른 service implementation import는 지원하지 않습니다.

### 최종 리포지토리 레이아웃

IS program은 리포지토리 소유권이 runtime 소유권과 일치해야 완료됩니다. 각 service는 하나의 service
root 아래에서 implementation, unit test, build definition 및 Python distribution을 소유합니다.
리포지토리 root에는 cross-service integration test와 workspace orchestration만 남고 두 번째
application package는 남지 않습니다.

```text
fdai/
├── services/
│   ├── core-control-plane/
│   │   ├── docker/Dockerfile
│   │   ├── services/core-control-plane/src/fdai/
│   │   ├── src/fdai_core_service/
│   │   ├── services/core-control-plane/tests/
│   │   └── pyproject.toml
│   ├── operator-service/
│   │   ├── docker/Dockerfile
│   │   ├── src/fdai_operator_service/
│   │   ├── services/core-control-plane/tests/
│   │   └── pyproject.toml
│   ├── document-ingestion-api/src/fdai_ingestion_api_service/
│   ├── document-processing-worker/src/fdai_document_worker_service/
│   └── isolated-executor/src/fdai_executor_service/
├── packages/
│   └── service-contracts/
│       ├── src/fdai_service_contracts/
│       ├── services/core-control-plane/tests/
│       └── pyproject.toml
├── services/core-control-plane/tests/
│   └── integration/
└── pyproject.toml
```

- **Service root:** `services/<service>/`는 5개 runtime service의 유일한 implementation 및 unit-test
  owner입니다. Service별 Dockerfile은 해당 service distribution만 build합니다.
- **Shared package:** `packages/service-contracts/`에는 versioned wire contract, provider Protocol 및
  telemetry primitive만 둡니다. Business logic, composition, data access 또는 다른 service의 adapter는
  포함하지 않습니다.
- **Root workspace:** Root `pyproject.toml`은 workspace member와 development tooling을 조정합니다.
  `package = false`로 설정되며 monolithic FDAI application distribution을 publish하거나
  install하지 않습니다.
- **Cross-service test:** Root `tests/integration/`은 wire compatibility와 deployed workflow를
  검증합니다. Unit test와 component test는 소유 service로 이동합니다.
- **폐기할 compatibility tree:** 최상위 `src/fdai/`, shared multi-target service Dockerfile, legacy
  service entry point 및 중복 contract 정의는 migration 전용 artifact입니다. IS-08에서 먼저 로컬로
  제거한 뒤, 최종 service-owned source를 사용해 IS-07의 image 기반 N/N-1 rollback을 증명합니다.
  Checked-in legacy source tree 대신 Git history와 변경 불가능한 이전 image를 rollback mechanism으로
  사용합니다.

| 완료 | ID | Work package | Dependency | Exit evidence |
|------|----|--------------|------------|---------------|
| [x] | IS-00 | 현재 implementation-import debt와 정확한 package, image, state, migration, rollback 목표를 고정합니다. | 없음 | Machine manifest와 non-growth gate |
| [x] | IS-01 | Service implementation이 없는 versioned shared contract SDK를 추출합니다. | IS-00 | Consumer 5개가 같은 SDK를 install하고 validate한 receipt |
| [x] | IS-02 | 독립 실행 가능한 service distribution과 composition root 5개를 추가합니다. | IS-01 | 독립 wheel 및 cold-start receipt 5개 |
| [x] | IS-03 | Cross-service implementation import를 모두 제거합니다. | IS-01, IS-02 | Import count 0과 enforced boundary gate |
| [x] | IS-04 | Durable writer grant와 migration branch를 service별로 분리합니다. | IS-02 | Migration head 5개와 writer overlap 0 |
| [x] | IS-05 | 최소 service image 5개를 build, scan, attest, publish합니다. | IS-02, IS-03 | Immutable image, SBOM, startup receipt 5개 |
| [x] | IS-06 | Shared platform에서 service Terraform root, state 및 deployment workflow를 분리합니다. | IS-04, IS-05 | Local root 5개, 격리된 backend contract, state ownership check 및 peer-isolation mechanics 통과 |
| [x] | IS-07 | 각 service의 N/N-1 contract와 독립 upgrade/rollback을 증명합니다. | IS-03, IS-06, IS-08 | Local N -> N-1 -> N artifact transition 5개와 peer-stable focused receipt 10개 통과 |
| [x] | IS-08 | Implementation, unit test, build definition 및 distribution을 5개 service root 아래로 이동하고 최상위 monolith source, 중복 contract, co-host, in-process authority, shared-image 및 shared-migration compatibility path를 제거합니다. | IS-03, IS-05 | 최종 리포지토리 레이아웃이 문서의 tree와 일치하고 최상위 production source 및 topology compatibility path 수가 0 |
| [x] | IS-09 | 최종 리포지토리 레이아웃을 enforce하고 독립 critique-and-hardening round를 10회 이상 실행한 뒤 program을 종료합니다. | IS-07, IS-08 | Layout 및 import gate 통과, Medium 이상 residual 0, 보류한 remote verification 통과 |

Machine source of truth는 `config/independent-services.json`입니다. 각 migration wave는 같은 focused
commit에서 status와 evidence를 업데이트합니다. Shared Event Hubs, PostgreSQL hosting, ACR, Key Vault,
networking 및 observability는 platform resource로 유지하지만 logical ownership, credential, schema,
migration history, deployment state 및 rollback은 service별로 분리합니다.

IS-06과 IS-07은 local executable evidence로 종료하여 deployment environment를 기다리지 않고 구현을
진행합니다. Exact remote plan/apply, peer-drift 및 rolling receipt는 IS-09가 소유하는 별도 program-final
verification gate입니다. 최종 verification이 실패하면 관련 package를 다시 열고 program 종료를
차단합니다. Local evidence는 live deployment 결과를 주장하지 않습니다.

승인된 IS-00 AST baseline은 `fdai.core`를 import하는 Operator file 140개, ingestion file 5개,
isolated Executor file 2개입니다. 이 값은 허용된 target dependency가 아니라 migration debt입니다.
Non-growth gate는 증가를 차단하고 이후 work package는 모든 count를 0으로 줄입니다.

IS-01/02는 implementation이 없는 contract wheel 1개와 고유 console entry point를 가진 service wheel
5개를 생성했습니다. 첫 composition root는 behavior를 변경하지 않기 위해 기존 FDAI implementation을
의도적으로 lazy import합니다. Wrapper import 5개는 명시적인 IS-03 debt이며 최종 source independence
evidence가 아닙니다.

IS-03은 wrapper와 5개 service distribution의 모든 cross-service implementation import를 제거했습니다.
로컬 IS-08에서 Core는 service root 아래의 `src/fdai`와 `src/fdai_core_service`를 물리적으로 소유합니다.
나머지 service 4개는 service-local implementation과 contract SDK만 포함합니다. 각 service는 test와
`docker/Dockerfile`을 소유하고, root workspace는 package를 만들지 않는 orchestration 전용이며,
`tests/integration`에는 cross-service check만 남습니다. Root 및 shared multi-target Dockerfile, legacy
entry point, duplicate contract와 generic ingestion co-host seam은 제거되었습니다.

로컬 완료 evidence에는 독립 build wheel 6개, nonroot service image 5개, image health check 5개,
104개 table과 11개 transition을 포함하는 검증된 migration branch 5개, 로컬에서 validate한 Terraform
root 5개, cross-service implementation import 0, 그리고 독립 critique-and-hardening 108회와 Medium 이상
로컬 residual 0이 포함됩니다. IS-06과 IS-07은 local 기준으로 완료됐습니다. Exact remote
plan/apply와 rolling 확인은 IS-09로 보류하며 최종 service-owned
input을 사용하고 monolith를 rollback source로 복원하지 않습니다. IS-09는 deployable distribution
`0.1.2` image를 N-1, distribution `0.1.3`을 N으로 고정하고 기존 contract-set `1.0.0`/`1.1.0` matrix를 유지합니다.

Protected service deployment는 immutable artifact provenance와 execution-control provenance를
분리합니다. Target `commit_sha`는 protected `main`의 어떤 ancestor도 될 수 있으므로 attestation된
N-1 image를 rollback rehearsal에 사용할 수 있습니다. Workflow 자체, 모든 deployment control
script, Terraform root, service migration 및 peer-state input은 항상 현재 protected `main`에서
가져오고, exact plan/apply replay는 두 run 사이의 control 변경을 거부합니다. Image build와 plan은
runner slot 5개에서 병렬 실행할 수 있지만 evidence-bearing apply는 각 service receipt가 나머지
peer state 4개가 그대로였음을 증명할 수 있도록 직렬 실행합니다.

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

2개 이상의 writing session이 활성 상태일 때 각 concurrent session은 편집 전에 work package,
branch 또는 worktree, owned path, 해제 조건을 예약합니다. 두 번째 session은 현재 예약과 대상
worktree의 dirty 및 미병합 path를 먼저 확인합니다. 서로 다른 branch를 사용하더라도 owned path가
하나라도 겹치면 handoff를 기다립니다. 단일 interactive writer 또는 serial integration owner는
기본적으로 primary `main` worktree에서 작업합니다.

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
- **Persistent worktree:** Concurrent implementation worker는
  `/home/moonchoi/dev/fdai-worktrees/` 아래의 경로를 사용합니다. 과거 registration만으로 active
  session이라고 판단하거나 새 worktree를 만들지 않습니다. Host 재시작이나 cleanup으로 handoff
  evidence 통합 전에 worktree가 제거될 수 있으므로 새 concurrent 예약에 `/tmp`를 사용할 수
  없습니다.

| 예약 | 현재 owner | 예약 path | 해제 조건 |
|------|------------|-----------|-----------|
| SD-01 completed route closure | `main`의 integration owner가 관리하며 retired worker head는 `refs/archive/worktrees/20260811/` 아래에 보존합니다. | 예약된 source path가 없습니다. Formal review에서 `e141ab07e`이 해당 behavior를 application owner로 이동했음을 확인하여 stale `chat_route_common.py` artifact를 통합 대상에서 제외했습니다. Exact non-integrated 상태는 `refs/archive/worktrees/20260811-reviewed/sd01-route-closure`에 보존합니다. | Transport-only route ownership, application lifecycle ownership, 변경되지 않은 wire behavior, reverse import 0이 focused validation과 독립 review를 통과한 후 완료하고 해제했습니다. |
| SD-03 completed effective access와 rollback | `main`의 integration owner가 관리하며 이전 worker head는 `refs/archive/worktrees/20260811/` 아래에 보존합니다. | 예약된 source path가 없습니다. | Live effective-access proof와 2초 rollback rehearsal을 수락하고 구현 예약을 해제했습니다. |
| SD-06 completed lineage | `main`의 integration owner가 관리하며 이전 worker head는 `refs/archive/worktrees/20260811/` 아래에 보존합니다. | `d4e430d60` 후 모든 SD-06 구현 path를 해제했습니다. | Canonical lineage, provider compatibility, decision/resilience trace, candidate-only learning, bounded Operator projection 및 critique round 14회가 focused validation을 통과하고 Medium 이상 residual이 없음을 증명합니다. Execution 및 promotion authority는 0을 유지합니다. |
| SD-07 completed shadow Executor | `main`의 integration owner가 관리하며 이전 worker head는 `refs/archive/worktrees/20260811/` 아래에 보존합니다. | `aa89b0bf1` 후 모든 SD-07 구현 및 image-admission path를 해제했습니다. | Exact protected apply, healthy shadow revision, canary, immutable receipt, digest-bound image admission, critique round 11회 및 focused validation이 통과했고 effect authority는 0을 유지합니다. |
| SD-08 완료 authority cutover | `main`의 integration owner가 관리하며 이전 worker head는 `refs/archive/worktrees/20260811/` 아래에 보존합니다. | Closing commit 후 예약된 source path가 없습니다. | Exact cutover/rollback plan, independent effect, 연속 offset, healthy service 5개, no-op convergence, cleanup 및 timed receipt를 수락했습니다. |
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
| 2026-08-11 | Worktree retirement review | 완료 | `refs/archive/worktrees/20260811-reviewed/` | 최종 service boundary를 기준으로 검토한 결과 남은 dirty artifact 2개를 모두 통합 대상에서 제외했습니다. Executor `uv.lock` delta는 현재 `0.1.3` service manifest와 lock에 이미 존재하는 `aiokafka`, `psycopg` dependency를 중복했고, route artifact는 metadata, metering, evidence helper가 application owner로 이동한 후 삭제된 Starlette-aware compatibility module을 복원합니다. Exact non-integrated 상태는 archive ref로 복구할 수 있으며 checkout은 제거했습니다. |
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
| 2026-08-08 | SD-08 | 진행 중 | Implementation-ready focused receipt | Additive Executor receipt `1.1.0`, remote direct-API command/receipt correlation, pre-effect audit intent, stable Core receipt consumer group, duplicate-safe isolated dispatch, explicit default-off Terraform cutover, gateway principal transfer, reversible NSG probe 및 protected workflow verification을 구현했습니다. Focused test 126개, strict mypy, Ruff, Terraform validate, root topology case 6개, module case 2개가 통과했습니다. Protected plan을 수락하고 apply하기 전까지 live effect authority는 변경되지 않습니다. |
| 2026-08-08 | SD-08 | 완료 | Plan `31207740363`, `31211368557`, `31214493667`; apply `31209982126`, `31211927016`, `31214900219` | 첫 isolated proof는 offset `[0,1]`, provider write 1회, ARM present/absent 관측, cleanup 및 142초 receipt를 기록했습니다. Rollback plan은 `0 add / 3 change / 0 destroy`였고 local transport는 write 1회와 cleanup을 450초에 증명했습니다. 최종 cutover plan은 `0 add / 4 in-place change / 0 destroy`였으며 replacement와 role-assignment change는 0이었습니다. 최종 isolated transport는 offset `[3,4]`로 이어졌고 provider write 정확히 1회, independent ARM 관측과 cleanup을 436초에 통과했으며 revision 5개가 모두 healthy 상태를 유지하고 canary와 no-change convergence를 완료했습니다. |
| 2026-08-08 | SD-09 | 완료 | Closing validation receipt | Capability catalog를 owned verification package로 옮긴 뒤 오래된 `routes.chat_verification` source-path facade를 제거했습니다. 검토된 boundary-docstring scope 22개를 모두 enforce로 전환했고 capability catalog, Operator layout 및 boundary suite의 focused test 30개가 boundary gap 보고 0건으로 통과했습니다. Centralized validation은 push 전에 test 15076개, environment-dependent skip 15개, source file 1904개 대상 strict mypy 및 모든 repository gate를 통과했습니다. |
| 2026-08-09 | IS-06 | Local 완료 | Local deployment receipt | Terraform root와 backend contract 5개, state-migration ownership contract 5개, protected plan/apply guard 및 semantic four-peer isolation mechanics가 focused deployment test 113개를 통과했습니다. Exact remote receipt는 IS-09 program-final gate로 보류하며 이 전환의 evidence로 주장하지 않습니다. |
| 2026-08-09 | IS-07 | Local 완료 | Local transition evidence | `0.1.3 -> 0.1.2 -> 0.1.3` wheel transition 5개, nonroot service image 10개 및 peer-stable focused migration/rollback receipt 10개가 offset 보존, peer restart 0, duplicate terminal effect 0으로 통과했습니다. Remote rolling 확인은 IS-09로 보류합니다. |
| 2026-08-09 | IS-09 | Local review 완료 | Round 11-14, `07db3e5d8` | 독립 round 4회에서 protected deploy provenance, semantic peer-state isolation, 7개 root drift detection 및 N/N-1 evidence integrity를 검토했습니다. Program-final status를 completed로 설정해도 accepted receipt count가 불완전할 수 있는 재현 가능한 Medium finding 1건을 수정하여 plan/apply 5개와 upgrade/rollback 5개 receipt를 모두 요구합니다. Focused manifest와 compatibility check가 통과했고 Medium 이상 local residual은 0건입니다. 보류된 remote 5+5 verification이 통과할 때까지 IS-09는 진행 중으로 유지합니다. |
| 2026-08-09 | IS-09 | Hardening 계속 | Round 15-28 | 독립 review 10회에서 protected deploy, plan sealing, peer isolation, rollback, live compatibility, migration, supply chain, drift, Terraform ownership 및 final closure를 검토했습니다. Live run을 통해 bounded parallel runner slot, remote shell expansion, explicit registration success 및 final-path image shebang을 추가로 hardening했습니다. Core run `31274885226`은 broken image가 fail closed하고 이전 healthy revision을 복원함을 증명했으며, 수정된 Core image는 local build와 import를 통과했습니다. Medium 이상 local residual은 0건이고 remote 5+5 verification은 계속 필요합니다. |
| 2026-08-09 | IS-09 | Live evidence hardening | Round 29 | `observed:false` content를 다시 hash한 live evidence artifact는 더 이상 통과하지 않습니다. Validation은 각 observation의 kind와 service를 binding하고 실제 observed result가 true인 경우에만 content-addressed ref가 live migration 또는 rollback receipt를 충족하도록 요구합니다. |
| 2026-08-09 | IS-09 | Worker cutover recovery | Round 30 | Run `31276433851`은 live legacy ClamAV sidecar에 probe가 없어 mutation 전에 실패했습니다. Initial cutover는 rollback용 exact empty probe contract만 snapshot하고 exact restoration을 검증합니다. Normal snapshot과 모든 새 worker revision은 계속 startup, liveness, readiness TCP probe를 요구합니다. |
| 2026-08-09 | IS-09 | Runtime dependency와 migration readiness | Round 31 | Live revision에서 ingestion API의 `aiohttp` 누락과 미적용 Operator/Executor role branch가 드러났습니다. Ingestion distribution은 async Azure transport dependency를 소유하고, protected service apply는 validated Key Vault reference에서 admin DSN을 읽어 mask한 뒤 traffic 전에 exact service-owned migration branch를 적용합니다. |
| 2026-08-09 | IS-09 | Exact secret rollback | Round 32 | Operator와 Executor recovery revision은 healthy였지만 post-apply `database-dsn` alias가 legacy name과 함께 남아 verification이 실패했습니다. Rollback은 immutable snapshot에 없는 secret name만 제거하고 prior Key Vault reference를 복원한 뒤 exact equality를 검증합니다. |
| 2026-08-09 | IS-09 | Enforced database principal | Round 33 | Plan은 `fdai_operator`, `fdai_executor` 등 service role을 선언하지만 일부 DSN secret은 admin principal로 인증했습니다. Service module 5개는 PostgreSQL `PGOPTIONS=-c role=<declared role>`을 설정해 readiness와 grant가 intended `current_user`를 평가하도록 합니다. |
| 2026-08-09 | IS-09 | Historical rollback provenance | Round 34 | Privileged workflow guard가 historical image source에 byte-identical deployment control을 요구해 control hardening이 한 번이라도 적용되면 N-1 rollback을 영구 차단했습니다. 이제 historical artifact revision은 protected-main ancestry와 attestation을 요구하고 실행 workflow와 control은 현재 protected `main`에 고정합니다. |
| 2026-08-09 | IS-09 | Current deployment source | Round 35 | Live preflight에서 `commit_sha`가 image revision과 historical Terraform을 함께 선택해 rollback 중 이후 role 및 recovery hardening을 조용히 제거할 수 있음을 발견했습니다. 이제 이 값은 immutable image provenance만 binding하고 Terraform root, migration, legacy state operation 및 peer capture는 모두 현재 protected `main`을 사용합니다. 취소한 Operator run은 backend validation 중 중단됐고 모든 mutation step은 skip됐습니다. |
| 2026-08-09 | IS-09 | Complete plan staleness fence | Round 36 | Successful plan 이후 migration dependency fix가 반영됐지만 apply provenance는 workflow와 helper script만 비교했습니다. 이제 exact apply는 workflow, deployment helper, 모든 service Terraform root와 shared module, service migration, root project dependency 또는 semantic `uv.lock` graph 변경을 거부합니다. Root release version만 변경되고 나머지가 동일한 경우에는 plan을 무효화하지 않습니다. 영향받은 plan은 apply 전에 모두 폐기했습니다. |
| 2026-08-09 | IS-09 | Initial migration adoption | Round 37 | Core apply run `31281314437`은 service migration baseline이 stamp되지 않아 snapshot 또는 Terraform mutation 전에 실패했습니다. 이제 initial cutover는 exact legacy head와 owned-schema fingerprint를 관측하고 commit-pinned rollback reference가 포함된 adoption 및 schema evidence를 저장하며 exact baseline만 idempotent하게 stamp한 뒤 service branch를 upgrade합니다. Standard apply는 baseline을 생성하지 않습니다. |
| 2026-08-09 | IS-09 | Adoption evidence schema parity | Round 38 | Public adoption-evidence schema는 legacy revision 79개를 요구했지만 검증된 adoption manifest는 모두 canonical 81개를 요구했습니다. 이제 schema가 live inventory와 일치하며 regression test가 canonical migration graph에서 required head와 revision count를 모두 도출합니다. |
| 2026-08-09 | IS-09 | Adoption retry 및 evidence durability | Round 39 | Initial cutover가 service migration branch를 upgrade한 뒤 후속 단계에서 중단되면 retry가 변경된 schema를 대상으로 baseline evidence를 다시 생성하여 스스로 차단할 수 있었습니다. 이제 prepare와 stamp는 exact service lineage가 baseline을 포함할 때만 no-op으로 처리하고 다른 기존 lineage는 모두 차단하며, 후속 migration 단계가 실패해도 portable adoption 및 schema evidence를 90일 동안 보존합니다. |
| 2026-08-09 | IS-09 | Legacy-head adoption prerequisite | Round 40 | Core apply run `31284637886`은 live legacy lineage가 `20260806_0077`이고 adoption은 `20260808_0079`를 요구하여 snapshot 또는 Terraform mutation 전에 실패했습니다. 이제 initial cutover는 additive ontology-direction migration으로 legacy Alembic lineage를 먼저 전진시킨 뒤 schema evidence 관측, service baseline stamp 및 service branch upgrade를 수행합니다. Legacy migration file과 `alembic.ini`도 exact plan/apply provenance input에 포함됩니다. |
| 2026-08-09 | IS-09 | Legacy migration working directory | Round 41 | Core apply run `31286708624`는 Alembic이 relative `script_location`을 protected checkout 밖에서 해석하여 snapshot 또는 Terraform mutation 전에 실패했습니다. 이제 legacy upgrade는 exact protected controls checkout을 root로 하는 subshell에서 실행하므로 `alembic.ini`와 tracked migration directory가 동일한 sealed source에서 해석됩니다. |
| 2026-08-09 | IS-09 | Release-safe plan provenance | Round 42 | Automatic release commit이 root package version만 변경해 dependency와 deployment control이 동일한데도 protected plan을 반복해서 무효화했습니다. 이제 apply는 strict control을 byte-for-byte로 비교하고 `pyproject.toml`과 `uv.lock`에서는 root FDAI release version만 제거한 뒤 semantic content를 비교합니다. Dependency, lock graph, migration, workflow, helper 또는 Terraform 변경은 계속 plan을 무효화합니다. |
| 2026-08-09 | IS-09 | Service migration revision capacity | Round 43 | Core apply run `31294369918`은 adopted service baseline까지 진행했지만 Alembic이 service version column을 32자로 생성했고 다음 branch revision id가 더 길어서 Terraform mutation 전에 실패했습니다. 이제 baseline stamp와 모든 service upgrade는 branch history를 기록하기 전에 service-owned version column만 128자로 확장하며 legacy Alembic table은 변경하지 않습니다. |
| 2026-08-09 | IS-09 | Bounded slow revision readiness | Round 44 | Core apply run `31295906457`은 migration과 Terraform apply를 완료했지만 새 digest-pinned revision이 기존 nominal 3분 polling window보다 오래 걸렸습니다. Automatic rollback이 prior image를 복원하고 검증한 뒤 해당 revision은 healthy로 관측되었습니다. 이제 post-apply health는 rollback 전에 기존 900초 deployment proof budget까지 기다리며 unhealthy 또는 inactive revision은 계속 fail closed 처리합니다. |
| 2026-08-09 | IS-09 | No-ingress revision activation | Round 45 | Core apply run `31297621282`은 900초 budget 전체를 기다렸지만 internal no-ingress service에는 traffic switch가 없어 새 revision이 healthy 상태이면서도 replica 0의 stopped 및 inactive 상태로 유지되었습니다. 이제 verification은 latest revision이 snapshot과 다르고 exact protected image를 실행하는지 확인한 뒤 bounded Container Apps revision activation을 한 번 수행하고 기존 health 및 rollback check를 계속합니다. |
| 2026-08-09 | IS-09 | Core runtime database role | Round 46 | Activation-aware Core run `31299720389`은 exact image를 시작했지만 PostgreSQL role `fdai_core`가 없어 반복적으로 exit code 1이 발생한 사실을 Log Analytics에서 확인했습니다. 이제 Core migration branch는 해당 non-login role을 만들고 Core-owned table 34개와 audit sequence에만 권한을 부여하며 schema-wide 및 default privilege는 허용하지 않습니다. |
| 2026-08-09 | IS-09 | Notification dependency degradation | Round 47 | Core-role run `31301828821`은 database startup을 통과했지만 A2 operational-alert channel 누락이 전체 Core process를 중단한 사실을 Log Analytics에서 확인했습니다. 이제 runtime은 unavailable route를 보고하고 unrelated read, deny, queue 및 shadow path를 유지합니다. 해당 notification route가 필요한 action은 usable delivery channel이 없으므로 delivery 성공을 주장할 수 없습니다. |
| 2026-08-09 | IS-09 | Complete container catalog selection | Round 48 | Corrected-image Core run `31311862255`은 role과 notification startup을 통과했지만 catalog discovery가 incomplete virtual-environment `rule-catalog`를 선택하여 chaos scenario schema를 찾지 못한 사실을 Log Analytics에서 확인했습니다. 이제 runtime catalog resolution은 package-parent development fallback보다 complete `/app/rule-catalog` payload를 먼저 검사하며 symptom-index startup은 import-time default 대신 resolved chaos catalog를 명시적으로 받습니다. |
| 2026-08-09 | IS-09 | Provisioned startup probe topic | Round 49 | Catalog-corrected Core run `31316016509`은 health server까지 도달했지만 primary bootstrap endpoint를 사용했고 전용 `runtime.startup.probe` entity는 operational namespace에 속해 있어 ready가 되지 못했습니다. 가득 찬 primary namespace를 재사용하는 bounded 중간 수정을 시험했지만 성공적인 round-trip을 확립하지 못했습니다. |
| 2026-08-10 | IS-09 | Startup probe consumer readiness | Round 51 | Live Core log에서 고유 Event Hubs consumer group이 join하는 데 약 3초가 필요했지만 independent service는 configured settle budget을 누락하여 runtime 기본값 0.5초 뒤에 publish했습니다. 따라서 consumer가 synthetic record 이후 latest offset에서 시작했고 round trip은 timeout됐습니다. 이제 service는 순서 validation 및 retry headroom과 함께 12초 settle budget, 30초 probe deadline 및 75초 phase deadline을 주입합니다. Exact round trip을 관측하지 못하면 probe는 계속 fail closed합니다. |
| 2026-08-09 | IS-09 | Operational startup probe binding | Round 50 | Canonical Core apply `31318043097`은 primary governed-ingress topic을 공유하면 synthetic consumer가 timeout하고 automatic rollback이 올바르게 시작됨을 증명했습니다. 이제 독립 Core contract는 기존 operational bootstrap endpoint와 전용 startup topic을 받아 synthetic scope, identity isolation 및 두 namespace의 entity 제한을 보존합니다. |
| 2026-08-09 | IS-09 | No-ingress health evidence | Round 51 | 같은 apply에서 Azure가 internal no-ingress Core app에 `healthState`를 보고하지 않는다는 사실도 확인했습니다. 이제 health 및 rollback verification은 ingress가 disabled이고 exact revision이 active, `Running`, replica 1개 이상일 때만 absent state를 수락합니다. Ingress-enabled app은 계속 `Healthy`를 요구합니다. |
| 2026-08-09 | IS-09 | Manifest context sanitization | Round 52 | Final-evidence 검토에서 deployment-context rejection이 remote aggregate에는 적용되지만 independent-service manifest input에는 적용되지 않는 문제를 확인했습니다. 이제 validation은 release 또는 distribution field를 읽기 전에 두 input 모두에 같은 recursive identifier, endpoint 및 deployment-key rejection을 적용합니다. |
| 2026-08-09 | IS-09 | Serial transition windows | Round 53 | Temporal critique에서 global serialization이 apply window만 다루고 protected plan은 포함하지 않으며, phase ordering도 첫 restore 전에 모든 rollback 완료를 명시적으로 요구하지 않는 문제를 확인했습니다. 이제 verifier는 겹치는 모든 plan/apply window를 거부하고 complete initial, rollback, restore phase join을 요구합니다. |
| 2026-08-10 | IS-09 | Canonical N source binding | Round 54 | Supply-chain critique에서 N-1은 manifest source에 binding되지만 N은 workflow head가 자체 source와 일치하기만 하면 임의 source revision을 수락하는 문제를 확인했습니다. 이제 transition manifest는 exact N source를 기록하며 final evidence는 해당 revision에서 시작하지 않은 N release, image set 또는 stage chain을 거부합니다. |
| 2026-08-10 | IS-09 | Closed local evidence schema | Round 55 | Evidence-boundary critique에서 local transition service와 artifact가 일부 field만 검사하여 인식되지 않은 field를 포함할 수 있는 문제를 확인했습니다. 이제 checker는 local N -> N-1 -> N evidence를 수락하기 전에 exact top-level, service 및 artifact key set을 요구합니다. |
| 2026-08-10 | IS-09 | Complete remote count join | Round 56 | Program-final critique에서 integration gate가 5/5 target 2개는 다시 검사하지만 plan 15개, apply 15개 및 peer receipt 30개는 nested verifier에만 의존하는 문제를 확인했습니다. 이제 completion join은 live compatibility evidence를 load하기 전에 derived count 5개를 모두 독립적으로 요구합니다. |
| 2026-08-10 | IS-09 | Exact document-service identity selection | Round 57 | Ingestion API run `31348846570`은 새 revision까지 도달했지만 Container App이 exact user-assigned client id를 선언했는데도 Azure SDK client가 selector 없는 Managed Identity credential을 사용하여 crash loop에 진입했습니다. 이제 API와 Worker는 `FDAI_MI_CLIENT_ID`를 요구하고 모든 Azure adapter credential을 해당 exact client id로 생성합니다. Identity selection이 없으면 provider probe 전에 실패합니다. |
| 2026-08-10 | IS-09 | Corrected canonical N image source | Round 58 | Supply-chain run `31349808536`은 identity-corrected source에서 image 5개를 모두 성공적으로 build, scan 및 attest했습니다. 이제 machine transition contract는 해당 source를 N으로 고정하므로 이후 plan, restore 및 final evidence에서 이전 crash-looping document image와 corrected peer를 섞을 수 없습니다. |
| 2026-08-10 | IS-09 | Key Vault secret normalization guard | Round 59 | Cutover 이후 Operator plan에서 변경되지 않은 Key Vault reference 옆의 비어 있거나 생략된 `secret[*].value`에만 AzureRM refresh drift가 나타났습니다. 이제 protected plan guard는 이 exact provider normalization shape만 허용합니다. 비어 있지 않은 value, 변경된 secret metadata 또는 추가 drift는 계속 차단합니다. |
| 2026-08-10 | IS-09 | Encoded context rejection | Round 60 | Customer-agnostic evidence review에서 percent-encoded Azure path와 compact GUID value가 literal identifier check를 우회할 수 있는 문제를 확인했습니다. 이제 validation은 evidence field를 읽기 전에 bounded URL decoding을 수행하고 exact compact GUID value를 거부합니다. |
| 2026-08-10 | IS-09 | Exact remote manifest schema | Round 61 | Manifest-shape review에서 remote verifier가 canonical transition key와 service coverage를 outer checker에 의존하는 문제를 확인했습니다. 이제 verifier는 exact transition schema와 unique canonical service declaration 5개를 독립적으로 요구합니다. |
| 2026-08-10 | IS-09 | Completion dependency join | Round 62 | Work-package review에서 program-final path가 remote completion은 검사하지만 IS-09 dependency 2개를 독립적으로 join하지 않는 문제를 확인했습니다. 이제 IS-09 completion은 IS-07과 IS-08이 completed 상태를 유지해야 합니다. |

| 2026-08-10 | IS-09 | Trusted GitHub evidence binding | Round 63 | Final-proof critique에서 tracked JSON의 internally consistent run id, timestamp, artifact digest 및 peer status가 여전히 self-asserted인 문제를 확인했습니다. 이제 dedicated read-only workflow가 모든 run을 GitHub API와 대조하고 각 plan metadata와 peer receipt artifact를 download하여 검사하며 deployment-input equivalence와 image attestation을 다시 검사한 뒤 aggregate에 서명합니다. Program-final completion은 해당 exact signer와 source revision에 대한 portable bundle verification을 요구합니다. |

| 2026-08-10 | IS-09 | Recovery revision metadata guard | Round 64 | Verified Core rollback이 Terraform state 외부에서 Azure의 computed latest revision name과 revision suffix를 변경하여 runtime 및 authority field가 그대로인데도 다음 standard plan이 차단됐습니다. 이제 guard는 computed identifier 2개만 수락하며 container, identity, secret, platform 또는 authority drift는 계속 부적격입니다. |
| 2026-08-10 | IS-09 | Observable sidecar contract normalization | Round 65 | Worker apply `31352359688`은 exact reviewed image와 healthy revision을 배포했지만 post-apply verification은 비어 있는 `args`, `env`, `volume_mounts` 및 `ephemeral_storage` 같은 Terraform container field를 해당 default를 생략하고 CPU와 memory를 `resources` 아래에 중첩하는 Azure Resource Manager revision shape와 비교했습니다. 이제 sealed sidecar digest는 ARM에서 관찰 가능한 exact name, CPU 및 memory contract를 포함합니다. Immutable image와 probe digest는 계속 분리되며 reviewed Terraform plan은 관찰할 수 없는 field를 계속 보호합니다. 알 수 없거나 비어 있지 않은 unsupported runtime field는 계속 fail-closed로 처리합니다. |
| 2026-08-10 | IS-09 | Adoption and compatibility-proof separation | Round 66 | Evidence review에서 positional `initial` N stage가 one-time `initial-cutover` deployment mode를 사용하도록 잘못 요구하는 문제를 확인했습니다. One-time state 및 schema adoption은 preparatory service transition이며 corrected image source마다 반복할 수 없습니다. 이제 final remote N -> N-1 -> N compatibility proof는 service 5개가 모두 adopted 상태가 된 이후에만 시작하고 모든 stage에 standard protected plan을 요구합니다. 이를 통해 repeated adoption을 방지하면서 fresh revision, rollback 및 peer-isolation evidence를 유지합니다. |
| 2026-08-10 | IS-09 | Durable remote adoption prerequisite | Round 67 | Program-final review에서 one-time adoption evidence가 90일 workflow artifact에만 남고 final attested aggregate에 join되지 않는 문제를 확인했습니다. 이제 aggregate는 adoption run 5개, artifact digest, observed legacy head 및 revision count, schema fingerprint, owned-table count, verification time, commit-pinned rollback reference를 기록합니다. GitHub binder는 final attestation 전에 각 run, 성공한 migration 및 artifact-upload step, API artifact digest와 download한 JSON record 2개를 검증합니다. 이후 health 또는 peer check가 실패해도 완료된 adoption은 지워지지 않지만 adoption step이 누락되거나 실패하면 closure가 차단됩니다. |
| 2026-08-10 | IS-09 | Genuine kind-specific live observations | Round 68 | Safety critique에서 live-evidence builder가 generic transition metadata를 `observed=true`인 kind 7개로 다시 표시하는 문제를 확인했습니다. 이제 successful apply는 image attestation, service migration, exact health 및 identity verification과 four-peer isolation이 성공한 뒤에만 별도 artifact를 seal합니다. Health, identity, image, state-offset, schema, source 및 topology record는 서로 다른 evidence를 포함합니다. Final aggregate는 exact content와 artifact digest를 저장하고 GitHub binder는 attestation 전에 successful step과 download한 artifact를 검사합니다. Builder는 해당 observed record만 복사하며 누락되거나 relabel된 content 및 `observed=false` content를 거부합니다. |
| 2026-08-10 | IS-09 | Deterministic live compatibility binding | Round 67 | Completion-path review에서 schema-valid live receipt와 observation manifest를 trusted remote aggregate와 독립적으로 작성할 수 있는 문제를 확인했습니다. 이제 program-final checker는 exact rollback/restore run, plan, context, peer-receipt, source 및 serial peer-version coordinate에서 migration/rollback receipt 10개와 observation record 35개를 모두 도출하고 compatibility validation 전에 byte-equivalent JSON value를 요구합니다. Self-asserted live record는 더 이상 IS-09를 완료할 수 없습니다. |
| 2026-08-10 | IS-09 | Plan별 fresh protected revision | Round 68 | Core apply `31353853013`에서 외부 verified rollback 이후 Terraform configuration은 N을 유지하지만 Azure latest active revision은 restored image로 남을 수 있음을 확인했습니다. 이 상태의 fresh plan은 변경 없이 apply되었고 health verification은 old image를 올바르게 거부했습니다. 이제 shared Container App module은 bounded plan-time revision suffix를 모든 saved plan에 seal하고 guard는 exact image change 옆에서 해당 syntax만 허용합니다. 따라서 모든 protected apply는 container, identity, secret, platform 또는 authority check를 약화하지 않고 새로 검증 가능한 revision을 생성합니다. |
| 2026-08-10 | IS-09 | Bounded direct peer-state capture | Round 69 | Remote operability review에서 각 evidence run이 isolated backend state를 읽기 위해 full Terraform peer root 4개를 두 번씩 initialize하여 30-run serial proof가 수 시간의 provider 및 backend delay에 취약한 문제를 확인했습니다. 이제 peer capture는 이미 authenticated된 runner identity와 60초 stop condition으로 exact allowlisted backend blob을 Azure CLI를 통해 각각 download합니다. 기존 canonical state projection과 before/after digest verifier는 변경하지 않습니다. |
| 2026-08-10 | IS-09 | Adoption observation과 completion 분리 | Round 70 | Adoption replay review에서 Core의 durable schema observation은 이후 migration failure 전에 upload되었고, 후속 protected run은 동일 migration을 완료했지만 one-time artifact를 다시 생성하지 않은 사실을 확인했습니다. Adoption 이후 `initial-cutover` replay는 올바르게 차단됩니다. 이제 remote evidence는 exact artifact run과 exact later completion run을 별도로 binding하고 두 run의 GitHub workflow step을 모두 검증하며, original immutable schema 및 rollback record와 결합된 protected-main migration success만 허용합니다. |
| 2026-08-10 | IS-09 | Split adoption controls equivalence | Round 71 | Follow-up critique에서 split completion run과 artifact run은 각각 GitHub에 bind되지만 aggregate의 deployment controls와 비교되지 않는 문제를 확인했습니다. 이제 attestation verifier는 completion workflow head, artifact workflow head 및 artifact rollback-reference controls commit이 aggregate controls와 deployment-input-equivalent 상태를 유지하도록 요구합니다. 이를 통해 release-only commit은 허용하면서 materially different migration, workflow, infrastructure 또는 dependency controls를 조합한 adoption proof는 거부합니다. |
| 2026-08-10 | IS-09 | Historical adoption ancestry correction | Round 72 | Executable review에서 final-control equivalence를 요구하면 이후 rollout hardening이 deployment input을 변경했기 때문에 valid one-time adoption도 거부됨을 확인했습니다. 이제 adoption evidence는 cited revision 3개가 모두 final protected-main controls commit의 ancestor일 것을 요구합니다. Exact GitHub run, successful step, artifact digest, schema fingerprint 및 rollback-reference binding은 계속 필수이며 historical controls와 final controls가 equivalent라는 잘못된 주장만 제거합니다. Final transition plan은 계속 deployment-input equivalence를 요구합니다. |
| 2026-08-10 | IS-09 | Observable sidecar probe normalization | Round 73 | Worker apply `31361034521`은 healthy N revision에 도달했지만 verification이 empty header 및 path와 zero delay 같은 Terraform provider default를 hash했고 Azure Resource Manager는 해당 default를 생략했습니다. 이제 plan sealing은 ARM이 생략하는 exact default value만 제거하고 hashing 전에 unknown probe field를 거부합니다. Non-default threshold, delay, interval, timeout, transport 및 port는 계속 seal되며 observed revision과 정확히 일치해야 합니다. |
| 2026-08-10 | IS-09 | Bounded rollback revision suffix | Round 74 | 동일한 Worker failure에서 verbose automatic rollback suffix가 가장 긴 service name에 대한 Azure Container App combined 54-character revision-name limit를 초과하여 recovery를 시작할 수 없는 문제를 확인했습니다. 이제 rollback suffix는 lowercase `r` prefix와 unique workflow run id로 구성됩니다. 모든 canonical service name에 맞으면서 deterministic하고 collision-resistant하며, rollback은 계속 exact captured revision만 copy하고 restored image와 sidecar contract를 검증합니다. |
| 2026-08-10 | IS-09 | Corrected N-1 artifact rebuild | Round 75 | Live rollback에서 original 0.1.2 document image가 attached user-assigned identity를 선택할 수 없어 protected topology에서 ready 상태가 될 수 없음을 확인했습니다. 이제 dedicated artifact-only source가 current identity, probe 및 recovery hardening이 적용된 service code에서 distribution 5개의 0.1.2 artifact를 다시 build합니다. Source는 temporary이며 즉시 0.1.3 development line을 복원하는 commit이 이어집니다. Final evidence는 broken image를 relabel하지 않고 exact 0.1.2 source, supply-chain run, image digest 및 attestation을 고정합니다. |
| 2026-08-10 | IS-09 | N-1 override retirement | Round 76 | Supply-chain run `31367288968`은 tracked override가 active인 exact source `352c8d1e661a6a53f0958767550fd57c2b975706`에서 성공했으므로 immutable artifact는 계속 0.1.2입니다. 이후 run `31367329056`은 automatic release commit에 속하며 override source 이후 실패했습니다. 이제 `main`에서 override는 inactive이며 이후 모든 image build는 committed 0.1.3 service 및 lockfile version을 사용합니다. 이를 통해 patched N-1과 final N에 distinct하고 attributable한 source revision을 만들고 향후 0.1.2 artifact가 실수로 publish되는 것을 방지합니다. |
| 2026-08-10 | IS-09 | Corrected remote release binding | Round 77 | Release contract는 이제 remote N-1을 corrected source `352c8d1e661a6a53f0958767550fd57c2b975706`에 binding하고 historical local-focused N-1 source `9f1234f93d356dedbddcb3b88aa7bc4da38b2dc2`는 별도 field에 유지합니다. Corrected 0.1.2 SBOM 5개가 intended service package version을 보고하며 provenance, SBOM 및 Core resolved-model attestation이 exact source와 protected supply-chain signer에 대해 verify되었습니다. |
| 2026-08-10 | IS-09 | Per-run deployment controls | Round 78 | Final-proof critique에서 initial N run과 corrected rollback run이 서로 다른 protected-main revision을 사용하므로 aggregate controls SHA 하나만 강제하면 valid evidence를 거부하거나 history를 잘못 표현하는 문제를 확인했습니다. 이제 remote evidence는 각 plan/apply pair에 plan-sealed controls를 기록하고 apply controls가 해당 plan과 일치하도록 요구합니다. GitHub binder는 API-bound workflow head와 artifact-bound controls revision 각각이 aggregate controls와 deployment-input-equivalent임을 증명합니다. Final-evidence equivalence는 artifact-only image-build override helper만 제외하며 모든 service-deploy plan/apply input은 계속 strict하게 검사합니다. |
| 2026-08-10 | IS-09 | Controls-verifier coverage | Round 79 | Follow-up critique에서 unique transition workflow head와 plan-sealed controls revision이 모두 equivalence verifier에 도달하는 executable check를 추가했습니다. 이 check는 stage별 distinct controls와 중복 제거도 검증합니다. One-time adoption은 adoption 이후 rollout hardening이 deployment input을 의도적으로 변경했으므로 ancestry-bound 상태를 유지합니다. Exact run, successful step, artifact 및 rollback controls는 계속 독립적으로 binding됩니다. High 및 Medium severity residual은 0건입니다. |
| 2026-08-10 | IS-09 | Evidence-only comparator separation | Round 80 | Executable review에서 service-deploy comparator에 exception을 추가하면 comparator 자체가 historical initial controls와 달라져 equivalence 주장이 self-defeating 상태가 되고 apply boundary도 약해지는 문제를 확인했습니다. Service-deploy comparator를 byte-for-byte strict form으로 복원했습니다. 별도 final-evidence comparator는 supply-chain helper만 제외하고 root release version만 normalize하며 그 밖의 workflow, helper, Terraform, migration, dependency 또는 lock 변경을 모두 거부합니다. Focused test가 두 boundary를 증명하며 High 및 Medium severity residual은 계속 0건입니다. |
| 2026-08-10 | IS-09 | Attestation workflow import path | Round 81 | Clean runner 실행에서 `remote-evidence-attest.yml`의 plain Python entry point 2개가 repository root를 module search path에서 찾지 못해 validation 전에 `ModuleNotFoundError`로 실패하는 문제를 재현했습니다. 이제 exact protected checkout을 job-level Python path로 사용하며 workflow contract test가 이 binding을 고정합니다. Aggregate 및 GitHub binder 동작은 변경하지 않았고 repository import가 없으면 attestation 전에 계속 실패합니다. |
| 2026-08-10 | IS-09 | Recovery image state alignment | Round 82 | Fresh Ingestion plan `31376583061`은 out-of-band automatic recovery가 live image와 computed revision metadata를 변경했지만 Terraform state는 recovery 전 image를 유지하여 fail closed했습니다. 이제 plan guard는 observed image가 이미 attested된 planned-before image와 같고 나머지 차이가 computed revision name, FQDN 및 suffix뿐인 경우에만 이 shape를 허용합니다. 다른 image 또는 runtime, identity, secret, platform, authority 변경은 계속 차단합니다. |
| 2026-08-10 | IS-09 | Final evidence contract hardening | Round 83-84 | Round 83은 closed public manifest projection을 remote deployment-context scanning과 분리하여 generic local evidence key가 aggregate 생성을 차단하지 않도록 했습니다. Round 84는 한 service의 initial N plan과 restored N plan이 immutable context를 의도적으로 공유하지만 fresh revision suffix로 서로 다른 plan digest를 생성함을 증명했습니다. 이제 verifier는 동일한 service와 release에서만 context 재사용을 허용하며 cross-service 또는 cross-release 재사용, stale apply binding 및 중복 plan digest는 계속 차단합니다. Focused regression이 통과했고 High 또는 Medium severity residual은 0건입니다. |
| 2026-08-10 | IS-09 | Artifact redirect credential boundary | Round 85 | Live GitHub verification에서 API bearer token이 artifact redirect를 따라 GitHub Actions blob storage로 전달될 때 401이 발생하는 문제를 재현했습니다. 이제 downloader는 정확한 HTTPS Actions artifact host pattern만 허용하고 signed redirect를 따르기 전에 API authorization을 제거합니다. 신뢰할 수 없는 redirect origin은 fail closed하며 focused test에서 High 및 Medium severity residual은 0건을 유지합니다. |
| 2026-08-10 | IS-09 | Privileged workflow guard compatibility | Round 86 | Central validation은 처음에 portable `diff --brief` exact-source comparison을 거부했습니다. Contract가 GNU diff에서 지원하지 않는 `diff --quiet`만 인식했기 때문입니다. 이제 contract는 protected workflow path, source, ancestry 및 operand check를 유지하면서 portable exact-comparison flag를 허용합니다. Focused validation이 통과했고 High 또는 Medium severity residual은 0건입니다. |
| 2026-08-10 | IS-09 | Program-final remote proof | Round 87 | Fresh initial N apply 5개, corrected N-1 rollback apply 5개 및 restored N apply 5개가 직렬로 완료되어 protected plan 15개, protected apply 15개, peer-isolation receipt 30개 및 genuine kind-specific live observation을 확보했습니다. GitHub run `31385698545`가 모든 run과 artifact를 binding하고 image attestation과 controls equivalence를 검증한 뒤 exact evidence source `a721d1ae587af73b8f32986fe3b54acaae400b63`를 attest했습니다. Portable bundle이 protected signer에 대해 verify되었고 accepted remote evidence는 5/5이며 IS-09는 completed 상태이고 High 또는 Medium severity residual은 0건입니다. |
| 2026-08-10 | IS-09 | Strict completion checker typing | Round 88 | Final focused validation에서 dynamically loaded live-evidence builder가 runtime validation으로 exact tuple shape를 이미 요구하지만 completion-checker boundary에서는 `Any`를 반환하는 문제를 확인했습니다. 이제 checker는 검증된 return contract만 cast하며 strict mypy가 통과하고 High 또는 Medium severity residual은 계속 0건입니다. |
| 2026-08-10 | IS-09 | 완료 후 decomposition assurance | Round 89-108 | 독립 review round 20회에서 physical ownership, 금지된 implementation import, identity와 writer 격리, typed transport, restart 및 idempotency behavior, health boundary, migration, Terraform root 5개, N/N-1 ordering, rollback, peer isolation 및 attestation된 completion evidence를 다시 확인했습니다. 의심된 Executor defect 5건을 다음 근거로 반증했습니다. Core client instance id는 local asyncio task label에만 사용됩니다. 생성되는 모든 shadow receipt는 durable audit ref를 포함하며 enforce-mode `1.0.0` receipt는 effect 없이 reject만 할 수 있습니다. `/live`는 process liveness를 보고하고 `/ready`는 최신 receipt-outbox publication을 포함합니다. Compatibility manifest는 Core rollback 전에 Executor N-1을 요구하고 Executor migration 전에 Core N을 요구합니다. Adoption evidence는 이후 workflow health check가 실패한 경우에도 정확히 성공한 artifact step과 migration step을 별도로 binding합니다. Independent-service 및 focused compatibility gate 통과 후 contract, evidence, service focused test 351개가 통과했습니다. 재현 가능한 Medium 이상 residual은 없습니다. Document service implementation 양쪽을 함께 사용하는 ingestion service-local test module 2개는 Low test-ownership cleanup으로 남습니다. 이 test는 production distribution에 포함되지 않고 runtime dependency를 만들지 않습니다. |

## 관련 문서

| 알아볼 내용 | 문서 |
|-------------|------|
| 승격, ownership, rollback gate | [서비스 승격과 데이터 소유권](service-graduation-and-ownership-ko.md) |
| Repository package boundary | [프로젝트 구조](project-structure-ko.md) |
| Azure runtime과 identity deployment | [배포 및 온보딩](../deployment/deploy-and-onboard-ko.md) |
| Operating ontology release boundary | [운영 온톨로지 플랫폼](operating-ontology-platform-ko.md) |
| Operator package ownership | [Operator Console Module Map](../interfaces/operator-console-module-map-ko.md) |
