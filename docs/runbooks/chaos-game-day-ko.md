---
title: Chaos Game Day Runbook
description: 범위가 제한된 chaos experiment를 계획, 승인, 실행, 복구하는 템플릿입니다.
translation_of: chaos-game-day.md
translation_source_sha: 524a3237130a5075baf472f394e8ab3f8f905d6d
translation_revised: 2026-08-11
---

# Chaos Game Day 런북

범위가 제한된 chaos 실험을 계획, 승인, 실행하고 복구할 때 이 런북을 사용합니다.
Game 일은 promoted 시나리오, 동결된 대상 집합, 지속적인 탐색, 검증된 롤백 경로를
사용해 하나의 복원력 가설을 검증합니다.

> 환경별 fault 주입은 다운스트림 포크에서만 실행하세요. 이 업스트림 절차는 실제 운영 대상
> 또는 프로바이더 명령이 아니라 안전성 및 근거 계약을 정의합니다.

## 이 런북을 사용하는 경우

시나리오가 스키마, 정책, 회귀, shadow 검토를 이미 통과했고 팀이 live-like
환경에서 통제된 근거를 확보해야 할 때 game 일을 사용합니다. 설명되지 않은
활성 인시던트를 진단하기 위해 game 일을 사용하지 않습니다.

일반적인 목표는 다음과 같습니다.

- **장애 조치 검증**: 의존성 또는 복제본이 목표 안에 takeover할 수 있음을 입증합니다.
- **Detection 검증**: 예상 발견된 문제, 인시던트, 알림이 나타남을 입증합니다.
- **Rollback 검증**: Injected fault를 제거하고 steady 상태를 복원할 수 있음을 입증합니다.
- **Human 응답 검증**: Owner가 근거를 받고 예상 인계를 따름을 입증합니다.

## 역할과 필수 입력

| 역할 또는 입력 | 책임 |
|----------------|------|
| Exercise 소유자 | 가설, 예약, coordination, 최종 기록을 책임집니다. |
| Approver | 범위, risk, stop 조건, 롤백을 독립적으로 검토합니다. |
| Operator | Authorized 프로바이더를 통해 approved 시나리오를 시작하고 중지합니다. |
| Observer | 탐색을 관찰하고 즉시 중지를 요청할 수 있습니다. |
| 시나리오 | Versioned fault, 대상 선택자, 소요 시간, 영향 범위 한도입니다. |
| Steady 상태 | 실험 중 유지돼야 하는 측정 가능한 상태입니다. |
| Rollback | Fault를 제거하고 이전 상태를 복원하는 검증된 액션입니다. |

Operator와 승인자는 구분하는 것이 좋습니다. 선언된 조건이 발생하거나 관찰된 상태가
불명확해지면 모든 participant가 중지를 요청할 수 있습니다.

## 사전 검사

Exercise 구간이 열리기 전에 preflight를 완료합니다.

1. 시나리오 버전과 shadow 근거를 확인합니다.
2. 하나의 반증 가능한 가설과 예상 탐색 movement를 작성합니다.
3. 정확한 대상 집합을 동결하고 protected 의존성이 제외됐는지 확인합니다.
4. 기준선 탐색 값을 기록하고 텔레메트리 최신성을 확인합니다.
5. Stop 조건, 최대 소요 시간, 동시성, affected 범위를 검증합니다.
6. Rollback 경로를 테스트하거나 동일 시나리오 버전의 최근 근거를 첨부합니다.
7. Operator 신원, 필수 잠금, 감사 쓰기 담당, 알림 경로를 확인합니다.
8. Exercise 구간을 알리고 stop 권한이 있는 사람을 식별합니다.

Preflight 항목을 사용할 수 없으면 no-op 결과를 기록하고 일정을 다시 잡습니다.

## 실행 절차

1. **Exercise를 엽니다.** 시나리오, 대상 집합, participant, 승인, 기준선 샘플,
	planned end 시간을 기록합니다.
2. **Safeguard를 획득합니다.** 필요한 리소스 잠금을 획득하고 conflicting 변경 또는
	활성 인시던트가 대상과 겹치지 않는지 확인합니다.
