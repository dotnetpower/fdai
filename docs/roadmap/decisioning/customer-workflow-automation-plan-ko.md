---
title: 고객 워크플로 자동화 제공 계획
translation_of: customer-workflow-automation-plan.md
translation_source_sha: 2175ccc66befba7c59453976265eb06156d86160
translation_revised: 2026-07-21
---

# 고객 워크플로 자동화 제공 계획

이 계획은 FDAI의 기존 워크플로 계약을 도입 조직의 운영 및 업무 프로세스를 자동화할 수
있는 프로덕션 경로로 전환합니다. 관찰 모드에서 제한된 적용 모드로 이동하는 데 필요한
제공 웨이브, 구현 책임, 안전 게이트 및 근거를 정의합니다.

> **범위.** 이 문서는 재사용 가능한 제공 방법을 다룹니다. 고객 절차, 식별자, 자격 증명,
> 임계값 및 어댑터 구성은 배포 구성이나 downstream 배포판에 둡니다. Upstream 저장소는
> customer-agnostic 상태를 유지합니다.

> **현재 상태.** 워크플로 저작, 검증, 지속성, 트리거, 프로세스 저널, 제어 스텝 및 통제된
> 작업 제안 dispatch는 구현되어 있습니다. 광범위한 리소스 변경, 동작 시뮬레이션 및 고객
> 시스템 어댑터는 완성되지 않았습니다. 따라서 도입은 관찰 모드에서 시작하고, 측정된
> 프로세스를 한 번에 하나씩 승격하는 것이 좋습니다.

## 설계 요약

고객 워크플로 자동화는 프로세스를 발견하고, 버전이 지정된 `Workflow`로 표현하고, 변경 없이
실행하고, 필요할 때 승인하고, 형식화된 `ActionType` 어댑터를 통해 실행하고, 중단 후 복구하고,
감사 근거로 재구성할 수 있을 때 준비된 것입니다. 이 계획은 6개 제공 웨이브를 사용합니다.
각 웨이브에는 릴리스 게이트가 있으며, 한 웨이브의 통과가 이후 웨이브의 권한을 부여하지는
않습니다.

```mermaid
flowchart LR
    A[발견 및 범위 제한] --> B[컴파일 및 검증]
    B --> C[재생 및 관찰]
    C --> D[승인 및 선택 도구 적용]
    D --> E[제한된 변경 추가]
    E --> F[확장 및 운영]
    C -. 회귀 .-> B
    D -. 정책 이탈 .-> C
    E -. 롤백 실패 .-> C
```

## 목표 결과

첫 번째 프로덕션 마일스톤은 제한 없는 자동화가 아닙니다. 명시적인 경계와 측정 가능한 결과를
가진 3-5개의 고빈도 결정론적 프로세스 포트폴리오입니다.

개별 프로세스가 프로덕션 준비 상태가 되려면 다음 조건을 모두 갖추는 것이 좋습니다.

- **소유권이 있는 정의**: 버전이 지정된 워크플로, 업무 책임자, 기술 책임자, 원본 절차 및
  검토 주기를 기록합니다.
- **형식화된 스텝**: 상태를 변경하는 모든 스텝은 등록된 `ActionType`으로 해석됩니다. 인라인
  스크립트나 우회 경로는 사용하지 않습니다.
- **안전한 실행**: 중지 조건, 롤백 또는 상태 전진 복구, 영향 범위, 안전한 재시도, 리소스별
  직렬화 및 최종 감사 레코드를 검증합니다.
- **사람 승인**: 정책에서 요구하는 경우 승인 역할, 정족수, 자기 승인 방지, 시간 제한,
  에스컬레이션 및 거절 복구를 테스트합니다.
- **운영 복구**: 대기 중이거나 중단된 프로세스는 완료된 변경을 반복하지 않고 재개할 수 있으며,
  운영자는 이를 취소하거나 관찰 모드로 되돌릴 수 있습니다.
- **측정된 승격**: 과거 재생 및 실시간 관찰이 워크플로와 ActionType 승격 임계값을 충족하고
  정책 이탈이 0건입니다.

## 현재 기준선

기준선은 구현된 플랫폼 기능과 도입 작업을 구분합니다.

