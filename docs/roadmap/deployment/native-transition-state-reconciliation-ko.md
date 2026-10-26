---
title: 네이티브 전환 상태 조정
translation_of: native-transition-state-reconciliation.md
translation_source_sha: 1b75152a0b247b917de9b28f6582c65e147948c5
translation_revised: 2026-10-27
---
# 네이티브 전환 상태 조정

이 설계는 Agent 상태가 밀리초 타임스탬프를 사용하고 Hub 완료 기록은 같은 시각을 더 높은
정밀도로 보존한 이전 네이티브 전환을 제한적으로 복구하는 방법을 정의합니다. 일반 상태 복구나
증적 다시 쓰기를 허용하지 않습니다.

## 이 문서에서 다루는 내용

Hub 완료 타임스탬프가 권위 있는 값입니다. 불변 전환 증적은 바꾸지 않으며, Agent의 영구 현재
상태만 전체 정밀도의 정규 타임스탬프와 다이제스트로 이동할 수 있습니다.

## 승인과 검증

인증된 운영자는 조정 승인 경로에
`fdai.lifecycle-native-transition-state-reconciliation-request.v1`을 제출합니다. Hub는 설치
행 잠금 안에서 원래 완료 감사와 증적, 설치, 이전·신규 Entity 및 범위 다이제스트, 네이티브
승인, 권위 있는 UID 다이제스트, Agent 신원, 현재 상태, 열린 Plan 부재를 검증합니다.

로컬 상태와 Hub 상태는 `observed_at`을 제외한 모든 정규 필드가 같아야 합니다. 양의 정밀도
차이는 1밀리초 이하여야 합니다. 다른 차이, 변경된 증적, 동시 상태, 다른 재시도, 누락된 감사
기록은 승인을 차단합니다.

## Agent 조정

Hub는 정확한 원본과 권위 있는 대체 상태에 서명합니다. Agent는 상태 잠금 안에서 서명, 불변
증적, 범위, UID 재고, 현재 상태, 보고하지 않은 Plan이나 활성 저널 부재를 검증합니다. 원래
바이트를 불변 롤백 기록에 보존하고 현재 상태만 원자적으로 교체합니다.

Agent는 `Agent.Access` 워크로드 신원으로 서명된 대체 상태를 제출합니다. Hub는 신원 또는 상태
변경을 차단하고 정규 상태와 해시 체인 감사를 추가하며 커밋된 상태를 재조회 결과로 반환합니다.
제출이 실패하면 원래 바이트를 복원합니다. 정확한 재시도는 커밋된 Hub 증적을 재사용합니다.

## 관련 문서

| 학습 대상 | 문서 |
|-----------|------|
| Hub 관리형 수명 주기 | [Hub 관리형 수명 주기](hub-managed-lifecycle-ko.md) |
| 운영자 절차 | [Hub 배포 인수인계](../../runbooks/hub-lifecycle-deployment-handoff-ko.md) |
