---
title: SRE Runbook
description: Incident response, recovery, governed automation을 위한 customer-neutral 운영자 절차와 템플릿입니다.
translation_of: README.md
translation_source_sha: dba5e386a1e6f3de67a84905abb6aaa6fe49da54
translation_revised: 2026-07-22
---

# SRE Runbook

이 runbook은 FDAI의 SRE 계약을 반복 가능한 운영자 절차로 바꿉니다. Upstream은 필수
안전 검사, 증거, 결정, terminal outcome을 문서화합니다. Downstream fork는 환경별 명령,
resource name, owner, paging integration, rollback implementation을 제공합니다.

## 인시던트 운영

| 절차 | 사용 시점 |
|------|-----------|
| [인시던트 분류](incident-triage-ko.md) | 새 incident의 scope, severity, ownership, investigation이 필요할 때 |
| [SLO burn 대응](slo-burn-response-ko.md) | Multi-window error-budget burn이 발견된 문제를 생성할 때 |
| [RCA 증거 수집](rca-evidence-collection-ko.md) | Investigation에 범위와 citation이 있는 evidence set이 필요할 때 |
| [인시던트 완화와 rollback](incident-mitigation-and-rollback-ko.md) | Response plan이 governed change를 제안할 때 |
| [포스트모템 workflow](postmortem-workflow-ko.md) | Resolved incident에 review와 follow-up이 필요할 때 |

## 대비

| 절차 | 사용 시점 |
|------|-----------|
| [Deep DB-DR 복원 훈련](db-dr-drill-ko.md) | PostgreSQL restore evidence를 갱신할 때 |
| [Chaos game day](chaos-game-day-ko.md) | 승격된 fault scenario를 훈련할 때 |
| [Alert tuning](alert-tuning-ko.md) | Noise, miss, stale routing을 측정해 수정할 때 |

## 거버넌스와 설정

- [예외 workflow](exemption-workflow-ko.md)
- [Entra 앱 등록](entra-app-registration-ko.md)

## 필수 runbook 계약

실행 가능한 모든 절차는 owner와 approver, bounded scope, preflight, stop condition,
rollback, evidence, audit reference, terminal no-op behavior를 정의합니다. 필수 항목을 사용할
수 없으면 중지하고 검토로 라우팅합니다.
