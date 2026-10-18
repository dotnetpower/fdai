---
title: FDAI 기능 준비 상태 평가
description: FDAI 제품 중분류 52개의 준비 상태 판정 근거와 남은 조건을 기록합니다.
translation_of: functional-readiness.md
translation_source_sha: ac31f2101a0f1a3f3312861b5b3b97c120d47c2f
translation_revised: 2026-10-18
---

# FDAI 기능 준비 상태 평가

이 문서는 [기능정의서](functional-specification-ko.md)의 각 기능을 Ready 또는 Partial로
판정한 이유를 기록합니다. 기능 이름만으로 준비 완료를 주장하지 않고 실행 가능한
구현, 문서에 명시된 미완료 항목, 설치 환경별 운영 검증을 구분합니다.

> **점검 기준:** 2026-10-18, 소스 개정 버전
> `8819a28951fd5c21858adc0a8e7a6d5278ba4745`입니다. F10-F15 중분류 21개 전체를 담당
> 원장, 관련 소스, 개별 이슈 상태와 대조하고 Ready 10건을 Partial로 정정했습니다.
> F01-F09는 기존 평가를 유지합니다. [전수 목록과 실행 계획](functional-readiness-backlog-ko.md)에
> 모든 점검 대상, 잔여 작업, 의존성, 완료 조건을 기록합니다. 이번 문서 점검에서는 런타임
> 테스트나 실제 운영 검증을 수행하지 않았습니다.

> **과거 구현 근거:** 개정 버전 `966082d265a7a230b41394b67e63ccd6fd328fa9`와
> F06/F07 구현 변경을 기준으로 완료 작업은 모든
> 필수 기능을 소스, 조립, 영속성, 권한, 증적 소유자까지 추적했습니다. 최종 누적 범위에서
> **집중 검사 908개**와 **실제 격리 PostgreSQL 검사 8개**가 통과했습니다. 관련 없는 선택형
> PostgreSQL 내보내기 검사 하나는 외부 검증 변수가 구성되지 않아 건너뛰었습니다. 각 기능군에
> 대해 10개 통제의 비평 라운드 10회를 완료했고 최종 구현 범위에는 확인된 Low 초과 결함이
> 없습니다. 이는 저장소 구현 근거이며 독립적인 사람 승인이나 Azure, 모델, 청구 데이터,
> 운영 데이터베이스, 배포에 대한 새로운 실제 환경 검증이 아닙니다.

## 판정 읽기

**전체:** <span class="fdai-readiness-badge" data-readiness="ready">Ready 28/52</span> <span class="fdai-readiness-badge" data-readiness="partial">Partial 24/52</span> <span class="fdai-readiness-badge" data-readiness="blocked">Blocked 0/52</span> <span class="fdai-readiness-badge" data-readiness="planned">Planned 0/52</span> <span class="fdai-readiness-badge" data-readiness="not-assessed">미평가 0/52</span>
Ready는 해당 기록에 명시된 지원 범위에만 적용됩니다. 모든 배포 환경, 공급자, 규모,
자율 작업을 검증한 것은 아닙니다. Partial은 구현이 있지만 인용한 담당 문서에 필수
지원 범위, 통합, 검증이 남아 있다는 뜻입니다. Blocked를 평가할 설치 환경은 선택하지
않았습니다. 중분류 전체가 설계만 있는 경우는 확인되지 않았으며 부분 구현된 기능 안의
설계 단계 구성요소는 명시적으로 남겨 둡니다.

Partial 24건은 구현된 부분과 기록된 집중 검사 근거를 유지하지만, 필수 기능이나 운영 근거를
지원 범위 밖으로 줄여서 제외하지 않습니다. 기존 실제 환경 증적은 과거 기록으로 유지하며 이번
세션에서 갱신하거나 특정 설치 환경을 검증한 것으로 취급하지 않습니다. 각 기록의 남은 조건을
모두 충족한 뒤에만 Ready로 승격합니다.

