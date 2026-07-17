---
title: 규칙에 override 적용
description: 규칙 카탈로그 자체를 편집하지 않고 특정 범위에서 승인된 규칙의 적용 범위를 좁히거나, 심각도를 낮추거나, 비활성화하는 방법.
translation_of: override-a-rule.md
translation_source_sha: e06ba558036f6bef09901cd144f8ddde253bbd1c
translation_revised: 2026-07-17
---

# 규칙에 override 적용

때때로 승인된 규칙은 일반적으로 옳지만 특정 범위에는 맞지 않을 수 있습니다. 임계값을
더 넓게 설정해야 하는 프로덕션 티어 또는 엄격한 가드레일의 실익보다 불편이 큰 개발
샌드박스가 그 예입니다.
규칙 텍스트를 편집(모두에게 영향)하거나 규칙을 전역 비활성화하는 대신, FDAI는
자동화된 quality-gate 위에서 동작하는 **범위가 제한된 override**를 지원합니다.

## Override가 할 수 있는 것

Override는 규칙 카탈로그 옆에 저장되는 policy-as-code 아티팩트입니다. Override는
지정된 범위의 규칙에 다음 중 정확히 하나를 적용할 수 있습니다:

- **`disabled`** - 해당 범위에서 규칙 실행이 멈춥니다. 탐지는 shadow에서 계속
  수행되고 감사 로그는 규칙이 원래 탐지했을 항목을 계속 기록합니다. 따라서 discovery
  loop가 반복되는 override 패턴을 확인할 수 있습니다.
- **`severity-downgrade`** - 규칙은 계속 발동하지만 낮은 severity를 적용합니다(예:
  `critical -> medium`). risk-gate는 변경된 탐지 결과를 다시 평가합니다. Override는
  해당 범위의 실행 수준을 낮추거나 실행을 억제할 수 있지만 하드 deny를 우회하거나
  자율성을 높일 수 없습니다.
- **`parameter-relaxation`** - 규칙 자체에 선언된 임계값을 완화합니다(예: 비용 이상
  기준을 `> 20%`에서 `> 40%`로 변경). 규칙에 선언된 매개 변수만 완화할 수 있으며,
  체크 로직 자체는 다시 작성할 수 없습니다.

더 넓은 제어, 즉 모든 범위에 걸친 전역 비활성화는 override가 아닙니다. 규칙의 전역
사용 중지이며, 별도 검토를 거쳐 카탈로그 파이프라인을 통과해야 합니다.

Override는 자율성을 낮추는 제어입니다. HIL을 AUTO로, DENY를 HIL로, shadow를
enforce로 바꾸지 않습니다.

## 범위 제한

**Override는 `resource-group`과 동등한 그룹 또는 그보다 좁은 범위에 한정해야 합니다.**
더 넓은 범위의 override(서브스크립션 전체, 테넌트 전체, 조직 전체)는 승격 파이프라인에서
차단됩니다. 그 정도로 넓은 범위가 필요하다면 규칙 사용 중지를 요청해야 합니다.

실무적으로:

- 특정 리소스 그룹 - OK.
- 단일 리소스 - OK.
- 서브스크립션 전체 - 거부.

## Override가 항상 필요로 하는 것

모드와 무관하게 모든 override는 기록합니다:

- **요청자** - override를 등록하는 운영자.
- **승인자** - 별개의 주체(자기 승인 없음).
- **사유** - 이 범위가 왜 다른지 설명합니다. 이 텍스트는 감사 로그에 기록되며 override가 영향을 주는
  모든 HIL 요청에 표시됩니다.
- **대상 규칙 + 범위 + 모드** - discovery loop가 항목을 찾을 수 있도록 기계 판독 가능한 형태로 기록합니다.

Override는 장기간 유지될 수 있습니다. 만료를 강제하지 않지만, 같은 규칙에 반복적으로
적용되거나 오랫동안 유지된 override는 discovery loop가 규칙 자체의 개정을 제안하는 신호로
취급합니다.

## Override가 억제하지 않는 것

- **감사 기록.** Override가 억제한 모든 탐지 결과는 왜 억제됐는지의 이유와 함께
  계속 기록됩니다. Override는 이벤트를 보이지 않게 만들지 않고, FDAI가 해당 이벤트에
  어떤 조치를 할지만 바꿉니다.
- **업스트림의 규칙 업데이트.** Override가 별도 아티팩트이므로 업스트림 규칙
  업데이트는 override에 영향을 주지 않고 반영됩니다.

## Override 등록 방법

1. 규칙 ID와 현재 판정을 확인합니다. 감사 로그에서 둘 다 찾을 수 있습니다.
2. 규칙을 편집하는 것과 같은 저장소에서 override 아티팩트(모드, 범위, 사유)를
   작성합니다.
3. PR을 엽니다. 검토자는 요청자와 달라야 합니다.
4. 병합되면 override는 다음번에 영향받는 이벤트가 발생할 때 적용됩니다.
  감사 로그는 원래 탐지 결과와 이를 억제한 override를 모두 보여 줍니다.

## Override 적용 확인

PR이 병합된 뒤 대상 범위에서 새 평가 결과 하나를 확인하세요:

1. 감사 항목에 예상한 규칙 ID, override ID, 모드, 제한된 범위가 기록되었는지
  확인합니다.
2. `disabled` override에서도 원래 탐지 결과가 계속 기록되는지 확인합니다.
3. 결과 severity, 매개 변수, 실행 억제가 override와 일치하며 자율성을 높이지 않았는지
  확인합니다.
4. 범위 밖의 인접 리소스에는 일반 규칙 동작이 계속 적용되는지 확인합니다.

Override 적용 결과가 예상과 다르면 별도 override 아티팩트를 제거하거나 수정하세요. 로컬
예외가 동작하는 것처럼 보이게 하려고 원본 규칙을 편집하지 마세요.

## 대신 규칙을 사용 중지해야 할 때

여러 범위에서 같은 규칙에 동일한 override를 반복해서 적용한다면 규칙 자체의 개정이
필요하다는 신호입니다. Override를 쌓지 말고, 규칙 카탈로그에 개정된 매개 변수로 PR을
열어 다른 규칙 변경과 마찬가지로 품질 게이트를 통과하게 하세요.

## 다음 단계

| 학습 대상 | 문서 |
|-----------|------|
| severity와 auto/HIL/DENY의 실행 시점 의미 | [../concepts/risk-tiers-ko.md](../concepts/risk-tiers-ko.md) |
| override가 실제로 적용되는지 확인하는 방법 | [read-audit-log-ko.md](read-audit-log-ko.md) |
| 예외 워크플로우 (owner 승인, 시간 한정) | [../../runbooks/exemption-workflow-ko.md](../../runbooks/exemption-workflow-ko.md) |
| 전체 Human Override 설계 | [../../../.github/instructions/architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) |