| 기능 | 현재 상태 | 제공 시 의미 |
|------|-----------|-------------|
| 정의 검증 및 private draft | 구현됨 | 지금 프로세스를 모델링하고 검토할 수 있습니다. Draft는 실행할 수 없습니다. |
| Signal 및 schedule 트리거 | 구현됨 | 정규화된 이벤트나 일정에서 관찰 실행을 시작할 수 있습니다. |
| Process snapshot 및 append-only journal | 구현됨 | 실행을 검사하고 결정론적으로 식별할 수 있습니다. |
| `WAIT`, `APPROVAL`, `DECISION`, `PARALLEL`, `GATE` 실행 | 런타임에 구현됨 | Builder 지원과 종단간 운영자 전환은 추가 완성이 필요합니다. |
| 읽기 전용 `EVIDENCE` 실행 | Browser evidence에 구현됨 | 별도 evidence dispatcher를 사용하고 shadow-only로 유지되며 action authority 없이 fail-closed됩니다. |
| Enforce 워크플로 명령 | Owner 및 allowlist로 제한됨 | 작업 스텝이 형식화된 `operator_request` 이벤트를 게시합니다. 직접 변경 권한은 아닙니다. |
| Tool 실행 | 선택된 어댑터에 제공됨 | GitHub, Jira, chaos, investigation 및 Azure VM 경로에는 명시적 구성과 도구별 승격이 필요합니다. |
| PR-native 수정 | 관찰 모드 전용 | Draft 수정 pull request를 생성하며 병합하지 않습니다. |
| Direct API 실행 | Core에서 관찰 모드 | Live Kubernetes handler는 범위가 좁고 일반 프로덕션 composition이 아닙니다. |
| 동작 시뮬레이션 | 구현되지 않음 | 구조 검증을 변경 미리 보기로 표현하면 안 됩니다. |
| 고객 프로세스 카탈로그 | Downstream 책임 | 고객 절차와 여기서 파생된 카탈로그 항목은 upstream에 두지 않습니다. |

## 제공 원칙

- **커넥터보다 프로세스에서 시작**: 측정 가능한 프로세스를 선택하고 필요한 어댑터만 도출합니다.
- **권한을 독립적으로 유지**: 배포 환경, fork 상태, 워크플로 수명 주기, 사용자 역할 및 적용
  모드는 별도 제어로 유지합니다.
- **가장 작은 단위를 승격**: 하나의 워크플로와 참조하는 각 ActionType을 별도로 승격합니다.
  워크플로 allowlist가 모든 스텝을 승격하지는 않습니다.
- **형식화된 ingress로 재진입**: 워크플로 작업은 trust router, 안전성 검토(`risk-gate`),
  승인 경로, executor 및 감사 경로로 돌아갑니다.
- **불확실할 때 안전한 쪽 선택**: 알 수 없는 매개 변수, 해석되지 않은 guard, 오래된 승인,
  누락된 어댑터 및 시뮬레이션 차이는 프로세스를 검토 대기로 둡니다.
- **고객 자료는 downstream에 유지**: 원본 매뉴얼, 프로세스 임계값, 자격 증명 및 맞춤형
  통합은 일반 upstream 배포판 외부에 둡니다.

## 작업 스트림

6개 작업 스트림이 제공 웨이브 전체에서 진행됩니다.

| 작업 스트림 | 필수 산출물 | 주요 구현 영역 |
|-------------|-------------|----------------|
| 프로세스 발견 | 우선순위 프로세스 목록, 책임자, 빈도, 실패 비용, anti-scope | Downstream onboarding 아티팩트 및 manual distillation |
| 정의 및 저작 | 버전 지정 Workflow, 매개 변수 스키마, 트리거, guard, 복구 그래프 | Workflow 카탈로그, 정의 store, builder |
| 실행 어댑터 | 승격 allowlist가 있는 형식화된 tool 또는 direct API 어댑터 | Downstream composition root 및 delivery 어댑터 |
| 승인 및 복구 | 지속성 있는 결정, 시간 제한, 에스컬레이션, 취소, 재개, 보상 | Workflow runtime, command API, notification 어댑터 |
| 시뮬레이션 및 근거 | 과거 재생, 동작 미리 보기, 고정 시나리오, KPI 보고서 | Assurance twin, 테스트 하네스, measurement store |
| 운영 | 대시보드, 경고, runbook, 담당자 인수인계, 강등 절차 | Console projection, reporting, 운영 문서 |

## 웨이브 0 - 파일럿 선택 및 범위 제한

기능을 추가하기 전에 3-5개 프로세스를 선택합니다. 좋은 파일럿 프로세스는 빈도가 높고,
결정론적이며, 되돌릴 수 있고, 영향 범위가 좁습니다.

### 산출물

