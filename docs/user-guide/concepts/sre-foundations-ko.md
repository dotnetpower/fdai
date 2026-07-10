---
title: SRE 기초(SRE foundations)
description: FDAI가 자동화하는 핵심 SRE 기능과, 각 기능이 컨트롤 루프·에이전트·세 버티컬에 어떻게 매핑되는가.
translation_of: sre-foundations.md
translation_source_sha: e1a3cf3c61ba91155e159233aaa839340324532e
translation_revised: 2026-07-11
sidebar:
  order: 1
---

# SRE 기초(SRE foundations)

FDAI는 **사이트 신뢰성 엔지니어링(Site Reliability Engineering, SRE)**에 대한
자율적 접근입니다. SRE 분야는 반복되는 기능 집합을 정의합니다. 시스템을
관찰하고, 회귀를 잡아내고, 변경을 안전하게 배포하고, 용량을 계획하고, 비용을
통제하고, 재해에 대비하고, 토일(toil)을 제거하는 것입니다. FDAI는 이 기능들을
유지하되 누가 실행하는지를 바꿉니다. 반복 가능한 다수는 에이전트가 규칙으로
실행하고, 사람은 위험한 잔여 소수에 대해서만 요청받습니다.

이 페이지는 지도입니다. FDAI가 커버하는 SRE 기능, 각 기능이 하는 일, 그리고
메커니즘을 깊이 읽을 위치를 정리합니다.

## FDAI가 자동화하는 기능

| SRE 기능 | FDAI에서 하는 일 | 버티컬 / 소유자 |
|----------|------------------|-----------------|
| 모니터링과 관측성 | 리소스 변경 신호·activity-log 이벤트·탐지기 finding을 수집하고 인시던트로 상관 | Heimdall, Huginn |
| 인시던트 탐지와 대응 | 각 신호를 신뢰도로 라우팅하고, 판정을 내리고, 실행하거나 에스컬레이션 | trust-router, Forseti |
| 변경 관리 | 제안된 모든 변경을 배포 전 policy-as-code에 대해 게이트 | Change Safety |
| 용량과 성능 | 측정된 수요에 맞춰 워크로드를 사이즈 최적화·스케일 | Freyr, Cost Governance |
| 비용과 효율 | 지출 이상을 탐지하고 낭비(유휴 디스크·orphan NIC·미사용 IP)를 회수 | Njord, Cost Governance |
| 신뢰성과 재해 복구 | DR 훈련·DB 복원 훈련·한정된 카오스 실험 실행 | Resilience, Loki, Vidar |
| 토일 제거 | 반복 가능한 다수를 결정론적으로, 사람 없이 해소 | deterministic-first |
| 포스트모템과 학습 | 모든 액션에 append-only 감사 엔트리를 남기고 운영 신호에서 카탈로그 갱신 제안 | Saga, Norns |

## 모니터링과 관측성

FDAI는 폴링 대시보드가 아니라 이벤트 기반입니다. 리소스 변경·activity-log
이벤트·이상 또는 예측 finding이 이벤트 버스로 도착합니다. 센싱 에이전트들이 이를
정규화·중복 제거·상관하여 인시던트로 묶어, 하나의 root 이벤트가 열 개의 증상으로
집계되지 않도록 합니다.

예시: 하나의 실패한 배포에서 다섯 개 알림이 발생 -> 수집기가 공유 리소스 키로
상관 -> 다섯 개가 아니라 하나의 인시던트가 루프에 진입.

## 인시던트 탐지와 대응

상관된 모든 이벤트는 **trust router**가 점수를 매기고, 결정할 수 있는 가장 낮은
티어를 선택합니다([risk-tiers-ko.md](risk-tiers-ko.md)). 결정론 케이스는 모델
호출 없이 T0에서 해소되고, 애매한 케이스는 에스컬레이션됩니다. 탐지는 결정론
우선을 유지합니다. 이상이나 예측은 risk gate가 관리하는 *finding*을 올릴 뿐,
스스로 auto-act 하지 않습니다.

## 변경 관리

변경이 배포되기 전에 policy-as-code에 대해 dry-run되고 blast-radius가 한정되며,
자동 병합되거나 HIL로 라우팅됩니다. 액션은 **remediation PR**로 전달되므로 리뷰·
승인·롤백을 git에서 물려받습니다.

예시: IaC PR이 public-egress 규칙 제안 -> risk gate가 고위험 판정 -> Teams로 승인
카드 도착 -> 승인 -> executor가 PR 병합 후 감사 엔트리 기록.

## 용량·성능·비용

용량과 비용은 같은 신호의 두 관점입니다. 리소스가 수요에 맞게 사이징되었는가?
FDAI는 과잉·과소 프로비저닝을 탐지하고 사이즈 최적화를 권고하며, 저위험
하위집합(유휴 디스크 정리·미사용 public IP 해제·orphan NIC 제거)만 자동 실행합니다.
라이브 워크로드를 저하시킬 수 있는 것은 게이트됩니다.

## 신뢰성과 재해 복구

여기서 신뢰성 작업은 능동적입니다. 예약된 DR 훈련, DB 복원 훈련, blast-radius가
한정된 카오스 실험이 주기적으로 돌아갑니다. 주기·범위·증거는 분리됩니다.
스케줄러가 주기, risk gate가 범위, 감사 로그가 증거를 담당합니다.

## 토일 제거

결정론 우선 설계의 핵심은 토일 제거입니다. 반복 가능한 다수를 규칙이 결정하므로,
운영자는 매주 같은 드리프트·비용 회귀·정책 위반을 손으로 승인하는 일을 멈춥니다.
사람은 신규이고 고위험인 것에만 남습니다([deterministic-first-ko.md](deterministic-first-ko.md)).

## 포스트모템과 학습

모든 종단 결정 - no-op·거부·HIL 타임아웃 포함 - 은 append-only 감사 엔트리를
남깁니다. 학습 루프가 그 신호(HIL 승인·shadow 드리프트·오버라이드)를 관찰하여
카탈로그 갱신을 제안하므로, 결정론 층은 사람이 손으로 다시 작성하지 않아도 계속
좋아집니다.

## 다음 단계

| 학습 대상 | 문서 |
|-----------|------|
| 반복 가능한 다수가 왜 LLM에 닿지 않는가 | [deterministic-first-ko.md](deterministic-first-ko.md) |
| 판정이 어떻게 auto vs HIL이 되는가 | [risk-tiers-ko.md](risk-tiers-ko.md) |
| 모든 액션이 어떻게 안전 계약을 물려받는가 | [ontology-driven-automation-ko.md](ontology-driven-automation-ko.md) |
| 어떤 에이전트가 각 기능을 돌리고 어떻게 자가 치유하는가 | [agents-and-self-healing-ko.md](agents-and-self-healing-ko.md) |
| 세 버티컬 전체 | [../get-started-ko.md](../get-started-ko.md) |
