---
translation_of: exemption-workflow.md
translation_source_sha: 1c08057d3ea8ca37263abb8cce0317bfc0bdb9ff
translation_revised: 2026-10-22
title: 예외 워크플로
owner: aw-owners (Owner-tier)
sla: "PR 생성 후 1영업일 이내 승인 결정"
---

# 예외 워크플로

특정 범위에 배정된 규칙의 적용을 한시적으로 유예할 때 이 절차를 사용합니다.
예외에는 **유효 기간, 감사 기록, 책임 담당자의 승인**이 필요합니다.
[`rule-catalog/schema/exemption.json`](../../services/core-control-plane/src/fdai/rule_catalog/schema/exemption.schema.json)
스키마와 `rule-catalog/exemptions/`를 변경하는 모든 PR에서 실행되는 CI 검증기가 이 절차를 뒷받침합니다.

## 언제 예외를 쓰나

예외는 특정 범위의 특정 규칙에 대한 **강제 적용**을 억제합니다.
다음 조건을 모두 충족할 때 사용합니다.

- 규칙은 일반적으로 올바르지만 **이 범위**에는 맞지 않습니다.
- 대상은 리소스 그룹 또는 그보다 좁은 범위로 한정됩니다.
- **예외를 제거할 계획**이 있습니다. 예외는 수정이 아니라 유예입니다.
- 규칙을 적용하지 않을 때의 영향을 이해하고 있으며 영향 범위가 제한되어 있습니다.

규칙 자체가 일반적으로 잘못되었다면 rule-catalog 파이프라인을 통해 **규칙을 폐기**하세요.
자동 실행과 사람 승인을 구분하는 기준이 문제라면 규칙 자체가 아니라 **`risk-classification`을 조정**하세요.

## 역할

- **요청자** - `aw-contributors` Entra 그룹 (또는 그 이상)의 누구든 예외 PR을 열 수
  있습니다.
- **승인자** - `aw-owners` 멤버여야 합니다. **승인자 ≠ 요청자** - 브랜치 보호가
  "작성자 ≠ 검토자"를 강제하고, 예외 아티팩트도 CI가 서로 다른 값인지 검사하는
  `requested_by`와 `approved_by` 필드를 담고 있습니다.
- **감사자** - 모든 상태 전환(활성 / 만료 / 철회)에 대해 행위 주체의 principal과
  함께 감사 로그를 남깁니다.

## 절차

1. **`Exemption Request` 템플릿으로 PR을 생성합니다.**
2. [스키마](../../services/core-control-plane/src/fdai/rule_catalog/schema/exemption.schema.json)에 따라
   `rule-catalog/exemptions/<id>.json`에 **아티팩트를 작성합니다.**
3. **CI가 다음을 검사합니다.**
   - 스키마 검증(`exemption-check` 작업).
   - 작성자와 검토자를 구분하는 브랜치 보호 규칙(저장소 설정).
   - `requested_by` ≠ `approved_by` 모델 불변식.
   - `expires_at > created_at` 모델 불변식.
4. **Owner-tier 검토 후 병합합니다.** 현재 병합 자체는 실제 Azure 리소스에 영향을
   주지 않습니다. 카탈로그 파이프라인(단계 2)이 예외를 인식하면 규칙 적용이 억제됩니다.
5. **자동 만료**. 저장소 작업은 검토된 아티팩트만 `state=expired`로 변경합니다. 런타임
   조정기는 검토된 정확한 배정 연결을 확인하고 안정적인 멱등성 키가 있는
   `governance.reapply-rule-assignment` 제안을 게시합니다. 제안은 일반 위험 평가, 사람 승인,
   Thor 실행, 롤백, 감사, 독립 효과 검증을 거칩니다. 연결 누락, 개정 충돌, 전달 사용 불가,
   알 수 없는 전달 결과는 보류 상태로 남고 안전하게 다시 시도할 수 있습니다.

## 시간 제한

- `expires_at`은 `created_at`보다 **엄격히 이후**여야 합니다.
- 최대 유효 기간은 여기서 고정하지 않습니다. 더 긴 기간을 지정하려면 PR 본문에
  사유를 명시해야 합니다.
- `expires_at` 14일 전에 기본 A1 채널로 만료 예정 요약을 보낼 수 있습니다. 각 항목에는
  정확한 예외 개정, 규칙, 만료 시점, 요청자 멘션을 포함합니다. 알림 전달은 권한을 부여하지
  않으며 만료를 지연하지 않습니다.

## 취소

Owner는 활성 예외를 다음과 같이 취소할 수 있습니다.

1. 아티팩트를 `state=revoked`로 변경하고 `revoked_at`, `revoked_by`를 설정합니다.
2. Owner-tier 검토 후 취소 PR을 병합합니다. 자기 승인은 허용되지 않습니다.

카탈로그 파이프라인이 취소 상태를 관찰하는 즉시 규칙 적용이 다시 활성화됩니다.

## 에스컬레이션

- 명백히 스키마를 충족하는 요청인데도 CI 결과가 성공과 실패를 반복하면, 기본 A1 채널로
  `aw-owners`를 호출하고 CI 로그를 첨부합니다.
- 예외가 거부됐지만 환경이 실질적으로 위험한 상태이면 `aw-break-glass`로
  에스컬레이션합니다. Conditional Access가 적용되는 단기 권한 부여이며,
  감사 기록을 남깁니다. 통제 절차를 우회하는 수단은 아닙니다.

## 참조

| 아티팩트 | 경로 |
|----------|------|
| 설계: 사람의 재정의 | [../../.github/instructions/architecture.instructions.md#human-override](../../.github/instructions/architecture.instructions.md#human-override) |
| 예외 스키마 | [../../services/core-control-plane/src/fdai/rule_catalog/schema/exemption.schema.json](../../services/core-control-plane/src/fdai/rule_catalog/schema/exemption.schema.json) |
| CI 검사 (`exemption-check` 작업) | [../../.github/workflows/ci.yml](../../.github/workflows/ci.yml) |
| 만료 CLI | [../../scripts/governance/exemption-expire.py](../../scripts/governance/exemption-expire.py) |
| PR 템플릿 | [../../.github/PULL_REQUEST_TEMPLATE/exemption.md](../../.github/PULL_REQUEST_TEMPLATE/exemption.md) |