- 트리거, 예상 결과, 현재 수동 스텝, 처리량, 기간, 오류율, 업무 책임자 및 기술 책임자가 있는
  프로세스 목록.
- 결정론, 가역성, API 가용성, 데이터 민감도, 승인 부담 및 영향 범위를 포함한 적합성 점수.
- 선택한 프로세스별 canonical 원본 절차 하나와 content hash.
- 명시적인 anti-scope, 중지 조건, 성공 지표 및 최대 영향 리소스 수.
- 기준 측정 기간과 과거 시나리오 세트.

### 종료 게이트

선택한 각 프로세스에는 책임자 2명, 안정된 원본 절차, 측정 가능한 기준선, 제한된 대상 집합이
있으며, 해결되지 않은 비밀 또는 개인 데이터 처리 경로가 없습니다. 제한 없는 자격 증명,
되돌릴 수 없는 대량 변경 또는 문서화되지 않은 판단이 필요한 프로세스는 파일럿에 포함하지
않습니다.

## 웨이브 1 - 컴파일 및 관찰 모드 실행

선택한 각 절차를 규칙, `ActionType` 항목 및 `Workflow`로 변환합니다. 관찰 모드는 고객
시스템 변경을 적용하지 않고 결정과 프로세스 전환을 기록합니다.

### 산출물

- Provenance와 immutable 버전이 있는 downstream 카탈로그 항목.
- 모든 작업 및 트리거 binding의 매개 변수 스키마.
- 스텝이 guard를 선언하는 경우 policy-as-code가 지원하는 구체적인 guard 평가.
- 파일럿에서 사용하는 작업 매개 변수와 제어 스텝 종류의 builder 지원.
- Process 및 audit projection이 있는 과거 재생 및 live 관찰 실행.
- 차단, 대기, 실패 및 건너뜀 스텝에 대한 운영자 표시 사유.

### 종료 게이트

모든 과거 시나리오가 예상 스텝 순서와 최종 상태를 생성합니다. Live 관찰 실행은 워크플로의
최소 샘플 및 정확도 임계값을 충족하고 정책 이탈이 없으며, 재시도가 Process 이벤트나 작업
제안을 중복 생성하지 않음을 보여 줍니다.

## 웨이브 2 - 승인 기반 tool 자동화 활성화

실제 tool 어댑터와 검증된 복구 계약이 지원하는 작업만 승격합니다. 일반적인 첫 대상은 인프라
변경보다 티켓 생성, 변경 요청 제출, 알림 및 저장소 워크플로 dispatch입니다.

### 산출물

- Process, step, requester, approver, role 및 timestamp에 연결된 지속성 있는 승인 결정.
- 명령 경계와 런타임 경계의 정족수 및 자기 승인 방지 검사.
- 승인 시간 제한, 에스컬레이션, 거절, 취소 및 재개 명령.
- 어댑터별 적용 allowlist와 최소 권한 identity.
- 지속성 있는 idempotency receipt와 편집된 어댑터 감사 세부 정보.
- GitHub, Jira, MCP 또는 선택한 다른 업무 도구의 contract 및 sandbox 테스트.

### 종료 게이트

Staging 연습에서 외부 효과를 중복시키지 않고 승인, 거절, 시간 초과, 재시도 및 재개를
수행합니다. 사용할 수 없는 어댑터는 실행 가능한 사유와 함께 프로세스를 대기 또는 실패
상태로 둡니다. Allowlist 항목을 제거하면 read 및 audit 접근은 유지하면서 새 적용을 즉시
차단합니다.

## 웨이브 3 - 제한된 substrate 변경 추가

실제 staging substrate에서 사전 조건, 관찰 경로 및 롤백 동작을 검증할 수 있는 작업에만 직접
변경을 추가합니다.

### 산출물

- `core/` 변경 없이 dependency injection을 통해 등록된 provider 어댑터.
- 의도한 대상 집합과 예상 상태 delta를 보고하는 preflight 및 동작 시뮬레이션.
- 둘 이상의 executor replica를 실행하는 배포를 위한 지속성 있는 분산 lock.
- Postcondition probe, 중지 조건 monitoring 및 보상 또는 상태 전진 복구.
- 일상적인 승인과 분리되고 완전히 감사되는 break-glass 절차.
- Timeout, 부분 성공, 오래된 상태, rate limit 및 롤백 실패의 fault-injection 테스트.

### 종료 게이트

