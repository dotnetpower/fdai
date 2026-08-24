---
title: Architecture Review Board 패킷
translation_of: architecture-review-board.md
translation_source_sha: f33e836df6814600fc299dd1543821a154560295
translation_revised: 2026-08-24
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

## 문서 모음

이 진입점은 간결하게 유지하고 완전한 설계는 역할이 분명한 문서가 담당합니다.

| 문서 | 담당 범위 |
|------|-----------|
| [온톨로지 기반 에이전트 루프](architecture-review/ontology-agent-loop-ko.md) | 권위 있는 온톨로지 상태, 15개 에이전트 책임, 근거 분기, 결정적 결합, 자율 검토 수준 |
| [근거 및 권한](architecture-review/evidence-and-authority-ko.md) | 근거 레인, 담당자 연결, 위험, 예외, 승인 무결성, 결정 증적, 운영 종료 |
| [전달 계획](architecture-review/delivery-plan-ko.md) | 의존성 순서에 따른 5개 작업 패키지, 첫 수직 경로, 검증 매트릭스 |
| [구현 원장](../../roadmap-implementation/architecture/architecture-review-board.md) | 이 진입점의 현재 구현 범위, 추가 전용 이력, 남은 작업 |

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

## 검토 및 근거 모델

[온톨로지 에이전트 루프](architecture-review/ontology-agent-loop-ko.md)는 모든 전이를 고정된
판테온의 책임 에이전트에게 할당하고 `Change`, 컨텍스트, 근거, `DecisionCase`, 승인, 결과
레코드에서 검토 상태를 파생합니다. [근거 및 권한 계약](architecture-review/evidence-and-authority-ko.md)은
운영 근거 프로필, 담당자 슬롯, 위험 및 예외 레코드, 변경할 수 없는 결정 증적, 실패 동작,
운영 종료 절차를 정의합니다.

`ReviewCase`와 `ReviewCheck`는 읽기 모델입니다. Process와 Console을 위해 권위 있는 계보를
요약하지만 판단, 승인, 실행 권한을 부여하지 않습니다.

## 결정

ADR index는 [Architecture Decision Records](decisions/README-ko.md)입니다. ADR-0001은 승인된
Azure day-zero platform baseline을 기록합니다. Numeric RPO/RTO, retention, cost cap,
production owner 같은 환경 결정은 숨겨진 architecture default가 아니라 fork binding입니다.

## Runtime 상태 및 수동 review

게시된 workflow app은 `/workflow-apps/architecture-review`에서 사용할 수 있습니다. 선택한
Process view는 선언형 view 및 report catalog를 통해 `/processes/{process_id}`에서 렌더링됩니다.
Manifest가 유효하지만 production evidence가 없으면 구조는 healthy로 유지되고 production
gate는 blocked 상태를 유지합니다. Process projection은 workflow 상태, review check, owner 및
evidence binding, approval, decision을 typed ontology object로 유지합니다.

Contributor는 `POST /workflows/run`을 통해 개정에 결합된 관찰 모드 검토를 제출할 수 있습니다.
Operator API는 현재 `mode=enforce`를 수락하지 않습니다. 권한을 수반하는 워크플로 경로와
로컬 및 배포 운영 근거는 아직 남은 작업입니다. ARB는 제어 전용으로 유지됩니다. 향후 거버넌스가
적용된 결정은 승인과 결정 전이를 저장할 수 있지만, 모든 리소스 변경은 일반 ActionType, 정책,
위험, 승인, 실행, 검증, 복구 경로로 다시 들어갑니다.

## 다음 단계

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| 승인된 platform 결정 | [Architecture Decision Records](decisions/README-ko.md) |
| 온톨로지 및 15개 에이전트 검토 루프 | [온톨로지 기반 에이전트 루프](architecture-review/ontology-agent-loop-ko.md) |
| 근거, 담당 체계, 승인, 운영 종료 | [근거 및 권한](architecture-review/evidence-and-authority-ko.md) |
| 의존성 순서에 따른 구현 | [전달 계획](architecture-review/delivery-plan-ko.md) |
| Data와 privacy evidence | [Data Governance](data-governance-ko.md) |
| Deployment inventory | [Deploy and Onboard](../deployment/deploy-and-onboard-ko.md) |
| Operational handoff | [Operational Readiness](../operations/operational-readiness-ko.md) |
| Machine-readable readiness 상태 | [`config/architecture-review.yaml`](../../../config/architecture-review.yaml) |
| 구현 상태 및 남은 작업 | [구현 원장](../../roadmap-implementation/architecture/architecture-review-board.md) |
