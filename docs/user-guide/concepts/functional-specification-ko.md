---
title: FDAI 기능정의서
description: FDAI의 운영 기능, 공통 자동화, 거버넌스, 제품 기반 기능을 계층별로 살펴보고 처리 흐름 및 구현 상태와 구분합니다.
translation_of: functional-specification.md
translation_source_sha: 30ed8d2eef86ab2e8b20c62acc53e69139b753c0
translation_revised: 2026-10-24
---

# FDAI 기능 정의서

FDAI는 승인된 관리 범위 내의 Azure 리소스를 관찰하고, 근거를 바탕으로 운영 문제를 식별하며, 운영자의 대응을 지원합니다. 운영자가 작업을 명시적으로 승인하거나 유효한 사전 권한을 부여하면, FDAI 에이전트는 해당 권한 범위 내에서 작업을 실행하고 결과를 검증하며 감사 기록을 보존합니다.

> 이 문서는 제품의 목표 기능을 정의하며, 모든 기능이 구현되었거나 활성화되었다는 의미는 아닙니다. 리소스 지원 범위, 지원되는 작업, 운영 준비 상태는 각각 별도의 구현 근거로 확인해야 합니다. 세부 안전 조건과 권한 요구사항은 [FDAI 헌법](../../roadmap/architecture/fdai-constitution-ko.md) 및 연결된 담당 문서를 따릅니다.

## 문서 범위

기능은 제품 목적, 기능 그룹, 하위 기능, 세부 기능의 4단계로 설명합니다. 이 계층 구조는 내부 에이전트 이름이 아닌 운영자가 얻는 결과를 기준으로 합니다. 제품 기능, 공통 운영 흐름, 구현 범위는 서로 구분합니다.

| 구분 | 답하는 질문 | 구성 |
|------|-------------|------|
| **제품 기능 계층** | FDAI는 무엇을 제공하나요? | 번호가 부여된 대분류, 중분류, 세부 요구사항입니다. |
| **공통 운영 흐름** | 각 기능은 어떻게 결과에 도달하나요? | 관찰, 판단, 계획, 승인, 실행, 검증, 복구, 감사, 개선입니다. |
| **구현 범위** | 지금 무엇을 지원하고 검증했나요? | 지원 대상과 작업, 배포 환경의 연결 구성, 제약, 일자가 포함된 코드 및 테스트와 운영 근거입니다. |

## 제품 목적

Azure 리소스의 운영 이상을 감지하고, 운영자의 신속한 대응을 지원하며, 명시적으로
승인된 범위에서 자동 조치를 수행합니다.

구독에 FDAI를 배포하는 것만으로 모든 리소스를 관찰하거나 변경할 권한이 생기지는
않습니다. 관찰 범위는 구성된 수집원, 지원 어댑터, 접근 권한에 따라 달라집니다.
운영자는 작업을 승인하고, 별도로 인증된 실행 계정이 작업을 수행합니다. FDAI는
운영자의 자격 증명을 공유하거나 운영자의 모든 권한을 상속하지 않습니다.

## 기능 계층

다음 목록은 운영 영역과 공통 제품 기능을 검증 가능한 기능으로 구체화합니다.
`F`로 시작하는 ID는 업무 단계나 에이전트 역할이 아니라 제품 기능을 나타냅니다.
각 중분류에는 별도의 수용 기준을 갖는 세부 요구사항을 정의할 수 있습니다.

> 준비 상태는 명시된 지원 범위의 구현 및 검증 상태를 나타냅니다. 특정 설치 환경의 연결
> 상태를 나타내거나 자동 실행 권한을 부여하지 않습니다. 로컬 검증과 실제 운영
> 검증은 판정 근거에서 구분합니다.

