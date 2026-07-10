---
translation_of: exemption-workflow.md
translation_source_sha: e0e27d7f30fb1112885515e26faa9f103431fe82
translation_revised: 2026-07-11
title: 예외 워크플로
owner: aw-owners (Owner-tier)
sla: "PR 오픈으로부터 1 영업일 내 승인 결정"
---

# 예외 워크플로

특정 스코프에 대해 rule assignment의 **시간 제한, 감사, owner 승인** waiver 경로입니다.
[`rule-catalog/schema/exemption.json`](../../src/fdai/rule_catalog/schema/exemption.schema.json)
과 `rule-catalog/exemptions/`를 만지는 모든 PR에서 실행되는 CI 검증기가 뒷받침합니다.

## 언제 예외를 쓰나

예외는 특정 스코프의 특정 rule에 대해 **enforce**를 억제합니다. 다음이 모두 성립할 때
적절한 도구입니다:

- Rule이 일반적으로는 옳지만 **이 스코프**에서는 틀리다.
- 스코프가 리소스 그룹 (또는 더 좁은 범위)으로 좁혀진다.
- **예외를 제거할 계획**이 존재한다 - 예외는 수정(fix)이 아니라 유예다.
- Rule을 끈 채로 둘 때의 blast radius가 이해되어 있고 그 범위가 제한되어 있다.

Rule이 일반적으로 틀렸다면 대신 rule-catalog 파이프라인을 통해 **rule을 폐기**하세요.
잘못된 차원이 auto-vs-HIL이라면 rule 자체가 아니라 **`risk-classification`을 조정**하세요.

## 역할

- **요청자** - `aw-contributors` Entra 그룹 (또는 그 이상)의 누구든 예외 PR을 열 수
  있습니다.
- **승인자** - `aw-owners` 멤버여야 합니다. **승인자 ≠ 요청자** - 브랜치 보호가
  "author ≠ reviewer"를 강제하고, 예외 아티팩트도 CI가 서로 다른 값인지 검사하는
  `requested_by`와 `approved_by` 필드를 담고 있습니다.
- **감사자** - 모든 상태 전환 (active / expired / revoked)은 행위 주체 principal과
  함께 감사 로그 엔트리를 기록합니다.

## 절차

1. **`Exemption Request` 템플릿**으로 PR 오픈.
2. [스키마](../../src/fdai/rule_catalog/schema/exemption.schema.json)에 따라
   `rule-catalog/exemptions/<id>.json`에 **아티팩트 채우기**.
3. **CI 실행**:
   - 스키마 검증 (`exemption-check` job).
   - Author-≠-reviewer 브랜치 보호 규칙 (repo settings).
   - `requested_by` ≠ `approved_by` 모델 불변식.
   - `expires_at > created_at` 모델 불변식.
4. **Owner-tier 리뷰 + 머지**. 머지는 현재 시점에서 라이브 Azure 리소스에 사이드
   이펙트를 주지 않습니다. enforcement 억제는 카탈로그 파이프라인(Phase 2)이 예외를
   인식한 시점에 적용됩니다.
5. **자동 만료**. 스케줄 잡 (`scripts/exemption-expire.py`; W4.1 이후 Container Apps
   Job)이 `expires_at`이 지나는 순간 각 아티팩트를 `state=expired`로 전환하고 기저
   rule assignment를 재적용합니다. 이벤트는 감사 로그에 기록됩니다.

## 시간 제한

- `expires_at`은 `created_at`보다 **엄격히 이후**여야 합니다.
- 최대 간격 상한은 여기에 코드화되어 있지 않습니다. 더 긴 창은 PR 본문에서
  정당화되어야 합니다.
- `expires_at` 14일 전에 `exemption_expiry_lookahead_weekly` 라우트에서 룩어헤드
  알림이 발송됩니다 (W5.4 - channels 어댑터 의존, 별도 추적).

## 취소

Owner는 active 예외를 다음과 같이 취소할 수 있습니다:

1. 아티팩트를 `state=revoked`, `revoked_at`, `revoked_by`로 편집.
2. 취소 PR 머지 - Owner-tier 리뷰, 자기 승인 금지.

취소는 즉시 enforce로 되돌립니다 (카탈로그 파이프라인이 상태 변화를 관찰하는 순간).

## 에스컬레이션

- 명백히 스키마를 만족하는 요청에 대해 CI가 flapping하면, 기본 A1 채널로
  `aw-owners`를 호출하고 CI 로그를 첨부합니다.
- 예외가 거부됐지만 환경이 실질적으로 위험한 상태이면 `aw-break-glass`로
  에스컬레이션합니다 - Conditional Access 아래, 이는 단기·감사된 부여이지 우회는
  아닙니다.

## 참조

| 아티팩트 | 경로 |
|----------|------|
| 설계: Human Override | [../../.github/instructions/architecture.instructions.md#human-override](../../.github/instructions/architecture.instructions.md#human-override) |
| 예외 스키마 | [../../src/fdai/rule_catalog/schema/exemption.schema.json](../../src/fdai/rule_catalog/schema/exemption.schema.json) |
| CI 검사 (`exemption-check` job) | [../../.github/workflows/ci.yml](../../.github/workflows/ci.yml) |
| 만료 CLI | [../../scripts/exemption-expire.py](../../scripts/exemption-expire.py) |
| PR 템플릿 | [../../.github/PULL_REQUEST_TEMPLATE/exemption.md](../../.github/PULL_REQUEST_TEMPLATE/exemption.md) |
