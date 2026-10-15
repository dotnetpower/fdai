---
title: FDAI 기능 준비 상태 평가
description: FDAI 제품 중분류 52개의 준비 상태 판정 근거와 남은 조건을 기록합니다.
translation_of: functional-readiness.md
translation_source_sha: 941471751a35ecdb01f93f546b5cdf59da4da8da
translation_revised: 2026-10-15
---

# FDAI 기능 준비 상태 평가

이 문서는 [기능정의서](functional-specification-ko.md)의 각 기능을 Ready 또는 Partial로
판정한 이유를 기록합니다. 기능 이름만으로 준비 완료를 주장하지 않고 실행 가능한
구현, 문서에 명시된 미완료 항목, 설치 환경별 운영 검증을 구분합니다.

> **평가 기준:** 2026-10-15, 기준 소스 개정 버전
> `426507a57cbfbd9bc7a9b2c8941c3c5f60db229d`와 현재 변경입니다. GitHub Copilot이 52개
> 요구사항을 담당 기록과 대조한 뒤 범위가 제한된 두 차례 작업에서 후보 30개를 구현하거나 다시
> 검증했습니다. 최근 20개 기능 확장에서는 **7개 집중 실행의 테스트 3,439개**가 통과했고,
> 적용 대상이 아니거나 데이터베이스가 없어 건너뛴 테스트가 9개였습니다. 저장소 평가이며 독립적인
> 사람 승인이나 새로운 실제 Azure, 모델, 운영 데이터베이스, 배포 검증이 아닙니다.

## 판정 읽기

**전체:** <span class="fdai-readiness-badge" data-readiness="ready">Ready 35/52</span> <span class="fdai-readiness-badge" data-readiness="partial">Partial 17/52</span> <span class="fdai-readiness-badge" data-readiness="blocked">Blocked 0/52</span> <span class="fdai-readiness-badge" data-readiness="planned">Planned 0/52</span> <span class="fdai-readiness-badge" data-readiness="not-assessed">미평가 0/52</span>
Ready는 해당 기록에 명시된 지원 범위에만 적용됩니다. 모든 배포 환경, 공급자, 규모,
자율 작업을 검증한 것은 아닙니다. Partial은 구현이 있지만 인용한 담당 문서에 필수
지원 범위, 통합, 검증이 남아 있다는 뜻입니다. Blocked를 평가할 설치 환경은 선택하지
않았습니다. 중분류 전체가 설계만 있는 경우는 확인되지 않았으며 부분 구현된 기능 안의
설계 단계 구성요소는 명시적으로 남겨 둡니다.

Partial 17건은 담당 원장의 근거와 문서화된 제약을 사용하며 모든 구성요소의 런타임
테스트를 새로 실행한 결과는 아닙니다. 기존 테스트와 실제 환경 증적은 과거 기록으로
유지하며 이번 세션에서 갱신한 것으로 취급하지 않습니다. 아래의 남은 조건은 전체
기능을 Ready로 판정할 수 없는 이유입니다. 코드, 선언한 범위, 근거가 바뀌면 재평가합니다.