**2026-10-18 F10-F15 점검**에서 F10부터 중분류 21개를 전수 대조하고 Ready 10건을
Partial로 정정했습니다. F01-F09는 기존 평가를 유지합니다. 대분류 집계는 중분류 평가
결과를 세며 배포 환경의 정상 여부나 완성 비율을 나타내지 않습니다.
대분류 집계에서 Partial이 0건이면 해당 배지를 표시하지 않으며, 개별 기능의 판정은 유지합니다.
**2026-10-19 집계 재확인:** 개정 버전 `c3a8a26275`를 기준으로 개별 평가 52개,
대분류 집계 15개, 영문·한국어 판정의 일치를 확인했습니다. 아래 집계가 이전의
Ready 38/52, Partial 14/52를 대체합니다. 이번 재집계는 기존 판정을 유지하며,
새로운 기능 검증이나 배포 적합성 검증은 아닙니다.
이후 2026-10-23 정확한 소스 수용으로 F14.2가 Ready로 복귀해 아래의 현재 집계
29/23을 만들었습니다.
**전체:** <span class="fdai-readiness-badge" data-readiness="ready">Ready 29/52</span> <span class="fdai-readiness-badge" data-readiness="partial">Partial 23/52</span> <span class="fdai-readiness-badge" data-readiness="blocked">Blocked 0/52</span> <span class="fdai-readiness-badge" data-readiness="planned">Planned 0/52</span> <span class="fdai-readiness-badge" data-readiness="not-assessed">미평가 0/52</span>
이 숫자는 제품 기능 집계이며 고객 본운영 수용 결과가 아닙니다.
[배포 증적](https://github.com/dotnetpower/fdai/issues/2210#issuecomment-6254158832)에 기록된
개발 환경의 전체 권한 활성화는 여전히 차단 상태입니다. 실패한 배포는 이전 버전으로
복구했으며, 이 집계로 운영 학습 개선이나 실제 비용 절감이 입증되지는 않습니다.
지원 범위와 과거 집중 검사는 [평가 기록](functional-readiness-ko.md)을, 소스 미비점,
필수 운영 검증, 연기한 범위, 의존성, 완료 조건은
[F10-F15 잔여 작업 전수 목록과 실행 계획](functional-readiness-backlog-ko.md)을 참조하세요.
이번 점검은 과거 테스트를 다시 실행하거나 새로운 실제 운영 검증을 수행한 것이 아닙니다.
상태 의미는 [준비 상태 정의](#준비-상태-정의)에서 확인하고, 기능명을 선택하면 해당 평가
기록으로 이동할 수 있습니다.

### 운영 기반

| 대분류 | 중분류 | <span style="display: inline-block; min-width: 16rem">세부 기능</span> | 준비 상태 |
|--------|--------|-----------|-----------|
| **F01. 운영 환경 설정** <br><span class="fdai-readiness-badge" data-readiness="ready">Ready 2/3</span><br><span class="fdai-readiness-badge" data-readiness="partial">Partial 1/3</span> | [F01.1 관리 범위](functional-readiness-ko.md#f01-1) | 관리할 구독과 리소스 그룹의 범위, 관찰 수집원, 접근 요구사항, 연결 준비 상태를 구성합니다. | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> |
|  | [F01.2 운영 기준](functional-readiness-ko.md#f01-2) | 서비스 목표, 임계값, 유지보수 시간, 알림 억제 조건, 영향 범위 제한을 관리 절차에 따른 설정으로 정의합니다. | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> |
|  | [F01.3 운영 책임](functional-readiness-ko.md#f01-3) | 책임 담당자와 대체 대응자, 연락 경로, 담당자 인수인계 요구사항을 지정합니다. | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> |
| **F02. 리소스 및 관계 관리** <br><span class="fdai-readiness-badge" data-readiness="ready">Ready 3/3</span> | [F02.1 리소스 목록](functional-readiness-ko.md#f02-1) | 리소스를 검색하고 구성 및 소유 정보를 수집하며 생성, 변경, 삭제를 반영합니다. | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> |
|  | [F02.2 서비스 및 의존 관계](functional-readiness-ko.md#f02-2) | 운영 의미를 공유하는 모델인 운영 온톨로지를 통해 리소스를 서비스 및 워크로드와 연결하고 의존 관계와 영향 경로를 살펴봅니다. | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> |
|  | [F02.3 상태 이력 및 관찰 범위](functional-readiness-ko.md#f02-3) | 명시된 시점의 상태와 토폴로지를 조회하고 출처와 최신성을 보존하며, 존재하지 않는 리소스와 관찰하지 못한 리소스를 구분합니다. | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> |

### 운영 영역별 기능

| 대분류 | 중분류 | <span style="display: inline-block; min-width: 16rem">세부 기능</span> | 준비 상태 |
|--------|--------|-----------|-----------|
| **F03. 관측 및 예방과 예측** <br><span class="fdai-readiness-badge" data-readiness="ready">Ready 4/4</span> | [F03.1 운영 신호](functional-readiness-ko.md#f03-1) | 지원되는 수집원을 통해 리소스 상태, 메트릭, 로그, 추적 정보, 이벤트, 변경을 수집합니다. | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> |
|  | [F03.2 서비스 신뢰성 목표](functional-readiness-ko.md#f03-2) | 서비스 수준 목표(SLO), 오류 예산, 오류 예산이 소진되는 속도를 평가합니다. | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> |
|  | [F03.3 용량 및 성능](functional-readiness-ko.md#f03-3) | 사용률, 성능 추세, 용량 부족 위험, 근거 기반 예측을 평가합니다. | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> |
|  | [F03.4 탐지 품질](functional-readiness-ko.md#f03-4) | 비정상 상태와 추세를 탐지하고 불필요한 알림을 평가하며 권한 부족, 오래된 신호, 불완전한 관찰 범위를 명시합니다. | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> |
| **F04. 인시던트 관리** <br><span class="fdai-readiness-badge" data-readiness="ready">Ready 3/3</span> | [F04.1 인시던트 수명 주기](functional-readiness-ko.md#f04-1) | 이벤트를 정규화하고 중복을 제거하며 관련 신호를 연결합니다. 심각도를 분류하고 확인, 담당 배정, 진행 상황, 종결을 추적합니다. | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> |
|  | [F04.2 조사 및 원인 분석](functional-readiness-ko.md#f04-2) | 범위가 제한된 근거를 수집하고 서비스 영향을 평가하며 원인 가설, 확인된 사실, 충돌하는 근거를 구분합니다. | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> |
|  | [F04.3 대응 및 후속 관리](functional-readiness-ko.md#f04-3) | 완화 조치를 제안하고 독립적으로 검증된 복구를 추적하며 미해결 결과를 보존합니다. 사후 검토와 후속 작업을 준비합니다. | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> |
| **F05. 복원력 및 복구 관리** <br><span class="fdai-readiness-badge" data-readiness="ready">Ready 1/3</span><br><span class="fdai-readiness-badge" data-readiness="partial">Partial 2/3</span> | [F05.1 백업 및 복구 준비](functional-readiness-ko.md#f05-1) | 백업 범위, 복구 지점의 가용성, 복원 사전 조건을 평가합니다. 백업 성공만으로 복구 가능성이 입증된 것으로 간주하지 않습니다. | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> |
|  | [F05.2 재해 복구 훈련](functional-readiness-ko.md#f05-2) | 복원 및 장애 조치 훈련을 계획하고 승인을 받으며 복구 지점 목표(RPO)와 복구 시간 목표(RTO)를 측정합니다. 복구와 원래 환경으로의 복귀 효과를 검증합니다. | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> |
|  | [F05.3 카오스 실험](functional-readiness-ko.md#f05-3) | 영향 범위 제한, 지속적인 중단 조건 확인, 검증된 복구를 갖춘 장애 주입 실험을 별도 승인 아래 계획합니다. | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> |
| **F06. 변경 및 아키텍처 거버넌스** <br><span class="fdai-readiness-badge" data-readiness="ready">Ready 1/3</span><br><span class="fdai-readiness-badge" data-readiness="partial">Partial 2/3</span> | [F06.1 변경 사전 평가](functional-readiness-ko.md#f06-1) | 제안된 인프라 및 구성 변경을 살펴보고 정책과 위험을 평가하며 변경 전 시뮬레이션과 롤백 근거를 제시합니다. | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> |
|  | [F06.2 구성 불일치 및 정책 준수](functional-readiness-ko.md#f06-2) | 구성 불일치와 통제 미비를 탐지하고 예외와 근거를 보존하며 관리 절차에 따른 수정을 제안합니다. | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> |
|  | [F06.3 아키텍처 및 준비 상태 검토](functional-readiness-ko.md#f06-3) | 아키텍처 검토 위원회(ARB)를 위한 근거를 구성하고 아키텍처 제약을 평가하며 인수인계나 승격 전에 담당 체계와 운영 준비 상태를 확인합니다. | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> |
| **F07. 비용 거버넌스** <br><span class="fdai-readiness-badge" data-readiness="ready">Ready 4/4</span> | [F07.1 비용 가시성 및 배분](functional-readiness-ko.md#f07-1) | 비용과 사용률을 리소스 및 서비스와 연결하고 비용 배분의 공백과 수집원의 관찰 범위를 설명합니다. | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> |
|  | [F07.2 예산 및 예측](functional-readiness-ko.md#f07-2) | 비용을 예산 및 기준선과 비교하고 이상을 탐지하며 가정을 명시해 비용을 예측합니다. | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> |
|  | [F07.3 최적화 계획](functional-readiness-ko.md#f07-3) | 리소스 크기 조정과 정리를 권장하고 신뢰성 및 용량 목표 사이의 상충을 평가하며 실행 가능한 작업을 승인 및 실행 절차로 전달합니다. | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> |
|  | [F07.4 실제 절감 효과](functional-readiness-ko.md#f07-4) | 비교 가능한 기준 구간과 조치 후 구간을 사용해 사용률과 비용 효과를 검증하며 예상 절감액과 실제 절감액을 구분합니다. | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> |

### 공통 자동화 및 운영자 지원

| 대분류 | 중분류 | <span style="display: inline-block; min-width: 16rem">세부 기능</span> | 준비 상태 |
|--------|--------|-----------|-----------|
| **F08. 작업 및 워크플로 관리** <br><span class="fdai-readiness-badge" data-readiness="ready">Ready 3/4</span><br><span class="fdai-readiness-badge" data-readiness="partial">Partial 1/4</span> | [F08.1 등록 작업 목록](functional-readiness-ko.md#f08-1) | 지원 작업과 워크플로, 매개변수, 사전 조건, 위험 제한, 복구 계약을 설명합니다. | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> |
|  | [F08.2 대응 계획](functional-readiness-ko.md#f08-2) | 여러 단계의 계획을 구성하고 대안과 목표 간 상충을 비교하며 정확한 대상, 기대 효과, 중단 조건을 검증합니다. | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> |
|  | [F08.3 실행 조건 및 일정](functional-readiness-ko.md#f08-3) | 운영자 요청, 이벤트, 일정에 따른 실행을 정해진 절차로 지원합니다. 실행 건과 이력을 추적하고 예약 작업을 선언된 범위로 격리합니다. | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> |
|  | [F08.4 실행 및 복구](functional-readiness-ko.md#f08-4) | 승인된 작업을 중복 없이 전달하고 진행 상황을 추적하며 정해진 지점에서 중단하고 승인된 롤백 또는 범위가 제한된 복구를 적용합니다. | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> |
| **F09. 운영자 조사 및 협업 지원** <br><span class="fdai-readiness-badge" data-readiness="ready">Ready 4/4</span> | [F09.1 근거 기반 대화](functional-readiness-ko.md#f09-1) | 지원되는 Web Console, CLI, ChatOps 접점에서 리소스, 인시던트, 계획, FDAI 동작에 관한 질문에 범위를 지켜 답하고 출처와 불확실성을 명시합니다. | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> |
|  | [F09.2 백그라운드 조사](functional-readiness-ko.md#f09-2) | 대화 상태를 실행 권한으로 간주하지 않으면서 장시간 조사를 영속적으로 추적하고 진행 상황, 취소, 입력 대기열, 결과 이어보기를 지원합니다. | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> |
|  | [F09.3 알림 및 에스컬레이션](functional-readiness-ko.md#f09-3) | 알림과 승인 요청을 전달하고 채널별 전달 및 확인 상태를 추적하며 선언된 대체 경로와 상위 담당자 전달을 적용합니다. 무응답을 동의로 해석하지 않습니다. | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> |
|  | [F09.4 연속성 및 인수인계](functional-readiness-ko.md#f09-4) | 허용된 대화 맥락, 검증된 채널 간 계정 연결, 대응자 배정, 명시적인 담당자 인수인계를 보존합니다. | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> |
| **F10. 운영 지식 및 규칙 관리** <br><span class="fdai-readiness-badge" data-readiness="ready">Ready 0/4</span><br><span class="fdai-readiness-badge" data-readiness="partial">Partial 4/4</span> | [F10.1 문서 및 첨부 수집](functional-readiness-ko.md#f10-1) | 접근 확인, 추출 제한, 보존 및 삭제 통제 아래 지원되는 운영 매뉴얼, 문서, 근거 첨부를 수집합니다. | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> |
|  | [F10.2 지식 조회 및 최신성](functional-readiness-ko.md#f10-2) | 출처, 버전, 범위, 수집 시각, 최신성과 함께 운영 지식과 과거 사례를 조회하고 지식의 부재나 충돌을 설명합니다. | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> |
|  | [F10.3 규칙 거버넌스](functional-readiness-ko.md#f10-3) | 규칙을 작성하고 적용 범위를 지정하며 버전, 활성화, 예외를 관리합니다. 추가, 개정, 폐기 제안을 검토합니다. | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> |
|  | [F10.4 운영 지식의 검증된 변환](functional-readiness-ko.md#f10-4) | 검토된 문서에서 규칙, 워크플로, 온톨로지 사실을 제안하고 출처 이력과 의미를 검증한 뒤 별도의 승인 및 활성화 절차를 적용합니다. | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> |
| **F11. 평가 및 학습과 승격** <br><span class="fdai-readiness-badge" data-readiness="ready">Ready 0/3</span><br><span class="fdai-readiness-badge" data-readiness="partial">Partial 3/3</span> | [F11.1 운영 피드백](functional-readiness-ko.md#f11-1) | 운영자 피드백과 변경 불가능한 인시던트 및 작업 결과를 출처가 명시된 학습 후보로 수집합니다. | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> |
|  | [F11.2 평가 및 재현](functional-readiness-ko.md#f11-2) | 시나리오 테스트, 과거 이력 재현, 비교 가능한 결과 측정을 통해 탐지, 추론, 계획, 복구를 평가합니다. | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> |
|  | [F11.3 기능 승격 및 회수](functional-readiness-ko.md#f11-3) | 관찰 모드에서 기능을 평가하고 활성화와 승격을 관리하며 회귀 시 하향 조정하거나 회수합니다. 학습 결과가 권한을 부여하지 못하도록 합니다. | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> |
| **F12. 권한 및 근거와 자체 운영 관리** <br><span class="fdai-readiness-badge" data-readiness="ready">Ready 0/4</span><br><span class="fdai-readiness-badge" data-readiness="partial">Partial 4/4</span> | [F12.1 계정 및 승인](functional-readiness-ko.md#f12-1) | 승인 계정과 실행 계정을 분리하면서 역할, 개별 작업 승인, 조건부 사전 승인, 승인 프로필, 만료, 철회를 관리합니다. | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> |
|  | [F12.2 정책 및 안전](functional-readiness-ko.md#f12-2) | 버전이 지정된 정책, 위험 제한, 비상 중지 통제, 필수 실행 안전 조건을 적용합니다. | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> |
|  | [F12.3 감사 및 데이터 거버넌스](functional-readiness-ko.md#f12-3) | 책임을 추적할 수 있는 판단과 효과 기록을 보존하고 재현을 지원하며 데이터 접근, 보존, 개인정보 보호, 근거 반출 경계를 적용합니다. | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> |
|  | [F12.4 FDAI 상태 및 복구](functional-readiness-ko.md#f12-4) | 필수 서비스, 모델, 수집원과 전달 경로의 연결, 영속 상태, 감사 의존성을 관찰합니다. 기능 저하 상태와 컨트롤 플레인 복구 필요 사항을 명시합니다. | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> |

### 제품 지원 기능

| 대분류 | 중분류 | <span style="display: inline-block; min-width: 16rem">세부 기능</span> | 준비 상태 |
|--------|--------|-----------|-----------|
| **F13. 운영 근거 및 보고서 제공** <br><span class="fdai-readiness-badge" data-readiness="ready">Ready 1/3</span><br><span class="fdai-readiness-badge" data-readiness="partial">Partial 2/3</span> | [F13.1 운영 현황](functional-readiness-ko.md#f13-1) | 허용된 조회 화면에서 리소스, 관계, 인시던트, 작업, 승인, 이력, 출처가 명시된 결과를 표시합니다. | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> |
|  | [F13.2 보고서 및 내보내기](functional-readiness-ko.md#f13-2) | 카탈로그에 정의된 보고서와 지원되는 내보내기 결과에 출처, 범위, 시각, 일부 수집원의 실패를 표시합니다. 보고서는 작업을 실행하지 않습니다. | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> |
|  | [F13.3 운영 성과 측정](functional-readiness-ko.md#f13-3) | 활동 건수만으로 개선을 주장하지 않고 선언된 기준선과 비교하여 신뢰성, 복구, 자동화, 비용 성과를 측정합니다. | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> |
| **F14. FDAI 설치 및 설정과 확장** <br><span class="fdai-readiness-badge" data-readiness="ready">Ready 1/4</span><br><span class="fdai-readiness-badge" data-readiness="partial">Partial 3/4</span> | [F14.1 설치 및 초기 설정](functional-readiness-ko.md#f14-1) | 설치 범위와 계정을 정하고 사전 조건을 검사하며 실제 수집원을 연결하고 시작 준비 상태를 검증합니다. | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> |
|  | [F14.2 업데이트 및 배포 방식](functional-readiness-ko.md#f14-2) | 소스 배포와 서명된 오프라인 패키지를 다룹니다. 설계되었지만 구현되지 않은 Hub 관리 수명 주기는 사용 가능한 설치 경로와 구분합니다. | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> |
|  | [F14.3 기능 설정](functional-readiness-ko.md#f14-3) | 사용 가능 여부, 활성화, 모드, 사전 조건, 라이선스 제한, 모델 상태를 표시합니다. 활성화나 사용 권한을 작업 실행 권한으로 간주하지 않습니다. | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> |
|  | [F14.4 신뢰할 수 있는 확장 및 연동](functional-readiness-ko.md#f14-4) | 게시자 신뢰, 호환성 확인, 범위가 제한된 접근, 활성화, 철회를 통해 버전이 지정된 기능 묶음, 스킬, 공급자 어댑터, Model Context Protocol(MCP) 도구를 관리합니다. | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> |
| **F15. 코드 보안 분석** <br><span class="fdai-readiness-badge" data-readiness="ready">Ready 2/3</span><br><span class="fdai-readiness-badge" data-readiness="partial">Partial 1/3</span> | [F15.1 관리 절차에 따른 검사 및 결과 수집](functional-readiness-ko.md#f15-1) | 승인된 정확한 개정 버전의 코드를 확보해 격리된 환경에서 검사하거나 지원되는 외부 보안 점검 결과를 수집하고 검사 범위와 한계를 명시합니다. | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> |
|  | [F15.2 점검 결과 및 우선순위](functional-readiness-ko.md#f15-2) | 근본 원인별로 결과를 통합하고 심각도, 신뢰도, 우선순위를 구분하며 검증과 오탐 검토를 기록합니다. | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> |
|  | [F15.3 개발자 수정 지원](functional-readiness-ko.md#f15-3) | 개발자가 실행하는 코딩 세션을 위한 근거 기반 수정 자료 묶음을 만들고 재검사로 수정 완료 주장을 검증합니다. 이 경로는 고객 저장소를 직접 편집하지 않습니다. | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> |

## 준비 상태 정의

| 상태 | 판정 기준 |
|------|-----------|
| <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 명시된 범위의 구현과 필수 검증을 완료했고, 현재 유효한 근거가 있으며 남은 필수 조건이 없습니다. |
| <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | 필수 구현이나 검증의 일부가 남아 있습니다. 지원되는 부분과 남은 작업을 기록합니다. |
| <span class="fdai-readiness-badge" data-readiness="blocked">Blocked</span> | 평가한 환경에서 필수 조건이 충족되지 않아 사용할 수 없습니다. 환경 범위, 차단 원인, 해제 조건을 기록합니다. |
| <span class="fdai-readiness-badge" data-readiness="planned">Planned</span> | 평가 범위에 대한 설계는 있으나 실행 가능한 구현이 없습니다. |
| <span class="fdai-readiness-badge" data-readiness="not-assessed">미평가</span> | 근거를 아직 검토하지 않았거나 현재 판정을 뒷받침할 수 없습니다. Ready도 아니고 미구현의 근거도 아닙니다. |

준비 상태는 제품 중분류에만 부여합니다. 아래의 공통 흐름은 처리 모델이며 별도의
상태 목록이 아닙니다. 일부 하위 기능만 Ready라고 대분류 전체를 Ready로 표시하지
않고 상태별 건수를 유지합니다. 근거 검토 후 해당 행, 대분류 집계, 전체 집계를
함께 갱신합니다. 범위나 소스 개정 버전이 바뀌면 다시 검증합니다.

담당 문서에 필수 구현, 통합, 운영 수용 기준이 남아 있으면 Ready로 표시하지 않습니다.
그 작업을 설치 환경별 검증이라고 부르는 것만으로 완료되지는 않습니다. 로컬 구현,
필수 운영 검증, 명시적으로 연기한 확장을
[F10-F15 점검 및 계획](functional-readiness-backlog-ko.md)처럼 분리해서 기록합니다.

## 준비 상태 판정 근거

[기능 준비 상태 평가](functional-readiness-ko.md)는 모든 제품 중분류의 판정, 지원
범위, 소스 근거, 남은 조건을 기록합니다. 상태 뱃지의 의미는 [준비 상태 정의](#준비-상태-정의)에서 설명합니다.
기능명을 선택하면 개별 근거 기록으로 이동합니다. 미평가 기능에는 빈 근거 기록을 만들지 않고
상태 정의에서 판정 기준을 확인합니다. 평가를 갱신할 때는 다음 항목을 사용합니다.

| 판정 항목 | 필요한 정보 |
|-----------|-------------|
| **기능, 상태 및 평가 기준** | 안정적인 기능 ID, 판정 상태, 책임 검토자, 소스 또는 릴리스 개정 버전, 평가 일자입니다. |
| **지원 범위** | 지원 리소스, 작업, 접점, 제외 범위, 평가할 수용 기준입니다. |
| **검증 근거** | 코드 및 테스트 참조와 일자가 포함된 관찰입니다. 로컬 검증, 실제 운영 검증, 운영 준비 완료 결과를 구분합니다. |
| **사용 조건** | 필요한 수집원 연결, 권한, 채널, 설정, 기능 모드, 환경별 평가가 적용되는 범위입니다. |
| **남은 작업 및 재평가** | 관찰 가능한 미충족 조건, Ready에 도달하기 위한 작업, 판정을 무효화하는 개정 버전 또는 최신성의 변경입니다. |

## 공통 운영 흐름

아래의 기존 5개 기능군은 전체 제품 목록이 아니라 재사용 가능한 처리 흐름입니다.
기존 숫자 참조는 연속성을 위해 유지하며 `F` ID와 구분합니다. 적용 대상인 각 제품
기능에는 이 흐름과 공통 통제가 사용됩니다. 조회 전용 기능이 계획 단계에 도달했다고
해서 변경 권한을 얻지는 않습니다.

| 대분류 | 중분류 | 세부 기능 |
|--------|--------|-----------|
| **1. 운영 상태 관찰** | 1.1 관리 대상 파악 | 허용된 범위에서 리소스를 검색하고 구성을 수집하며 의존 관계를 파악합니다. |
| | 1.2 상태 수집 | 지원되는 리소스 상태, 메트릭, 로그, 이벤트를 출처 및 시각 정보와 함께 수집합니다. |
| | 1.3 변경 감지 | 리소스 생성, 수정, 삭제와 구성 및 배포 변경을 감지합니다. |
| | 1.4 관찰 품질 관리 | 수집 공백, 권한 부족, 오래된 데이터, 불완전한 관찰 범위를 확인합니다. |
| **2. 이상 및 장애 판단** | 2.1 이상 탐지 | 구성된 운영 기준에 따라 정책 위반, 비정상 상태, 주의가 필요한 추세를 탐지합니다. |
| | 2.2 장애 분석 | 관련 이벤트를 연결하고 영향받는 리소스를 분석하며 원인 후보를 도출합니다. |
| | 2.3 판단 결과 설명 | 심각도를 분류하고 근거를 제시하며, 사실과 가설을 구분하고 판단 불가 또는 근거 충돌을 명시합니다. |
| **3. 운영자 대응 지원** | 3.1 알림 및 에스컬레이션 | 책임 담당자에게 알리고 전달 및 확인 상태를 추적하며 정책에 따라 상위 담당자에게 전달합니다. |
| | 3.2 조사 지원 | 허용된 범위에서 상태, 변경 이력, 장애 근거, 조치 진행 상황에 관한 질문에 답합니다. |
| | 3.3 대응 계획 제안 | 조치 방안, 예상 효과, 위험, 영향 범위, 중단 조건, 복구 계획을 제시합니다. |
| **4. 승인 기반 자동 조치** | 4.1 실행 권한 관리 | 작업별 승인, 조건부 사전 승인, 승인 만료 및 철회를 관리합니다. |
| | 4.2 실행 전 검증 | 현재 권한, 정책, 대상 식별 정보와 개정 버전, 영향 범위 제한, 필수 안전 조건을 확인합니다. |
| | 4.3 등록 작업 실행 | 지원되는 등록 작업을 실행하고 진행 상황을 추적하며 중복 변경을 방지합니다. |
| **5. 조치 결과 검증 및 복구** | 5.1 기대 효과 검증 | 독립적이고 신뢰할 수 있는 원본 관찰을 통해 의도한 효과가 발생했는지 확인합니다. |
| | 5.2 실패 대응 | 중단 조건과 승인된 롤백 또는 범위가 제한된 복구를 적용하고, 복구를 진행할 수 없으면 담당자에게 전달합니다. |
| | 5.3 결과 보고 | 검증된 성공, 실패, 미해결을 구분해 운영자에게 알리고 후속 대응을 연결합니다. |

예: 리소스 상태 이벤트가 수신되고 관련 관측 데이터가 장애 판단을 뒷받침하면,
운영자는 근거가 포함된 대응 계획을 받습니다. 승인된 작업은 실행 전 검증을 통과한
뒤 실행 계정을 통해 수행됩니다. 독립적인 관찰로 기대 효과를 확인한 후에만 성공으로
보고합니다.

감사와 근거 보존은 5개 기능군 전체에 적용됩니다. 검증된 결과와 운영자 피드백은
F10과 F11에 전달되어 검토를 거치는 지식 및 규칙 개선의 후보가 됩니다. 정책 변경이나
다음 작업 실행을 자동으로 허용하지는 않습니다.

## 공통 통제

공통 통제는 추가 업무 단계가 아니라 전체 기능 계층에 적용되는 요구사항입니다.

| 구분 | 기능 요구사항 |
|------|---------------|
| **관리 범위 및 접근 제어** | 관리할 구독과 리소스 그룹의 범위, 사용자 역할, 실행 계정, 최소 권한을 정의합니다. 접근 권한이 없거나 관찰하지 못한 리소스는 관찰 범위의 한계로 명시합니다. |
| **근거 및 판단** | 출처, 이력, 시각, 최신성, 완전성을 보존합니다. 반복 가능한 판단에는 결정론적 규칙을 우선 적용하고, 남은 모호함에는 범위가 제한되고 근거가 검증된 추론을 사용합니다. 근거 부족은 정상이 아니라 알 수 없음으로 처리합니다. |
| **정책 및 실행 안전** | 위험도와 승인 정책을 적용합니다. 모든 자율 상태 변경에는 중단 조건, 검증된 롤백 또는 범위가 제한된 복구, 영향 범위 제한, 성공한 사전 검증 또는 명시적으로 허용된 동등한 검증, 논리적 대상 잠금, 중복 방지, 실행 전후 감사 기록이 필요합니다. |
| **기능 수명 주기** | 사용 가능 여부, 활성화 여부, 실행 권한을 구분합니다. 새 기능은 제안된 변경을 적용하지 않고 판단과 기록만 수행하는 관찰 모드에서 시작하며, 모드 변경에는 정해진 승격 절차를 적용합니다. |
| **감사 및 추적성** | 관찰, 판단, 알림, 승인, 실행, 검증, 복구를 연결합니다. 각 결과를 재구성하는 데 필요한 계정 정보, 버전, 시각, 근거를 보존합니다. |
| **FDAI 자체 운영 상태** | 수집 및 알림 장애와 필수 구성요소의 가용성을 표시합니다. 안전 관련 의존성이 없으면 통제를 생략하지 않고 해당 변경을 차단합니다. |

## 권한 경계

조회 권한과 변경 권한은 별개입니다. 현재 정책, 위험도, 계정, 승인, 기능 모드,
안전성 검토가 모두 허용하는 경우에만 작업을 실행할 수 있습니다.

| 상황 | 기대 동작 |
|------|-----------|
| 허용된 관찰 또는 조사 | 허용된 범위에서 조회하고 설명합니다. 리소스 변경 권한을 의미하지 않습니다. |
| 개별 작업의 명시적 승인 | 승인이 유효한 동안 승인된 작업, 대상, 개정 버전, 범위 안에서만 실행합니다. |
| 유효한 사전 승인 | 선언된 실행 조건, 작업, 범위, 유효기간, 적용 위험 조건을 충족하는 경우에만 실행합니다. |
| 권한 부재, 만료, 철회 또는 불일치 | 작업을 시작하지 않습니다. 필요한 승인을 요청하거나 검토를 위해 보류하거나 차단하고 감사 기록을 남깁니다. |

알림에 응답하지 않았다는 사실, 자연어 요청, 광범위한 역할 부여만으로 특정 변경을
승인한 것으로 간주하지 않습니다. 승인이 철회되면 해당 승인에 따른 신규 실행을
차단합니다. 이미 진행 중인 작업에는 정해진 중단 및 복구 정책을 적용합니다.
운영 환경의 되돌릴 수 없는 작업에는 사전 상시 승인이 아니라 실행 건별 현재 승인이
필요합니다.

세부 승인 프로필과 긴급 조치 제한은 [위험 티어](risk-tiers-ko.md)와
[에스컬레이션 및 상시 승인](../../roadmap/decisioning/escalation-and-standing-authority-ko.md)을
참조하세요.

## 운영 영역

SRE는 전체 운영 모델입니다. F03-F07은 아래의 4개 운영 영역을 제품 기능으로
구체화하며, 공통 기능은 모든 영역을 지원합니다. 보고서와 코드 보안 분석은 지원
기능이며 헌법에 정의된 운영 영역을 추가하지 않습니다. 영역을 나열했다는 사실만으로
전체 구현 범위를 입증하지는 않습니다.

| 영역 | 공통 흐름의 적용 |
|------|------------------|
| **SRE 운영** | 가용성과 성능을 관찰하고 인시던트와 서비스 목표를 평가하며 복구를 검증합니다. SRE는 전체 운영 모델입니다. |
| **복원력** | 백업 및 복구 준비 상태를 평가하고 재해 복구 훈련, 복원, 장애 조치, 별도로 승인된 카오스 실험을 관리합니다. |
| **변경 안전성** | 변경 전후에 제안된 변경, 구성 불일치, 정책 준수, 아키텍처 제약을 평가합니다. |
| **비용 거버넌스** | 비용과 사용률을 관찰하고 이상을 탐지하며 최적화를 제안하고 승인된 변경의 효과를 검증합니다. |

## 기능 범위 및 담당 문서

이 목록은 로드맵 목차, SRE 기능 지도, 제품화 설계, 보고서 및 코드 보안 담당 문서와
대조했습니다. 참조 문서는 기능 범위의 근거이며 전체 코드 검토, 실제 환경 검증,
런타임 준비 완료를 주장하는 근거는 아닙니다. 세부 계약과 현재 구현 상태는 각 담당
문서에서 관리합니다.

| 기능군 | 담당 문서 |
|--------|-----------|
| **F01-F02: 운영 기반** | [운영 의도](../../roadmap/architecture/operating-intent-source-ko.md), [지속적 리소스 및 관계 관찰](../../roadmap/architecture/continuous-operational-instance-graph-ko.md), [담당 배정 및 인수인계](../../roadmap/interfaces/human-agent-assignment-and-knowledge-handover-ko.md). |
| **F03-F04: SRE 및 인시던트** | [SRE 기능 지도](../sre/README-ko.md), [인시던트 관리](../sre/incident-management-ko.md), [용량 및 성능](../sre/capacity-and-performance-ko.md). |
| **F05: 복원력** | [복원력](../capabilities/resilience-ko.md), [재해 복구 및 훈련](../sre/disaster-recovery-and-drills-ko.md), [카오스 엔지니어링](../sre/chaos-engineering-ko.md). |
| **F06: 변경 및 아키텍처** | [변경 안전성](../capabilities/change-safety-ko.md), [아키텍처 검토](../../roadmap/architecture/architecture-review-board-ko.md), [운영 준비 상태](../../roadmap/operations/operational-readiness-ko.md). |
| **F07: 비용** | [비용 거버넌스](../capabilities/cost-governance-ko.md), [리소스 효율성](../../roadmap/architecture/finops-resource-efficiency-ko.md). |
| **F08: 작업 및 워크플로** | [에이전트 워크플로](../../roadmap/agents/agent-workflows-ko.md), [운영 계획](../../roadmap/decisioning/operational-planning-ko.md), [프로세스 자동화](../../roadmap/decisioning/process-automation-ko.md). |
| **F09: 운영자 지원** | [운영자 대화](../guides/use-operator-conversations-ko.md), [채널 및 알림](../../roadmap/interfaces/channels-and-notifications-ko.md), [백그라운드 조사](../../roadmap/interfaces/background-task-sessions-ko.md). |
| **F10: 지식 및 규칙** | [문서 수집](../../roadmap/interfaces/document-ingestion-ko.md), [운영 매뉴얼 변환](../../roadmap/rules-and-detection/manual-distillation-ko.md), [규칙 거버넌스](../../roadmap/rules-and-detection/rule-governance-ko.md). |
| **F11: 평가 및 학습** | [운영 학습](../../roadmap/rules-and-detection/operational-learning-ontology-ko.md), [사후 분석 및 학습](../sre/postmortems-and-learning-ko.md), [기능 수명 주기](../../roadmap/architecture/capability-bundle-lifecycle-ko.md). |
| **F12: 권한 및 자체 운영** | [FDAI 헌법](../../roadmap/architecture/fdai-constitution-ko.md), [거버넌스 프로필](../../roadmap/decisioning/operator-governance-profiles-ko.md), [데이터 거버넌스](../../roadmap/architecture/data-governance-ko.md), [운영 및 검증](../../roadmap/operations/operating-and-verification-ko.md). |
| **F13: 보고서 및 성과** | [보고서](../../roadmap/interfaces/reporting-subsystem-ko.md), [SRE 성과 측정](../sre/measuring-sre-outcomes-ko.md). |
| **F14: 제품 수명 주기 및 확장** | [배포 빠른 시작](../deploy-quickstart-ko.md), [Hub 관리 수명 주기](../../roadmap/deployment/hub-managed-lifecycle-ko.md), [제품화 및 확장성](../../roadmap/fork-and-sequencing/productization-and-extensibility-ko.md). |
| **F15: 코드 보안** | [코드 보안 점검 결과](../../roadmap/operations/code-security-findings-ko.md), [코드 보안 검사](../../roadmap/operations/code-security-scanning-ko.md). |

## 세부 기능 명세

각 세부 기능에는 중분류 아래의 ID를 부여합니다. 표현이 바뀌어도 ID는 유지하고,
수용 테스트와 구현 근거를 연결하는 데 사용합니다. 목표 요구사항과 구현 상태는
혼합하지 않습니다.

다음 예시는 제품 중분류 `F12.1`을 검증 가능한 개별 요구사항으로 구체화합니다.
기존 초안의 ID `4.1.3`은 승인 철회 기능의 기존 참조를 보존하기 위한 별칭으로
유지합니다.

| 항목 | 예시 |
|------|------|
| **기능 ID** | `F12.1.3` |
| **기존 초안 ID** | `4.1.3` |
| **준비 상태** | 예시 요구사항이며 상위 기능 F12.1은 전체 요구사항과 운영 근거가 충족될 때까지 Partial로 평가합니다. 아래 기준은 별도의 검증 증적이 아닙니다. |
| **기능명** | 실행 승인 철회 |
| **행위자 및 동작 조건** | 권한 있는 운영자가 기존 승인을 철회합니다. |
| **사전 조건** | 운영자에게 해당 승인을 철회할 권한이 있고 정확한 승인 개정 버전을 지정합니다. |
| **기대 동작** | 철회된 승인에 따른 신규 실행을 차단합니다. 진행 중 작업에는 정해진 중단 및 복구 정책을 적용합니다. |
| **수용 기준** | 철회된 승인에 따른 신규 실행 요청이 차단되고, 진행 중 작업의 명시적인 처리 결과가 기록되며, 감사 기록에서 운영자, 승인 개정 버전, 시각, 영향받는 작업을 확인할 수 있습니다. |
| **예외 처리** | 권한 없는 요청은 차단합니다. 현재 권한을 확인할 수 없으면 관련 신규 실행을 검토 대기로 보류합니다. |

별도의 구현 기록에서 각 기능 ID에 구현 상태, 지원 리소스 및 작업 유형, 제약,
코드와 테스트 참조, 검증 일자가 포함된 근거를 연결합니다. 구현, 로컬 검증, 실제
운영 검증, 운영 환경 준비 완료는 서로 다른 주장입니다. 이 기능정의서의 존재만으로
어느 것도 입증되지 않습니다.

이러한 주장을 하나의 완료 또는 미완료 표시로 합치지 말고 구분해 기록합니다. 평가
기록이 현재 판정을 제공하며 이후 변경에는 새로운 근거가 필요합니다. 뒷받침되지
않는 주장은 이전 Ready 표시를 물려받지 않고 미평가로 되돌립니다.

| 구현 범위 항목 | 필요한 정보 |
|----------------|-------------|
| **기능 및 구현** | 안정적인 기능 ID, 담당자, 별도로 근거가 확인된 설계 단계, 부분 구현, 구현 완료 범위입니다. |
| **지원 범위** | 리소스 및 작업 유형, 접점, 알려진 제외 대상, 배포 사전 조건입니다. |
| **연결 구성 및 권한** | 실제 수집원과 채널의 연결, 유효 범위, 기능 모드, 승인 요구사항입니다. |
| **검증** | 로컬 테스트 결과, 실제 운영 관찰, 승격 또는 운영 준비 완료 근거를 구분합니다. |
| **추적성** | 정확한 소스 또는 릴리스 개정 버전, 테스트 참조, 관찰 시각, 근거의 출처 이력, 남은 작업입니다. |

## 관련 문서

| 알아볼 내용 | 문서 |
|-------------|------|
| 초기 설정과 운영자 업무 흐름 | [시작하기](../get-started-ko.md) |
| 구성요소별 책임 | [FDAI 아키텍처](../architecture-ko.md) |
| 변경 활성화 전 관찰 | [관찰 후 변경 적용](shadow-then-enforce-ko.md) |
| 승인 및 알림 접점 | [승인과 채널](approvals-and-channels-ko.md) |
| 기능별 판정 및 남은 조건 | [기능 준비 상태 평가](functional-readiness-ko.md) |
| F10-F15 잔여 작업 전수 목록과 의존 순서 | [준비 상태 점검 및 완료 계획](functional-readiness-backlog-ko.md) |
| 제품 안전 및 권한 요구사항 | [FDAI 헌법](../../roadmap/architecture/fdai-constitution-ko.md) |
