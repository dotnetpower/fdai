---
title: Data Governance와 Privacy Evidence
translation_of: data-governance.md
translation_source_sha: afd75170776f53994c8987699c427128d03489f5
translation_revised: 2026-08-11
---
# 데이터 거버넌스와 Privacy 근거

이 문서는 FDAI의 데이터 분류, minimization, 수명 주기, residency, privacy 근거
계약을 정의합니다. 재사용 가능한 컨트롤 모델을 제공하며 각 배포는 customer
데이터를 업스트림에 커밋하지 않고 승인 값과 근거를 기록합니다.

> **범위:** 이 문서는 certification 또는 완료된 privacy 영향 평가가 아닙니다.
> 포크가 privacy 소유자, 데이터 소유자, 보존 값, model-provider 조건, 승인 평가를
> `config/architecture-review.yaml`에 연결할 때까지 운영 승인은 차단된입니다.

## 한눈에 보는 설계

FDAI는 가능한 경우 raw customer 페이로드 대신 식별자와 derived operational 사실을
저장합니다. 머신/감사 기록은 English를 유지하고 접근은 role-scoped이며 transit와
at-rest encryption이 필요합니다. 모델로 보내는 내용은 trust 경계를 벗어나기 전에
민감정보 제거합니다.

## 데이터 인벤토리

| 데이터 등급 | 예 | 기본 처리 | System of 기록 |
|------------|----|-----------|------------------|
| Event 메타데이터 | Event id, 리소스 타입, 상관관계 id, 정규화된 속성 | 최소화하고 유입에서 시크릿을 거부합니다. | Event 버스, 이후 감사/상태 저장소 |
| 도구와 인벤토리 출력 | Resource 그래프 사실, 정책 결과, deployment-plan 사실 | 결정과 근거에 필요한 필드만 유지합니다. | 상태 저장소 또는 수명이 짧은 버퍼 |
| 감사 기록 | 결정, 행위자 id, 계층, 룰 인용, 멱등성/롤백 참조 | 추가 전용, tamper-evident, legal-hold capable | 감사 원장 |
| 텔레메트리 | 로그, 메트릭, 추적, 상태/performance 측정 | 텔레메트리는 샘플/집계할 수 있지만 필수 감사 항목은 샘플하지 않습니다. | Log Analytics 또는 구성된 백엔드 |
| 임베딩과 pattern | 해결 인시던트와 승인 knowledge에서 파생한 vector | 모델과 출처를 versioning하고 시크릿/raw personal 데이터 임베딩을 피합니다. | PostgreSQL + pgvector |
| Operator 대화 | 질문, 검증된 도구 호출, 근거에 기반한 답변, 제안 참조 | 표현 텍스트와 머신 결정을 분리하고 승인 세션 보존을 적용합니다. | Operator-memory 저장소 |
| 거버넌스 산출물 | Rule, 배정, exemption, 재정의, ADR | 코드로 versioning하고 검토합니다. | Git |

## 분류와 접근

포크는 각 등급을 공개, 내부, confidential, restricted 같은 organization taxonomy에
대응합니다. 데이터 소유자, 허용 principal, 승인 지역, encryption 프로파일, 다운스트림
processor를 기록합니다. 분류가 없으면 가장 제한적인 구성된 등급으로 처리하고
모델 프로바이더 내보내기를 차단합니다.

접근은 다음 규칙을 따릅니다.

- **최소 권한:** Console은 변환 결과를 읽으며 실행기 신원을 보유하지 않습니다.
- **용도 한계:** 프로바이더는 선언된 연산에 필요한 필드만 받습니다.
- **시크릿 propagation 방지:** 시크릿은 이벤트, 로그, 감사, 프롬프트, 고정본, 근거 첨부에
  기록하지 않습니다.
- **행위자 traceability:** Human/워크로드 신원은 감사에서 고정된 객체 식별자를 사용합니다.
- **Break-glass 가시성:** Emergency 접근은 time-bounded, alerted, 검토된 상태입니다.

## 수명 주기와 보존

포크는 모든 데이터 등급에 다음 필드를 포함한 보존 예약을 유지합니다.