3. **시나리오를 시작합니다.** Approved 프로바이더를 통해서만 inject하고 프로바이더 연산
	참조와 시작 시간을 기록합니다.
4. **계속 관찰합니다.** 실험 동안 steady-state, detection, 의존성, 범위 탐색을
	평가합니다. 누락된 또는 stale 샘플은 healthy 값이 아니라 실패입니다.
5. **보류 또는 stop합니다.** 모든 가드 조건이 유효한 동안에만 계속합니다.
	Authorized 관찰기는 누구나 stop 가지를 시작할 수 있습니다.
6. **Fault를 제거합니다.** 소요 시간 한도, 가설 관찰 또는 stop 조건 발생 시
	선언된 롤백을 실행합니다.
7. **복구를 검증합니다.** 대상 집합이 steady 상태로 돌아오고 injected 리소스,
	잠금, temporary 권한이 남지 않았는지 확인합니다.
8. **Exercise를 종료합니다.** 가설 결과, unexpected 영향, 복구 시간,
	후속 조치 소유자를 기록합니다.

## 중지 조건

다음 조건이 발생하면 주입을 즉시 중지합니다.

- **범위 expansion**: 동결된 집합 외부의 대상이 영향을 받습니다.
- **Protected 영향**: Protected 의존성 또는 control-plane 컴포넌트가 저하됩니다.
- **Stale 관측**: 필수 탐색, 인벤토리 스냅샷 또는 감사 쓰기 담당을 사용할 수 없습니다.
- **안전성 한도**: 소요 시간, 동시성, 오류 비율, 지연 시간 또는 affected-resource 상한에 도달합니다.
- **Conflicting 연산**: 동일 대상에서 인시던트 응답 또는 배포가 시작됩니다.
- **Rollback uncertainty**: Rollback 경로를 사용할 수 없거나 precondition이 변경됩니다.

중지는 유효한 실험 결과입니다. 활성 실행 안에서 소요 시간 또는 대상 집합을
확장하지 않습니다.

## 복구와 에스컬레이션

문서화된 순서로 롤백을 실행하고 모든 필수 steady-state 조건이 설정된 복구
구간 동안 통과할 때까지 sampling을 계속합니다. 복구가 완료되지 않으면 [인시던트
분류](incident-triage-ko.md)로 전환하고 실험 상관관계 ID를 보존하며 exercise를
인시던트 출처로 취급합니다.

첫 주입을 보상하려고 두 번째 주입을 시작하지 않습니다. 복구 액션은 자체
approved 경로를 따라야 하며 별도의 감사 기록을 남겨야 합니다.

## 근거와 감사

다음 근거를 기록합니다.

- **계획**: 시나리오 및 카탈로그 버전, 가설, 대상 해시, exercise 구간입니다.
- **권한**: Owner, 승인자, 운영자, 관찰기, 승인 참조입니다.
- **기준선**: Pre-exercise 탐색 값과 텔레메트리 시각입니다.
- **실행**: 잠금 참조, 프로바이더 연산, 주입 및 stop 시간, stop 사유입니다.
- **관측**: Steady-state, detection, 의존성, 범위 샘플입니다.
- **복구**: Rollback 참조, 복구 샘플, 복구 시간, 잔여 영향입니다.
- **결과**: Supported, disproved 또는 inconclusive 가설과 owned 후속 조치입니다.

## 완료 기준

Rollback이 완료되고 steady 상태가 검증되며 temporary 접근이 제거되고 잠금이 해제되며
모든 후속 조치에 소유자와 근거 대상이 지정된 뒤에만 game 일을 종료합니다. 새로
발견한 detection 또는 응답 공백은 [사후 분석 작업 흐름](postmortem-workflow-ko.md)를
통해 제출합니다.

## 관련 런북

| 다음 작업 | 문서 |
|-----------|------|
| 예상하지 못한 서비스 영향 분류 | [인시던트 분류](incident-triage-ko.md) |
| 통제된 복구 액션 적용 | [인시던트 완화와 롤백](incident-mitigation-and-rollback-ko.md) |
| Exercise 발견된 문제를 소유자가 있는 개선으로 전환 | [사후 분석 작업 흐름](postmortem-workflow-ko.md) |
