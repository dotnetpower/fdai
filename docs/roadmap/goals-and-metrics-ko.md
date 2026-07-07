---
title: 목표와 메트릭
translation_of: goals-and-metrics.md
translation_source_sha: 09c87ef59567e49b9a79aa8c0e8a817bf6288acb
translation_revised: 2026-07-07
---

# 목표와 메트릭

로드맵은 **증명이 있는 자율성(autonomy with proof)**을 최적화합니다. 모든 자율성 주장은
측정된 베이스라인으로 뒷받침되며, 어떤 것도 추정으로 단언되지 않습니다. 아래의 개선 배수
(`5×`, `large reduction`, `1/5`)는 달성된 결과가 아니라 **목표(targets)** 이며 - 동일한
시나리오 세트에서 레퍼런스 베이스라인과 AIOpsPilot 트리트먼트가 **모두 측정된 후에만**
달성으로 언급할 수 있습니다 ([Measurement-First Rule](#measurement-first-rule) 참조).

이 문서는 KPI의 진실 원본(source of truth)입니다.
[architecture.instructions.md](../../.github/instructions/architecture.instructions.md)의
티어 커버리지 목표와 정합하며
[phase-0-instrumentation-ko.md](phases/phase-0-instrumentation-ko.md) 에서 운영으로
구현됩니다.

## 주요 목표(Primary Objective)

3개 초기 버티컬(Resilience, Change Safety, Cost Governance)을 가진 AIOps 접근에서 클라우드
운영의 사람 검토을 최소화 - 대부분의 이벤트를 결정론적(T0/T1)으로 해결하고 LLM 추론(T2)은
잔여 모호한 소수에 한정하며, **가드 메트릭을 회귀시키지 않은 채로** 달성합니다. 성공 메트릭을
개선하면서 가드 메트릭을 악화시키는 자율성은 실패이지 승리가 아닙니다.

## 정의(Definitions)

메트릭 전반에서 사용되는 용어를 여기서 고정해 모호성을 없앱니다:

- **Event**: `event-ingest` 이후 컨트롤 루프에 들어가는 정규화·중복제거된 한 항목. 안정적인
  idempotency key로 식별됩니다. 이벤트당(rate) 계산은 모두 이 단위 위에서 이루어집니다.
- **Scenario set**: 베이스라인과 트리트먼트에 동일하게 사용되는 고정·버전된 Resilience, Change
  Safety, Cost Governance 케이스 모음. 각 릴리스는 시나리오 세트 버전을 기록합니다(예: `v2026.07`).
- **Reference agent**: Phase 0에서 측정된 고정 비교 시스템(문서화됨, 단일 모델, 티어링 없음).
  버전은 베이스라인 실행마다 고정됩니다.
- **Human touchpoint**: 사람의 결정 또는 입력이 필요한 모든 액션(HIL 승인, 수동 편집, 수동
  롤백). 콘솔의 읽기 전용 조회는 터치포인트가 **아닙니다**.
- **Auto-resolved event**: 측정 윈도우 내에서 사람 터치포인트 0회, 사후 롤백 없이 종단의
  올바른 결과에 도달한 이벤트.
- **Measurement window**: 실행당 고정된 관측 기간(기본값: 30일 롤링, 또는 전체 시나리오 세트
  1회 리플레이). 보고되는 모든 수치와 함께 명시됩니다.

## 성공 메트릭(Success Metrics)

각 메트릭은 단위, 공식, 보고 윈도우를 고정합니다. 목표는 동일 시나리오 세트 버전에서 레퍼런스
에이전트 대비 상대값이며, 측정 전까지는 방향 목표(directional target)입니다.

| # | 메트릭 | 정확한 정의 | 단위 | 방향 | 베이스라인 대비 목표 |
|---|--------|------------|------|------|---------------------|
| 1 | Cost per unit | 처리된 단위당 귀속 총 지출 ÷ 처리 단위 수. `$/incident`, `$/change`, `$/optimization`로 각각 계산 | USD/unit | 낮을수록 좋음 | 큰 폭 감소 (측정된 경우에만 배수 명시) |
| 2 | Auto-resolution rate | 자동 해결된 이벤트 ÷ 총 이벤트 (`[0, 1]`) | 비율 | 높을수록 좋음 | 베이스라인의 5×(최대 1.0) |
| 3a | MTTR | 해결된 인시던트의 mean(resolve_time − detect_time) | 초 | 낮을수록 좋음 | 5× 짧게(베이스라인의 0.2×) |
| 3b | Change lead time | 변경의 mean(merge_time − change_request_time) | 초 | 낮을수록 좋음 | 5× 짧게(베이스라인의 0.2×) |
| 4 | Human intervention | 사람 터치포인트 ÷ (총 이벤트 ÷ 100) | 100 이벤트당 터치포인트 | 낮을수록 좋음 | 베이스라인의 0.2×(즉 1/5) |

주의:
- 메트릭 1의 비용은 처리에 귀속되는 모델 추론, 컴퓨트, 저장소, 이벤트 버스 지출을 포함합니다.
  AIOpsPilot가 아닌 워크로드와 공유되는 고정 플랫폼 오버헤드는 제외합니다.
- MTTR과 lead time은 mean과 함께 **median과 p90**을 보고합니다. 지연 분포가 편향돼 있어 평균만
  으로는 꼬리(regression)를 감춥니다.
- 비율(metric 2)에서의 `5×` 목표는 상한이 있습니다 - 배수와 절대 비율을 함께 보고합니다.
  베이스라인이 이미 높으면 배수는 의미가 없어지기 때문입니다.

## 가드 메트릭(회귀 금지)

가드 메트릭은 승격을 거부합니다: 위반이 발생하면 액션은 enforce에서 shadow로 강등됩니다. 각
메트릭은 방향이 아니라 명시적 임계값(threshold)을 갖습니다.

| 가드 메트릭 | 정의 | 임계값 |
|-------------|------|--------|
| Change failure rate (CFR) | 인시던트/롤백을 유발한 변경 ÷ 총 변경 | ≤ 베이스라인 CFR(증가 없음) |
| False-positive rate | 잘못된 액션 ÷ 실행된 액션 | ≤ 베이스라인. > 베이스라인 + 1pp면 알림 |
| False-negative rate | 놓친 진짜 이벤트 ÷ 진짜 이벤트 | ≤ 베이스라인. > 베이스라인 + 1pp면 알림 |
| Rollback rate | 롤백된 액션 ÷ 실행된 액션 | ≤ 베이스라인 롤백률 |
| Policy-violation escapes | 정책을 위반하고 enforce에 도달한 자율 액션 | **정확히 0**(모든 escape은 release-blocking) |

임계값은 성공 메트릭과 동일한 측정 윈도우와 시나리오 세트 버전에서 평가되어, 이득과 가드 위반이
다른 데이터에서 비교되지 않습니다.

## 선행 vs 후행 지표(Leading vs Lagging Indicators)

성공 메트릭 1-4는 **후행(lagging)** 입니다(충분한 이벤트가 해결된 후에만 관측 가능). 승격
결정은 가드-메트릭 건강을 더 일찍 예측하는 **선행(leading)** 지표도 함께 봅니다:

- 티어별 커버리지 비율(T0 70-80%, T1 15-20%, T2 5-10%)이 대역을 벗어남,
- mixed-model 불일치율(T2 quality gate)의 상승 추세,
- verifier abstain/fail 비율의 상승,
- 후보 액션의 shadow-vs-enforce 결정 다이버전스(divergence).

선행 지표는 후행 가드 메트릭이 회귀하기 전에 조사를 트리거합니다.

## Measurement-First 규칙

- 자율성은 자신의 효과를 측정할 원격측정(metrics 1-4 + 모든 가드 메트릭) 없이는 출시되지 않습니다.
- Phase 0가 KPI 대시보드와 레퍼런스 베이스라인을 **어떤 티어도 라이브 가기 전에** 확립합니다
  ([phase-0-instrumentation-ko.md](phases/phase-0-instrumentation-ko.md)).
- 배수 주장(2-4)은 베이스라인과 트리트먼트가 **동일한 고정 시나리오 세트 버전에서** 모두
  측정된 후에만 언급됩니다.
- **통계적 타당성**: 각 배수는 표본 크기(이벤트 수), 신뢰구간, 시나리오 세트 버전과 함께
  보고합니다. 신뢰구간 안의 차이는 개선이 아니라 "측정된 변화 없음"으로 보고합니다.
- **공정성**: 베이스라인과 트리트먼트는 동일한 시나리오, 동일한 입력 분포, 동일한 측정
  윈도우에서 실행합니다. 레퍼런스 에이전트를 의도적으로 불리하게 만들지 않습니다.

## 데이터 수집과 원격측정

모든 메트릭은 대시보드가 구축 가능하도록(열망만이 아닌) 구체적인 원격측정 소스에 매핑됩니다:

- **구조화된 이벤트 + 트레이스** (OpenTelemetry)가 `event_id`, `tier`, `decision`,
  `mode`(shadow/enforce), 타임스탬프를 운반 - 메트릭 2, 3a/3b, 선행 지표의 소스.
- **append-only 감사 로그**가 사람 터치포인트(metric 4), 롤백, 정책 escape의 소스.
- **비용/사용 기록**(모델 토큰, 컴퓨트 시간, 저장소, 버스 처리량)이 metric 1의 소스.
  귀속 키는 지출을 발생 `event_id`에 연결합니다.
- 모든 메트릭 입력은 영문, 시크릿 없음, 고객-비종속 - 저장소 범위 규칙 준수.

## 리뷰 주기(Review Cadence)

- **승격마다**: 메트릭 + 가드 리뷰가 통과하지 않으면 shadow → enforce로 이동하는 액션은 없음.
- **주간**: 선행 지표와 가드-메트릭 드리프트 대시보드 리뷰.
- **시나리오 세트 버전 갱신마다**: 목표가 오래된 것이 아닌 현재의 공정한 레퍼런스를 추적하도록
  전체 베이스라인 재측정.

## 목표 배수가 어디서 오는가

아래 메커니즘들은 목표 이득의 **가설(hypothesized)** 출처입니다. 각각은 베이스라인 대비
측정된 후에만 인정됩니다. 프레이밍은 의도적으로 "LLM을 더 잘 쓴다"가 아니라 "LLM을 **덜 쓴다**"
입니다.

| 목표 | 가설된 메커니즘 |
|------|-----------------|
| Auto-resolution ↑ | T0/T1이 이벤트의 ~85-90% 다수를 결정론적으로 종결; T2/HIL로의 escalation 감소. |
| MTTR / lead time ↓ | T0/T1에는 LLM 라운드트립(ms-s)이 없음; auto-remediation PR이 사람 대기 시간을 제거. |
| Human intervention ↓ | 리스크 게이트가 저위험 액션을 자동 승인; 학습된 T1 액션이 반복 사람 터치를 회피. |
| Cost per unit ↓ | 이벤트의 ~5-10%만 프론티어 모델에 도달; OSS/CSP-중립 스택; 이벤트-기반 scale-to-zero. |

> 핵심 통찰: 이득은 더 똑똑한 LLM이 아니라 **LLM을 덜 쓰는** 구조에서 온다는 가설이며 - 이
> 주장은 Phase 0 측정으로 살거나 죽습니다.

## 다음 단계

| 학습 대상 | 문서 |
|-----------|------|
| 베이스라인 계기화 방식 | [phases/phase-0-instrumentation-ko.md](phases/phase-0-instrumentation-ko.md) |
| 티어별 커버리지 목표와 trust router | [../../.github/instructions/architecture.instructions.md](../../.github/instructions/architecture.instructions.md) |
| Guard 메트릭이 강제하는 안전 불변식 | [../../.github/instructions/coding-conventions.instructions.md](../../.github/instructions/coding-conventions.instructions.md) |
| P0와 함께 배송되는 KPI 대시보드 | [../dashboards/phase-0-kpi.json](../dashboards/phase-0-kpi.json) |