동일한 immutable 작업 아티팩트가 시뮬레이션과 staging 실행을 통과합니다. 롤백 연습은 승인된
상태를 복원하거나 문서화된 상태 전진 복구를 완료합니다. 동시성 상황에서 영향 범위와 속도
제한이 적용되며, 테스트한 어떤 실패 경로도 최종 감사 레코드를 잃지 않습니다.

## 웨이브 4 - 저작 및 운영 경험 완성

Console에 변경 권한을 부여하지 않고 복잡한 워크플로를 관리할 수 있게 합니다.

### 산출물

- Schema 기반 매개 변수 편집 및 스텝 삽입, 제거, 순서 변경.
- Wait, approval, decision, parallel, gate 및 failure branch 저작 지원.
- Draft 복구, deep link, immutable 검토 diff 및 GitHub 카탈로그 제안 흐름.
- 구조 검증과 명확하게 구분된 동작 미리 보기.
- 승인 대기, 시간 초과, 실패, 보상 중 및 중단된 실행의 Process inbox.
- 취소, 안전 경계에서 재시도, 재개 및 관찰 모드 강등을 위한 운영자 명령.

### 종료 게이트

운영자는 데이터베이스에 직접 접근하지 않고 파일럿 워크플로를 저작하고, 검토하고, 거버넌스를
통해 게시하고, binding하고, 관찰하고, 승인하고, 진단하고, 복구할 수 있습니다. Reader view는
read-only 상태를 유지하며 모든 명령은 capability gate를 거치고 Process journal에 나타납니다.

## 웨이브 5 - 확장 및 운영 인수인계

파일럿 포트폴리오가 서비스 및 안전 목표 내에서 운영된 후에만 확장합니다.

### 산출물

- Cell-aware scheduling, 분산 lock, backpressure 및 tenant별 동시성 제한.
- Queue 지연, process 기간, 승인 지연, 작업 성공, 롤백 성공, 중복 억제 및 정책 이탈의
  service-level indicator.
- 품질, 안전 또는 어댑터 상태가 임계값을 넘을 때 자동 강등.
- 담당자 인수인계, on-call runbook, 어댑터 자격 증명 rotation 및 재해 복구 연습.
- 오래된 정의와 원본 절차를 폐기하는 분기별 프로세스 검토.

### 종료 게이트

부하 및 실패 테스트가 선언된 서비스 목표를 충족합니다. 운영자가 개발자 없이 복구 연습을
완료하고, 승격 및 강등 근거를 질의할 수 있으며, 모든 프로덕션 워크플로에 주 담당자와 백업
담당자가 있습니다.

## 구현 순서

구현은 아래 소유권 경계를 따르는 것이 좋습니다. 실제 pull request는 한 행을 더 나눌 수 있지만,
승격을 capability의 첫 구현과 결합하지 않습니다.

| 순서 | 변경 | 예상 검증 |
|-----:|------|-----------|
| 1 | Downstream 프로세스 목록 및 고정 시나리오 추가 | 원본 hash, secret scan, 책임자 검토 |
| 2 | 관찰 모드의 Workflow, Rule 및 ActionType 항목 추가 | Schema load, cross-reference, catalog regression |
| 3 | 구체적인 guard evaluator binding | Guard true, false, error 및 stale-input 테스트 |
| 4 | 매개 변수 및 제어 스텝 저작 완성 | Console reducer, decoder, accessibility, production build |
| 5 | 지속성 있는 승인 및 재개 명령 추가 | RBAC, quorum, 자기 승인, timeout, replay 테스트 |
| 6 | 파일럿 요구별 실제 tool 어댑터 하나 추가 | Contract, sandbox, idempotency, redaction, fault 테스트 |
| 7 | 과거 재생 및 live 관찰 실행 | 정확도, 정책 이탈, 중복, 지연 보고서 |
| 8 | Tool 작업 하나와 워크플로 하나 승격 | Owner 승인, allowlist, staging 근거, 롤백 계획 |
| 9 | 필요할 때 동작 시뮬레이션 및 direct mutation 어댑터 추가 | 상태 delta parity 및 롤백 연습 |
| 10 | 확장 제어 및 운영 인수인계 추가 | 부하, failover, 강등 및 on-call 연습 |

## 검증 매트릭스

