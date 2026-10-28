---
title: Architecture Review Board 패킷
translation_of: architecture-review-board.md
translation_source_sha: e7a472c1e9fc6c0534c453b5b03b245b663c267e
translation_revised: 2026-10-22
---
# Architecture Review Board 패킷

이 패킷을 FDAI 목표 아키텍처 검토의 기준 진입점으로 사용하세요. 설계 기준선 승인과 프로덕션 배포
또는 적용 모드 승인을 분리하고, 모든 주장을 저장소 산출물 또는 포크가 제공하는 근거 연결과
연계합니다.

> **요청 결정:** Azure 목표 아키텍처 기준선의 조건부 승인을 요청합니다.
> `config/architecture-review.yaml`이 `production_approval_status: blocked`를 보고하는 동안
> 프로덕션 배포와 적용 모드 승인은 범위에 포함되지 않습니다.
>
> **고객 경계:** 업스트림은 재사용 가능한 아키텍처와 근거 계약을 정의합니다.
> 포크는 환경 값, 책임자, 개인정보 관련 결정, 서비스 목표, 프로덕션 근거를 제공합니다.

## 한눈에 보는 설계

FDAI는 권한이 없는 Console과 GitOps/ChatOps 전달 경로를 사용하는 에이전트 중심의 헤드리스
컨트롤 플레인입니다. 고정된 15개 에이전트가 타입이 지정된 pub/sub를 통해 감지, 판단, 중재,
승인, 실행, 검증, 복구, 감사, 학습을 담당합니다. 운영 온톨로지는 사실과 안전성을 뒷받침하는
기반으로서 에이전트의 해석을 제한하지만, 권한을 부여하거나 직접 행동하지 않습니다.

반복 가능한 이벤트는 T0 결정론적 규칙과 T1 검증된 재사용으로 해결하고, 남은 모호성만
T2 근거 기반 추론으로 보냅니다. 모든 변경은 risk-gate를 통과하고 중지, 롤백, 영향, 감사,
독립적인 효과 검증 계약을 갖추며 shadow mode에서 시작합니다.

