---
title: FDAI 기능 준비 상태 평가
description: FDAI 제품 중분류 52개의 준비 상태 판정 근거와 남은 조건을 기록합니다.
translation_of: functional-readiness.md
translation_source_sha: 80290f0426659b403eb299be20a66dd56dd7ac2a
translation_revised: 2026-10-15
---

# FDAI 기능 준비 상태 평가

이 문서는 [기능정의서](functional-specification-ko.md)의 각 기능을 Ready 또는 Partial로
판정한 이유를 기록합니다. 기능 이름만으로 준비 완료를 주장하지 않고 실행 가능한
구현, 문서에 명시된 미완료 항목, 설치 환경별 운영 검증을 구분합니다.

> **평가 기준:** 2026-10-15, 기준 소스 개정 버전
> `426507a57cbfbd9bc7a9b2c8941c3c5f60db229d`와 현재 변경입니다. GitHub Copilot이 52개
> 요구사항을 담당 기록과 대조한 뒤 가장 빨리 완료할 수 있는 후보 10개를 구현하거나 다시
> 검증했습니다. 현재 작업에서 **27개 집중 파일 선택 범위의 테스트 389개**, Console
> typecheck, Terraform 형식 검사가 통과했습니다. 저장소 평가이며 독립적인
> 사람 승인이나 새로운 실제 Azure, 모델, 운영 데이터베이스, 배포 검증이 아닙니다.

## 판정 읽기

**전체:** <span class="fdai-readiness-badge" data-readiness="ready">Ready 5/52</span> <span class="fdai-readiness-badge" data-readiness="partial">Partial 47/52</span> <span class="fdai-readiness-badge" data-readiness="blocked">Blocked 0/52</span> <span class="fdai-readiness-badge" data-readiness="planned">Planned 0/52</span> <span class="fdai-readiness-badge" data-readiness="not-assessed">미평가 0/52</span>
Ready는 해당 기록에 명시된 지원 범위에만 적용됩니다. 모든 배포 환경, 공급자, 규모,
자율 작업을 검증한 것은 아닙니다. Partial은 구현이 있지만 인용한 담당 문서에 필수
지원 범위, 통합, 검증이 남아 있다는 뜻입니다. Blocked를 평가할 설치 환경은 선택하지
않았습니다. 중분류 전체가 설계만 있는 경우는 확인되지 않았으며 부분 구현된 기능 안의
설계 단계 구성요소는 명시적으로 남겨 둡니다.

Partial 47건은 담당 원장의 근거와 문서화된 제약을 사용하며 모든 구성요소의 런타임
테스트를 새로 실행한 결과는 아닙니다. 기존 테스트와 실제 환경 증적은 과거 기록으로
유지하며 이번 세션에서 갱신한 것으로 취급하지 않습니다. 아래의 남은 조건은 전체
기능을 Ready로 판정할 수 없는 이유입니다. 코드, 선언한 범위, 근거가 바뀌면 재평가합니다.

