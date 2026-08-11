---
title: SRE Runbook
description: Incident response, recovery, governed automation을 위한 customer-neutral 운영자 절차와 템플릿입니다.
translation_of: README.md
translation_source_sha: ead0596f0cae176cbc8fda54249a555dc76619ff
translation_revised: 2026-08-11
---

# SRE 런북

이 런북은 FDAI의 SRE 계약을 반복 가능한 운영자 절차로 바꿉니다. 업스트림은 필수
안전 검사, 증거, 결정, 최종 결과를 문서화합니다. 다운스트림 포크는 환경별 명령,
리소스 이름, 소유자, paging 통합, 롤백 구현을 제공합니다.

## 인시던트 운영

| 절차 | 사용 시점 |
|------|-----------|
| [인시던트 분류](incident-triage-ko.md) | 새 인시던트의 범위, 심각도, 소유권, 조사가 필요할 때 |
| [SLO burn 대응](slo-burn-response-ko.md) | Multi-window error-budget burn이 발견된 문제를 생성할 때 |
| [RCA 증거 수집](rca-evidence-collection-ko.md) | 조사에 범위와 인용이 있는 근거 집합이 필요할 때 |
| [인시던트 완화와 롤백](incident-mitigation-and-rollback-ko.md) | 응답 계획이 통제된 변경을 제안할 때 |
| [포스트모템 작업 흐름](postmortem-workflow-ko.md) | Resolved 인시던트에 검토와 후속 조치가 필요할 때 |

## 대비

| 절차 | 사용 시점 |
|------|-----------|
| [배포 복구](deployment-recovery-ko.md) | Protected 계획, offline 키트 또는 startup-readiness 검사가 안전한 배포를 차단할 때 |
| [Deep DB-DR 복원 훈련](db-dr-drill-ko.md) | PostgreSQL 복원 근거를 갱신할 때 |
| [컨트롤 플레인 regional 장애 조치 및 failback](control-plane-failover-ko.md) | Regional 장애 또는 예약된 full control-plane 복구 훈련을 선언할 때 |
| [Chaos game 일](chaos-game-day-ko.md) | 승격된 fault 시나리오를 훈련할 때 |
| [경보 튜닝](alert-tuning-ko.md) | Noise, miss, stale 라우팅을 측정해 수정할 때 |

## 거버넌스와 설정

- [예외 작업 흐름](exemption-workflow-ko.md)
- [Entra 앱 등록](entra-app-registration-ko.md)
- [Offline release trust 의식](offline-trust-ceremony-ko.md)

## 필수 런북 계약

실행 가능한 모든 절차는 소유자와 승인자, 범위가 제한된 범위, preflight, stop 조건,
롤백, 근거, 감사 참조, 최종 no-op 행동을 정의합니다. 필수 항목을 사용할
수 없으면 중지하고 검토로 라우팅합니다.
