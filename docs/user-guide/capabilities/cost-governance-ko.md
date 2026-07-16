---
title: 비용 거버넌스
description: FDAI가 지출 이상을 감지하고, 라이트사이징을 권장하고, 저위험 정리를 자동 실행하는 방법 - 위험한 비용 변경은 승인을 기다립니다.
translation_of: cost-governance.md
translation_source_sha: 89756e907af7463440ce56cf6cb4e0dc050e0cf3
translation_revised: 2026-07-17
---

# 비용 거버넌스

FDAI는 다른 모든 것을 지켜보는 방식 그대로 클라우드 지출을 지켜봅니다: 먼저
결정론적 감지, 저위험 대다수에 대해서만 자율 액션, 해를 끼칠 수 있는 것은 사람
승인. 낭비를 찾고, 라이트사이징을 제안하며, 안전한 부분집합은 스스로 정리합니다 -
실제 blast radius를 가진 변경은 여러분을 기다립니다.

## 무엇을 얻나요

- **지출 이상 감지.** 예상 베이스라인에서 벗어난 비용 신호는 finding을 올립니다.
  감지는 shadow로 실행되며 결코 스스로 자동 실행하지 않습니다.
- **라이트사이징 권장.** 과다 프로비저닝된 리소스는 구체적이고 되돌릴 수 있는
  remediation과 함께 플래그됩니다.
- **안전한 정리는 자동으로.** 저위험 부분집합 - 유휴 디스크 정리, 미사용 public IP
  해제, 고아 NIC 제거 - 은 롤백 경로와 함께 자동 실행됩니다.
- **위험한 비용 변경은 사람을 기다립니다.** 안전 임계값을 넘는 것은 무엇이든
  HIL(사람 개입) 승인으로 라우팅되며 자동 적용되지 않습니다.

## 비용 액션이 enforce에 도달하는 방법

<!-- fdai:steps -->

1. **이상 감지.** 비용 이상 감지기가 예컨대 과다 프로비저닝된 캐시 티어에서
   작동하여 정규화된 finding을 올립니다.
2. **규칙 매칭.** 결정론 티어(T0)가 finding을 라이트사이징 또는 정리 규칙에
   매칭합니다.
3. **shadow에서 증명.** 규칙은 [shadow 모드](../concepts/shadow-then-enforce-ko.md)로
   실행되어, 승격 게이트를 통과할 때까지 변경 없이 판단과 로깅만 합니다.
4. **enforce로 승격.** 측정된 정확도가 유지될 때에만 액션이 자율화됩니다.
5. **롤백과 함께 전달.** 라이트사이징 또는 정리는 자체 롤백 참조와 감사 항목을 담은
   remediation pull request로 전달됩니다.

## 약속이 아니라 증거

비용 거버넌스는 단언하지 않고 베이스라인 대비 측정합니다(
[목표와 메트릭](../../roadmap/architecture/goals-and-metrics-ko.md)과 예시
[비용 모델](../../roadmap/interfaces/cost-model-ko.md) 참조):

- **단위당 비용** - 비용 액션의 경우 `$/optimization`으로 보고 - 은 낮추는 방향의
  목표이며, 베이스라인과 처리(treatment)를 같은 시나리오 세트에서 측정한 뒤에만
  명시됩니다.
- **롤백률**은 가드 메트릭입니다: 베이스라인 대비 증가하면 안 됩니다.
- FDAI는 짝지어진 측정 없이는 비용 배수를 결코 주장하지 않습니다.

## 관련 문서

<!-- fdai:cards -->

- [결정론 우선](../concepts/deterministic-first-ko.md) - 감지가 규칙 기반이고 검토 가능하게 남는 이유.
- [리스크 티어](../concepts/risk-tiers-ko.md) - 비용 변경이 auto, HIL, deny로 라우팅되는 방식.
- [Shadow 후 enforce](../concepts/shadow-then-enforce-ko.md) - 비용 액션이 자율성을 얻는 방법.
- [비용 모델](../../roadmap/interfaces/cost-model-ko.md) - 예시 Azure 비용 범위.
- [배포와 온보딩](../../roadmap/deployment/deploy-and-onboard-ko.md) - FDAI를 여러분의 환경에 도입하기.
