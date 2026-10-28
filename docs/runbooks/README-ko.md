---
title: SRE 런북
description: 인시던트 대응, 복구, 통제된 자동화를 위한 범용 운영 절차와 템플릿입니다.
translation_of: README.md
translation_source_sha: f693c37f91d31b767d1e2d283b4ebb2930ac3f2f
translation_revised: 2026-10-22
---

# SRE 런북

이 런북은 FDAI의 SRE 계약을 운영자가 반복해서 실행할 수 있는 절차로 구체화합니다.
업스트림 문서는 필수 안전 검사, 증거, 의사 결정, 최종 결과를 정의합니다. 다운스트림 포크는
환경별 명령, 리소스 이름, 담당자, 호출 알림 연동, 롤백 구현을 제공합니다.

## 인시던트 운영

| 절차 | 사용 시점 |
|------|-----------|
| [인시던트 분류](incident-triage-ko.md) | 새 인시던트의 범위, 심각도, 담당자를 정하고 조사를 시작해야 할 때 |
| [SLO 오류 예산 소진 대응](slo-burn-response-ko.md) | 여러 시간 구간에서 측정한 오류 예산 소진으로 문제가 감지될 때 |
| [RCA 근거 수집](rca-evidence-collection-ko.md) | 조사 범위가 정해져 있고 출처를 인용할 수 있는 근거 집합이 필요할 때 |
| [인시던트 완화와 롤백](incident-mitigation-and-rollback-ko.md) | 대응 계획에서 통제된 변경을 제안할 때 |
| [사후 분석 작업 흐름](postmortem-workflow-ko.md) | 해결된 인시던트를 검토하고 후속 조치를 정해야 할 때 |

## 대비

| 절차 | 사용 시점 |
|------|-----------|
| [배포 복구](deployment-recovery-ko.md) | 보호된 계획, 오프라인 키트 또는 시작 준비 상태 검사로 안전한 배포를 진행할 수 없을 때 |
| [심층 DB-DR 복원 훈련](db-dr-drill-ko.md) | PostgreSQL 복원 근거를 갱신할 때 |
| [컨트롤 플레인 지역 간 장애 조치와 원상 복귀](control-plane-failover-ko.md) | 지역 장애를 선언하거나 예정된 컨트롤 플레인 전체 복구 훈련을 시작할 때 |
| [Chaos Game Day](chaos-game-day-ko.md) | 승격된 장애 시나리오로 훈련할 때 |
| [경보 튜닝](alert-tuning-ko.md) | 불필요한 경보, 탐지 누락, 오래된 라우팅을 측정해 개선해야 할 때 |
| [알림 과다 수신 관리](alert-noise-governance-ko.md) | shadow 우선 알림 평가나 정확한 계획에 따른 네 수동 PR 작업의 선행 조건, 검증, 복구 안내가 필요할 때 |

## 거버넌스와 설정

- [예외 작업 흐름](exemption-workflow-ko.md)
- [Entra 앱 등록](entra-app-registration-ko.md)
- [오프라인 release 신뢰 설정 절차](offline-trust-ceremony-ko.md)

## 필수 런북 계약

실행 가능한 모든 절차에는 담당자와 승인자, 한정된 작업 범위, 사전 검사, 중지 조건,
롤백, 근거, 감사 참조, 작업을 수행하지 않는 최종 결과인 no-op의 동작을 정의합니다.
필수 항목 중 하나라도 확보할 수 없으면 중지하고 검토를 요청합니다.
