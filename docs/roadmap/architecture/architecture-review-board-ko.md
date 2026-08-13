---
title: Architecture Review Board 패킷
translation_of: architecture-review-board.md
translation_source_sha: 616b10287ea0c403d3ea2f2d82e06ca0fe8e81d2
translation_revised: 2026-08-13
---
# Architecture Review Board 패킷

이 패킷은 FDAI target architecture를 검토하는 canonical entry point입니다. 설계 baseline
승인과 production 배포 또는 enforce 승인 범위를 분리하고, 모든 주장을 repository artifact
또는 포크가 제공하는 evidence binding에 연결합니다.

> **요청 결정:** Azure target-architecture baseline을 조건부 승인합니다.
> `config/architecture-review.yaml`이 `production_approval_status: blocked`를 보고하는 동안
> production 배포와 enforce-mode 승인은 범위에 포함되지 않습니다.
>
> **Customer 경계:** Upstream은 재사용 가능한 architecture와 evidence contract를 정의합니다.
> 포크는 환경 값, 책임자, privacy 결정, 서비스 목표, production evidence를 제공합니다.

## 한눈에 보는 설계

FDAI는 non-privileged console과 GitOps/ChatOps delivery를 사용하는 agent-driven headless control
plane입니다. 고정된 15개 에이전트가 typed pub/sub를 통해 sensing, judgment, arbitration,
approval, execution, verification, recovery, audit, learning을 소유합니다. 운영 온톨로지는
supporting truth 및 safety infrastructure이며 agent interpretation을 제한하지만 authority를
부여하거나 직접 행동하지 않습니다.

반복 가능한 event는 T0 deterministic rule과 T1 verified reuse로 해결하고 residual ambiguity만
T2 grounded reasoning으로 보냅니다. 모든 mutation은 risk gate를 통과하고 stop, rollback,
impact, audit, independent effect-verification contract를 가지며 shadow mode에서 시작합니다.

