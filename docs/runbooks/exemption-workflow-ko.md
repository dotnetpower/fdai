---
translation_of: exemption-workflow.md
translation_source_sha: e820101bf4ee79a28dd253740ec1c41d7d635475
translation_revised: 2026-07-07
title: 예외 워크플로
owner: aw-owners (Owner-tier)
sla: "PR 오픈으로부터 1 영업일 내 승인 결정"
---

# 예외 워크플로

특정 스코프에 대해 rule assignment 의 **시간 제한, 감사, owner 승인** waiver 경로.
[`rule-catalog/schema/exemption.json`](../../src/aiopspilot/rule_catalog/schema/exemption.schema.json)
와 `rule-catalog/exemptions/` 를 만지는 모든 PR 에서 실행되는 CI 검증기가 뒷받침합니다.

## 언제 예외를 쓰나

예외는 특정 스코프의 특정 rule 에 대해 **enforce** 를 억제합니다. 다음이 모두 성립하는
경우가 옳은 도구입니다:

- Rule 이 일반적으로는 옳지만 **이 스코프**에서는 틀렸다.
- 스코프가 리소스 그룹 (또는 더 좁은 범위) 로 좁혀진다.
- **예외를 제거할 계획** 이 존재한다 - 예외는 fix 가 아니라 지연.
- Rule 을 끄고 두는 blast radius 가 이해되었고 제한되어 있다.

Rule 이 일반적으로 틀렸다면 대신 **rule 폐기** (rule-catalog 파이프라인 통해). 잘못된
차원이 auto-vs-HIL 이라면 rule 자체가 아니라 **risk-classification 조정** 을 사용하세요.

## 역할

- **요청자** - `aw-contributors` Entra 그룹 (또는 그 이상) 의 누구든 예외 PR 을 열 수
  있음.
- **승인자** - `aw-owners` 여야 함. **승인자 ≠ 요청자** - 브랜치 보호가 "author ≠
  reviewer" 를 강제하고, 예외 아티팩트도 CI 가 서로 다름을 검사하는
  `requested_by` 와 `approved_by` 필드를 운반합니다.
- **감사자** - 모든 상태 전환 (active / expired / revoked) 이 행위 주체 principal 와
  함께 감사 로그 엔트리를 씁니다.

## 절차

1. **`Exemption Request` 템플릿**으로 PR 오픈.
2. [스키마](../../src/aiopspilot/rule_catalog/schema/exemption.schema.json) 에 따라
   `rule-catalog/exemptions/<id>.json` 에 **아티팩트 채우기**.
3. **CI 실행**:
   - 스키마 검증 (`exemption-check` job).
   - Author-≠-reviewer 브랜치 보호 규칙 (repo settings).
   - `requested_by` ≠ `approved_by` 모델 invariant.
   - `expires_at > created_at` 모델 invariant.
4. **Owner-tier 리뷰 + 머지**. 머지가 오늘은 라이브 Azure 리소스에 사이드 이펙트를 주지
   않음; enforcement 억제는 카탈로그 파이프라인 (Phase 2) 이 예외를 픽업하면 발효.
5. **자동 만료**. 스케줄 잡 (`scripts/exemption-expire.py`; W4.1 이후 Container Apps
   Job) 이 `expires_at` 이 지나는 순간 각 아티팩트를 `state=expired` 로 전환하고 기저
   rule assignment 를 재적용. 이벤트는 감사 로깅됨.

## 시간 제한

- `expires_at` 은 `created_at` 보다 **엄격히 이후** 여야 함.
- 최대 간격 상한은 여기 코드화 안 됨; 더 긴 창은 PR 본문에서 정당화되어야 함.
- `expires_at` 14일 전에 `exemption_expiry_lookahead_weekly` 라우트에서 lookahead
  알림이 발화 (W5.4 - channels 어댑터 대기, 별도 추적).

## 취소

Owner 는 active 예외를 다음으로 취소할 수 있음:

1. 아티팩트를 `state=revoked`, `revoked_at`, `revoked_by` 로 편집.
2. 취소 PR 머지 - Owner-tier 리뷰, 자기 승인 금지.

취소는 즉시 enforce 로 되돌림 (카탈로그 파이프라인이 상태 변화를 관찰하는 순간).

## 에스컬레이션

- 명백히 스키마를 만족하는 요청에 대해 CI 가 flapping 하면, 기본 A1 채널로
  `aw-owners` 를 페이지 + CI 로그 첨부.
- 예외가 거부됐지만 환경이 실질적으로 위험하면, `aw-break-glass` 로 에스컬레이션 -
  Conditional Access 아래, 이는 단기·감사된 부여이지 우회가 아님.

## 참조

| 아티팩트 | 경로 |
|----------|------|
| 설계: Human Override | [../../.github/instructions/architecture.instructions.md#human-override](../../.github/instructions/architecture.instructions.md#human-override) |
| 예외 스키마 | [../../src/aiopspilot/rule_catalog/schema/exemption.schema.json](../../src/aiopspilot/rule_catalog/schema/exemption.schema.json) |
| CI 검사 (`exemption-check` job) | [../../.github/workflows/ci.yml](../../.github/workflows/ci.yml) |
| 만료 CLI | [../../scripts/exemption-expire.py](../../scripts/exemption-expire.py) |
| PR 템플릿 | [../../.github/PULL_REQUEST_TEMPLATE/exemption.md](../../.github/PULL_REQUEST_TEMPLATE/exemption.md) |