기능정의서의 상태 뱃지 의미는 [준비 상태 정의](functional-specification-ko.md#준비-상태-정의)에서
확인할 수 있고 기능명은 이 문서의 해당 기록으로 연결됩니다. 엔지니어링 구현 원장은 영문으로
제공되며 이 평가로 대체하지 않습니다.

## F01. 운영 환경

| 기능 | 상태 | 근거, 지원 범위 및 남은 조건 |
|------|------|-----------------------------|
| <span id="f01-1">F01.1</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 고정된 관리 범위의 수용, 지속적인 재검증, 안전한 쪽으로 닫히는 격리 및 복구 처리 구조, 정확히 구성된 수집원 연결입니다. [운영 의도 원장](../../roadmap-implementation/architecture/operating-intent-source.md), [리소스 원장](../../roadmap-implementation/architecture/continuous-operational-instance-graph.md), 현재 집중 검사가 이 범위를 뒷받침합니다. 특정 설치 환경의 공급자 연결과 관리 절차에 따른 격리 훈련은 Ready 범위가 아닌 배포 검증입니다. |
| <span id="f01-2">F01.2</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [운영 의도 원장](../../roadmap-implementation/architecture/operating-intent-source.md)에 운영 의도와 변경 시간이, [규칙 원장](../../roadmap-implementation/rules-and-detection/rule-governance.md)에 규칙 설정과 예외가 구현되어 있습니다. 수집원 재검증 근거와 영속 규칙 개정 버전 업그레이드가 남아 있습니다. |
| <span id="f01-3">F01.3</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 구성된 연결의 기본 및 대체 담당자, 담당 범위 검사, 에스컬레이션 해석, 명시적인 인수인계 처리 구조입니다. [담당 체계 원장](../../roadmap-implementation/interfaces/human-agent-assignment-and-knowledge-handover.md)과 현재 집중 검사가 이 범위를 뒷받침합니다. 디렉터리별 실제 담당자, 연락 가능성 훈련, 설치 환경의 승격 증적은 별도 배포 검증입니다. |

## F02. 리소스 및 관계

| 기능 | 상태 | 근거, 지원 범위 및 남은 조건 |
|------|------|-----------------------------|
| <span id="f02-1">F02.1</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 완전한 세대 단위 인벤토리 수집, 원자적 스냅샷 승격, 추가·변경·삭제 정합성 조정, 승격 증적, 안전한 쪽으로 닫히는 일관성 검사입니다. [리소스 원장](../../roadmap-implementation/architecture/continuous-operational-instance-graph.md)과 집중 인벤토리 검사가 이 범위를 뒷받침합니다. 공급자 연결, 배포 스키마 및 권한, 특정 설치 환경의 완전한 수집은 별도 배포 검증입니다. |
| <span id="f02-2">F02.2</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 타입이 지정된 리소스 및 워크로드 관계, 독립적으로 검증한 양방향 연결, 카디널리티 검사, 완전성 한도를 명시한 그래프 탐색입니다. [리소스 원장](../../roadmap-implementation/architecture/continuous-operational-instance-graph.md)과 관계 및 역량 집중 검사가 이 범위를 뒷받침합니다. 모델에 있는 연결만으로 모든 애플리케이션 의존성을 입증하지 않으며 실제 호출 기반 범위는 별도 배포 검증입니다. |
| <span id="f02-3">F02.3</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 정규화된 이중 시간축 관찰, 특정 시점의 토폴로지, 명시적인 수집원 및 시간 구간 범위 사유, 없음과 관찰하지 못함의 구분입니다. [리소스 원장](../../roadmap-implementation/architecture/continuous-operational-instance-graph.md)과 보류 상태 및 PostgreSQL 집중 검사가 이 범위를 뒷받침합니다. 설치 환경의 보존 기간, 보관 및 복원 훈련, 공급자 전체 구간의 완전성은 별도 배포 검증입니다. |

## F03. 관측 및 예방과 예측

| 기능 | 상태 | 근거, 지원 범위 및 남은 조건 |
|------|------|-----------------------------|
| <span id="f03-1">F03.1</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 지원되는 인벤토리, 리소스 상태, 메트릭, Kubernetes, 관찰 캠페인 어댑터와 타입이 지정된 수집원 증적, 범위가 제한된 수집, 사용 불가·불완전·오래됨·권한 부족 상태의 명시입니다. [SRE 기능 지도](../sre/README-ko.md), [리소스 원장](../../roadmap-implementation/architecture/continuous-operational-instance-graph.md), 집중 관찰 검사가 이 범위를 뒷받침합니다. 수집원 등록과 측정된 수집 범위는 별도 설치 검증입니다. |
| <span id="f03-2">F03.2</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 스키마로 검증한 워크로드 SLO, 오류 예산 및 여러 구간의 소진 평가, 데이터 부족 시 안전한 쪽으로 닫히는 처리, 위반 이벤트 게시, 선택적인 단일 복제본 예약 작업입니다. [SLO 가이드](../sre/slos-and-error-budgets-ko.md)와 집중 CLI 및 인프라 검사가 이 범위를 뒷받침합니다. 워크로드 정의, 메트릭 연결, 일정 활성화, 측정 실행 증적은 설치 환경의 설정 및 검증입니다. |
| <span id="f03-3">F03.3</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 타입이 지정된 용량 예측, 수요 및 제약 입력, 선택지 평가 전 강제 제약 필터링, 범위가 제한된 시뮬레이션, 용량을 고려한 운영 계획입니다. [용량 가이드](../sre/capacity-and-performance-ko.md), [계획 원장](../../roadmap-implementation/decisioning/operational-planning.md), 계획 및 전문가 집중 검사가 이 범위를 뒷받침합니다. 최신 수요, 할당량, 의존성, 관찰된 확장 결과는 별도 설치 검증입니다. |
| <span id="f03-4">F03.4</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 결정론적 알림 품질 평가, 수집원 공백 및 완전성 보고, 범위가 제한된 시간축 평가, 제안 안전 검사, 명시적인 알 수 없음 결과입니다. [알림 품질 원장](../../roadmap-implementation/operations/alert-noise-governance.md)과 Core 및 Operator 집중 검사가 이 범위를 뒷받침합니다. 공급자별 정답 표기, 수신자 연결, 운영 수용은 별도 설치 검증입니다. |

## F04. 인시던트

| 기능 | 상태 | 근거, 지원 범위 및 남은 조건 |
|------|------|-----------------------------|
| <span id="f04-1">F04.1</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 심각도 및 상태 변경, 배정, 감사 기록, 재현을 포함한 기본 인시던트 레지스트리와 관련 신호를 연결하는 수명 주기 워크플로입니다. [레지스트리](../../../services/core-control-plane/src/fdai/core/incident/registry.py)와 [워크플로](../../../services/core-control-plane/src/fdai/core/incident/workflow.py)를 검토하고 검사 A에서 [수명 주기](../../../services/core-control-plane/tests/core/incident/test_incident_lifecycle.py), [워크플로](../../../services/core-control-plane/tests/core/incident/test_incident_workflow.py), [이벤트 폭주](../../../services/core-control-plane/tests/core/incident/test_storm.py) 테스트를 재실행했습니다. 외부 알림의 적합성 검증은 F09.3에서 별도로 다룹니다. |
| <span id="f04-2">F04.2</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 티어별 인과 가설, 통제된 문서 및 관측 데이터 근거, 토폴로지 및 변경 구분, 충돌 근거 처리, 판단 보류, 감사 가능한 인과 체인입니다. [원인 분석 원장](../../roadmap-implementation/rules-and-detection/root-cause-analysis.md)과 집중 RCA 검사가 이 범위를 뒷받침합니다. 정확한 원인 분석 품질과 여러 작업 영역의 수집원 범위는 별도 설치 및 운영 검증입니다. |
| <span id="f04-3">F04.3</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 타입이 지정된 대응 계획, 완화 대안, 기대 효과, 중단 및 복구 계약, 인시던트 인계, 미해결 결과 보존, 사후 분석 및 후속 작업 준비입니다. [계획 원장](../../roadmap-implementation/decisioning/operational-planning.md), [학습 가이드](../sre/postmortems-and-learning-ko.md), 집중 계획 검사가 이 범위를 뒷받침합니다. 특정 작업의 승인, 실행, 관찰된 복구는 별도 작업 및 배포 검증입니다. |

## F05. 복원력 및 복구

| 기능 | 상태 | 근거, 지원 범위 및 남은 조건 |
|------|------|-----------------------------|
| <span id="f05-1">F05.1</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 백업 준비 상태 평가, 복구 지점 근거 요구사항, 복원 사전 조건, 범위가 제한된 복구 계획, 무결성 근거가 없을 때 안전한 쪽으로 닫히는 처리입니다. [재해 복구 가이드](../sre/disaster-recovery-and-drills-ko.md), [복구 원장](../../roadmap-implementation/decisioning/recovery-and-chaos-enforcement.md), 집중 복구 검사가 이 범위를 뒷받침합니다. 정확한 워크로드의 백업, 복원, 독립 무결성 증적은 별도 설치 검증이며 백업 성공만으로 복구 가능성을 입증하지 않습니다. |
| <span id="f05-2">F05.2</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [재해 복구 가이드](../sre/disaster-recovery-and-drills-ko.md)는 구현된 단일 지역 복구 기반과 대체 지역 인프라, 트래픽 및 이벤트 연속성, 측정된 장애 조치 및 복귀를 구분합니다. 전체 범위의 RPO/RTO와 정리 증적이 필요합니다. |
| <span id="f05-3">F05.3</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [카오스 원장](../../roadmap-implementation/decisioning/recovery-and-chaos-enforcement.md)에 공급자 패키지와 안전 조건을 적용한 실행 구조가 있습니다. 보호된 공급자 입력, 실제 에이전트 소유 권한 기록, 적법한 승격, 관리 절차에 따른 장애 주입 및 복구 검증이 남아 있습니다. |

## F06. 변경 및 아키텍처

| 기능 | 상태 | 근거, 지원 범위 및 남은 조건 |
|------|------|-----------------------------|
| <span id="f06-1">F06.1</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 타입이 지정된 제안 변경 수집, 정책 및 위험 평가, 정확한 대상 및 개정 버전 검증, 범위가 제한된 시뮬레이션, 대안 비교, 중단 조건, 최종 계획의 롤백 근거입니다. [변경 가이드](../capabilities/change-safety-ko.md), [계획 원장](../../roadmap-implementation/decisioning/operational-planning.md), 집중 계획 검사가 이 범위를 뒷받침합니다. 승인, 실행, 독립적인 변경 후 관찰은 별도 작업 검증이며 제안만으로 변경을 종결하지 않습니다. |
| <span id="f06-2">F06.2</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [규칙 원장](../../roadmap-implementation/rules-and-detection/rule-governance.md)에 규칙 범위 지정, 활성화, 예외가 있습니다. 영속 규칙 개정 버전의 호환성 업그레이드와 운영 적용 단계, 구성 불일치 판단을 위한 완전한 수집 범위가 남아 있습니다. |
| <span id="f06-3">F06.3</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [아키텍처 검토 원장](../../roadmap-implementation/architecture/architecture-review-board.md)과 [준비 상태 원장](../../roadmap-implementation/operations/operational-readiness.md)에 검토 처리 구조가 있습니다. 운영 근거 및 담당자 연결과 수정 제안을 위험 및 승인 입력 경로로 전달하는 게시자가 완성되지 않았습니다. |

## F07. 비용 거버넌스

| 기능 | 상태 | 근거, 지원 범위 및 남은 조건 |
|------|------|-----------------------------|
| <span id="f07-1">F07.1</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 구독 및 리소스의 비용과 사용률 분석, 배분 공백, 서비스 및 리소스 귀속, 수집원 출처 이력, 불완전하거나 사용할 수 없는 근거를 보존하는 Console 변환 결과입니다. [효율성 원장](../../roadmap-implementation/architecture/finops-resource-efficiency.md)과 집중 FinOps 검사가 이 범위를 뒷받침합니다. 현재 청구 및 사용률 연결과 완전한 관계 범위는 별도 설치 검증입니다. |
| <span id="f07-2">F07.2</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [효율성 원장](../../roadmap-implementation/architecture/finops-resource-efficiency.md)과 [FinOps 원장](../../roadmap-implementation/architecture/finops-autonomous-operations.md)에 예산, 추세, 이상 탐지 기반이 있습니다. 호환되는 사용률 근거와 조건을 충족하는 운영 평가 집단은 불완전하며 기존 부분 분석만으로 전체 예측 검증을 대신하지 않습니다. |
| <span id="f07-3">F07.3</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | 일반적인 크기 조정 안전 조건은 있지만 [효율성 원장](../../roadmap-implementation/architecture/finops-resource-efficiency.md)에 검토된 서비스 계열별 프로파일, 결합 대상의 결정 구성, 범위가 제한된 확인 질문은 명시적으로 미착수 상태입니다. 공통 기반만으로 리소스별 최적화가 완성되지는 않습니다. |
| <span id="f07-4">F07.4</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [FinOps 원장](../../roadmap-implementation/architecture/finops-autonomous-operations.md)에 독립적인 효과 정산이 구현되어 있습니다. [효율성 원장](../../roadmap-implementation/architecture/finops-resource-efficiency.md)에는 비용, 용량, 서비스, 복구 효과가 모두 정산된 실제 환경의 고정된 리소스 효율성 사례가 아직 없습니다. |

## F08. 작업 및 워크플로

| 기능 | 상태 | 근거, 지원 범위 및 남은 조건 |
|------|------|-----------------------------|
| <span id="f08-1">F08.1</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 매개변수, 참조, 위험 및 복구 선언, 관찰 모드 기본값을 포함한 배포된 등록 ActionType 및 Workflow 카탈로그입니다. [ActionType](../../../services/core-control-plane/src/fdai/rule_catalog/schema/action_type.py) 및 [Workflow](../../../services/core-control-plane/src/fdai/rule_catalog/schema/workflow.py) 로더를 검토하고 검사 A에서 [작업 카탈로그](../../../services/core-control-plane/tests/rule_catalog/test_action_type_catalog.py) 및 [워크플로 카탈로그](../../../services/core-control-plane/tests/rule_catalog/test_workflow_catalog.py) 테스트를 재실행했습니다. 카탈로그 유효성은 모든 설계 목록의 워크플로 구현이나 승격을 입증하지 않습니다. |
| <span id="f08-2">F08.2</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 여러 단계의 계획 구성, 강제 제약 필터링, 전문가 의견 중재, 정확한 대상 및 효과 검증, 복구 계약, 봉인된 계획 다이제스트, 전달 준비 검사입니다. [계획 원장](../../roadmap-implementation/decisioning/operational-planning.md)과 집중 계획 및 전문가 검사가 이 범위를 뒷받침합니다. 계획을 실행할 때는 사람 승인과 효과 검증이 계속 필요합니다. |
| <span id="f08-3">F08.3</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 기본 예약 및 수동 전달, 지원 일정 종류, 범위가 제한된 격리, 이력, 결과 연결 처리 구조입니다. [스케줄러](../../../services/core-control-plane/src/fdai/core/scheduler/service.py)를 검토했고 검사 B에서 중복 방지, 이력, 격리, 결과 연결의 보존 및 전달을 포함한 [스케줄러 테스트 파일](../../../services/core-control-plane/tests/core/scheduler/) 7개를 재실행했습니다. 전달 수락은 작업 성공이나 실제 채널 검증을 뜻하지 않습니다. |
| <span id="f08-4">F08.4</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [워크플로 원장](../../roadmap-implementation/decisioning/process-automation.md)과 [복구 원장](../../roadmap-implementation/decisioning/recovery-and-chaos-enforcement.md)에 형식이 지정된 실행, 중단, 복구 처리 구조가 있습니다. 독립적인 효과 및 복구 종결이 있는 승격된 워크플로가 남아 있으며 공급자 차원의 동시 실행 차단도 긴급 상시 권한을 제한합니다. |

## F09. 운영자 조사 및 협업

| 기능 | 상태 | 근거, 지원 범위 및 남은 조건 |
|------|------|-----------------------------|
| <span id="f09-1">F09.1</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 모델 기반 타입 지정 의도, principal 범위 읽기 조사, 온톨로지 및 RCA 근거 선택, 범위가 제한된 인용과 제약, 명시적인 알 수 없음 및 부분 결과, Web·CLI·ChatOps 표시 계약입니다. [운영자 가이드](../guides/use-operator-conversations-ko.md), [원인 분석 원장](../../roadmap-implementation/rules-and-detection/root-cause-analysis.md), 집중 의미 및 읽기 조사 검사가 이 범위를 뒷받침합니다. 수집원 및 채널 등록과 실제 원인 품질 측정은 별도 설치 검증입니다. |
| <span id="f09-2">F09.2</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 소유자 범위의 영속 읽기 조사, 임차 기간, 할당량, 진행 상황, 타입이 지정된 생성 및 취소 수용, 재시작에 안전한 완료, Web 전달, Slack/Teams 발신 대기열 등록, Live 전용 Console 제어입니다. [백그라운드 작업 원장](../../roadmap-implementation/interfaces/background-task-sessions.md), 집중 검사, 격리된 반응형 Console 검사가 이 범위를 뒷받침합니다. 공급자 전달과 프로세스 손실 훈련은 별도 배포 검증입니다. |
| <span id="f09-3">F09.3</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 타입이 지정된 알림 범주, 영속 라우팅 및 채널별 상태, 검증된 계정 연결, 확인, 대체 경로, 범위가 제한된 에스컬레이션, 시간 초과 시 작업 없음, Slack 및 Teams 어댑터 계약입니다. [채널 원장](../../roadmap-implementation/interfaces/channels-and-notifications.md)과 집중 알림 및 채널 검사가 이 범위를 뒷받침합니다. 공급자 전달, 테넌트 콜백, 브로커 증적은 별도 설치 검증이며 무응답을 동의로 간주하지 않습니다. |
| <span id="f09-4">F09.4</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 principal에 결속된 결과 연결 지점, 보존된 타입 지정 맥락, 후속 전달 상태, 만료, 범위가 제한된 보존입니다. [결과 연결 원장](../../roadmap-implementation/interfaces/scheduled-result-continuations.md)과 현재 집중 검사가 이 범위를 뒷받침합니다. 실제 채널 출처 계정, 실제 대응자 배정, 법적 보존 삭제, 선제적 인수인계 승격은 별도 설치 검증입니다. |

## F10. 지식 및 규칙

| 기능 | 상태 | 근거, 지원 범위 및 남은 조건 |
|------|------|-----------------------------|
| <span id="f10-1">F10.1</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 인증된 문서 및 첨부 수집, 변경 불가능한 버전, 형식 및 크기 제한, 악성 코드 및 보호 상태, 격리된 추출 및 OCR, 색인, 미리 보기 및 다운로드, 보존, 삭제, 재시작에 안전한 인계, 명시적인 수집원 제약입니다. [문서 원장](../../roadmap-implementation/interfaces/document-ingestion.md)과 문서 및 변환 테스트 929개가 이 범위를 뒷받침합니다. 외부 SharePoint 및 보호 연결과 배포 환경의 서비스 간 증적은 별도 설치 검증입니다. |
| <span id="f10-2">F10.2</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 개정 버전에 안전한 클라우드 지식 수집, 예약, 추출, 활성화 및 교체, 출처를 보존하는 조회, 명시적인 최신성 및 적용 가능 상태입니다. [클라우드 지식 원장](../../roadmap-implementation/interfaces/cloud-resource-knowledge-lifecycle.md)과 현재 집중 검사가 이 범위를 뒷받침합니다. 배포 환경 소유 수집원 등록, 신뢰 절차, 연결 구성요소 훈련, 현재 문서 집합의 최신성은 별도 설치 검증입니다. |
| <span id="f10-3">F10.3</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [규칙 원장](../../roadmap-implementation/rules-and-detection/rule-governance.md)에 작성, 활성화, 범위 지정, 예외가 있습니다. 영속 규칙 개정 버전의 이중 읽기 호환성과 순서에 따른 적용 및 롤백 단계가 남아 있습니다. |
| <span id="f10-4">F10.4</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 검토된 문서 수용, 내용보다 먼저 확인하는 출처 이력, 민감도 및 최신성 검사, 온톨로지 적합성, 결정론적 위원회 검증, 비활성 규칙·워크플로·온톨로지 제안, 통제된 인수인계입니다. [변환 원장](../../roadmap-implementation/rules-and-detection/manual-distillation.md)과 집중 변환 검사가 이 범위를 뒷받침합니다. 활성화는 별도 승인 및 승격 경로이며 배포 환경의 접근, 철회, 법적 보존 작업은 별도 설치 검증입니다. |

## F11. 평가 및 학습과 승격

| 기능 | 상태 | 근거, 지원 범위 및 남은 조건 |
|------|------|-----------------------------|
| <span id="f11-1">F11.1</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [학습 원장](../../roadmap-implementation/rules-and-detection/operational-learning-ontology.md)에 변경 불가능한 사례와 학습 후보가 있습니다. 범위가 제한된 Pattern 보존, 현재 권한에 따른 수용, 예측 학습 통합 기준은 완성되지 않았습니다. |
| <span id="f11-2">F11.2</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [학습 원장](../../roadmap-implementation/rules-and-detection/operational-learning-ontology.md)과 [워크플로 원장](../../roadmap-implementation/agents/agent-workflows.md)에 재현, 시나리오 평가, 측정 기반 기준이 있습니다. 전체 평가를 주장하려면 완전한 실제 재발 관찰 구간, 작업 표본, 기준선과 추적 근거가 필요합니다. |
| <span id="f11-3">F11.3</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 근거 기반 및 귀속된 재정의 승격, 자동 강등, 영속 기능 회수 및 해제, 모든 승격 종류보다 우선하는 회수, 안전한 쪽으로 닫히는 `shadow` 강제, Operator 및 Console의 회수 표시, 권한이 없는 읽기 변환 결과입니다. [거버넌스 원장](../../roadmap-implementation/decisioning/operator-governance-profiles.md), Core 회수 검사, 현재 Operator 및 Console 검사가 이 범위를 뒷받침합니다. 운영 Release 최대값 수집원과 특정 설치의 승격 근거는 별도 배포 검증입니다. |

## F12. 권한 및 근거와 자체 운영

| 기능 | 상태 | 근거, 지원 범위 및 남은 조건 |
|------|------|-----------------------------|
| <span id="f12-1">F12.1</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | 역할과 승인 프로필은 있지만 [권한 원장](../../roadmap-implementation/decisioning/escalation-and-standing-authority.md)은 공급자가 효과 반영 시점의 현재 임대와 동시 실행 차단을 강제할 수 있을 때까지 긴급 상시 권한을 보류합니다. 승인 처리 구조만으로 조건부 사전 권한이 완성되지 않습니다. |
| <span id="f12-2">F12.2</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [거버넌스 원장](../../roadmap-implementation/decisioning/operator-governance-profiles.md)에 버전이 지정된 정책과 안전 검사가 있습니다. 회수 상태 조회 결과, Release 최대값 입력, [상태 원장](../../roadmap-implementation/operations/operating-and-verification.md)의 측정된 배포 비상 중지 및 실행 없는 기본 검사가 남아 있습니다. |
| <span id="f12-3">F12.3</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [개인정보 원장](../../roadmap-implementation/architecture/data-governance.md)에 해시 체인 감사, 보존, 비식별화, 법적 보존 계약이 있습니다. 배포 환경의 개인정보 승인, 감사 외부 고정, 삭제, 법적 보존, 접근 검토, 사고 대응 증적이 남아 있습니다. |
| <span id="f12-4">F12.4</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [상태 원장](../../roadmap-implementation/operations/operating-and-verification.md)과 [재해 복구 가이드](../sre/disaster-recovery-and-drills-ko.md)에 상태 신호와 복구 기반이 있습니다. 전체 관측 내보내기·임계값·담당자·대체 경로 매핑, 수치로 측정한 카나리 감사 지연, 운영 복구 훈련이 남아 있습니다. |

## F13. 근거 조회 및 보고서

| 기능 | 상태 | 근거, 지원 범위 및 남은 조건 |
|------|------|-----------------------------|
| <span id="f13-1">F13.1</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 리소스, 관계, 인시던트, 계획 및 Process, 승인, 감사 및 이력, 출처가 명시된 결과, 승격 및 회수 상태를 보여 주는 허용된 읽기 화면이며 사용 불가 및 부분 근거를 명시합니다. [리소스 원장](../../roadmap-implementation/architecture/continuous-operational-instance-graph.md), [보고서 원장](../../roadmap-implementation/interfaces/reporting-subsystem.md), 기존 화면 검사, 현재 회수 변환 결과 검사가 이 범위를 뒷받침합니다. 배포 수집원의 최신성과 인증된 공급자 범위는 별도 설치 검증입니다. |
| <span id="f13-2">F13.2</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 선언형 보고서 카탈로그, 범위가 제한된 렌더링, 위젯별 오류 격리, 선택적 PDF를 포함한 지원 내보내기, 감사 기반 인시던트 자료, available/partial/unavailable 원본 출처입니다. [보고서 원장](../../roadmap-implementation/interfaces/reporting-subsystem.md)과 집중 모델 검사가 이 범위를 뒷받침합니다. 데이터 원본별 최신성 및 시간 초과 검증과 인증된 배포 조합은 별도 설치 검증입니다. |
| <span id="f13-3">F13.3</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [성과 가이드](../sre/measuring-sre-outcomes-ko.md)에 기준선에 따른 측정이 정의되어 있고 [FinOps 원장](../../roadmap-implementation/architecture/finops-autonomous-operations.md)에 정산 및 검증 집계가 있습니다. 조건을 충족하는 작업 사례와 완전한 기준 및 조치 후 결과 구간이 남아 있습니다. |

## F14. 설치 및 설정과 확장

| 기능 | 상태 | 근거, 지원 범위 및 남은 조건 |
|------|------|-----------------------------|
| <span id="f14-1">F14.1</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 체크아웃에서 실행하는 한 줄 소스 배포, 사전 조건 및 호스트 도구 검사, 대상 및 범위 입력 검증, 소스 이미지 준비, Terraform 계획 및 적용 조정, 키 없는 Trial 활성화, 사용 권한을 고려한 시작, 상태 및 준비 검증, 업데이트, 롤백, 제거 처리 구조입니다. [소스 배포 원장](../../roadmap-implementation/deployment/source-deployment.md)과 소스 배포 집중 테스트 207개가 이 범위를 뒷받침합니다. Azure 연결, 선택한 대상 값, 설치 증적은 별도 배포 검증입니다. |
| <span id="f14-2">F14.2</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 현재 사용할 수 있는 두 배포 방식인 소스 배포와 분리 서명을 검증하는 오프라인 패키지이며, 패키징, 변조 거부, 기한 및 취소 처리, 공급자 미러 입력, 업데이트 안전 조건을 포함합니다. [소스 원장](../../roadmap-implementation/deployment/source-deployment.md)과 오프라인 집중 테스트 70개가 이 범위를 뒷받침합니다. [Hub 관리 수명 주기](../../roadmap-implementation/deployment/hub-managed-lifecycle.md)는 설계되었지만 구현되지 않은 상태로 명시하며 사용 가능한 경로로 표시하지 않습니다. |
| <span id="f14-3">F14.3</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 기능의 사용 가능 여부, 활성화, 기본 및 유효 모드, 사전 조건, 선택한 제품 프로필 및 추가 기능, 라이선스 및 Trial 상태와 워터마크, 모델 상태 및 연결, 승격 출처, 운영자 재정의, 활성 회수 표시이며 어떤 표시 상태도 작업 권한으로 간주하지 않습니다. [제품화 담당 문서](../../roadmap/fork-and-sequencing/productization-and-extensibility-ko.md), [소스 원장](../../roadmap-implementation/deployment/source-deployment.md), 현재 회수 변환 결과 검사가 이 범위를 뒷받침합니다. 실제 사용 권한 전환과 공급자 및 모델 연결은 별도 설치 검증입니다. |
| <span id="f14-4">F14.4</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 게시자 신뢰 확인, 호환성 검증, 변경 불가능한 비활성 우선 설치, 활성화 및 비활성화와 철회 수명 주기, 타입이 지정된 런타임 등록, 연결된 증적 완전성 규칙입니다. [기능 묶음 원장](../../roadmap-implementation/architecture/capability-bundle-lifecycle.md)과 현재 확장 및 패키지 보증 검사가 이 범위를 뒷받침합니다. 보호된 설치 환경의 정확한 산출물 절차와 재시작 및 공개 증적 묶음은 별도 설치 검증입니다. |

## F15. 코드 보안

| 기능 | 상태 | 근거, 지원 범위 및 남은 조건 |
|------|------|-----------------------------|
| <span id="f15-1">F15.1</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 승인된 정확한 개정 버전의 코드 확보, 격리된 결정론적 검사 경로, SARIF 수집, Console 및 예약 작업자, 독립적인 결과 재구성, 검사 범위 보고, 최종 요청 변환 결과입니다. [검사 원장](../../roadmap-implementation/operations/code-security-scanning.md)과 현재 작업자 및 수용 검사가 이 범위를 뒷받침합니다. 배포된 작업자 heartbeat와 정확한 게시 및 재조회 증적은 별도 설치 검증입니다. |
| <span id="f15-2">F15.2</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 결정론적 통합 이슈, 심각도·신뢰도·우선순위 구분, 범위가 제한된 요약, 검증 및 판정입니다. [통합 처리](../../../services/core-control-plane/src/fdai/core/security/code_findings/canonical.py)와 [검증](../../../services/core-control-plane/src/fdai/core/security/code_findings/verification.py)을 검토하고 검사 A에서 통합, 심각도, 이슈 요약, 검증 테스트를 재실행했습니다. 탐지기의 재현율, 임의의 취약점, 실제 스캐너 정확도를 보증하지 않습니다. |
| <span id="f15-3">F15.3</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 서명되고 범위가 제한된 개발자 수정 자료 묶음, 보조 도구의 안전 검사, 결과 주장, 동등한 검사 범위에 따른 재검증입니다. [자료 묶음 런타임](../../../services/core-control-plane/src/fdai/core/security/code_findings/pack_runtime.py)과 [검증](../../../services/core-control-plane/src/fdai/core/security/code_findings/verification.py)을 검토했습니다. 검사 A에는 [실제 임시 Git 보조 도구 세션](../../../services/core-control-plane/tests/core/security/code_findings/test_pack_helper_session.py), 서명, 내보내기, 안전 검사, 재검사 테스트가 포함됩니다. FDAI가 고객 저장소를 편집하거나 반환된 주장을 검증된 수정으로 취급하지 않습니다. |

## 수행한 집중 검증

| 검사 | 정확한 로컬 선택 범위 | 결과 |
|------|----------------------|------|
| **A** | Incident `test_incident_lifecycle.py`, `test_incident_workflow.py`, `test_storm.py`; rule catalog `test_action_type_catalog.py`, `test_workflow_catalog.py`; code findings `test_canonical.py`, `test_severity.py`, `test_issue_summary.py`, `test_pack.py`, `test_pack_helper_session.py`, `test_diff_guard.py`, `test_signing.py`, `test_result_import.py`, `test_export_gate.py`, `test_verification.py`. | **286개 통과**, 건너뜀 없음, 파일 15개입니다. |
| **B** | Scheduler `test_scheduler.py`, `test_history.py`, `test_isolation.py`, `test_console_tool.py`, `test_continuation.py`, `test_continuation_delivery.py`, `test_continuation_retention.py`. | **111개 통과**, 건너뜀 없음, 파일 7개입니다. |
| **C** | 운영 의도 수용 및 재검증, 온톨로지 범위 사유, 기능 확장 및 패키지 보증, 클라우드 지식 수집·예약·추출, 담당 체계 범위, 예약 결과 연결, 코드 보안 결과 수용 및 작업자입니다. | **333개 통과**, 건너뜀 없음, 파일 21개입니다. |
| **D** | 변경한 Python 계약인 보고 출처, Operator 백그라운드 작업 경계, SLO 소진 일회 실행 명령입니다. | **15개 통과**, 건너뜀 없음, 파일 3개입니다. |
| **E** | 변경한 Console 모델과 Container Apps 예약 작업 계약입니다. | **41개 통과**, 적용되지 않는 수동 트리거 건너뜀 1개, 파일 3개입니다. Console typecheck와 Terraform 형식 검사도 통과했습니다. |
| **F** | 인벤토리 및 정합성 조정, 관계 검증, 지원 관찰 어댑터, 알림 품질, RCA, 복구 준비 처리 구조입니다. | **1,196개 통과**, 건너뜀 없음입니다. |
| **G** | 운영 계획, 용량 및 FinOps 전문가, 읽기 조사와 의미 턴, 알림, 채널 신원 및 연결, Slack 및 Teams 어댑터입니다. | **1,024개 통과**, 적용되지 않는 통합 테스트 건너뜀 8개입니다. |
| **H** | 문서 계약, 수집 API, 처리 작업자, Core 문서 소유 경로, 관리 절차에 따른 변환입니다. | **929개 통과**, 데이터베이스를 사용할 수 없어 건너뜀 1개입니다. |
| **I** | 배포 CLI 자체 pytest 설정으로 실행한 소스 배포 입력, 이미지, Terraform, Trial, 업데이트, 제거, 제어 패키지 처리 구조입니다. | **207개 통과**, 건너뜀 없음입니다. |
| **J** | 서명된 오프라인 패키지의 제품화, 변조 거부, Release 안전 조건, 기한, 미러 입력, 빌드 환경, 중첩 취소입니다. | **70개 통과**, 건너뜀 없음입니다. |
| **K** | 새 기능 회수 Operator 결합과 Console 계약 및 표시입니다. | **13개 통과**, 건너뜀 없음입니다. |

첫 번째 구현 작업을 마친 뒤 권한 경계, 안전한 쪽으로 닫히는 동작, 멱등성, 비동기 정리, API 변경,
메트릭 의미, Kafka 연결, Terraform 최소 권한, Live 및 Sample 상태의 정직한 표현,
접근성, 테스트 신뢰도, 문서의 정확성이라는 12개 비평 관점을 두 차례 적용했습니다. 첫 번째
검토에서 동시 취소 제어 공백과 모호한 Terraform 사전 조건 메시지를 찾았습니다. 두 항목을
보강하고 다시 검토한 결과 Medium 이상 코드 지적은 남지 않았습니다. 이어진 격리된 시각
검사에서 모바일 입력 크기가 작은 문제를 찾았습니다. 이를 보강한 뒤 테스트 전용 Console
경로는 1440x900과 390x844에서 문서 및 main overflow 0, 모든 모바일 양식 대상 44px 이상,
Sample 모드 생성 및 취소 제어 0개를 측정했습니다. Browser Entra 또는 전체 스택 근거는
아닙니다. 배포 환경별 근거 공백은 코드 결함이나 Ready 근거로 바꾸지 않고 Partial 상태로
유지합니다.

검사는 체크아웃의 로컬 Python 및 JavaScript 도구, 테스트 대역, 임시 파일, 로컬 계약 검사를
사용했습니다. 운영 설치 환경을 선택하거나 검증하지 않았습니다.

## 관련 문서

| 알아볼 내용 | 문서 |
|-------------|------|
| 전체 기능 설명과 상태 정의 | [기능정의서](functional-specification-ko.md) |
| 세부 소스 담당 영역과 구현 상태 | [로드맵 목차](../../roadmap/README-ko.md) |