FDAI는 이를 **[Outcome-Driven Token Economics](llm-strategy-ko.md#비용-컨트롤cost-controls)**라고
부릅니다. Ontology-grounded T0/T1 경로를 기본으로 사용하고, 남은 모호성이나 위험에만 원문
검색, 더 강한 모델, verification, 사람 승인을 사용하여 모델 호출, token, latency, 비용은
최소화하고 검증된 운영 가치는 최대화합니다. 정확도와 safety는 비용보다 우선하는 제약입니다.

## 결정 경계

| 결정 | 현재 요청 | 승인 효과 |
|------|-----------|-----------|
| Target architecture | 조건부 승인 | 시스템 경계, Azure day-zero 선택, control loop, safety model을 수락합니다. |
| Production 배포 | 요청하지 않음 | Production evidence gate 통과가 필요합니다. |
| Enforce-mode capability | 요청하지 않음 | Action별 shadow evidence와 별도 승인이 필요합니다. |
| Hyperscale Plan B | 참고만 제공 | Hyperscale 설계의 측정 trigger를 넘을 때만 적용됩니다. |
| Sovereign profile | 참고만 제공 | 별도 규제 및 residency 검토가 필요합니다. |

Machine-readable 결정 상태는
[`config/architecture-review.yaml`](../../../config/architecture-review.yaml)에 있습니다. 모든
변경에서 구조 검사를 실행합니다.

```bash
python3 scripts/governance/check-arb-readiness.py
```

Production promotion pipeline은 fail-closed 형식을 사용합니다.

```bash
python3 scripts/governance/check-arb-readiness.py --require-production-ready
```

## 범위와 컨텍스트

### 포함 범위

- Headless control plane의 Azure 구현과 provider 경계.
- Kafka endpoint를 통한 Event Hubs, Container Apps, pgvector를 포함한 PostgreSQL Flexible
  Server, Key Vault reference, managed identity, Log Analytics, Application Insights.
- T0/T1/T2 control loop, quality gate, unified risk gate, executor, audit, GitOps, HIL.
- Shadow-before-enforce 제어가 적용되는 development, staging, production artifact promotion.
- Day-zero 운영, rollback, observability, 비용, cell-based scale로 가는 측정 경로.

### 이번 결정에서 제외되는 범위

- 비-Azure provider 구현.
- Customer-specific rule, threshold, identity, endpoint, organization policy.
- Upstream에서 owner 및 evidence binding이 비어 있으므로 production 승인.
- Plan B 배포, sovereign-profile 인증, secondary-region resource.

## Architecture view

| View | 설계 authority | 검토 초점 |
|------|----------------|-----------|
| System context와 layer 경계 | [App Shape](../../../.github/instructions/app-shape.instructions.md) | 사람, Git, ChatOps, console, core, privileged executor 경계 |
| Control flow | [Architecture](../../../.github/instructions/architecture.instructions.md) | event ingest, tiering, verification, risk decision, execution, audit |
| Module과 deployment mapping | [Project Structure](project-structure-ko.md) | ownership 경계와 provider adapter |
| Azure day-zero deployment | [Deploy and Onboard](../deployment/deploy-and-onboard-ko.md) | concrete resource inventory와 bootstrap 순서 |
| Identity와 data flow | [Security and Identity](security-and-identity-ko.md) | trust boundary, authorization, secret, STRIDE threat |
| Scale transition | [Hyperscale Cell Architecture](hyperscale-cell-architecture-ko.md) | 단일 cell에서 sharded cell로 이동하는 trigger |

### Current, target, transition 상태

| 상태 | 설명 | Evidence 상태 |
|------|------|---------------|
| Current upstream | 재사용 코드, Terraform module, test, generic config, 설계 문서이며 customer production 값은 포함하지 않습니다. | 이 repository에서 검증할 수 있습니다. |
| Day-zero target | 단일 Azure region, Container Apps cell 하나, Event Hubs Kafka, PostgreSQL + pgvector, Key Vault, scoped managed identity, Log Analytics | ADR-0001에서 설계가 결정되었으며 production evidence는 추가로 필요합니다. |
| Production target | Signed image, private 또는 allow-listed data flow, bound owner, 승인 objective, blocking release control, operational-readiness report | Manifest production gate가 통과할 때까지 blocked입니다. |
| Scale target | 여러 cell, policy-driven fan-in, CQRS audit indexing, deployment profile | 측정 trigger를 넘을 때까지 deferred입니다. |

## 요구 사항 추적

| 요구 사항 | 설계 대응 | 검증 source |
|-----------|-----------|-------------|
| Agent-owned closed loop | observe, decide, plan, execute, verify, recover, learn transition별 accountable agent 하나 | Pantheon parity, topic ownership, lifecycle test |
| Deterministic-first 결정 | T0 exact rule, T1 reuse, quality-gated T2 순서 | Tier test와 frozen scenario set |
| Contract-conformant accuracy | wrong-target, unauthorized, policy escape, unverified success outcome을 0으로 유지 | Guard metric과 outcome receipt |
| 최소 사람 개입 | evidence recovery, reevaluation, 더 작은 safe plan, no-op, rollback을 사람 검토보다 먼저 수행 | Touchpoint metric과 escalation trace |
| Ungated autonomous mutation 방지 | Unified risk gate와 role-bound executor | Risk-gate property test와 audit evidence |
| 직무 분리 | Requester, approver, judge, executor를 별도 principal로 유지 | RBAC config와 HIL test |
| Retry 안전성 | Stable idempotency key와 resource별 serialization | Idempotency와 replay test |
| 복구 가능성 | ActionType별 rollback contract와 stop condition | Rollback rehearsal evidence |
| Customer 격리 | Fork-supplied 값과 dependency injection | Generic-scope gate와 config validation |
| 운영 가능성 | Health signal, canary, smoke, alert routing, runbook | Operational-readiness report |
| 비용 제어 | Scale-to-zero, token budget, resource budget, 측정 graduation trigger | Cost confirmation과 capacity evidence |

## Nonfunctional evidence contract

배포에 따라 달라지는 target은 upstream universal constant가 아닙니다. Production deployment는 승인
값, 측정 방법, 결과, timestamp, approver를 evidence binding에 기록합니다.

| 영역 | 필수 production evidence | 통과 조건 |
|------|--------------------------|-----------|
| Availability | Control-plane SLO와 error budget | 승인 objective와 측정된 staging 결과 |
| Latency | Tier별 p50/p95/p99와 end-to-end canary | 포크 승인 budget 이내 |
| Capacity | 지속/burst event rate, partition lag, DB saturation, quota headroom | 손실 없음, bounded lag, saturation point 기록 |
| Reliability | Service별 RPO/RTO와 business-impact analysis | Numeric objective 승인 |
| Recovery | Isolated restore와 regional failover/failback drill | Integrity와 smoke 통과, primary fencing, event recovery 및 failback 검증, objective 충족 |
| Security | Threat review, private/allow-listed data-flow validation, least-privilege probe | 미해결 critical/high finding 없음 |
| Privacy | Privacy impact assessment와 data inventory | Privacy owner 승인 |
| Operations | Signed operational-readiness report, canary, smoke, alert, runbook evidence | 모든 production check 통과 |
| Supply chain | SBOM, signature, provenance, vulnerability/IaC scan | Release artifact 검증, blocking scan clean |
| Cost | 최신 calculator export, monthly cap, quota, 12/36개월 assumption | Cost owner 승인 |

## Data, privacy, compliance

[Data Governance](data-governance-ko.md)는 classification, minimization, residency, retention,
legal hold, deletion, model provider, privacy-assessment contract를 정의합니다. Upstream 설계는
customer compliance certification을 주장하지 않습니다. Deployment owner는 control profile을
선택하고 control을 evidence에 mapping하며 exception과 privacy/data owner를 기록합니다.

## Ownership과 support

Production gate는 다음 accountable slot을 요구합니다. Group이 slot을 채울 수 있지만 모든
binding은 escalation route와 직무 분리가 필요한 경우 별도 approval authority를 식별해야 합니다.

| Owner slot | 책임 범위 |
|------------|-----------|
| `architecture-owner` | Architecture baseline, ADR, accepted technical debt |
| `security-owner` | Threat model, identity, network posture, security exception |
| `privacy-owner` | Privacy impact assessment와 data-processing 결정 |
| `data-owner` | Classification, retention, legal hold, deletion, data quality |
| `operations-owner` | On-call, alert, runbook, operational-readiness 수락 |
| `reliability-owner` | SLO, RPO/RTO, recovery 설계, drill 수락 |
| `release-owner` | Artifact provenance, deployment, rollback, promotion gate |
| `cost-owner` | Budget, quota, price 확인, capacity graduation |

Agent stewardship는 별도 accountability overlay입니다. Authorization을 부여하거나 production
owner slot을 대체하지 않습니다.

각 `owner_bindings` entry는 다음 shape를 사용합니다.

```yaml
architecture-owner:
   subject: group:<fork-owned-subject>
   escalation: <fork-owned-escalation-route>
```

각 `evidence_bindings` entry는 evidence body가 아니라 immutable evidence metadata입니다.

```yaml
production-terraform-plan:
   uri: evidence://<governed-store-reference>
   sha256: <64-lowercase-hex-digest>
   approved_by: group:<fork-owned-approver>
   approved_at: 2026-07-13T00:00:00Z
   expires_at: 2027-01-13T00:00:00Z
```

Checker는 unknown binding key, missing field, malformed digest, invalid timestamp를 차단합니다.
`expires_at`은 `approved_at`보다 뒤여야 하며 만료된 binding은 production readiness를
차단합니다. Customer name, resource id, evidence body는 포크의 governed store에 유지합니다.

Upstream required-evidence key는 Azure Well-Architected Reliability `RE:01-10` 및 Operational
Excellence `OE:01-11` Best Practice requirement 전체를 커버합니다. Checklist evaluator는
control에 더 짧은 freshness window가 선언된 경우 이를 적용합니다. Binding expiry는 외부 validity
ceiling이며 control-specific freshness window를 연장하지 않습니다.

## Dependency와 failure behavior

| Dependency | 계약 | Failure behavior | Production evidence |
|------------|------|------------------|---------------------|
| Event Hubs Kafka | Ordered at-least-once event log와 DLQ topic | Backpressure 또는 사람 검토, silent drop 없음 | Round-trip, lag, replay, DLQ test |
| PostgreSQL + pgvector | Transactional state, audit projection, T1 vector | Fail closed, production in-memory fallback 없음 | Connection, backup, restore, saturation test |
| Key Vault reference | Environment secret injection | 필수 secret 미해결 시 startup 실패 | Rotation과 unavailable-vault test |
| Entra와 managed identity | Short-lived audience-scoped identity | Access deny, credential fallback 없음 | Least-privilege와 recertification evidence |
| Git host | Reviewed remediation와 governance 변경 | Proposal queue, out-of-band 실행 없음 | Protected-branch와 rollback test |
| HIL channel | Authenticated action-bound approval | Queue 및 fallback 사용, timeout은 no-op | Primary/fallback 및 replay-resistance test |
| Model provider | Budgeted grounded T2 및 narrator access | unavailable 또는 unverified이면 사람 검토 | Provider, residency, retention, budget evidence |
| Observability backend | Correlated log, metric, trace, alert | Monitor-of-monitor signal 발생 | Canary와 alert delivery 결과 |

## 결정

ADR index는 [Architecture Decision Records](decisions/README-ko.md)입니다. ADR-0001은 승인된
Azure day-zero platform baseline을 기록합니다. Numeric RPO/RTO, retention, cost cap,
production owner 같은 환경 결정은 숨겨진 architecture default가 아니라 fork binding입니다.

## Risk, assumption, issue, exception

Active critical/high risk는 `config/architecture-review.yaml`의 `blockers`에 machine-readable
형태로 있습니다.

| 유형 | 규칙 |
|------|------|
| Risk | Severity, accountable owner slot, mitigation, residual risk, review date를 가집니다. |
| Assumption | Validation evidence를 식별하며 반증되거나 측정되면 만료됩니다. |
| Issue | 종료하는 artifact 또는 implementation에 연결됩니다. |
| Exception | 범위가 제한되고 필요한 경우 time-bound이며 별도 승인과 audit를 가집니다. |

Accepted risk는 resolved blocker가 아닙니다. Production gate는 critical/high 항목의 status와
evidence가 review를 통해 갱신된 후에만 수락합니다.

## Runtime 상태 및 수동 review

게시된 workflow app은 `/workflow-apps/architecture-review`에서 사용할 수 있습니다. 선택한
Process view는 선언형 view 및 report catalog를 통해 `/processes/{process_id}`에서 렌더링됩니다.
Manifest가 유효하지만 production evidence가 없으면 구조는 healthy로 유지되고 production
gate는 blocked 상태를 유지합니다. Process projection은 workflow 상태, review check, owner 및
evidence binding, approval, decision을 typed ontology object로 유지합니다.

Contributor는 `POST /workflows/run`으로 shadow review를 시작하거나 재개할 수 있습니다.
Owner는 `architecture-review`가 `FDAI_WORKFLOW_ENFORCE_ALLOWLIST`에 있을 때만
`mode=enforce`를 요청할 수 있습니다. ARB는 control-only이므로 enforce는 실제 approval 및
decision transition을 저장하지만 resource를 배포하거나 ActionType을 승격하지 않습니다.

## Implementation status

재사용 가능한 ARB contract, fail-closed production gate, workflow, ontology projection,
read-only workflow app은 구현되어 있습니다. Upstream manifest에는 의도적으로 customer owner
및 evidence binding이 없고 모든 critical/high blocker가 open 상태이므로 production readiness는
blocked 상태를 유지합니다.

### Implementation scope

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| Machine-readable review contract와 readiness checker | implemented | `config/architecture-review.yaml`; `core/architecture_review/readiness.py`; `scripts/governance/check-arb-readiness.py`; 집중 readiness test | 구조 상태와 production readiness를 별도로 평가하며 malformed, incomplete, unknown, expired evidence는 fail closed 처리됩니다. |
| Review workflow, production gate, ontology projection | implemented | `rule-catalog/workflows/architecture-review.yaml`; `core/architecture_review/projection.py`; `runtime/control_loop.py`; 집중 projection test | Control-only workflow는 resource를 배포하거나 ActionType을 활성화하지 않고 check, approval, decision을 기록합니다. |
| 선언형 운영자 review 화면 | implemented | `rule-catalog/operator-console/architecture-review.yaml`, `views/architecture-review.yaml`, `reports/architecture-review-process.yaml`; 집중 view 및 report test | 게시된 read-only workflow app과 Process view는 catalog로 검증된 경로를 통해 projection된 review 상태를 노출합니다. |
| Production owner binding, evidence, approval | in-progress | `config/architecture-review.yaml`은 `production_approval_status: blocked`, 빈 binding map, open 상태의 critical/high blocker를 보고합니다. | Repository test는 gate 동작을 입증하지만 customer production 승인 또는 거버넌스된 runtime 결과를 입증하지 않습니다. |

### Implementation history

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-08-13 | in-progress | 구현 원장을 도입하고 runtime 노출을 선언형 workflow app에 맞게 수정했으며 재사용 가능한 ARB 구현과 production 승인을 구분했습니다. | Current change: 이 문서 쌍과 위 scope evidence이며 집중 ARB readiness, projection, view, report test 명령에서 19개 test가 통과했습니다. 이전 provenance는 재구성하지 않았습니다. | Production owner와 거버넌스된 evidence를 binding하고 blocker를 해결하며 승인된 runtime decision을 기록해야 합니다. |

### Remaining work

- [ ] Customer fork에서 모든 필수 owner 및 evidence binding을 채우고 모든 critical/high blocker를 해결하거나 정식으로 accept한 뒤 만료되지 않은 거버넌스 evidence에 대해 `python3 scripts/governance/check-arb-readiness.py --require-production-ready` 통과 결과를 기록합니다.
- [ ] Production gate를 통과하고 필요한 독립 owner 승인을 받은 staging `architecture-review` Process를 기록하며 resource 배포나 ActionType 승격 없이 signed decision과 audit receipt가 영속화되는지 입증합니다.

## Production 종료 절차

1. Customer 포크에서 모든 필수 owner slot을 binding합니다.
2. 필수 evidence artifact를 첨부하고 upstream repository에는 secret/customer data가 없도록
   확인합니다.
3. 적절한 governance path에서 각 blocker를 해결하거나 공식적으로 accept합니다.
4. Production artifact를 `ready`로 표시하고 design review를 승인한 뒤 production approval을
   `ready`로 설정합니다.
5. Promotion job에서 `python3 scripts/governance/check-arb-readiness.py --require-production-ready`를
   실행합니다.
6. ARB 결정, approver, condition, exception expiry를 audit store에 기록합니다.

이 gate를 통과하면 production deployment review를 진행할 수 있습니다. 어떤 ActionType도
자동으로 enable되지 않으며 각 capability는 별도 shadow-to-enforce promotion gate를 따릅니다.

## 다음 단계

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| 승인된 platform 결정 | [Architecture Decision Records](decisions/README-ko.md) |
| Data와 privacy evidence | [Data Governance](data-governance-ko.md) |
| Deployment inventory | [Deploy and Onboard](../deployment/deploy-and-onboard-ko.md) |
| Operational handoff | [Operational Readiness](../operations/operational-readiness-ko.md) |
| Machine-readable readiness 상태 | [`config/architecture-review.yaml`](../../../config/architecture-review.yaml) |