FDAI는 이를 **[Outcome-Driven Token Economics](llm-strategy-ko.md#비용-컨트롤cost-controls)**라고
부릅니다. 온톨로지 기반 T0/T1 경로를 기본으로 사용하고, 남은 모호성이나 위험에만 원문
검색, 더 강한 모델, 검증, 사람 승인을 사용하여 모델 호출, 토큰, 지연 시간, 비용은
최소화하고 검증된 운영 가치는 최대화합니다. 정확도와 안전성은 비용보다 우선하는 제약입니다.

## 문서 모음

이 진입점은 간결하게 유지하고 완전한 설계는 역할이 분명한 문서가 담당합니다.

| 문서 | 담당 범위 |
|------|-----------|
| [온톨로지 기반 에이전트 루프](architecture-review/ontology-agent-loop-ko.md) | 권위 있는 온톨로지 상태, 15개 에이전트 책임, 근거 분기, 결정론적 결합, 자율 검토 수준 |
| [근거 및 권한](architecture-review/evidence-and-authority-ko.md) | 근거 레인, 담당자 연결, 위험, 예외, 승인 무결성, 결정 증적, 운영 종료 |
| [전달 계획](architecture-review/delivery-plan-ko.md) | 의존성 순서에 따른 5개 작업 패키지, 첫 수직 경로, 검증 매트릭스 |
| [구현 원장](../../roadmap-implementation/architecture/architecture-review-board.md) | 이 진입점의 현재 구현 범위, 추가 전용 이력, 남은 작업 |

## 결정 경계

| 결정 | 현재 요청 | 승인 효과 |
|------|-----------|-----------|
| Target architecture | 조건부 승인 | 시스템 경계, Azure day-zero 선택, 컨트롤 루프, 안전 모델을 수락합니다. |
| Production 배포 | 요청하지 않음 | 프로덕션 근거 게이트를 통과해야 합니다. |
| Enforce-mode capability | 요청하지 않음 | 액션별 shadow 근거와 별도 승인이 필요합니다. |
| Hyperscale Plan B | 참고만 제공 | Hyperscale 설계에서 측정한 전환 기준을 넘을 때만 적용됩니다. |
| Sovereign profile | 참고만 제공 | 별도의 규제 및 데이터 상주 위치 검토가 필요합니다. |

기계가 읽을 수 있는 결정 상태는
[`config/architecture-review.yaml`](../../../config/architecture-review.yaml)에 있습니다. 모든
변경에서 구조 검사를 실행합니다.

```bash
python3 scripts/governance/check-arb-readiness.py
```

프로덕션 승격 파이프라인은 검증에 실패하면 차단합니다.

```bash
python3 scripts/governance/check-arb-readiness.py --require-production-ready
```

## 범위와 컨텍스트

### 포함 범위

- 헤드리스 컨트롤 플레인의 Azure 구현과 공급자 경계.
- Kafka 엔드포인트를 통한 Event Hubs, Container Apps, pgvector를 포함한 PostgreSQL Flexible
  Server, Key Vault 참조, Managed Identity, Log Analytics, Application Insights.
- T0/T1/T2 컨트롤 루프, quality gate, 통합 risk-gate, 실행기, 감사, GitOps, HIL.
- Shadow-before-enforce 제어를 적용하는 개발, 스테이징, 프로덕션 산출물 승격.
- Day-zero 운영, 롤백, 관측성, 비용, 셀 기반 확장으로 전환하기 위한 측정 경로.

### 이번 결정에서 제외되는 범위

- 비-Azure 공급자 구현.
- 고객별 규칙, 임계값, 신원, 엔드포인트, 조직 정책.
- 업스트림에서 담당자 및 근거 연결이 비어 있으므로 프로덕션 승인.
- Plan B 배포, sovereign-profile 인증, 보조 지역 리소스.

## Architecture view

| 관점 | 설계 기준 | 검토 초점 |
|------|----------------|-----------|
| 시스템 맥락과 계층 경계 | [App Shape](../../../.github/instructions/app-shape.instructions.md) | 사람, Git, ChatOps, Console, Core, 특권 실행기의 경계 |
| 제어 흐름 | [Architecture](../../../.github/instructions/architecture.instructions.md) | 이벤트 수집, 계층 선택, 검증, 위험 판단, 실행, 감사 |
| 모듈과 배포 매핑 | [Project Structure](project-structure-ko.md) | 담당 경계와 공급자 어댑터 |
| Azure day-zero 배포 | [Deploy and Onboard](../deployment/deploy-and-onboard-ko.md) | 구체적인 리소스 인벤토리와 부트스트랩 순서 |
| 신원과 데이터 흐름 | [Security and Identity](security-and-identity-ko.md) | 신뢰 경계, 권한 부여, 시크릿, STRIDE 위협 |
| 확장 전환 | [Hyperscale Cell Architecture](hyperscale-cell-architecture-ko.md) | 단일 셀에서 분할된 셀로 전환하는 기준 |

### Current, target, transition 상태

| 상태 | 설명 | Evidence 상태 |
|------|------|---------------|
| Current upstream | 재사용 코드, Terraform 모듈, 테스트, 범용 구성, 설계 문서이며 고객의 프로덕션 값은 포함하지 않습니다. | 이 저장소에서 검증할 수 있습니다. |
| Day-zero target | 단일 Azure 지역, Container Apps 셀 하나, Event Hubs Kafka, PostgreSQL + pgvector, Key Vault, 범위가 지정된 Managed Identity, Log Analytics | ADR-0001에서 설계가 결정되었으며 프로덕션 근거가 추가로 필요합니다. |
| Production target | 서명된 이미지, 비공개 또는 허용 목록 기반 데이터 흐름, 연결된 담당자, 승인된 목표, 릴리스를 차단할 수 있는 제어, 운영 준비 상태 보고서 | 매니페스트의 프로덕션 게이트를 통과할 때까지 차단 상태입니다. |
| Scale target | 여러 셀, 정책 기반 fan-in, CQRS 감사 인덱싱, 배포 프로필 | 측정한 전환 기준을 넘을 때까지 보류합니다. |

## 검토 및 근거 모델

[온톨로지 에이전트 루프](architecture-review/ontology-agent-loop-ko.md)는 모든 전이를 고정된
판테온의 책임 에이전트에게 할당하고 `Change`, 컨텍스트, 근거, `DecisionCase`, 승인, 결과
레코드에서 검토 상태를 파생합니다. [근거 및 권한 계약](architecture-review/evidence-and-authority-ko.md)은
운영 근거 프로필, 담당자 슬롯, 위험 및 예외 레코드, 변경할 수 없는 결정 증적, 실패 동작,
운영 종료 절차를 정의합니다.

현재 재사용 가능한 구현은 검증한 바로 그 스냅샷에 기반한 계획 변경 그래프 근거를 전달하고, 완전하고
현재 유효한 위험 또는 예외 레코드가 없는 수락된 심각 또는 높음 차단 항목을 거부하며, 운영
준비 상태를 인정하기 전에 공급자를 통한 근거 본문 증명을 요구합니다. 변경할 수 없는 최종 결정 증적은 정확한
근거와 독립적으로 기록된 승인을 실행 권한 없이 결합합니다. 런타임 프로덕션 게이트는 이제
변환 결과에 기록된 최신의 모호하지 않은 증적을 확인하고 내용 기반 신원을 다시 검증하며,
정확한 근거, 리비전, 결과, 유효 시간 및 사람 승인 일치를 요구합니다. 프로덕션 담당자/근거
연결과 완전한 관찰 모드 에이전트 루프는 여전히 남아 있습니다.

`ReviewCase`와 `ReviewCheck`는 읽기 모델입니다. Process와 Console을 위해 권위 있는 계보를
요약하지만 판단, 승인, 실행 권한을 부여하지 않습니다.

## 결정

ADR 목록은 [Architecture Decision Records](decisions/README-ko.md)에 있습니다. ADR-0001은 승인된
Azure day-zero 플랫폼 기준선을 기록합니다. RPO/RTO 수치, 보존 기간, 비용 상한,
프로덕션 담당자 같은 환경 결정은 숨겨진 아키텍처 기본값이 아니라 포크에서 연결하는 값입니다.

## Runtime 상태 및 수동 review

게시된 워크플로 앱은 `/workflow-apps/architecture-review`에서 사용할 수 있습니다. 선택한
Process 보기는 선언형 보기 및 보고서 카탈로그를 통해 `/processes/{process_id}`에서 렌더링됩니다.
매니페스트가 유효하지만 프로덕션 근거가 없으면 구조는 정상으로 유지되고 프로덕션
게이트는 차단 상태를 유지합니다. Process 변환 결과는 워크플로 상태, 검토 점검, 담당자 및
근거 연결, 승인, 결정을 타입이 지정된 온톨로지 객체로 유지합니다.

Contributor는 `POST /workflows/run`을 통해 개정에 결합된 관찰 모드 검토를 제출할 수 있습니다.
Operator API는 현재 `mode=enforce`를 수락하지 않습니다. 권한을 수반하는 워크플로 경로와
로컬 및 배포 운영 근거는 아직 남은 작업입니다. ARB는 제어 전용으로 유지됩니다. 향후 거버넌스가
적용된 결정은 승인과 결정 전이를 저장할 수 있지만, 모든 리소스 변경은 일반 ActionType, 정책,
위험, 승인, 실행, 검증, 복구 경로로 다시 들어갑니다.

## 다음 단계

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| 승인된 플랫폼 결정 | [Architecture Decision Records](decisions/README-ko.md) |
| 온톨로지 및 15개 에이전트 검토 루프 | [온톨로지 기반 에이전트 루프](architecture-review/ontology-agent-loop-ko.md) |
| 근거, 담당 체계, 승인, 운영 종료 | [근거 및 권한](architecture-review/evidence-and-authority-ko.md) |
| 의존성 순서에 따른 구현 | [전달 계획](architecture-review/delivery-plan-ko.md) |
| 데이터와 개인정보 근거 | [Data Governance](data-governance-ko.md) |
| 배포 인벤토리 | [Deploy and Onboard](../deployment/deploy-and-onboard-ko.md) |
| 운영 인계 | [Operational Readiness](../operations/operational-readiness-ko.md) |
| 기계가 읽을 수 있는 준비 상태 | [`config/architecture-review.yaml`](../../../config/architecture-review.yaml) |
| 구현 상태 및 남은 작업 | [구현 원장](../../roadmap-implementation/architecture/architecture-review-board.md) |
