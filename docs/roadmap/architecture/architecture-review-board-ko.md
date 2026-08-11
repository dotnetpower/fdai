---
title: Architecture Review Board 패킷
translation_of: architecture-review-board.md
translation_source_sha: b7fff7f1b6c38d0a71f415972ed95767b2221f7c
translation_revised: 2026-08-11
---
# 아키텍처 검토 Board 패킷

이 패킷은 FDAI 대상 아키텍처를 검토하는 정본 항목 지점입니다. 설계 기준선
승인과 운영 배포 또는 강제 적용 승인 범위를 분리하고, 모든 주장을 저장소 산출물
또는 포크가 제공하는 근거 연결에 연결합니다.

> **요청 결정:** Azure target-architecture 기준선을 조건부 승인합니다.
> `config/architecture-review.yaml`이 `production_approval_status: blocked`를 보고하는 동안
> 운영 배포와 enforce-mode 승인은 범위에 포함되지 않습니다.
>
> **Customer 경계:** 업스트림은 재사용 가능한 아키텍처와 근거 계약을 정의합니다.
> 포크는 환경 값, 책임자, privacy 결정, 서비스 목표, 운영 근거를 제공합니다.

## 한눈에 보는 설계

FDAI는 non-privileged 콘솔과 GitOps/ChatOps 전달을 사용하는 agent-driven headless 컨트롤
평면입니다. 고정된 15개 에이전트가 타입이 지정된 pub/sub를 통해 sensing, judgment, 중재,
승인, 실행, 검증, 복구, 감사, learning을 소유합니다. 운영 온톨로지는
supporting truth 및 안전성 infrastructure이며 에이전트 interpretation을 제한하지만 권한을
부여하거나 직접 행동하지 않습니다.

반복 가능한 이벤트는 T0 결정론적 룰과 T1 검증된 reuse로 해결하고 잔여 모호함만
T2 근거에 기반한 reasoning으로 보냅니다. 모든 변경은 risk 게이트를 통과하고 stop, 롤백,
영향, 감사, 독립적인 effect-verification 계약을 가지며 그림자 모드에서 시작합니다.