| 계층 | 필수 테스트 | 릴리스를 차단하는 결과 |
|------|-------------|------------------------|
| Catalog | Schema, cross-reference, version pin, provenance, anti-scope | 알 수 없는 참조 또는 버전 없는 정의 |
| Builder | Decode, 매개 변수 schema, graph edit, draft 복구, localization | UI가 server validation에서 거부되는 정의를 생성함 |
| Runtime | 모든 step kind, resume, timeout, concurrency, deterministic replay | 완료된 스텝이 반복되거나 journal이 snapshot과 달라짐 |
| Approval | Role, quorum, 자기 승인 방지, 오래된 결정, escalation | 권한 없는 변경 또는 자기 승인 변경이 실행 가능해짐 |
| Adapter | Shadow no-op, enforce allowlist, idempotency, redaction, recovery | Receipt, audit 또는 제한된 대상 집합 없이 변경됨 |
| Simulation | 대상 집합, 예상 delta, 오래된 상태, staging과 parity | Simulation과 staging이 서로 다른 리소스에 영향을 줌 |
| Operations | Alert, demotion, cancel, restore, credential rotation | 운영자가 실패한 실행을 중지하거나 재구성할 수 없음 |

## 승격 근거

승격 근거는 워크플로 버전 및 ActionType 버전별로 저장합니다. 릴리스 패킷에는 다음 항목이
포함되는 것이 좋습니다.

- 고정 시나리오 세트 식별자 및 재생 결과.
- 관찰 기간, 샘플 수, 정확도, false-positive 비율 및 정책 이탈.
- 승인 경로 및 복구 연습 결과.
- Simulation-to-staging 대상 및 상태 delta 비교.
- 관찰된 최대 영향 범위 및 동시성.
- 어댑터 identity 및 권한 검토.
- 책임자 결정, 만료 또는 검토 날짜 및 자동 강등 임계값.

승격은 지정된 버전의 권한만 변경합니다. 새 Workflow 또는 ActionType 버전은 자체 근거를
생성할 때까지 관찰 모드로 돌아갑니다.

## 위험 및 제어

| 위험 | 제어 |
|------|------|
| 프로세스가 오래된 매뉴얼을 자동화함 | Source content hash, 검토 날짜 및 tombstone 전파 |
| Workflow allowlist를 step 권한으로 오해함 | Workflow 및 ActionType의 독립적인 승격 검사 |
| 재시도가 외부 효과를 반복함 | 안정된 idempotency key와 지속성 있는 adapter receipt |
| Context 변경 후 승인이 재생됨 | 결정을 process revision에 binding하고 오래된 결정 만료 |
| 부분 실패로 혼합 상태가 남음 | Postcondition probe, compensation, 상태 전진 복구 및 운영자 hold |
| Connector가 광범위한 자격 증명을 받음 | 최소 권한 identity 및 adapter 범위 secret reference |
| Simulation이 잘못된 확신을 줌 | 대상 집합 및 상태 delta를 staging 실행과 비교 |
| 확장으로 동시 변경이 발생함 | 분산 resource lock 및 tenant별 concurrency envelope |

## 완료 정의

다음 조건을 충족하면 프로세스 포트폴리오의 고객 워크플로 자동화 capability가 완료된 것입니다.

1. 최소 3개의 프로덕션 프로세스가 웨이브 0-4를 통과했습니다.
2. 각 프로세스가 최소 한 번의 승격과 한 번의 강등 또는 롤백 연습을 완료했습니다.
3. 등록되지 않은 변경, 인라인 자격 증명 또는 추적되지 않은 수동 상태에 의존하는 프로세스가
   없습니다.
4. 운영자가 지원되는 surface에서 모든 실행을 중지, 재개, 진단 및 재구성할 수 있습니다.
5. 품질 및 안전 임계값이 적용을 자동으로 차단하거나 강등합니다.
6. 주 담당자와 백업 담당자가 운영 인수인계 및 검토 일정을 수락했습니다.

이 완료 정의는 포트폴리오별로 적용됩니다. 모든 카탈로그 워크플로나 고객 시스템이 적용 모드로
준비되었다는 의미는 아닙니다.

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| Workflow 계약 및 runtime | [프로세스 자동화](process-automation-ko.md) |
| Action 권한 및 executor | [실행 모델](execution-model-ko.md) |
| 절차를 카탈로그로 전환 | [매뉴얼 증류](../rules-and-detection/manual-distillation-ko.md) |
| Downstream 구현 경계 | [Downstream fork 가이드](../fork-and-sequencing/downstream-fork-guide-ko.md) |
| 사람 역할 및 명령 권한 | [사용자 RBAC 및 identity](../interfaces/user-rbac-and-identity-ko.md) |
| 프로덕션 인수인계 게이트 | [운영 준비 상태](../operations/operational-readiness-ko.md) |