기능정의서의 상태 뱃지 의미는 [준비 상태 정의](functional-specification-ko.md#준비-상태-정의)에서
확인할 수 있고 기능명을 선택하면 이 문서의 해당 기록으로 이동합니다. 엔지니어링 구현 원장은 영문으로
제공되며 이 평가로 대체하지 않습니다.

## F01. 운영 환경

| 기능 | 상태 | 근거, 지원 범위 및 남은 조건 |
|------|------|-----------------------------|
| <span id="f01-1">F01.1</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 고정된 관리 범위의 수용, 지속적인 재검증, 안전한 쪽으로 닫히는 격리 및 복구 처리 구조, 정확히 구성된 수집원 연결입니다. [운영 의도 원장](../../roadmap-implementation/architecture/operating-intent-source.md), [리소스 원장](../../roadmap-implementation/architecture/continuous-operational-instance-graph.md), 현재 집중 검사가 이 범위를 뒷받침합니다. 특정 설치 환경의 공급자 연결과 관리 절차에 따른 격리 훈련은 Ready 범위가 아닌 배포 검증입니다. |
| <span id="f01-2">F01.2</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | 범위는 버전이 지정된 운영 의도, 서비스 목표 및 임계값, 유지보수 시간, 알림 억제, 영향 제한, 현재 스키마에 따른 규칙 활성화 및 개정된 예외입니다. [운영 의도 원장](../../roadmap-implementation/architecture/operating-intent-source.md), [규칙 원장](../../roadmap-implementation/rules-and-detection/rule-governance.md), 집중 테스트 9개가 이 범위를 뒷받침합니다. 설치 수집원 재검증과 기존 규칙 개정 버전의 업그레이드는 별도 배포 검증입니다. |
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
| <span id="f04-1">F04.1</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 감지기가 생성하는 Incident, 심각도 및 상태 변경, 배정, 감사 기록, 재현을 포함한 기본 인시던트 레지스트리와 수명 주기 워크플로입니다. 기본 정책은 범위가 제한된 완전한 근거를 포함한 서로 다른 발견된 문제 5건이 5분 안에 같은 상관관계로 들어온 경우에만 중간 이상의 심각도 에피소드를 엽니다. 낮음 및 정보 심각도, 드물거나 관련이 없는 발견된 문제, 중복된 문제는 올바르게 Incident를 만들지 않습니다. [레지스트리](../../../services/core-control-plane/src/fdai/core/incident/registry.py), [워크플로](../../../services/core-control-plane/src/fdai/core/incident/workflow.py), 분석기에서 Incident로 이어지는 경로를 검토하고 수명 주기, 워크플로, 이벤트 폭주, 자동 열기, 런타임 설정, 분석기 인계 집중 검사를 다시 실행했습니다. 따라서 Incident 수가 0이라는 사실만으로 준비 상태 실패를 뜻하지 않습니다. 설치 환경의 재정의와 새로운 운영 생성 근거는 별도 배포 검증입니다. 외부 알림의 적합성 검증은 F09.3에서 별도로 다룹니다. |
| <span id="f04-2">F04.2</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 티어별 인과 가설, 통제된 문서 및 관측 데이터 근거, 토폴로지 및 변경 구분, 충돌 근거 처리, 판단 보류, 감사 가능한 인과 체인입니다. [원인 분석 원장](../../roadmap-implementation/rules-and-detection/root-cause-analysis.md)과 집중 RCA 검사가 이 범위를 뒷받침합니다. 정확한 원인 분석 품질과 여러 작업 영역의 수집원 범위는 별도 설치 및 운영 검증입니다. |
| <span id="f04-3">F04.3</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 타입이 지정된 대응 계획, 완화 대안, 기대 효과, 중단 및 복구 계약, 인시던트 인계, 미해결 결과 보존, 사후 분석 및 후속 작업 준비입니다. [계획 원장](../../roadmap-implementation/decisioning/operational-planning.md), [학습 가이드](../sre/postmortems-and-learning-ko.md), 집중 계획 검사가 이 범위를 뒷받침합니다. 특정 작업의 승인, 실행, 관찰된 복구는 별도 작업 및 배포 검증입니다. |

## F05. 복원력 및 복구

| 기능 | 상태 | 근거, 지원 범위 및 남은 조건 |
|------|------|-----------------------------|
| <span id="f05-1">F05.1</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 백업 준비 상태 평가, 복구 지점 근거 요구사항, 복원 사전 조건, 범위가 제한된 복구 계획, 무결성 근거가 없을 때 안전한 쪽으로 닫히는 처리입니다. [재해 복구 가이드](../sre/disaster-recovery-and-drills-ko.md), [복구 원장](../../roadmap-implementation/decisioning/recovery-and-chaos-enforcement.md), 집중 복구 검사가 이 범위를 뒷받침합니다. 정확한 워크로드의 백업, 복원, 독립 무결성 증적은 별도 설치 검증이며 백업 성공만으로 복구 가능성을 입증하지 않습니다. |
| <span id="f05-2">F05.2</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | 범위는 계획 및 권한 검사, Azure 복원 전달, 무결성 및 기본 동작 검증, 측정된 RPO/RTO, 최종 감사, 정리, 민감정보를 제거한 보고를 포함하는 PostgreSQL 복원 훈련입니다. [재해 복구 가이드](../sre/disaster-recovery-and-drills-ko.md)와 집중 테스트 26개가 이 범위를 뒷받침합니다. 대체 지역 인프라, 트래픽 및 이벤트 연속성, 특정 설치 환경의 장애 조치 및 복귀 증적은 별도 배포 검증입니다. |
| <span id="f05-3">F05.3</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | 범위는 타입이 지정된 카오스 계획, 별도의 현재 권한, 범위가 제한된 공급자 장애 주입, 지속적인 중단 조건 평가, 복구, 효과 검증, 최종 감사, 미지원 공급자의 안전한 차단입니다. [카오스 원장](../../roadmap-implementation/decisioning/recovery-and-chaos-enforcement.md)과 집중 테스트 23개가 이 범위를 뒷받침합니다. 공급자 자격 증명, 승격된 실험, 실제 장애 및 복구 검증은 별도 배포 검증입니다. |

## F06. 변경 및 아키텍처

| 기능 | 상태 | 근거, 지원 범위 및 남은 조건 |
|------|------|-----------------------------|
| <span id="f06-1">F06.1</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 타입이 지정된 제안 변경 수집, 정책 및 위험 평가, 정확한 대상 및 개정 버전 검증, 범위가 제한된 시뮬레이션, 대안 비교, 중단 조건, 최종 계획의 롤백 근거입니다. [변경 가이드](../capabilities/change-safety-ko.md), [계획 원장](../../roadmap-implementation/decisioning/operational-planning.md), 집중 계획 검사가 이 범위를 뒷받침합니다. 승인, 실행, 독립적인 변경 후 관찰은 별도 작업 검증이며 제안만으로 변경을 종결하지 않습니다. |
| <span id="f06-2">F06.2</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | 범위는 현재 스키마의 구성 불일치 및 통제 미비 결과, 범위가 지정된 정책 평가, 근거가 있는 예외, 결정론적 충돌, 보존된 산출물과 cohort 활성화, 폐기, 롤백, 권한 비교 후 설정까지 포함하는 룰 개정 9단계 전체입니다. [규칙 원장](../../roadmap-implementation/rules-and-detection/rule-governance.md)과 현재 집중 검사 78개가 구현 범위를 뒷받침합니다. 실제 설치 환경의 기존 포인터 이행, 완전한 공급자 수집, 신뢰된 Entra 검증 근거, 여러 복제본의 수렴, 직접 또는 오프라인 활성화 증적, 측정된 적용 품질은 필수 운영 조건이므로 Partial을 유지합니다. |
| <span id="f06-3">F06.3</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | 범위는 변경 불가능한 ARB 근거 묶음 및 증적, 아키텍처와 준비 상태 평가, 런타임이 선택한 타입 지정 ORR 수신, 증적 기반 준비 상태, Forseti 소유 관찰, 여러 복제본에 걸친 영구 중복 제거 및 변환 결과 보호입니다. 원본이 없거나 모호하거나 오래되거나 잘리거나 불완전하면 승인, 토픽 소유권, 변경 또는 실행 권한 없이 보류합니다. [아키텍처 검토 원장](../../roadmap-implementation/architecture/architecture-review-board.md), [준비 상태 원장](../../roadmap-implementation/operations/operational-readiness.md), 집중 검사 194개와 격리 PostgreSQL 검사 4개가 이 범위를 뒷받침합니다. 프로덕션 posture/report/admission 공급자, 실제 책임 담당자 승인, 전체 shadow 및 승격 cohort, 서명된 종료 증적, 배포된 Workflow 효과 증적은 필수이지만 검증되지 않았으므로 Partial을 유지합니다. |

## F07. 비용 거버넌스

| 기능 | 상태 | 근거, 지원 범위 및 남은 조건 |
|------|------|-----------------------------|
| <span id="f07-1">F07.1</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 구독 및 리소스의 비용과 사용률 분석, 배분 공백, 서비스 및 리소스 귀속, 수집원 출처 이력, 불완전하거나 사용할 수 없는 근거를 보존하는 Console 변환 결과입니다. [효율성 원장](../../roadmap-implementation/architecture/finops-resource-efficiency.md)과 집중 FinOps 검사가 이 범위를 뒷받침합니다. 현재 청구 및 사용률 연결과 완전한 관계 범위는 별도 설치 검증입니다. |
| <span id="f07-2">F07.2</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 제한된 예산 비교, 기준선 및 추세 분석, 출처 구간이 있는 예측, 표본 수, MAPE, 부호가 있는 편향, 원본 계보를 보존하는 영구 예측-실제값 보정, 명시적인 부분 또는 사용 불가 상태입니다. [효율성 원장](../../roadmap-implementation/architecture/finops-resource-efficiency.md), [FinOps 원장](../../roadmap-implementation/architecture/finops-autonomous-operations.md), 비용 거버넌스 집중 검사가 이 범위를 뒷받침합니다. 현재 설치 환경의 청구 및 사용률 연결과 실제값이 0이 아닌 측정 보정 cohort는 별도 설치 검증입니다. 실제값 분모가 없거나 0이면 오류 0으로 표시하지 않습니다. |
| <span id="f07-3">F07.3</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 버전이 지정된 서비스 기능군 프로필 5개, 필수 메트릭 및 비호환성 검사, 단일 리소스 및 제한된 결합 대상 계획, 활성화 개정으로 제한된 정규 수신, Njord 소유 영구 게시, 책임이 구분된 Freyr/Forseti/Odin 처리, 타입이 지정된 확인 근거 재수집, 기존 Var/Thor 승인 및 실행 연결입니다. [효율성 원장](../../roadmap-implementation/architecture/finops-resource-efficiency.md)과 집중 패키지, 에이전트, 전달 및 교차 vertical 검사가 이 범위를 뒷받침합니다. 실제 설치 환경의 승인, 실행, 롤백 및 독립 정산 결과 증적은 별도 검증이며 Ready 상태만으로 충족되지 않습니다. |
| <span id="f07-4">F07.4</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 정확한 사례 및 작업 개정 정산, 하나의 통화, 비교 가능한 기준 및 처리 구간, 수요 정규화, 독립 비용·용량·서비스·복구 효과, 검증된 실행 요율과 청구서 배부 근거 등급의 분리입니다. 청구서 배부에는 확정 청구와 배부 규칙 증적도 필요합니다. [FinOps 원장](../../roadmap-implementation/architecture/finops-autonomous-operations.md), [효율성 원장](../../roadmap-implementation/architecture/finops-resource-efficiency.md), 집중 정산 검사가 이 범위를 뒷받침합니다. 실제 고정 정산 에피소드와 확정 청구 증적은 구현 근거가 아니라 별도 설치 검증입니다. |

## F06 및 F07의 남은 운영 작업

완료 작업에서는 재현할 수 있는 저장소 구현 공백을 모두 수정했습니다. 아래 항목에는 정확한 설치
환경, 외부 신원, 책임 담당자, 공급자 원본 또는 측정된 운영 에피소드가 필요합니다. 모두 필수
조건으로 유지합니다. F07의 Ready는 일반 구현이 명시된 동작을 지원한다는 뜻이며, 설치별 입력이나
프로덕션 절감 효과를 만들어 냈다는 뜻이 아닙니다.

### F06.2 배포 및 정책 적용

| 남은 작업 | 최종 소유자 | 완료 근거 |
|-----------|-------------|-----------|
| 보존된 이전 Rule 포인터와 cohort를 현재 9단계 개정 경로로 이행 | Mimir 및 release 소유자 | 정확한 이전/새 release, 이행 증적, 활성 포인터 재확인, 롤백과 이력 보존 검증 |
| 완전한 구성 불일치 및 통제 미비 공급자 수집 연결 | Huginn, Heimdall 및 배포 공급자 소유자 | 인증된 범위, 원본 신원, 완전성/최신성 증적과 누락 원본 동작 측정 |
| 신뢰된 Entra 거버넌스 검증 GitHub App 배포 | 보안 및 저장소 소유자 | 설치된 App id, 피싱 방지 신원 증명과 수락된 exact-head 검사 |
| 관리 변경의 차단 후 독립 검토 수정으로 해제되는 과정 검증 | Var, Mimir 및 Saga | 자기 승인 또는 정족수 미달 차단, 수정 승인, exact-head 검사와 감사 연결 |
| 프로덕션 알림기로 예외 만료 예약 | Mimir, Saga 및 운영 소유자 | 작업 일정, 만료 감사, 실제 알림 증적 하나와 중복 억제 |
| 재정의 검색 근거 원본 연결 | Norns, Mimir 및 배포 조립 소유자 | 현재 `governance.override_resolved` 원본, 정확한 구간과 독립 원본 인가 |
| 실행 중 복제본 간 세대 수렴 검증 | Mimir 및 런타임/release 소유자 | 복제본 2개 이상이 재시작과 롤백 뒤 같은 세대를 재확인 |
| 직접 및 오프라인 활성화 경로 실행 | Mimir, Var, Saga 및 release 소유자 | 인증된 직접 승인과 서명된 오프라인 패키지 증적 및 정확한 개정 재확인 |
| 공급자 전체 구성 불일치 품질 측정 | Heimdall 및 Forseti | 동결 범위의 오탐, 미탐, 보류, 관찰 범위 분모 |

### F06.3 ARB 및 운영 준비 상태 검증

| 남은 작업 | 최종 소유자 | 완료 근거 |
|-----------|-------------|-----------|
| 프로덕션 posture 공급자 연결 | Heimdall, Assurance Twin 및 배포 소유자 | 원본 신원, 최신성, 완전성을 가진 현재 workload/범위 변환 결과 |
| 준비 상태 보고서 게시자 연결 | Forseti, Saga 및 Operator 소유자 | 정확한 소스 개정에 연결된 인증 Checks API 또는 Console 변환 결과 증적 |
| ARB 결정 근거 인가 연결 | 보안 및 근거 소유자 | 관리되는 근거 저장소, 신뢰 루트, 목적, 범위, 개정 인가 |
| 실제 ARB 소유자, 근거, 승인 경로 구성 | 아키텍처, 보안, 개인정보, 데이터, 운영, 신뢰성, release, 비용, 성능 소유자 | 지정된 소유자, 에스컬레이션 경로, 근거 다이제스트와 귀속된 승인 |
| 관리되는 ORR shadow 증적 하나 보존 | Forseti, Saga 및 운영 소유자 | 소유권 인수인계 이벤트, 독립 묶음, 영구 보고서와 실행 효과 없음 |
| ORR 하나를 안전성 검토와 사람 승인까지 전달 | Forseti, Var 및 Saga | 브로커 증적, 정확한 위험 결정과 별도 귀속 승인자 |
| 동결 오탐 shadow cohort 측정 | Forseti, Muninn 및 보증 소유자 | 대표 시나리오 매니페스트, 결정, 결과, 분모, 불확실성 |
| 권위 있는 승격 결정 기록 | Mimir, Var 및 승격 소유자 | 검토된 cohort, 정확한 승격 대상, 승인, 현재 레지스트리 재확인 |
| 준비 환경 ARB Process를 서명된 종료까지 실행 | Forseti, Var, Saga 및 ARB 소유자 | 소유자 승인, Process 이력과 독립 검증한 서명 종료 증적 |
| Workflow 적용의 로컬/배포 일치 검증 | Var, Thor, Saga 및 배포 소유자 | 같은 허용 Workflow, 승격된 ActionType과 독립 효과 |
| 소유 토픽 전체 ARB 추적 보존 | Pantheon 토픽 소유자 | 선언된 각 소유 토픽의 스키마 검증 단계 기록과 인과 상관관계 |
| ARB-4 효과 및 ARB-5 승격 cohort 종결 | Heimdall, Vidar, Muninn, Norns 및 Mimir | ActionRun, 독립 결과, 복구, 장기 cohort 증적 |

### F07 설치 활성화 및 측정

| 남은 작업 | 최종 소유자 | 완료 근거 |
|-----------|-------------|-----------|
| 실제 청구, Budget, Advisor, 사용률 원본 연결 | 설치 및 Cost Analytics 공급자 소유자 | 현재 인증 원본 매니페스트와 완전/부분/사용 불가 재확인 |
| 서비스, workload, 관계 범위 검증 | 설치 온톨로지 및 인벤토리 소유자 | 정확한 비용 배부 범위의 관찰 범위 증적 |
| 실제값이 0이 아닌 예측 보정 cohort 축적 | Njord 및 분석 근거 소유자 | 권위 있는 실제값, 표본 수, MAPE, 부호가 있는 편향과 원본 계보 |
| 고정된 실제 DecisionCase와 승인 보존 | Forseti, Var 및 설치 운영자 | 정확한 사례/작업 개정, 대상, 현재 정책과 귀속된 승인 |
| 실행 및 롤백 증적 보존 | Thor, Vidar 및 실행기 배포 소유자 | 멱등 실행, 사후 조건, 롤백 여부와 효과 상관관계 |
| 독립 비용, 용량, 서비스, 복구 효과 생성 | Heimdall, Saga 및 정산 생성자 | 같은 작업과 구간에 연결된 독립 원본 상태 4개 |
| 비교 가능한 수요의 실행 요율 절감 검증 | Cost Governance 측정 소유자 | 기준/처리 수요 정규화와 검증된 실행 요율 증적 |
| 청구서 배부 절감 검증 | 청구 및 배부 소유자 | 확정 청구서와 정확한 배부 규칙 증적 |
| W7 운영 cohort 축적 | 설치 소유자 및 보호된 캠페인 | 서로 다른 30일, 적격 표본 100개 이상, 선언된 재발 구간 |
| 독립 대상 검토 완료 | 독립적인 사람 검토자 6명 | 정확한 대상 패키지와 전체 근거에 대한 귀속 검토 6개 |
| 프로덕션 패키지 전환 | release 및 배포 소유자 | 활성 패키지 개정, 비활성 Core facade 제거, 롤백 및 재확인 증적 |
| 후속 W7 cohort와 독립 대상 검토 완료 | FDAI 유지관리자, 설치 소유자 및 독립 검토자 6명 | [W7 cohort #2207](https://github.com/dotnetpower/fdai/issues/2207)과 [대상 검토 #2208](https://github.com/dotnetpower/fdai/issues/2208)을 정확한 개정의 캠페인 근거 및 서로 분리되어 귀속된 결정 6건으로 종결 |
| 선택형 campaign-export PostgreSQL 검사 실행 | 로컬 검증 소유자 | 전용 검증 DSN과 내보내기 영속성 검사 통과. 실제 운영 근거를 대체하지 않음 |

## F08. 작업 및 워크플로

| 기능 | 상태 | 근거, 지원 범위 및 남은 조건 |
|------|------|-----------------------------|
| <span id="f08-1">F08.1</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 매개변수, 참조, 위험 및 복구 선언, 관찰 모드 기본값을 포함한 배포된 등록 ActionType 및 Workflow 카탈로그입니다. [ActionType](../../../services/core-control-plane/src/fdai/rule_catalog/schema/action_type.py) 및 [Workflow](../../../services/core-control-plane/src/fdai/rule_catalog/schema/workflow.py) 로더를 검토하고 검사 A에서 [작업 카탈로그](../../../services/core-control-plane/tests/rule_catalog/test_action_type_catalog.py) 및 [워크플로 카탈로그](../../../services/core-control-plane/tests/rule_catalog/test_workflow_catalog.py) 테스트를 재실행했습니다. 카탈로그 유효성은 모든 설계 목록의 워크플로 구현이나 승격을 입증하지 않습니다. |
| <span id="f08-2">F08.2</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 여러 단계의 계획 구성, 강제 제약 필터링, 전문가 의견 중재, 정확한 대상 및 효과 검증, 복구 계약, 봉인된 계획 다이제스트, 전달 준비 검사입니다. [계획 원장](../../roadmap-implementation/decisioning/operational-planning.md)과 집중 계획 및 전문가 검사가 이 범위를 뒷받침합니다. 계획을 실행할 때는 사람 승인과 효과 검증이 계속 필요합니다. |
| <span id="f08-3">F08.3</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 기본 예약 및 수동 전달, 지원 일정 종류, 범위가 제한된 격리, 이력, 결과 연결 처리 구조입니다. [스케줄러](../../../services/core-control-plane/src/fdai/core/scheduler/service.py)를 검토했고 검사 B에서 중복 방지, 이력, 격리, 결과 연결의 보존 및 전달을 포함한 [스케줄러 테스트 파일](../../../services/core-control-plane/tests/core/scheduler/) 7개를 재실행했습니다. 전달 수락은 작업 성공이나 실제 채널 검증을 뜻하지 않습니다. |
| <span id="f08-4">F08.4</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | 범위는 정확한 개정 버전 전달, 중복 방지, 대상별 잠금, 진행 및 중단 검사, 승인된 롤백 또는 범위가 제한된 복구, 최종 감사, 지원되는 워크플로 및 공급자 계약의 독립 효과 종결입니다. [워크플로 원장](../../roadmap-implementation/decisioning/process-automation.md), [복구 원장](../../roadmap-implementation/decisioning/recovery-and-chaos-enforcement.md), 집중 테스트 360개가 이 범위를 뒷받침합니다. 공급자 동시 실행 차단, 승격, 실제 복구 종결은 별도 배포 검증입니다. |

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
| <span id="f10-1">F10.1</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | 로컬 구현은 인증된 수집, 불변 버전, 제한된 추출 및 OCR, 색인, 보존 및 삭제, 재시작에 안전한 인계와 K02의 목적별 보호 원본 다운로드입니다. 반출에는 정규화된 감사 증적, 제한된 유효 기간, 현재 접근 및 개정 확인, 스트림 재검사가 적용됩니다. [문서 원장](../../roadmap-implementation/interfaces/document-ingestion.md)은 #2214의 동작 검사 132개와 소유권 검사 29개를 과거 검사 929개와 분리해 기록합니다. 서비스 5개의 정확한 수명 주기 및 실패 증적과 승인된 SharePoint 및 보호, 철회, 삭제, 커서, 역압력 결과 조회는 남습니다. [K01-K02](functional-readiness-backlog-ko.md#f10-지식-및-규칙-작업)는 필수 운영 기준이며 로컬 반출 구현만으로 완료되지 않습니다. |
| <span id="f10-2">F10.2</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | 로컬 구현은 개정에 안전한 수집 및 예약, 수동 v2/v3 수락, 날짜 기반 조회 및 격리, #2217의 명시적 기존 정책 적용 API입니다. Var 및 Saga의 독립 검증과 트랜잭션으로 보호한 저장 결과 재조회를 유지합니다. [클라우드 지식 원장](../../roadmap-implementation/interfaces/cloud-resource-knowledge-lifecycle.md)과 [구조화 조회 원장](../../roadmap-implementation/interfaces/cloud-resource-knowledge-structured-rag.md)은 집중 검사 670개와 실제 PostgreSQL 검사 24개를 운영 근거와 분리해 기록합니다. 실제 독립 승인 정책 및 읽기 권한과 승격, 원문 및 답변 품질, 신뢰 및 등록, 연결 및 외부 통신 차단 증적은 남습니다. [K03-K05](functional-readiness-backlog-ko.md#f10-지식-및-규칙-작업)를 참조하세요. 소스 구현을 운영 검증으로 취급하지 않고 Partial로 유지합니다. |
| <span id="f10-3">F10.3</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | 범위는 현재 스키마의 규칙 작성, 출처 및 품질 검증, 변경 불가능한 버전, 범위 지정 활성화, 개정 버전별 예외, 폐기 제안, 충돌 해결, 롤백에 안전한 카탈로그 상태입니다. [규칙 원장](../../roadmap-implementation/rules-and-detection/rule-governance.md)과 집중 테스트 72개가 이 범위를 뒷받침합니다. 기존 개정 버전 이중 읽기 이행과 배포 환경의 단계별 적용은 별도 설치 및 업그레이드 검증입니다. |
| <span id="f10-4">F10.4</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | 로컬 구현은 내용보다 먼저 확인하는 출처 이력, 민감도 및 최신성과 온톨로지 검사, 독립적인 결정론 검증, 비활성 제안, 비공개 패키지 폐기입니다. [변환 원장](../../roadmap-implementation/rules-and-detection/manual-distillation.md)에는 배포된 ACL 및 목적, 철회, 법적 보존 보류 및 삭제, 공급자 및 표본, 실제 EN/KO 보조 기술 출력의 필수 근거가 남습니다. [K06-K07](functional-readiness-backlog-ko.md#f10-지식-및-규칙-작업)을 참조하세요. 변환은 활성화 권한을 부여하지 않으며 로컬 테스트는 운영 적합성 기준을 충족하지 않습니다. |

## F11. 평가 및 학습과 승격

| 기능 | 상태 | 근거, 지원 범위 및 남은 조건 |
|------|------|-----------------------------|
| <span id="f11-1">F11.1</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | 출처가 명시된 피드백, 불변 인시던트 및 작업 사례, 예측 종결, 비활성 후보, 로컬 보존 통제가 구현되어 있습니다. [학습 원장](../../roadmap-implementation/rules-and-detection/operational-learning-ontology.md)과 [예측 원장](../../roadmap-implementation/rules-and-detection/prediction-learning-and-case-history.md)에는 운영 기준 외에도 수집원 이력, Settings 및 수집기, 맥락 수명 주기, 보존 Pattern 통합 작업이 남습니다. [L01-L03](functional-readiness-backlog-ko.md#f11-f13-학습-권한-자체-상태-성과)을 참조하세요. 격리 LOCAL 임대 구현은 외부 수집원을 검증하지 않습니다. |
| <span id="f11-2">F11.2</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | 실행하지 않는 재현, 시나리오 및 보증 트윈 평가, 기준선 비교, 평가 제외 결과, 정확한 임계값 정책에 연결된 O7 근거가 구현되어 있습니다. [학습 원장](../../roadmap-implementation/rules-and-detection/operational-learning-ontology.md)과 [작업 흐름 상태](../../roadmap/agents/agent-workflows-ko.md#구현-상태)가 로컬 검사를 뒷받침합니다. 일관된 외부 발급자, 사전 등록한 SLO 및 안전 예산 비교, 완전한 재발 구간, 작업별 운영 일수 및 표본 수, 신뢰도 및 정책 위반 누락 없음 근거가 남습니다. [L03-L04](functional-readiness-backlog-ko.md#f11-f13-학습-권한-자체-상태-성과)를 참조하세요. |
| <span id="f11-3">F11.3</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | 승격 및 재정의 주체 추적, 자동 하향 조정, 영속 회수 및 해제, 회수 우선순위, `shadow` 강제, Operator 및 Console 회수 표시가 구현되어 있습니다. [거버넌스 원장](../../roadmap-implementation/decisioning/operator-governance-profiles.md)과 기록된 집중 검사가 이 부분을 뒷받침합니다. 운영 Release 상한 통합과 관리 절차에 따른 활성화 및 회수 증적은 [A01-A02](functional-readiness-backlog-ko.md#f11-f13-학습-권한-자체-상태-성과)로 남습니다. 현재 안전하게 제한하는 shadow 전용 상한은 구현 경계이며 운영 연결이 아닙니다. |

## F12. 권한 및 근거와 자체 운영

| 기능 | 상태 | 근거, 지원 범위 및 남은 조건 |
|------|------|-----------------------------|
| <span id="f12-1">F12.1</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | 범위는 역할 분리, 정확한 작업 승인, 만료 및 철회, 조건부 사전 권한, 현재 임대 및 동시 실행 차단 계약, 승인 정족수 프로필, 권한 또는 공급자 강제를 사용할 수 없을 때의 안전한 전달 차단입니다. [권한 원장](../../roadmap-implementation/decisioning/escalation-and-standing-authority.md)과 집중 테스트 702개가 이 범위를 뒷받침합니다. 효과 반영 시점에 동시 실행 차단을 강제하는 공급자 연결과 상시 권한 훈련은 별도 배포 검증입니다. |
| <span id="f12-2">F12.2</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | 범위는 버전이 지정된 정책 및 위험 판정, 비상 중지 및 회수 우선순위, 7가지 실행 안전 조건, 차단 및 작업 없음의 최종 감사, 안전한 쪽으로 닫히는 실행 방지, 인증된 운영 상태 읽기 화면입니다. 서명된 Operator-Var 비상 정지 경로, [보안 원장](../../roadmap-implementation/architecture/security-and-identity.md), [정본 상태 정보](../../roadmap/operations/operating-and-verification-ko.md#구현-상태), 집중 안전 검사가 로컬 구현을 뒷받침합니다. Release 최대값 연결과 배포 환경에서 측정한 활성화-실행 차단-비활성화 훈련은 별도 설치 검증으로 남아 있습니다. |
| <span id="f12-3">F12.3</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | 범위는 책임을 추적할 수 있는 해시 체인 감사, 결정론적 재현, 목적 및 범위 접근 검사, 모델 입력 전 최소화, 비식별화된 내보내기, 범위가 제한된 보존 및 삭제, 법적 보존, 삭제 표시, 재시도에 안전한 감사 증적입니다. [개인정보 원장](../../roadmap-implementation/architecture/data-governance.md)과 집중 감사·보존·개인정보 검사가 이 범위를 뒷받침합니다. 개인정보 승인, 외부 감사 고정 또는 WORM 저장소, 실제 접근 검토 및 사고 증적은 별도 배포 검증입니다. |
| <span id="f12-4">F12.4</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | 신호 15개의 정책 및 내보내기 레지스트리, 운영 상태 필드 8개의 계약, 서비스 및 모델과 근거 상태 조회, 소비된 정확한 카나리의 30초 검사가 구현되어 있습니다. #2218 / PR #2220에서 실제 수신 서버, 보호된 준비 상태, 저장된 비상 중지 신호와 설치 버전, 소비한 정책 다이제스트, 비상 중지 필드를 연결하고 집중 검사 92개를 통과했습니다. [정본 상태 정보](../../roadmap/operations/operating-and-verification-ko.md#구현-상태)는 나머지 신호 12개와 필드 5개를 명시적 사용 불가로 유지합니다. 실제 수집원, 측정된 기본 및 대체 전달, 실제 카나리, 안정화, 복구 훈련 근거는 필수로 남습니다. |

## F13. 근거 조회 및 보고서

| 기능 | 상태 | 근거, 지원 범위 및 남은 조건 |
|------|------|-----------------------------|
| <span id="f13-1">F13.1</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 리소스, 관계, 인시던트, 계획 및 Process, 승인, 감사 및 이력, 출처가 명시된 결과, 승격 및 회수 상태를 보여 주는 허용된 읽기 화면이며 사용 불가 및 부분 근거를 명시합니다. [리소스 원장](../../roadmap-implementation/architecture/continuous-operational-instance-graph.md), [보고서 원장](../../roadmap-implementation/interfaces/reporting-subsystem.md), 기존 화면 검사, 현재 회수 변환 결과 검사가 이 범위를 뒷받침합니다. 배포 수집원의 최신성과 인증된 공급자 범위는 별도 설치 검증입니다. |
| <span id="f13-2">F13.2</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | 선언형 카탈로그, 제한된 렌더링, 위젯 격리, 내보내기 및 PDF, 수집원 출처가 구현되어 있습니다. [보고서 원장](../../roadmap-implementation/interfaces/reporting-subsystem.md)에는 과거 인증된 기본 Incident RCA/PDF 근거가 있지만 더 넓은 수집원과 인증된 오류 및 격리 증적은 미완료입니다. 검증한 부분을 전체 보고서 기능으로 확대하기 전에 [V01](functional-readiness-backlog-ko.md#f11-f13-학습-권한-자체-상태-성과)을 완료합니다. |
| <span id="f13-3">F13.3</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | 범위는 신뢰성·복구·자동화·비용의 기준 및 조치 후 집단 측정, 출처 및 완전성 검사, 독립 정산, 검증 불가 결과, 활동 건수를 개선으로 간주하지 않는 판정입니다. [성과 가이드](../sre/measuring-sre-outcomes-ko.md), [FinOps 원장](../../roadmap-implementation/architecture/finops-autonomous-operations.md), 집중 측정 검사가 이 범위를 뒷받침합니다. 조건을 충족하는 실제 사례와 완전한 운영 구간은 별도 배포 검증입니다. |

## F14. 설치 및 설정과 확장

| 기능 | 상태 | 근거, 지원 범위 및 남은 조건 |
|------|------|-----------------------------|
| <span id="f14-1">F14.1</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | 소스 배포, 사전 조건, 대상 검증, 이미지 및 Terraform 조정, Trial, 상태, 업데이트 및 롤백, 제거가 구현되어 있습니다. [소스 원장](../../roadmap-implementation/deployment/source-deployment.md)과 과거 테스트 207개가 이 부분을 뒷받침합니다. WP6에는 신규 Trial 증적 1건이 있으나 변경 없는 Trial 재실행, 정식 사용 권한 신규 설치, Trial 전환 재실행 및 워터마크 제거가 남습니다. [I01](functional-readiness-backlog-ko.md#f14-f15-배포-방식-확장-코드-검사)을 참조하세요. |
| <span id="f14-2">F14.2</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | 소스 및 서명 검증 오프라인 배포, 변조 및 기한과 취소 방지, 격리된 휠 설치가 구현되어 있습니다. [소스 원장](../../roadmap-implementation/deployment/source-deployment.md)의 WP6 이후 WP8 경로 정리가 남고 현행 도움말 및 파서는 `--online`을 표시합니다. [I02-I03](functional-readiness-backlog-ko.md#f14-f15-배포-방식-확장-코드-검사)에서 배포 복구 및 수용 기준을 대조합니다. [Hub 원장](../../roadmap-implementation/deployment/hub-managed-lifecycle.md)에는 일부 코드만 있으며 사용 가능한 전체 수명 주기는 없습니다. Hub 및 공개 게시는 소스와 오프라인 경로의 선행 조건이 아닙니다. |
| <span id="f14-3">F14.3</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | 사용 가능 여부, 활성화, 유효 모드, 프로필 및 추가 기능, Trial 워터마크, 모델 상태, 재정의 및 회수 표시가 구현되어 있으며 작업 권한을 부여하지 않습니다. [거버넌스 원장](../../roadmap-implementation/decisioning/operator-governance-profiles.md), [소스 원장](../../roadmap-implementation/deployment/source-deployment.md), 기록된 회수 검사가 로컬 동작을 뒷받침합니다. 운영 Release 상한 입력과 실제 사용 권한 전환 조회인 [A01 및 I01](functional-readiness-backlog-ko.md)이 남습니다. 선택적 작성 UI 및 물리 정책 테이블 이행은 별도의 조건부 범위입니다. |
| <span id="f14-4">F14.4</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | 게시자 신뢰, 호환성, 불변 비활성 우선 기능 묶음, 활성화 및 비활성화와 철회, 형식이 지정된 등록이 구현되어 있습니다. [기능 묶음 원장](../../roadmap-implementation/architecture/capability-bundle-lifecycle.md)에는 수명 주기, 재시작 및 공개 정보, 형식이 지정된 경로, 감사에 대한 필수 동일 산출물 연결 증적이 남습니다. [X01](functional-readiness-backlog-ko.md#f14-f15-배포-방식-확장-코드-검사)을 완료합니다. #355를 계획하지 않음으로 닫은 것은 그 기준의 검증이 아닙니다. |

## F15. 코드 보안

| 기능 | 상태 | 근거, 지원 범위 및 남은 조건 |
|------|------|-----------------------------|
| <span id="f15-1">F15.1</span> | <span class="fdai-readiness-badge" data-readiness="partial">Partial</span> | 정확한 개정 확보, 격리 경로, SARIF 수집, Console 및 예약 워커, 독립적 로컬 결과 수락, 지원 범위 및 종료 표시가 구현되어 있습니다. [검사 원장](../../roadmap-implementation/operations/code-security-scanning.md)에 과거 설치 환경 격리 및 준비 근거는 있지만 #2128은 중지된 상태이며 설치 환경 검사 종료나 같은 상관관계의 업무 연결 완료는 없습니다. [S01-S02](functional-readiness-backlog-ko.md#f14-f15-배포-방식-확장-코드-검사)를 완료합니다. 워커 준비, 공급자 수락, 로컬 검사 증적은 누락된 배포 종료 증적이 아닙니다. |
| <span id="f15-2">F15.2</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 결정론적 통합 이슈, 심각도·신뢰도·우선순위 구분, 범위가 제한된 요약, 검증 및 판정입니다. [통합 처리](../../../services/core-control-plane/src/fdai/core/security/code_findings/canonical.py)와 [검증](../../../services/core-control-plane/src/fdai/core/security/code_findings/verification.py)을 검토하고 검사 A에서 통합, 심각도, 이슈 요약, 검증 테스트를 재실행했습니다. 탐지기의 재현율, 임의의 취약점, 실제 스캐너 정확도를 보증하지 않습니다. |
| <span id="f15-3">F15.3</span> | <span class="fdai-readiness-badge" data-readiness="ready">Ready</span> | 범위는 서명되고 범위가 제한된 개발자 수정 자료 묶음, 보조 도구의 안전 검사, 결과 주장, 동등한 검사 범위에 따른 재검증입니다. [자료 묶음 런타임](../../../services/core-control-plane/src/fdai/core/security/code_findings/pack_runtime.py)과 [검증](../../../services/core-control-plane/src/fdai/core/security/code_findings/verification.py)을 검토했습니다. 검사 A에는 [실제 임시 Git 보조 도구 세션](../../../services/core-control-plane/tests/core/security/code_findings/test_pack_helper_session.py), 서명, 내보내기, 안전 검사, 재검사 테스트가 포함됩니다. FDAI가 고객 저장소를 편집하거나 반환된 주장을 검증된 수정으로 취급하지 않습니다. |

## 과거 집중 검증

다음 결과는 이전 구현 작업의 근거입니다. 이번 문서 점검에서는 명시된 범위로 재사용하며
다시 실행하지 않았습니다. [F10-F15 계획](functional-readiness-backlog-ko.md)은 소스 작업과
미충족 필수 운영 검증을 구분하며 과거 테스트 수를 새로운 검증 증적으로 취급하지 않습니다.

| 검사 | 정확한 로컬 선택 범위 | 결과 |
|------|----------------------|------|
| **A** | Incident `test_incident_lifecycle.py`, `test_incident_workflow.py`, `test_storm.py`; rule catalog `test_action_type_catalog.py`, `test_workflow_catalog.py`; 코드 보안 점검 결과 `test_canonical.py`, `test_severity.py`, `test_issue_summary.py`, `test_pack.py`, `test_pack_helper_session.py`, `test_diff_guard.py`, `test_signing.py`, `test_result_import.py`, `test_export_gate.py`, `test_verification.py`. | **286개 통과**, 건너뜀 없음, 파일 15개입니다. |
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
| **L** | 버전이 지정된 단일 리소스 최적화 플래너, 근거 경계, 안전 검사, 권한 없는 후보 계약입니다. | **15개 통과**, 건너뜀 없음이며 Ruff와 strict mypy도 통과했습니다. |
| **M** | 운영 기준, 규칙 및 구성 불일치 거버넌스, ARB 근거, 준비 상태, 규칙 수명 주기입니다. | **389개 통과**, 건너뜀 없음입니다. |
| **N** | 재해 복구 및 카오스 훈련, 워크플로 실행 및 복구, 정확한 승인 및 조건부 사전 권한 계약입니다. | **1,114개 통과**, 건너뜀 없음이며 미지원 공급자 검증 61개가 안전한 차단을 확인했습니다. |
| **O** | 비용 예산, 예측, 최적화, 정산, 기준선 기반 성과 측정입니다. | **652개 통과**, 선택형 데이터베이스를 사용할 수 없어 1개를 건너뛰었습니다. |
| **P** | 운영 피드백, 재현 및 보증 트윈, 감사, 개인정보, 보존, 법적 보존, 상태, 준비 및 복구 신호입니다. | **810개 통과**, 선택형 데이터베이스를 사용할 수 없어 1개를 건너뛰었습니다. |

첫 번째 구현 작업을 마친 뒤 권한 경계, 불확실할 때 실행을 차단하는 동작, 멱등성, 비동기 정리, API 변경,
메트릭 의미, Kafka 연결, Terraform 최소 권한, Live 및 Sample 상태의 정직한 표현,
접근성, 테스트 신뢰도, 문서의 정확성이라는 12가지 관점에서 두 차례 검토했습니다. 첫 번째
검토에서 동시 취소 제어 공백과 모호한 Terraform 사전 조건 메시지를 찾았습니다. 두 항목을
보강하고 다시 검토한 결과 Medium 이상 코드 지적은 남지 않았습니다. 이어진 격리된 시각
검사에서 모바일 입력 크기가 작은 문제를 찾았습니다. 이를 보강한 뒤 테스트 전용 Console
경로를 1440x900과 390x844에서 측정한 결과, 문서 및 main 영역 넘침은 0이었고 모든 모바일 양식의 조작 대상은 44px 이상이었으며,
Sample 모드의 생성 및 취소 제어는 0개였습니다. 브라우저 Entra 인증 또는 전체 스택을 검증한 근거는
아닙니다. 배포 환경별 근거 공백은 코드 결함이나 Ready 근거로 바꾸지 않고 Partial 상태로
유지합니다.

검사는 체크아웃의 로컬 Python 및 JavaScript 도구, 테스트 대역, 임시 파일, 로컬 계약 검사를
사용했습니다. 운영 설치 환경을 선택하거나 검증하지 않았습니다.

## 관련 문서

| 알아볼 내용 | 문서 |
|-------------|------|
| 전체 기능 설명과 상태 정의 | [기능정의서](functional-specification-ko.md) |
| F10-F15 잔여 작업 전체, 담당자, 의존성, 완료 조건 | [준비 상태 점검 및 완료 계획](functional-readiness-backlog-ko.md) |
| 세부 소스 담당 영역과 구현 상태 | [로드맵 목차](../../roadmap/README-ko.md) |