FDAI는 이를 **[Outcome-Driven 토큰 Economics](llm-strategy-ko.md#비용-컨트롤cost-controls)**라고
부릅니다. Ontology-grounded T0/T1 경로를 기본으로 사용하고, 남은 모호성이나 위험에만 원문
검색, 더 강한 모델, 검증, 사람 승인을 사용하여 모델 호출, 토큰, 지연 시간, 비용은
최소화하고 검증된 운영 가치는 최대화합니다. 정확도와 안전성은 비용보다 우선하는 제약입니다.

## 결정 경계

| 결정 | 현재 요청 | 승인 효과 |
|------|-----------|-----------|
| 대상 아키텍처 | 조건부 승인 | 시스템 경계, Azure day-zero 선택, 컨트롤 루프, 안전성 모델을 수락합니다. |
| 운영 배포 | 요청하지 않음 | 운영 근거 게이트 통과가 필요합니다. |
| Enforce-mode 기능 | 요청하지 않음 | 액션별 그림자 근거와 별도 승인이 필요합니다. |
| Hyperscale 계획 B | 참고만 제공 | Hyperscale 설계의 측정 트리거를 넘을 때만 적용됩니다. |
| Sovereign 프로파일 | 참고만 제공 | 별도 규제 및 residency 검토가 필요합니다. |

기계가 읽는 결정 상태는
[`config/architecture-review.yaml`](../../../config/architecture-review.yaml)에 있습니다. 모든
변경에서 구조 검사를 실행합니다.

```bash
python3 scripts/governance/check-arb-readiness.py
```

운영 승격 파이프라인은 실패 시 차단 형식을 사용합니다.

```bash
python3 scripts/governance/check-arb-readiness.py --require-production-ready
```

## 범위와 컨텍스트

### 포함 범위

- Headless 컨트롤 평면의 Azure 구현과 프로바이더 경계.
- Kafka 엔드포인트를 통한 Event Hubs, Container Apps, pgvector를 포함한 PostgreSQL Flexible
 서버, Key Vault 참조, managed 신원, Log Analytics, Application Insights.
- T0/T1/T2 컨트롤 루프, quality 게이트, unified risk 게이트, 실행기, 감사, GitOps, HIL.
- Shadow-before-enforce 제어가 적용되는 개발, staging, 운영 산출물 승격.
- Day-zero 운영, 롤백, observability, 비용, cell-based 규모로 가는 측정 경로.

### 이번 결정에서 제외되는 범위

- 비-Azure 프로바이더 구현.
- Customer-specific 룰, 임계값, 신원, 엔드포인트, organization 정책.
- 업스트림에서 소유자 및 근거 연결이 비어 있으므로 운영 승인.
- 계획 B 배포, sovereign-profile 인증, secondary-region 리소스.

## 아키텍처 화면

| 화면 | 설계 권한 | 검토 초점 |
|------|----------------|-----------|
| System 맥락과 계층 경계 | [App 형태](../../../.github/instructions/app-shape.instructions.md) | 사람, Git, ChatOps, 콘솔, 코어, privileged 실행기 경계 |
| 컨트롤 흐름 | [아키텍처](../../../.github/instructions/architecture.instructions.md) | 이벤트 ingest, tiering, 검증, risk 결정, 실행, 감사 |
| 모듈과 배포 대응 | [Project Structure](project-structure-ko.md) | 소유권 경계와 프로바이더 어댑터 |
| Azure day-zero 배포 | [Deploy and Onboard](../deployment/deploy-and-onboard-ko.md) | 구체적인 리소스 인벤토리와 초기화 순서 |
| 신원과 데이터 흐름 | [Security and 신원](security-and-identity-ko.md) | trust 경계, 권한 확인, 시크릿, STRIDE threat |
| 규모 전이 | [Hyperscale Cell 아키텍처](hyperscale-cell-architecture-ko.md) | 단일 cell에서 sharded cell로 이동하는 트리거 |

### 현재, 대상, 전이 상태

| 상태 | 설명 | 근거 상태 |
|------|------|---------------|
| 현재 업스트림 | 재사용 코드, Terraform 모듈, 테스트, 범용 구성, 설계 문서이며 customer 운영 값은 포함하지 않습니다. | 이 저장소에서 검증할 수 있습니다. |
| Day-zero 대상 | 단일 Azure 지역, Container Apps cell 하나, Event Hubs Kafka, PostgreSQL + pgvector, Key Vault, scoped managed 신원, Log Analytics | ADR-0001에서 설계가 결정되었으며 운영 근거는 추가로 필요합니다. |
| 운영 대상 | Signed 이미지, 비공개 또는 allow-listed 데이터 흐름, 한계 소유자, 승인 목표, 차단 release 컨트롤, operational-readiness 보고 | 매니페스트 운영 게이트가 통과할 때까지 차단된입니다. |
| 규모 대상 | 여러 cell, policy-driven fan-in, CQRS 감사 인덱싱, 배포 프로파일 | 측정 트리거를 넘을 때까지 deferred입니다. |

## 요구 사항 추적

| 요구 사항 | 설계 대응 | 검증 출처 |
|-----------|-----------|-------------|
| Agent-owned closed 루프 | observe, decide, 계획, execute, verify, recover, learn 전이별 accountable 에이전트 하나 | Pantheon 동등성, 토픽 소유권, 수명 주기 테스트 |
| Deterministic-first 결정 | T0 exact 룰, T1 reuse, quality-gated T2 순서 | Tier 테스트와 고정된 시나리오 집합 |
| Contract-conformant accuracy | wrong-target, 승인되지 않은, 정책 escape, 검증되지 않은 성공 결과를 0으로 유지 | 가드 메트릭과 결과 증적 |
| 최소 사람 개입 | 근거 복구, reevaluation, 더 작은 safe 계획, no-op, 롤백을 사람 검토보다 먼저 수행 | Touchpoint 메트릭과 에스컬레이션 추적 |
| Ungated 자율 변경 방지 | Unified risk 게이트와 role-bound 실행기 | Risk-gate 속성 테스트와 감사 근거 |
| 직무 분리 | 요청자, 승인자, 판정자, 실행기를 별도 principal로 유지 | RBAC 구성과 HIL 테스트 |
| 재시도 안전성 | 고정된 멱등성 키와 리소스별 직렬화 | 멱등성과 재생 테스트 |
| 복구 가능성 | ActionType별 롤백 계약과 stop 조건 | Rollback 예행 연습 근거 |
| Customer 격리 | Fork-supplied 값과 의존성 주입 | Generic-scope 게이트와 구성 검증 |
| 운영 가능성 | Health 신호, canary, smoke, alert 라우팅, 런북 | Operational-readiness 보고 |
| 비용 제어 | Scale-to-zero, 토큰 예산, 리소스 예산, 측정 graduation 트리거 | 비용 확인과 용량 근거 |

## Nonfunctional 근거 계약

배포에 따라 달라지는 대상은 업스트림 universal constant가 아닙니다. 운영 배포는 승인
값, 측정 방법, 결과, 시각, 승인자를 근거 연결에 기록합니다.

| 영역 | 필수 운영 근거 | 통과 조건 |
|------|--------------------------|-----------|
| 가용성 | Control-plane SLO와 오류 예산 | 승인 목표와 측정된 staging 결과 |
| 지연 시간 | Tier별 p50/p95/p99와 종단 간 canary | 포크 승인 예산 이내 |
| 용량 | 지속/burst 이벤트 비율, 파티션 lag, DB 포화, 할당량 headroom | 손실 없음, 범위가 제한된 lag, 포화 지점 기록 |
| Reliability | 서비스별 RPO/RTO와 business-impact analysis | Numeric 목표 승인 |
| 복구 | Isolated 복원과 regional 장애 조치/failback 훈련 | 무결성과 smoke 통과, 기본 fencing, 이벤트 복구 및 failback 검증, 목표 충족 |
| Security | Threat 검토, 비공개/allow-listed data-flow 검증, least-privilege 탐색 | 미해결 critical/high 발견 사항 없음 |
| Privacy | Privacy 영향 평가와 데이터 인벤토리 | Privacy 소유자 승인 |
| Operations | Signed operational-readiness 보고, canary, smoke, alert, 런북 근거 | 모든 운영 검사 통과 |
| Supply 체인 | SBOM, 서명, 출처 이력, vulnerability/IaC 검사 | release 산출물 검증, 차단 검사 clean |
| 비용 | 최신 calculator 내보내기, monthly 상한, 할당량, 12/36개월 assumption | 비용 소유자 승인 |

## 데이터, privacy, compliance

[데이터 거버넌스](data-governance-ko.md)는 분류, minimization, residency, 보존,
legal 보류, deletion, 모델 프로바이더, privacy-assessment 계약을 정의합니다. 업스트림 설계는
customer compliance certification을 주장하지 않습니다. 배포 소유자는 컨트롤 프로파일을
선택하고 컨트롤을 근거에 대응하며 exception과 privacy/데이터 소유자를 기록합니다.

## 소유권과 support

운영 게이트는 다음 accountable 자리를 요구합니다. 그룹이 자리를 채울 수 있지만 모든
연결은 에스컬레이션 경로와 직무 분리가 필요한 경우 별도 승인 권한을 식별해야 합니다.

| Owner 자리 | 책임 범위 |
|------------|-----------|
| `architecture-owner` | 아키텍처 기준선, ADR, accepted technical debt |
| `security-owner` | Threat 모델, 신원, 네트워크 자세, security exception |
| `privacy-owner` | Privacy 영향 평가와 data-processing 결정 |
| `data-owner` | 분류, 보존, legal 보류, deletion, 데이터 quality |
| `operations-owner` | On-call, alert, 런북, operational-readiness 수락 |
| `reliability-owner` | SLO, RPO/RTO, 복구 설계, 훈련 수락 |
| `release-owner` | 산출물 출처 이력, 배포, 롤백, 승격 게이트 |
| `cost-owner` | 예산, 할당량, price 확인, 용량 graduation |

에이전트 담당 체계는 별도 accountability 오버레이입니다. 권한 확인을 부여하거나 운영
소유자 자리를 대체하지 않습니다.

각 `owner_bindings` 항목은 다음 형태를 사용합니다.

```yaml
architecture-owner:
 subject: group:<fork-owned-subject>
 escalation: <fork-owned-escalation-route>
```

각 `evidence_bindings` 항목은 근거 본문이 아니라 변경할 수 없는 근거 메타데이터입니다.

```yaml
production-terraform-plan:
 uri: evidence://<governed-store-reference>
 sha256: <64-lowercase-hex-digest>
 approved_by: group:<fork-owned-approver>
 approved_at: 2026-07-13T00:00:00Z
 expires_at: 2027-01-13T00:00:00Z
```

검사기는 알 수 없음 연결 키, 누락된 필드, malformed 다이제스트, 잘못된 시각을 차단합니다.
`expires_at`은 `approved_at`보다 뒤여야 하며 만료된 연결은 운영 준비 상태를
차단합니다. Customer 이름, 리소스 id, 근거 본문은 포크의 통제된 저장소에 유지합니다.

업스트림 required-evidence 키는 Azure Well-Architected Reliability `RE:01-10` 및 Operational
Excellence `OE:01-11` Best Practice 요구사항 전체를 커버합니다. Checklist 평가기는
컨트롤에 더 짧은 최신성 구간이 선언된 경우 이를 적용합니다. 연결 만료는 외부 validity
상한이며 control-specific 최신성 구간을 연장하지 않습니다.

## 의존성과 실패 행동

| 의존성 | 계약 | 실패 행동 | 운영 근거 |
|------------|------|------------------|---------------------|
| Event Hubs Kafka | Ordered at-least-once 이벤트 로그와 DLQ 토픽 | Backpressure 또는 사람 검토, silent 폐기 없음 | Round-trip, lag, 재생, DLQ 테스트 |
| PostgreSQL + pgvector | Transactional 상태, 감사 변환 결과, T1 vector | 실패 시 차단, 운영 in-memory 대체 경로 없음 | 연결, 백업, 복원, 포화 테스트 |
| Key Vault 참조 | 환경 시크릿 주입 | 필수 시크릿 미해결 시 시작 실패 | 교대와 unavailable-vault 테스트 |
| Entra와 managed 신원 | 수명이 짧은 audience-scoped 신원 | 접근 거부, 자격 증명 대체 경로 없음 | Least-privilege와 recertification 근거 |
| Git 호스트 | 검토된 교정과 거버넌스 변경 | 제안 큐, out-of-band 실행 없음 | Protected-branch와 롤백 테스트 |
| HIL 채널 | 인증된 action-bound 승인 | 큐 및 대체 경로 사용, 시간 초과는 no-op | 기본/대체 경로 및 replay-resistance 테스트 |
| 모델 프로바이더 | Budgeted 근거에 기반한 T2 및 서술기 접근 | 사용 불가 또는 검증되지 않은이면 사람 검토 | 프로바이더, residency, 보존, 예산 근거 |
| Observability 백엔드 | Correlated 로그, 메트릭, 추적, alert | Monitor-of-monitor 신호 발생 | Canary와 alert 전달 결과 |

## 결정

ADR 인덱스는 [아키텍처 결정 Records](decisions/README-ko.md)입니다. ADR-0001은 승인된
Azure day-zero platform 기준선을 기록합니다. Numeric RPO/RTO, 보존, 비용 상한,
운영 소유자 같은 환경 결정은 숨겨진 아키텍처 기본값이 아니라 포크 연결입니다.

## Risk, assumption, issue, exception

활성 critical/high risk는 `config/architecture-review.yaml`의 `blockers`에 기계가 읽는
형태로 있습니다.

| 유형 | 규칙 |
|------|------|
| Risk | 심각도, accountable 소유자 자리, 완화, 잔여 risk, 검토 date를 가집니다. |
| Assumption | 검증 근거를 식별하며 반증되거나 측정되면 만료됩니다. |
| Issue | 종료하는 산출물 또는 구현에 연결됩니다. |
| Exception | 범위가 제한되고 필요한 경우 time-bound이며 별도 승인과 감사를 가집니다. |

Accepted risk는 resolved 차단 요인이 아닙니다. 운영 게이트는 critical/high 항목의 상태와
근거가 검토를 통해 갱신된 후에만 수락합니다.

## 런타임 상태 및 수동 검토

`GET /arb/status`는 계약 구조, 운영 준비 상태, 최신 `architecture-review`
프로세스를 분리합니다. 매니페스트가 유효하지만 운영 근거가 없으면 계약 healthy,
운영 차단된으로 보고합니다. 근거 또는 승인을 기다리는 프로세스는 `next_action`과
함께 healthy로 표시하고 `failed`, `timed_out`, `cancelled`는 런타임 unhealthy로 표시합니다.

기여자는 `POST /workflows/run`으로 그림자 검토를 시작하거나 재개할 수 있습니다.
Owner는 `architecture-review`가 `FDAI_WORKFLOW_ENFORCE_ALLOWLIST`에 있을 때만
`mode=enforce`를 요청할 수 있습니다. ARB는 control-only이므로 강제 적용은 실제 승인 및
결정 전이를 저장하지만 리소스를 배포하거나 ActionType을 승격하지 않습니다.

## 운영 종료 절차

1. Customer 포크에서 모든 필수 소유자 자리를 연결합니다.
2. 필수 근거 산출물을 첨부하고 업스트림 저장소에는 시크릿/customer 데이터가 없도록
 확인합니다.
3. 적절한 거버넌스 경로에서 각 차단 요인을 해결하거나 공식적으로 수용합니다.
4. 운영 산출물을 `ready`로 표시하고 design 검토를 승인한 뒤 운영 승인을
 `ready`로 설정합니다.
5. 승격 작업에서 `python3 scripts/governance/check-arb-readiness.py --require-production-ready`를
 실행합니다.
6. ARB 결정, 승인자, 조건, exception 만료를 감사 저장소에 기록합니다.

이 게이트를 통과하면 운영 배포 검토를 진행할 수 있습니다. 어떤 ActionType도
자동으로 활성화되지 않으며 각 기능은 별도 shadow-to-enforce 승격 게이트를 따릅니다.

## 다음 단계

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| 승인된 platform 결정 | [아키텍처 결정 Records](decisions/README-ko.md) |
| 데이터와 privacy 근거 | [데이터 거버넌스](data-governance-ko.md) |
| 배포 인벤토리 | [Deploy and Onboard](../deployment/deploy-and-onboard-ko.md) |
| Operational 인계 | [Operational 준비 상태](../operations/operational-readiness-ko.md) |
| 기계가 읽는 준비 상태 상태 | [`config/architecture-review.yaml`](../../../config/architecture-review.yaml) |