| 필드 | 요구 사항 |
|-------|-----------|
| 용도 | Operational, security, legal, training 또는 다른 승인 목적 |
| 활성 보존 | 기본 저장소에서 조회 가능한 기간 |
| 보관 보존 | 기간, 보관 계층, 복원 expectation |
| Legal 보류 | 권한, 보류 표시, release 프로세스, 변경할 수 없는 근거 |
| Deletion | 트리거, 메서드, 검증, 다운스트림 propagation |
| 백업 inheritance | 백업 만료를 기다리는지 승인 키 destruction을 사용하는지 |
| 검토 cadence | Owner와 다음 검토 date |

Azure day-zero 텔레메트리 기본값은 30일입니다. 감사, 대화, 임베딩, customer 기록
보존은 이 값을 자동 상속하지 않습니다. 포크에서 값을 승인하고 운영 근거
연결에 첨부해야 합니다.

## Privacy 평가

Privacy 영향 평가는 다음을 기록합니다.

1. 시스템에 들어올 수 있는 데이터 대상과 personal/customer-identifying 필드;
2. 용도, lawful basis, necessity, proportionality, minimization 컨트롤;
3. 이벤트, 상태, 텔레메트리, Git, ChatOps, model-provider 경계의 데이터 흐름;
4. 지역과 cross-border transfer 제약;
5. processor 조건, 보존, training-use restriction, 인시던트 알림 조건;
6. 적용 가능한 접근, correction, 내보내기, deletion, legal-hold 처리;
7. 잔여 privacy risk, 완화, 승인자, 검토 date.

선택한 model-provider 조건에 맞게 페이로드를 충분히 민감정보 제거할 수 없으면 FDAI는 사람 검토로
보내고 전송하지 않습니다.

## 모델과 임베딩 컨트롤

- 프로바이더, 발행기, 모델 계열/버전, 배포 지역, 보존 조건, submitted 데이터의
  프로바이더 training 비활성 여부를 기록합니다.
- 모델 또는 임베딩 호출 전에 시크릿/personal-data 민감정보 제거를 적용합니다.
- 프롬프트/도구 입력을 결정론적 판정과 감사 권한에서 분리합니다.
- 출처 출처 이력, 분류, 모델, deletion 계보와 함께 임베딩을 versioning합니다.
- 승인 출처가 삭제되고 legal 보류가 없으면 derived vector를 재생성하거나 삭제합니다.

## Compliance 근거

업스트림 카탈로그는 MCSB, CIS 또는 다른 standard 컨트롤을 인용할 수 있지만 certification을
증명하지는 않습니다. 배포 소유자는 컨트롤 id, 구현, automated/수동 근거,
소유자, frequency, exception, 잔여 risk가 포함된 crosswalk를 만듭니다. 지원하지 않는 또는
not-applicable 컨트롤은 명시적으로 남기며 조용히 누락하지 않습니다.

## 운영 게이트

운영 데이터/privacy 준비 상태에는 다음이 필요합니다.

- 승인된 데이터 인벤토리와 분류 대응;
- privacy/데이터 소유자 연결;
- 승인된 보존, legal-hold, deletion, 백업 행동;
- data-flow와 residency 검증;
- model-provider와 subprocessor 검토;
- 완료된 privacy 영향 평가;
- 선택한 customer 프로파일의 compliance crosswalk;
- 접근 검토, deletion, incident-response 테스트 근거.

이 산출물은 customer 기록이므로 포크 또는 통제된 근거 저장소에 둡니다. 업스트림
매니페스트에는 필수 근거 키와 범용 차단 요인 상태만 기록합니다.

## 다음 단계

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| ARB 결정과 근거 연결 | [아키텍처 검토 Board 패킷](architecture-review-board-ko.md) |
| Security와 threat 모델 | [Security and 신원](security-and-identity-ko.md) |
| Human 권한 확인 | [User RBAC and Entra 신원](../interfaces/user-rbac-and-identity-ko.md) |
| 감사와 텔레메트리 규모 | [Hyperscale Cell 아키텍처](hyperscale-cell-architecture-ko.md) |