기능정의서의 상태 뱃지 의미는 [준비 상태 정의](functional-specification-ko.md#준비-상태-정의)에서
확인할 수 있고 기능명은 이 문서의 해당 기록으로 연결됩니다. 엔지니어링 구현 원장은 영문으로
제공되며 이 평가로 대체하지 않습니다.

## F01. 운영 환경

| 기능 | 상태 | 근거, 지원 범위 및 남은 조건 |
|------|------|-----------------------------|
| <span id="f01-1">F01.1</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [운영 의도 원장](../../roadmap-implementation/architecture/operating-intent-source.md)과 [리소스 원장](../../roadmap-implementation/architecture/continuous-operational-instance-graph.md)에 고정된 범위의 수용, 재검증, 격리 처리 구조, 수집원 연결이 구현되어 있으며 현재 집중 검사를 통과했습니다. 배포 환경에서 관리 절차에 따른 격리 및 복구 증적 하나와 정확한 공급자 범위의 수집 완료 근거가 필요합니다. 설정과 로컬 재현만으로 모든 연결을 입증하지 않습니다. |
| <span id="f01-2">F01.2</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [운영 의도 원장](../../roadmap-implementation/architecture/operating-intent-source.md)에 운영 의도와 변경 시간이, [규칙 원장](../../roadmap-implementation/rules-and-detection/rule-governance.md)에 규칙 설정과 예외가 구현되어 있습니다. 수집원 재검증 근거와 영속 규칙 개정 버전 업그레이드가 남아 있습니다. |
| <span id="f01-3">F01.3</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [담당 체계 원장](../../roadmap-implementation/interfaces/human-agent-assignment-and-knowledge-handover.md)에 배정, 대체 담당자, 인수인계, 담당 범위 검사 구조가 구현되어 있으며 현재 담당 체계 집중 검사를 통과했습니다. 자리표시자가 아닌 운영 담당자 연결, 검증된 대체 또는 에스컬레이션 담당 범위, 별도의 인수인계 승격 증적이 남아 있습니다. |

## F02. 리소스 및 관계

| 기능 | 상태 | 근거, 지원 범위 및 남은 조건 |
|------|------|-----------------------------|
| <span id="f02-1">F02.1</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [리소스 원장](../../roadmap-implementation/architecture/continuous-operational-instance-graph.md)에 완전한 목록의 승격 및 정합성 조정 구현과 기존 검증이 있습니다. 프라이빗 연결 환경의 변경 가속, 정확한 main 개정 버전의 공급자 수집 완료 근거, 배포별 스키마 및 권한 검증이 남아 있습니다. |
| <span id="f02-2">F02.2</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [리소스 원장](../../roadmap-implementation/architecture/continuous-operational-instance-graph.md)에 검증된 관계와 범위가 제한된 그래프 탐색이 있습니다. 애플리케이션 중심 관계의 완성과 인증된 런타임 호출 근거가 남아 있으며 모델에 있는 연결만으로 모든 의존성을 입증하지 않습니다. |
| <span id="f02-3">F02.3</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [리소스 원장](../../roadmap-implementation/architecture/continuous-operational-instance-graph.md)에 이중 시간축 토폴로지, 정규화된 관찰, 명시적 관찰 범위 사유, 관찰 범위를 고려한 이력이 있으며 보류 상태 및 PostgreSQL 범위 사유 집중 검사를 통과했습니다. 운영 환경의 토폴로지 보존, 보관 및 복원 근거, 완전한 시간 구간의 관찰 범위가 남아 있습니다. |

## F03. 관측 및 예방과 예측

| 기능 | 상태 | 근거, 지원 범위 및 남은 조건 |
|------|------|-----------------------------|
| <span id="f03-1">F03.1</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [SRE 기능 지도](../sre/README-ko.md)와 [리소스 원장](../../roadmap-implementation/architecture/continuous-operational-instance-graph.md)에 신호 어댑터와 탐지기가 있습니다. 전체 수집원에 대한 실제 관측 데이터 연결, 수집원별 완전성, 배포 환경의 수집 측정이 필요합니다. |
| <span id="f03-2">F03.2</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [SLO 가이드](../sre/slos-and-error-budgets-ko.md)에 레지스트리, 평가기, 이벤트 실행기, 안전한 쪽으로 닫히는 일회 실행 명령, 단일 복제본의 선택적 Container Apps 일정이 구현되어 있으며 집중 CLI 및 인프라 검사를 통과했습니다. 배포 환경은 비어 있지 않은 워크로드 카탈로그를 패키징하고, 권위 있는 메트릭 공급자를 연결하고, 일정을 활성화하고, 완전한 실행과 데이터 부족 실행의 증적을 남겨야 합니다. |
| <span id="f03-3">F03.3</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [용량 가이드](../sre/capacity-and-performance-ko.md)와 [계획 원장](../../roadmap-implementation/decisioning/operational-planning.md)에 용량 및 예측 추론이 있습니다. 최신 수요, 할당량 및 의존성 근거와 관리 절차에 따른 확장 결과의 평가 집단이 남아 있습니다. |
| <span id="f03-4">F03.4</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [알림 품질 원장](../../roadmap-implementation/operations/alert-noise-governance.md)에 결정론적 평가와 수집원 공백 보고가 구현되어 있습니다. 신뢰할 수 있는 수신자 및 담당 체계 근거, 독립적인 정답 표기, 공급자 적합성, 운영 수용 검증은 확인되지 않았습니다. |

## F04. 인시던트

| 기능 | 상태 | 근거, 지원 범위 및 남은 조건 |
|------|------|-----------------------------|
| <span id="f04-1">F04.1</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 심각도 및 상태 변경, 배정, 감사 기록, 재현을 포함한 기본 인시던트 레지스트리와 관련 신호를 연결하는 수명 주기 워크플로입니다. [레지스트리](../../../services/core-control-plane/src/fdai/core/incident/registry.py)와 [워크플로](../../../services/core-control-plane/src/fdai/core/incident/workflow.py)를 검토하고 검사 A에서 [수명 주기](../../../services/core-control-plane/tests/core/incident/test_incident_lifecycle.py), [워크플로](../../../services/core-control-plane/tests/core/incident/test_incident_workflow.py), [이벤트 폭주](../../../services/core-control-plane/tests/core/incident/test_storm.py) 테스트를 재실행했습니다. 외부 알림의 적합성 검증은 F09.3에서 별도로 다룹니다. |
| <span id="f04-2">F04.2</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [원인 분석 원장](../../roadmap-implementation/rules-and-detection/root-cause-analysis.md)에 티어별 가설, 통제된 문서, 관측 데이터 경로, 인과 근거가 구현되어 있습니다. 정확한 개정 버전의 운영 원인 정확도, 판단 보류, 여러 작업 영역의 근거, 독립적으로 검증된 결과가 남아 있습니다. |
| <span id="f04-3">F04.3</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [계획 원장](../../roadmap-implementation/decisioning/operational-planning.md)과 [학습 가이드](../sre/postmortems-and-learning-ko.md)에 대응 계획 및 사후 분석 기반이 있습니다. 전체 대응 경로의 관리 절차에 따른 승인, 실행, 관찰된 복구, 후속 조치 종결은 입증되지 않았습니다. |

## F05. 복원력 및 복구

| 기능 | 상태 | 근거, 지원 범위 및 남은 조건 |
|------|------|-----------------------------|
| <span id="f05-1">F05.1</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [재해 복구 가이드](../sre/disaster-recovery-and-drills-ko.md)에 백업 검사와 복원 사전 조건이 정의되어 있고 [복구 원장](../../roadmap-implementation/decisioning/recovery-and-chaos-enforcement.md)에 복구 처리 구조가 구현되어 있습니다. 정확한 워크로드의 복구 지점, 복원, 독립적인 무결성 근거가 필요하며 백업 성공만으로는 충분하지 않습니다. |
| <span id="f05-2">F05.2</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [재해 복구 가이드](../sre/disaster-recovery-and-drills-ko.md)는 구현된 단일 지역 복구 기반과 대체 지역 인프라, 트래픽 및 이벤트 연속성, 측정된 장애 조치 및 복귀를 구분합니다. 전체 범위의 RPO/RTO와 정리 증적이 필요합니다. |
| <span id="f05-3">F05.3</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [카오스 원장](../../roadmap-implementation/decisioning/recovery-and-chaos-enforcement.md)에 공급자 패키지와 안전 조건을 적용한 실행 구조가 있습니다. 보호된 공급자 입력, 실제 에이전트 소유 권한 기록, 적법한 승격, 관리 절차에 따른 장애 주입 및 복구 검증이 남아 있습니다. |

## F06. 변경 및 아키텍처

| 기능 | 상태 | 근거, 지원 범위 및 남은 조건 |
|------|------|-----------------------------|
| <span id="f06-1">F06.1</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [변경 가이드](../capabilities/change-safety-ko.md)와 [계획 원장](../../roadmap-implementation/decisioning/operational-planning.md)에 정책 평가와 형식이 지정된 계획이 있습니다. 현재 개정 버전의 전체 경로 사람 승인 및 독립적인 결과 근거가 남아 있으며 시뮬레이션이나 제안만으로 변경이 종결되지 않습니다. |
| <span id="f06-2">F06.2</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [규칙 원장](../../roadmap-implementation/rules-and-detection/rule-governance.md)에 규칙 범위 지정, 활성화, 예외가 있습니다. 영속 규칙 개정 버전의 호환성 업그레이드와 운영 적용 단계, 구성 불일치 판단을 위한 완전한 수집 범위가 남아 있습니다. |
| <span id="f06-3">F06.3</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [아키텍처 검토 원장](../../roadmap-implementation/architecture/architecture-review-board.md)과 [준비 상태 원장](../../roadmap-implementation/operations/operational-readiness.md)에 검토 처리 구조가 있습니다. 운영 근거 및 담당자 연결과 수정 제안을 위험 및 승인 입력 경로로 전달하는 게시자가 완성되지 않았습니다. |

## F07. 비용 거버넌스

| 기능 | 상태 | 근거, 지원 범위 및 남은 조건 |
|------|------|-----------------------------|
| <span id="f07-1">F07.1</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [효율성 원장](../../roadmap-implementation/architecture/finops-resource-efficiency.md)에 구독 및 리소스 분석과 Console 조회 결과가 구현되어 있습니다. 완전한 사용률 및 관계 범위, 정확한 기준 시점의 제외 대상, 현재 원본 데이터의 재조회가 남아 있습니다. |
| <span id="f07-2">F07.2</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [효율성 원장](../../roadmap-implementation/architecture/finops-resource-efficiency.md)과 [FinOps 원장](../../roadmap-implementation/architecture/finops-autonomous-operations.md)에 예산, 추세, 이상 탐지 기반이 있습니다. 호환되는 사용률 근거와 조건을 충족하는 운영 평가 집단은 불완전하며 기존 부분 분석만으로 전체 예측 검증을 대신하지 않습니다. |
| <span id="f07-3">F07.3</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | 일반적인 크기 조정 안전 조건은 있지만 [효율성 원장](../../roadmap-implementation/architecture/finops-resource-efficiency.md)에 검토된 서비스 계열별 프로파일, 결합 대상의 결정 구성, 범위가 제한된 확인 질문은 명시적으로 미착수 상태입니다. 공통 기반만으로 리소스별 최적화가 완성되지는 않습니다. |
| <span id="f07-4">F07.4</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [FinOps 원장](../../roadmap-implementation/architecture/finops-autonomous-operations.md)에 독립적인 효과 정산이 구현되어 있습니다. [효율성 원장](../../roadmap-implementation/architecture/finops-resource-efficiency.md)에는 비용, 용량, 서비스, 복구 효과가 모두 정산된 실제 환경의 고정된 리소스 효율성 사례가 아직 없습니다. |

## F08. 작업 및 워크플로

| 기능 | 상태 | 근거, 지원 범위 및 남은 조건 |
|------|------|-----------------------------|
| <span id="f08-1">F08.1</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 매개변수, 참조, 위험 및 복구 선언, 관찰 모드 기본값을 포함한 배포된 등록 ActionType 및 Workflow 카탈로그입니다. [ActionType](../../../services/core-control-plane/src/fdai/rule_catalog/schema/action_type.py) 및 [Workflow](../../../services/core-control-plane/src/fdai/rule_catalog/schema/workflow.py) 로더를 검토하고 검사 A에서 [작업 카탈로그](../../../services/core-control-plane/tests/rule_catalog/test_action_type_catalog.py) 및 [워크플로 카탈로그](../../../services/core-control-plane/tests/rule_catalog/test_workflow_catalog.py) 테스트를 재실행했습니다. 카탈로그 유효성은 모든 설계 목록의 워크플로 구현이나 승격을 입증하지 않습니다. |
| <span id="f08-2">F08.2</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [계획 원장](../../roadmap-implementation/decisioning/operational-planning.md)에 여러 단계의 계획, 전문가 의견 중재, 복구 계약이 있습니다. 독립 서비스의 사람 승인 연결과 관리 절차에 따른 전체 확장 효과 근거가 남아 있습니다. |
| <span id="f08-3">F08.3</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 기본 예약 및 수동 전달, 지원 일정 종류, 범위가 제한된 격리, 이력, 결과 연결 처리 구조입니다. [스케줄러](../../../services/core-control-plane/src/fdai/core/scheduler/service.py)를 검토했고 검사 B에서 중복 방지, 이력, 격리, 결과 연결의 보존 및 전달을 포함한 [스케줄러 테스트 파일](../../../services/core-control-plane/tests/core/scheduler/) 7개를 재실행했습니다. 전달 수락은 작업 성공이나 실제 채널 검증을 뜻하지 않습니다. |
| <span id="f08-4">F08.4</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [워크플로 원장](../../roadmap-implementation/decisioning/process-automation.md)과 [복구 원장](../../roadmap-implementation/decisioning/recovery-and-chaos-enforcement.md)에 형식이 지정된 실행, 중단, 복구 처리 구조가 있습니다. 독립적인 효과 및 복구 종결이 있는 승격된 워크플로가 남아 있으며 공급자 차원의 동시 실행 차단도 긴급 상시 권한을 제한합니다. |

## F09. 운영자 조사 및 협업

| 기능 | 상태 | 근거, 지원 범위 및 남은 조건 |
|------|------|-----------------------------|
| <span id="f09-1">F09.1</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [운영자 가이드](../guides/use-operator-conversations-ko.md)와 [원인 분석 원장](../../roadmap-implementation/rules-and-detection/root-cause-analysis.md)에 범위가 제한된 대화와 근거 기반 조사가 있습니다. 관리 절차에 따른 원인 분석 품질 검증과 완전한 수집원 및 채널 연결이 남아 있으며 답변이 표시된다는 사실만으로 의미의 정확성을 입증하지 않습니다. |
| <span id="f09-2">F09.2</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [백그라운드 작업 원장](../../roadmap-implementation/interfaces/background-task-sessions.md)에 영속 작업, 임대, 타입이 지정된 생성 및 취소 수용, Web 전달, Slack/Teams 발신 대기열 등록, Live 전용 Console 생성 및 취소 제어가 구현되어 있습니다. 관리 절차에 따른 요청, 재시작, 전달, 관측 증적이 남아 있습니다. |
| <span id="f09-3">F09.3</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [채널 원장](../../roadmap-implementation/interfaces/channels-and-notifications.md)에 라우팅과 영속 채널 처리 구조가 있습니다. 실제 콜백 및 브로커 증적, Slack 발신 승인 연결과 [권한 원장](../../roadmap-implementation/decisioning/escalation-and-standing-authority.md)의 긴급도 및 에스컬레이션 근거가 남아 있습니다. |
| <span id="f09-4">F09.4</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [결과 연결 원장](../../roadmap-implementation/interfaces/scheduled-result-continuations.md)에 계정 연결, 보존된 맥락, 결과 전달, 보존 처리 구조가 있으며 현재 집중 검사를 통과했습니다. 검증된 운영 배정, 채널 출처 연속성, 관리 절차에 따른 삭제, 별도의 선제적 인수인계 승격 증적이 남아 있습니다. |

## F10. 지식 및 규칙

| 기능 | 상태 | 근거, 지원 범위 및 남은 조건 |
|------|------|-----------------------------|
| <span id="f10-1">F10.1</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [문서 원장](../../roadmap-implementation/interfaces/document-ingestion.md)에 수집, 보호, 추출, 색인, 보존 통제가 있습니다. 관리 절차에 따른 5개 서비스의 업로드부터 인용·삭제·재시작까지의 증적과 승인된 외부 보호 및 SharePoint 연결이 남아 있습니다. |
| <span id="f10-2">F10.2</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [클라우드 지식 원장](../../roadmap-implementation/interfaces/cloud-resource-knowledge-lifecycle.md)에 개정 버전을 안전하게 처리하는 수집, 예약, 추출, 교체, 통제된 조회가 구현되어 있으며 현재 집중 검사를 통과했습니다. 배포 환경 소유의 문서 평가 집단, 연결 구성요소의 수명 주기 근거, 원본 데이터의 최신성 검증이 남아 있습니다. |
| <span id="f10-3">F10.3</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [규칙 원장](../../roadmap-implementation/rules-and-detection/rule-governance.md)에 작성, 활성화, 범위 지정, 예외가 있습니다. 영속 규칙 개정 버전의 이중 읽기 호환성과 순서에 따른 적용 및 롤백 단계가 남아 있습니다. |
| <span id="f10-4">F10.4</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [변환 원장](../../roadmap-implementation/rules-and-detection/manual-distillation.md)에 문서를 규칙 및 워크플로로 바꾸는 변환과 통제된 인수인계가 구현되어 있습니다. 배포 환경의 접근·목적·철회, 법적 보존 후 삭제, 공급자 적합성, 별도의 승격 근거가 남아 있습니다. |

## F11. 평가 및 학습과 승격

| 기능 | 상태 | 근거, 지원 범위 및 남은 조건 |
|------|------|-----------------------------|
| <span id="f11-1">F11.1</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [학습 원장](../../roadmap-implementation/rules-and-detection/operational-learning-ontology.md)에 변경 불가능한 사례와 학습 후보가 있습니다. 범위가 제한된 Pattern 보존, 현재 권한에 따른 수용, 예측 학습 통합 기준은 완성되지 않았습니다. |
| <span id="f11-2">F11.2</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [학습 원장](../../roadmap-implementation/rules-and-detection/operational-learning-ontology.md)과 [워크플로 원장](../../roadmap-implementation/agents/agent-workflows.md)에 재현, 시나리오 평가, 측정 기반 기준이 있습니다. 전체 평가를 주장하려면 완전한 실제 재발 관찰 구간, 작업 표본, 기준선과 추적 근거가 필요합니다. |
| <span id="f11-3">F11.3</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [거버넌스 원장](../../roadmap-implementation/decisioning/operator-governance-profiles.md)에 통제된 승격 및 운영자 재정의 제어가 있습니다. Operator 및 Console의 회수 상태 표시와 운영 Release 최대값 연결이 남아 있으며 기능 묶음 수명 주기 검증도 불완전합니다. |

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
| <span id="f13-1">F13.1</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [리소스 원장](../../roadmap-implementation/architecture/continuous-operational-instance-graph.md)과 [보고서 원장](../../roadmap-implementation/interfaces/reporting-subsystem.md)에 목록 탐색과 보고서 및 인시던트 화면의 기존 검증이 있습니다. 회수 상태 표시를 포함해 나열된 작업, 승인, 결과 화면 전체의 현재 원본 데이터에 근거한 범위는 불완전합니다. |
| <span id="f13-2">F13.2</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [보고서 원장](../../roadmap-implementation/interfaces/reporting-subsystem.md)에 보고서 카탈로그, 렌더링, 격리, 형식, 감사 기반 인시던트 자료 및 PDF, 명시적인 부분 원본 출처가 구현되어 있습니다. 모든 운영 데이터 수집원의 최신성, 시간 초과, 부분 수집 증적과 전체 인증 화면 검증이 남아 있습니다. |
| <span id="f13-3">F13.3</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [성과 가이드](../sre/measuring-sre-outcomes-ko.md)에 기준선에 따른 측정이 정의되어 있고 [FinOps 원장](../../roadmap-implementation/architecture/finops-autonomous-operations.md)에 정산 및 검증 집계가 있습니다. 조건을 충족하는 작업 사례와 완전한 기준 및 조치 후 결과 구간이 남아 있습니다. |

## F14. 설치 및 설정과 확장

| 기능 | 상태 | 근거, 지원 범위 및 남은 조건 |
|------|------|-----------------------------|
| <span id="f14-1">F14.1</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [소스 배포 원장](../../roadmap-implementation/deployment/source-deployment.md)에 브라우저, 목록, 상태, 변경 없음 근거를 갖춘 검증된 키 없는 설치 기록이 있습니다. 변경 없는 키 없는 재실행, 키 보유자 설치, Trial에서 전체 사용 권한으로의 전환 검증이 남아 있으며 하나의 증적으로 전체 설치 조합을 검증하지 않습니다. |
| <span id="f14-2">F14.2</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | 소스 및 오프라인 경로는 있지만 [Hub 원장](../../roadmap-implementation/deployment/hub-managed-lifecycle.md)에 인증 API, 마이그레이션, 수명 주기 에이전트, 설치 수용 검증이 남아 있습니다. 로컬 Hub 시연은 지원되는 완성된 수명 주기가 아닙니다. |
| <span id="f14-3">F14.3</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [제품화 담당 문서](../../roadmap/fork-and-sequencing/productization-and-extensibility-ko.md)에 모델 및 설정 기반이 있고 [소스 원장](../../roadmap-implementation/deployment/source-deployment.md)에 Trial 및 워터마크 처리 구조가 있습니다. 실제 키 보유자 및 Trial에서 전체 사용 권한으로 전환할 때의 워터마크 근거와 전체 회수 모드 표시가 남아 있습니다. |
| <span id="f14-4">F14.4</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [기능 묶음 원장](../../roadmap-implementation/architecture/capability-bundle-lifecycle.md)에 신뢰, 호환성, 비활성 설치 후 활성화, 철회, 연결된 증적의 완전성 규칙이 구현되어 있으며 현재 확장 및 패키지 보증 집중 검사를 통과했습니다. 운영 환경에서 정확한 산출물의 설치, 활성화, 비활성화, 철회, 재시작, 공개 증적 묶음이 남아 있습니다. |

## F15. 코드 보안

| 기능 | 상태 | 근거, 지원 범위 및 남은 조건 |
|------|------|-----------------------------|
| <span id="f15-1">F15.1</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | [검사 원장](../../roadmap-implementation/operations/code-security-scanning.md)에 코드 확보, 격리된 검사 경로, SARIF 수집, Console 및 예약 작업자, 독립적인 결정론적 결과 수용, 최종 요청 변환 결과가 구현되어 있으며 현재 작업자 및 수용 집중 검사를 통과했습니다. 선택한 배포 환경의 작업자 heartbeat와 정확한 최종 게시 및 재조회 증적 하나가 남아 있습니다. |
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

구현을 마친 뒤 권한 경계, 안전한 쪽으로 닫히는 동작, 멱등성, 비동기 정리, API 변경,
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
