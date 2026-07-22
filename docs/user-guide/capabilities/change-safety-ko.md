---
title: 변경 안전성
description: FDAI가 제안된 모든 변경을 안전하게 유지하는 방법 - 정책 게이트, 리스크 분류, 감사 가능한 pull request 전달.
translation_of: change-safety.md
translation_source_sha: 8e7f03d7556e183e718dc066cdcbd5f23dffec1d
translation_revised: 2026-07-22
---

# 변경 안전성

IaC(코드형 인프라) pull request, 드리프트된 구성, 정책 위반 등 클라우드에 적용되는
모든 변경은 프로덕션에 도달하기 전에 평가됩니다. FDAI는 변경 안전성을 먼저 결정론적
게이트로 다루고, 결정론적 티어가 판단할 수 없을 때만 별도의 판단 경로로 넘깁니다. 따라서
반복 가능한 대다수 변경은 사람도 모델도 없이 해소됩니다.

## 무엇을 얻나요

- **모든 변경에 정책 게이트.** 제안된 각 변경은 적용되기 전에 policy-as-code에
  대한 dry-run(what-if 평가)을 거칩니다.
- **드리프트 감지와 교정.** 선언된 상태에서 벗어난 구성은 감지 및 분류된 뒤 자동
  교정되거나 검토 대상으로 전달됩니다.
- **고위험 변경은 사람 승인을 기다립니다.** 안전성 검토가 저위험 변경을 자동 병합으로,
  고위험 변경을 사람 승인으로 라우팅합니다.
- **감사와 롤백은 기본 제공됩니다.** 액션은 수정 pull request로 전달되므로,
  변경 기록과 롤백 경로가 이미 Git 안에 있습니다.

## FDAI가 변경을 안전하게 유지하는 방법

<!-- fdai:steps -->

1. **감지.** 리소스 변경, 활동 로그 이벤트, 드리프트 신호가 하나의 정규화된
   이벤트로 컨트롤 루프에 들어옵니다.
2. **정책 대비 dry-run.** 결정론적 티어가 policy-as-code에 대해 what-if로 변경을
  평가합니다. 이 단계에서는 아직 변경을 적용하지 않습니다.
3. **리스크 분류.** 안전성 검토가 변경을
  [리스크 분류](../../roadmap/decisioning/risk-classification-ko.md) 표에 따라 분류합니다:
   auto, 사람 승인, deny.
4. **자동 병합 또는 승인 요청.** 저위험 변경은 자동 병합되고, 고위험 변경은 설정된
  채널을 통한 [승인](../guides/approve-change-ko.md)을 기다립니다.
5. **전달과 감사.** 변경은 롤백 참조를 담은 pull request로 전달되고, `deny`와 `no-op`을
  포함한 모든 결정이 기록됩니다.

## 약속이 아니라 증거

변경 안전성은 단언하지 않고 측정합니다. FDAI는 고정된 시나리오 세트에서 측정된
베이스라인을 기준으로 다음 지표를 보고합니다. 자세한 내용은
[목표와 메트릭](../../roadmap/architecture/goals-and-metrics-ko.md)을 참조하세요.

- **변경 리드 타임** - 변경 요청에서 병합까지 걸리는 시간입니다. 단축 여부를 보는
  방향성 목표이며 평균뿐 아니라 중앙값과 p90으로 보고됩니다.
- **변경 실패율**은 가드 메트릭입니다: 증가하면 안 됩니다. 상승 시 해당 액션은
  enforce에서 shadow로 자동 강등됩니다.
- **정책 위반 escape**는 정확히 0이어야 합니다. 정책을 위반하고 enforce에 도달하는
  자율 변경이 하나라도 있으면 릴리스가 차단됩니다.

새 게이트는 변경을 적용하지 않고 판단과 로깅만 수행하는
[shadow 모드](../concepts/shadow-then-enforce-ko.md)로 먼저 출시됩니다. 승격 게이트를
통과한 뒤에만 적용 모드로 승격됩니다.

## 관련 문서

<!-- fdai:cards -->

- [결정론 우선](../concepts/deterministic-first-ko.md) - 반복 가능한 대다수가 규칙 기반으로 남는 이유.
- [리스크 티어](../concepts/risk-tiers-ko.md) - 변경이 auto, 사람 승인, deny로 라우팅되는 방식.
- [온톨로지 기반 자동화](../concepts/ontology-driven-automation-ko.md) - 변경으로 인스턴스화되는 타입 지정 액션.
- [변경 승인](../guides/approve-change-ko.md) - 사람 승인의 운영자 측면.
- [배포와 온보딩](../../roadmap/deployment/deploy-and-onboard-ko.md) - FDAI를 환경에 도입하는 방법.
