---
title: 규칙 Override
description: 규칙 카탈로그 자체를 편집하지 않고 특정 스코프에서 승격된 규칙을 좁히거나, 격을 낮추거나, 비활성화하는 법.
translation_of: override-a-rule.md
translation_source_sha: f558d383c851bc85e804713158cf6d7e7db6411e
translation_revised: 2026-07-07
---

# 규칙 Override

때때로 승격된 규칙은 일반적으론 옳지만 특정 스코프에서는 틀립니다 - 정당하게 넓은
임계값을 원하는 프로덕션 티어, 엄격한 가드레일이 도움보다 성가신 개발 샌드박스 등.
규칙 텍스트를 편집(모두에게 영향)하거나 규칙을 전역 비활성화하는 대신, AIOpsPilot
은 자동 품질 게이트 위에 앉는 **스코프된 override**를 지원합니다.

## Override가 할 수 있는 것

Override는 규칙 카탈로그 옆에 저장되는 policy-as-code 아티팩트입니다. 주어진
스코프의 규칙에 대해 override는 다음 중 정확히 하나를 할 수 있습니다:

- **`disabled`** - 그 스코프에서 규칙 실행이 멈춥니다. 탐지는 shadow로 계속 돕니다
  (감사 로그는 규칙이 *would have flagged* 것을 계속 기록), 발견 루프가 반복되는
  override 패턴을 잡을 수 있게.
- **`severity-downgrade`** - 규칙은 여전히 발동하지만 낮은 severity로 (예:
  `critical → medium`), 보통 AUTO 나 DENY 에서 HIL로 라우팅됩니다.
- **`parameter-relaxation`** - 규칙 스스로 선언한 임계값의 확대(예: 비용 이상
  `> 20%`가 `> 40%`가 됨). 규칙이 선언한 파라미터만 확대할 수 있으며, 체크 로직
  자체는 다시 작성할 수 없습니다.

더 넓은 것 - 모든 스코프에 걸친 전역 비활성 - 은 override가 아닙니다. 규칙 은퇴
이며, 자체 리뷰를 가진 카탈로그 파이프라인을 통과해야 합니다.

## 스코프 제한

**Override는 `resource-group` 동등 그룹 또는 그보다 좁게 경계지어져야 합니다.**
더 넓은 override(서브스크립션 전체, 테넌트 전체, 조직 전체)는 승격 파이프라인이
거부합니다. 그런 폭이 필요하다면 규칙 은퇴를 요청하는 것입니다.

실무적으로:

- 특정 리소스 그룹 - OK.
- 단일 리소스 - OK.
- 서브스크립션 전체 - 거부.

## Override가 항상 필요로 하는 것

모드와 무관하게 모든 override는 기록합니다:

- **액터** - override를 올리는 운영자.
- **승인자** - 별개의 principal(자기 승인 없음).
- **정당화** - 이 스코프가 왜 다른지의 이유. 이 텍스트는 감사되며 override가 건드릴
  모든 HIL 요청에 표시됩니다.
- **대상 규칙 + 스코프 + 모드** - 발견 루프가 항목을 찾을 수 있게 기계 판독 가능.

Override는 장수(long-lived)할 수 있습니다. 만료를 강제하지 않지만, 같은 규칙에
반복 · 장수 override는 발견 루프가 규칙 자체의 개정을 제안하는 신호로 취급합니다.

## Override가 억제하지 *않는* 것

- **감사 기록.** Override가 가로챈 모든 finding은 왜 억제됐는지의 이유와 함께
  여전히 로깅됩니다. Override는 이벤트를 보이지 않게 만들지 않고, AIOpsPilot이
  그것으로 무엇을 할지를 바꿉니다.
- **Upstream 규칙 업데이트.** Override가 별도 아티팩트이므로 upstream 규칙
  업데이트는 override를 건드리지 않고 흐릅니다.

## 어떻게 올리나

1. 규칙 id와 현재 판정을 확인합니다(감사 로그에 둘 다 있음).
2. 규칙을 편집하는 것과 같은 리포에서 override 아티팩트(모드, 스코프, 정당화)를
   작성합니다.
3. PR을 엽니다. 리뷰어는 본인이 아니어야 합니다.
4. 머지되면 override는 다음 번 영향받는 이벤트가 발동할 때 효과가 있습니다.
   감사 로그는 기초 finding과 그것을 가로챈 override를 모두 보여줍니다.

## 대신 규칙을 은퇴시켜야 할 때

여러 스코프에 같은 규칙에 대해 같은 override를 반복해서 올리고 있다면 그건 발견
루프의 일이지만 - 규칙 자체의 개정이 필요하다는 신호이기도 합니다. Override를
쌓지 말고, 규칙 카탈로그에 개정된 파라미터로 PR을 열어 다른 규칙 변경과 같은
품질 게이트를 지나게 합니다.

## 다음 단계

| 학습 대상 | 문서 |
|-----------|------|
| severity와 auto/HIL/DENY의 실행 시점 의미 | [../concepts/risk-tiers-ko.md](../concepts/risk-tiers-ko.md) |
| override가 실제로 효과를 내는지 보는 법 | [read-audit-log-ko.md](read-audit-log-ko.md) |
| 예외 워크플로우 (owner 승인, 시간 한정) | [../../runbooks/exemption-workflow-ko.md](../../runbooks/exemption-workflow-ko.md) |
| 전체 Human Override 설계 | [../../../.github/instructions/architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) |
