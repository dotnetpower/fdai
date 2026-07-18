---
title: Architecture Review Board 패킷
translation_of: architecture-review-board.md
translation_source_sha: fcfd38edba8fe4000e61716884b85b05a3d093ce
translation_revised: 2026-07-18
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

FDAI는 read-only console과 GitOps/ChatOps delivery를 사용하는 headless event-driven control
plane입니다. 반복 가능한 event는 T0 deterministic rule과 T1 similarity reuse로 해결하고,
모호한 case만 T2 grounded reasoning으로 보냅니다. 모든 변경 proposal은 risk gate를 통과하고
stop condition, rollback contract, blast-radius limit, audit record를 가지며 shadow mode에서
시작합니다.

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
| Deterministic-first 결정 | T0 exact rule, T1 reuse, quality-gated T2 순서 | Tier test와 frozen scenario set |
| Ungated autonomous mutation 방지 | Unified risk gate와 role-bound executor | Risk-gate property test와 audit evidence |
| 직무 분리 | Requester, approver, judge, executor를 별도 principal로 유지 | RBAC config와 HIL test |
| Retry 안전성 | Stable idempotency key와 resource별 serialization | Idempotency와 replay test |
| 복구 가능성 | ActionType별 rollback contract와 stop condition | Rollback rehearsal evidence |
| Customer 격리 | Fork-supplied 값과 dependency injection | Generic-scope gate와 config validation |
| 운영 가능성 | Health signal, canary, smoke, alert routing, runbook | Operational-readiness report |
| 비용 제어 | Scale-to-zero, token budget, resource budget, 측정 graduation trigger | Cost confirmation과 capacity evidence |

## Nonfunctional evidence contract

배포에 따라 달라지는 target은 upstream universal constant가 아닙니다. Production 포크는 승인
값, 측정 방법, 결과, timestamp, approver를 evidence binding에 기록합니다.

| 영역 | 필수 production evidence | 통과 조건 |
|------|--------------------------|-----------|
| Availability | Control-plane SLO와 error budget | 승인 objective와 측정된 staging 결과 |
| Latency | Tier별 p50/p95/p99와 end-to-end canary | 포크 승인 budget 이내 |
| Capacity | 지속/burst event rate, partition lag, DB saturation, quota headroom | 손실 없음, bounded lag, saturation point 기록 |
| Reliability | Service별 RPO/RTO와 business-impact analysis | Numeric objective 승인 |
| Recovery | Isolated restore와 failover drill | Integrity 및 smoke check 통과, objective 충족 |
| Security | Threat review, private/allow-listed data-flow validation, least-privilege probe | 미해결 critical/high finding 없음 |
| Privacy | Privacy impact assessment와 data inventory | Privacy owner 승인 |
| Operations | Signed operational-readiness report, canary, smoke, alert, runbook evidence | 모든 production check 통과 |
| Supply chain | SBOM, signature, provenance, vulnerability/IaC scan | Release artifact 검증, blocking scan clean |
| Cost | 최신 calculator export, monthly cap, quota, 12/36개월 assumption | Cost owner 승인 |

## Data, privacy, compliance

[Data Governance](data-governance-ko.md)는 classification, minimization, residency, retention,
legal hold, deletion, model provider, privacy-assessment contract를 정의합니다. Upstream 설계는
customer compliance certification을 주장하지 않습니다. Production 포크는 control profile을
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
```

Checker는 unknown binding key, missing field, malformed digest, invalid timestamp를 차단합니다.
Customer name, resource id, evidence body는 포크의 governed store에 유지합니다.

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
