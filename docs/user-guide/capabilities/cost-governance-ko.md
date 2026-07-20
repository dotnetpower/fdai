---
title: 비용 거버넌스
description: FDAI가 지출 이상을 감지하고, 라이트사이징을 권장하고, 저위험 정리를 자동 실행하는 방법 - 위험한 비용 변경은 승인을 기다립니다.
translation_of: cost-governance.md
translation_source_sha: d1843cdad5b6550ffbbdb18cb175e478cd6f62ca
translation_revised: 2026-07-21
---

# 비용 거버넌스

FDAI는 다른 운영 신호를 관찰할 때와 같은 방식으로 클라우드 지출을 살핍니다. 먼저
결정론적으로 감지하고, 저위험 대다수에만 자율 액션을 허용하며, 피해를 줄 수 있는
변경에는 사람의 승인을 요구합니다. 낭비를 찾고 라이트사이징을 제안하며 안전한 범위는
스스로 정리하지만, 실질적인 blast radius가 있는 변경은 사람 승인을 기다립니다.

## 무엇을 얻나요

- **지출 이상 감지.** 예상 베이스라인에서 벗어난 비용 신호는 finding을 생성합니다.
  감지는 shadow에서 수행되며, 탐지 결과만으로 액션을 자동 실행하지 않습니다.
- **라이트사이징 권장.** 과다 프로비저닝된 리소스는 구체적이고 되돌릴 수 있는
  remediation 대상으로 표시됩니다.
- **안전한 정리는 자동으로.** 유휴 디스크 정리, 미사용 public IP 할당 해제, 고아 NIC
  제거와 같은 저위험 액션은 롤백 경로와 함께 자동 실행됩니다.
- **위험한 비용 변경은 사람 승인을 기다립니다.** 안전 임계값을 넘는 액션은 모두
  human-in-the-loop (HIL) 승인으로 라우팅되며 자동 적용되지 않습니다.

## 비용 액션이 enforce에 도달하는 방법

<!-- fdai:steps -->

1. **이상 감지.** 비용 이상 감지기가 과다 프로비저닝된 캐시 티어 등을 감지해
  정규화된 finding을 생성합니다.
2. **규칙 일치.** 결정론적 티어(T0)가 finding에 맞는 라이트사이징 또는 정리 규칙을
  찾습니다.
3. **shadow에서 증명.** 규칙은 [shadow 모드](../concepts/shadow-then-enforce-ko.md)로
  실행되며, 승격 게이트를 통과할 때까지 변경을 적용하지 않고 판단과 로깅만 수행합니다.
4. **enforce로 승격.** 승격 기준을 충족하는 정확도가 측정된 뒤에만 액션을 자율 실행할
  수 있습니다.
5. **롤백과 함께 전달.** 라이트사이징 또는 정리 변경은 자체 롤백 참조와 감사 항목을
  담은 remediation pull request로 전달됩니다.

## 약속이 아니라 증거

비용 거버넌스는 단언하지 않고 베이스라인을 기준으로 측정합니다. 자세한 내용은
[목표와 메트릭](../../roadmap/architecture/goals-and-metrics-ko.md)과 예시
[비용 모델](../../roadmap/interfaces/cost-model-ko.md)을 참조하세요.

- **단위당 비용** - 비용 액션에서는 `$/optimization` 단위로 보고합니다. 비용을 낮추는
  방향성 목표이며, 베이스라인과 처리군(treatment)을 같은 시나리오 세트에서 측정한
  뒤에만 명시합니다.
- **롤백률**은 가드 메트릭입니다: 베이스라인 대비 증가하면 안 됩니다.
- FDAI는 베이스라인과 처리군을 동일 조건에서 함께 측정하지 않고는 비용 배수를 주장하지
  않습니다.

## 관련 문서

<!-- fdai:cards -->

- [결정론 우선](../concepts/deterministic-first-ko.md) - 감지가 규칙 기반이고 검토 가능하게 남는 이유.
- [리스크 티어](../concepts/risk-tiers-ko.md) - 비용 변경이 auto, HIL, deny로 라우팅되는 방식.
- [Shadow 후 enforce](../concepts/shadow-then-enforce-ko.md) - 비용 액션이 자율성을 얻는 방법.
- [비용 모델](../../roadmap/interfaces/cost-model-ko.md) - 예시 Azure 비용 범위.
- [배포와 온보딩](../../roadmap/deployment/deploy-and-onboard-ko.md) - FDAI를 환경에 도입하는 방법.
