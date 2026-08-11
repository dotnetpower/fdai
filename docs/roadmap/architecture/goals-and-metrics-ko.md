---
title: 목표와 메트릭
translation_of: goals-and-metrics.md
translation_source_sha: 28fc74aa7c0414e08d1a81e8e8ba55f509ebb209
translation_revised: 2026-08-11
---

# 목표와 메트릭

로드맵은 **증명이 있는 자율성(자율성 with 증명)**을 최적화합니다. 모든 자율성 주장은
측정된 베이스라인으로 뒷받침되며, 어떤 것도 추정으로 단언되지 않습니다. 아래의 개선 배수
(`5×`, `large reduction`, `1/5`)는 달성된 결과가 아니라 **목표(targets)** 이며 - 동일한
시나리오 세트에서 레퍼런스 베이스라인과 FDAI 트리트먼트가 **모두 측정된 후에만**
달성으로 언급할 수 있습니다 ([Measurement-First Rule](#measurement-first-rule) 참조).

이 문서는 KPI의 진실 원본(정본)입니다.
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md)의
티어 커버리지 목표와 정합하며
[phase-0-instrumentation-ko.md](../phases/phase-0-instrumentation-ko.md) 에서 운영으로
구현됩니다.

## 주요 목표(기본 Objective)

3개 초기 버티컬(복원력, 변경 안전성, 비용 거버넌스)을 가진 AIOps 접근에서 클라우드
운영의 사람 검토를 최소화 - 대부분의 이벤트를 결정론적(T0/T1)으로 해결하고 LLM 추론(T2)은
잔여 모호한 소수에 한정하며, **가드 메트릭을 회귀시키지 않은 채로** 달성합니다. 성공 메트릭을
개선하면서 가드 메트릭을 악화시키는 자율성은 실패이지 승리가 아닙니다.

SRE는 세 버티컬 전체의 운영 모델입니다. 재해 복구와 Chaos Engineering은 복원력
기능이고, 아키텍처 검토 Board 거버넌스는 도메인 전체에 적용되며, FinOps는 비용
거버넌스 규율입니다.

### 정확성 계약

FDAI는 모든 새로운 진단이 맞는다고 주장하지 않습니다. 목표는 **100% contract-conformant
행동**입니다. 에이전트는 schema-valid, evidence-supported, authorized 결과를 만들거나
명시적인 알 수 없음, no-op, denial, 롤백 또는 사람 검토 결과를 기록합니다. 강제 답변이
아니라 unsafe guess 0건이 플랫폼 목표입니다.

다음 위반의 release 임계값은 정확히 0입니다.

- 잘못된 객체 신원 또는 stale 대상 개정 번호를 대상으로 한 액션
- 등록된 ActionType, standing 권한 또는 영향 범위 밖의 실행
- 독립적인 효과 검증 없이 브로커/API 증적으로 성공을 주장하는 경우
- 권위 있는 관측이 아닌 온톨로지 쓰기로 외부 상태를 주장하는 경우
- 검토와 승격 근거 없이 권한을 높이는 learning 출력

### 사람 검토 전 자율 처리

해결되지 않은 이벤트를 즉시 사람 작업으로 만들지 않습니다. 범위가 제한된 기한 안에서 fresh 근거
acquisition, alternate 권위 있는 출처, 결정론적 reevaluation, 검증된 pattern reuse,
더 작은 safe 계획, no-op 또는 pre-authorized 복구를 시도합니다. 모호함이 남거나 정책이
승인을 요구하거나 risk가 standing 권한을 넘을 때만 사람 검토를 시작합니다. 모든 시도는
이벤트 상관관계를 공유하고 추가 human touchpoint를 만들지 않습니다.

## 정의(Definitions)

메트릭 전반에서 사용되는 용어를 여기서 고정해 모호성을 없앱니다:

- **Event**: `event-ingest` 이후 컨트롤 루프에 들어가는 정규화·중복제거된 한 항목. 안정적인
 멱등성 키로 식별됩니다. 이벤트당(비율) 계산은 모두 이 단위 위에서 이루어집니다.
- **시나리오 집합**: SRE, ARB / 변경 안전성, FinOps / 비용 거버넌스, DR 및 Chaos Engineering
 기능 pack을 포괄하며 기준선과 treatment에 동일하게 사용하는 고정된, versioned
 수집입니다. 각 release는 시나리오 집합 및 pack별 버전을 기록합니다(예: `v2026.07`).

> **현재 커버리지 공백:** `services/core-control-plane/tests/scenarios/manifests/v2026.07.json`은 모든 고정본을 SRE, ARB /
> 변경 안전성, FinOps, DR 또는 Chaos에 할당합니다. 커버리지 dimension은 해당 pack이 소유한
> 시나리오와 실제 실행 가능한 테스트를 함께 인용할 때만 계산됩니다. 집합은 `incomplete`입니다.
> SRE 시나리오가 없고 모든 기존 pack이 하나 이상의 필수 사례를 누락합니다. 다섯 pack이 모두
> 완전한일 때까지 완전한 domain 커버리지를 주장하면 안 됩니다.
- **참조 에이전트**: Phase 0에서 측정된 고정 비교 시스템(문서화됨, 단일 모델, 티어링 없음).
 버전은 베이스라인 실행마다 고정됩니다.
- **Human touchpoint**: 사람의 결정 또는 입력이 필요한 모든 액션(HIL 승인, 수동 편집, 수동
 롤백). 고유하게 식별된 액션 또는 승인은 각각 한 번 계산하며, 같은 액션 또는 승인의
 반복 수명 주기 행은 touchpoint를 추가하지 않습니다. 하나의 이벤트가 둘 이상의 touchpoint를
 제공할 수 있습니다. 콘솔의 읽기 전용 조회는 touchpoint가 **아닙니다**.
- **Auto-resolved 이벤트**: 측정 윈도우 내에서 사람 터치포인트 0회, 사후 롤백 없이 종단의
 올바른 결과에 도달한 이벤트. 실행기 전달은 명시적인 `measurement.action_outcome.v1`
 기록이 enforce 모드, 검증 통과, auto 결정 및 롤백 없음으로 관측을 닫을
 때까지 resolved가 아니라 pending입니다.
- **측정 구간**: 실행당 고정된 관측 기간(기본값: 30일 롤링, 또는 전체 시나리오 세트
 1회 리플레이). 보고되는 모든 수치와 함께 명시됩니다.
- **Contract-conformant 결과**: 대상, 근거, 권한, 액션, 효과 검증, 감사
 기록이 exact versioned 계약을 충족하는 최종 결과입니다. 명시적 알 수 없음 또는 safe
 no-op은 conformant하지만 지원하지 않는 성공은 아닙니다.

## 성공 메트릭(성공 Metrics)

각 메트릭은 단위, 공식, 보고 윈도우를 고정합니다. 목표는 동일 시나리오 세트 버전에서 레퍼런스
에이전트 대비 상대값이며, 측정 전까지는 방향 목표(directional 대상)입니다.

| # | 메트릭 | 정확한 정의 | 단위 | 방향 | 베이스라인 대비 목표 |
|---|--------|------------|------|------|---------------------|
| 1 | 비용 per 단위 | 처리된 단위당 귀속 총 지출 ÷ 처리 단위 수. `$/incident`, `$/change`, `$/optimization`로 각각 계산 | USD/단위 | 낮을수록 좋음 | 큰 폭 감소 (측정된 경우에만 배수 명시) |
| 2 | Auto-resolution 비율 | 자동 해결된 이벤트 ÷ 총 이벤트 (`[0, 1]`) | 비율 | 높을수록 좋음 | 베이스라인의 5×(최대 1.0) |
| 3a | MTTR | 해결된 인시던트의 mean(resolve_time − detect_time) | 초 | 낮을수록 좋음 | 5× 짧게(베이스라인의 0.2×) |
| 3b | 변경 lead 시간 | 변경의 mean(merge_time − change_request_time) | 초 | 낮을수록 좋음 | 5× 짧게(베이스라인의 0.2×) |
| 4 | Human intervention | 사람 터치포인트 ÷ (총 이벤트 ÷ 100) | 100 이벤트당 터치포인트 | 낮을수록 좋음 | 베이스라인의 0.2×(즉 1/5) |

주의:
- 메트릭 1의 비용은 처리에 귀속되는 모델 추론, 컴퓨트, 저장소, 이벤트 버스 지출을 포함합니다.
 FDAI가 아닌 워크로드와 공유되는 고정 플랫폼 오버헤드는 제외합니다.
- MTTR과 lead 시간은 mean과 함께 **median과 p90**을 보고합니다. 지연 분포가 편향돼 있어 평균만
 으로는 꼬리(회귀)를 감춥니다.
- 비율(메트릭 2)에서의 `5×` 목표는 상한이 있습니다 - 배수와 절대 비율을 함께 보고합니다.
 베이스라인이 이미 높으면 배수는 의미가 없어지기 때문입니다.

## 가드 메트릭(회귀 금지)

가드 메트릭은 승격을 거부합니다: 위반이 발생하면 액션은 enforce에서 그림자로 강등됩니다. 각
메트릭은 방향이 아니라 명시적 임계값(임계값)을 갖습니다.

| 가드 메트릭 | 정의 | 임계값 |
|-------------|------|--------|
| 변경 실패 비율 (CFR) | 인시던트/롤백을 유발한 변경 ÷ 총 변경 | ≤ 베이스라인 CFR(증가 없음) |
| False-positive 비율 | 잘못된 액션 ÷ 실행된 액션 | ≤ 베이스라인. > 베이스라인 + 1pp면 알림 |
| False-negative 비율 | 놓친 진짜 이벤트 ÷ 진짜 이벤트 | ≤ 베이스라인. > 베이스라인 + 1pp면 알림 |
| Rollback 비율 | 롤백된 액션 ÷ 실행된 액션 | ≤ 베이스라인 롤백률 |
| Policy-violation escapes | 정책을 위반하고 enforce에 도달한 자율 액션 | **정확히 0**(모든 escape은 release-blocking) |
| Wrong-target 또는 stale-revision 실행 | 승인 계획과 다른 객체 또는 개정 번호에 적용된 액션 | **정확히 0** |
| 승인되지 않은 실행 | 등록 타입, 신원, standing 권한 또는 영향 범위 밖의 액션 | **정확히 0** |
| 검증되지 않은 성공 점유 | 독립적인 expected-effect 종결 없이 성공으로 보고된 액션 | **정확히 0** |

임계값은 성공 메트릭과 동일한 측정 윈도우와 시나리오 세트 버전에서 평가되어, 이득과 가드 위반이
다른 데이터에서 비교되지 않습니다.

## 선행 vs 후행 지표(Leading vs Lagging Indicators)

성공 메트릭 1-4는 **후행(lagging)** 입니다(충분한 이벤트가 해결된 후에만 관측 가능). 승격
결정은 가드-메트릭 건강을 더 일찍 예측하는 **선행(leading)** 지표도 함께 봅니다:

- 티어별 커버리지 비율(T0 70-80%, T1 15-20%, T2 5-10%)이 대역을 벗어남,
- mixed-model 불일치율(T2 quality 게이트)의 상승 추세,
- 검증기 abstain/fail 비율의 상승,
- 후보 액션의 shadow-vs-enforce 결정 다이버전스(divergence).

선행 지표는 후행 가드 메트릭이 회귀하기 전에 조사를 트리거합니다.

## Measurement-First 규칙

- 자율성은 자신의 효과를 측정할 원격측정(metrics 1-4 + 모든 가드 메트릭) 없이는 출시되지 않습니다.
- Phase 0가 KPI 대시보드와 레퍼런스 베이스라인을 **어떤 티어도 라이브 가기 전에** 확립합니다
 ([phase-0-instrumentation-ko.md](../phases/phase-0-instrumentation-ko.md)).
- 배수 주장(2-4)은 베이스라인과 트리트먼트가 **동일한 고정 시나리오 세트 버전에서** 모두
 측정된 후에만 언급됩니다.
- **통계적 타당성**: 각 배수는 표본 크기(이벤트 수), 신뢰구간, 시나리오 세트 버전과 함께
 보고합니다. 신뢰구간 안의 차이는 개선이 아니라 "측정된 변화 없음"으로 보고합니다. Zero-sample
 Wilson 간격은 accuracy가 정확히 0이라는 근거가 아니라 `[0, 1]` 알 수 없음입니다.
- **Operational 승격 근거**: 고정된 벤치마크와 live-shadow 샘플을 하나의 full FDAI
 개정 번호, ActionType 다이제스트, 시나리오 사례, 권위 있는 측정 단위에 연결하고 최신
 correction이 집단, 시나리오, 관측 시간, causal 계보를 바꾸지 않고 이전 행을
 대체합니다. Separate 고정된/실제 운영 Wilson 95% lower 한계, 서로 다른 실제 운영 일, zero escape,
 executed-action 롤백과 완전한 recurrence 구간, 검증된 causal 증적, Dynamic 검토가
 모두 통과해야 합니다. Closed causal 증적은 confirmed 종결일 때만 계산합니다. Raw 메트릭은
 promote할 수 없고 검증된 증적은 별도 검토만 허용합니다.
- **공정성**: 베이스라인과 트리트먼트는 동일한 시나리오, 동일한 입력 분포, 동일한 측정
 윈도우에서 실행합니다. 레퍼런스 에이전트를 의도적으로 불리하게 만들지 않습니다.

## 데이터 수집과 원격측정

모든 메트릭은 대시보드가 구축 가능하도록(열망만이 아닌) 구체적인 원격측정 소스에 매핑됩니다:

- **구조화된 이벤트 + 트레이스** (OpenTelemetry)가 `event_id`, `tier`, `decision`,
 `mode`(그림자/enforce), 타임스탬프를 운반 - 메트릭 2, 3a/3b, 선행 지표의 소스.
- **추가 전용 감사 로그**가 사람 터치포인트(메트릭 4), 롤백, 정책 escape의 소스.
- **결과 finalization 기록**(`measurement.action_outcome.v1`)가 auto-resolution의 권한입니다.
 Dispatch-only 이벤트는 pending으로 유지되고, 검증된 non-rollback 결과만 finalized denominator에
 들어가며, 롤백/adverse 결과는 성공이 되지 않고 계속 표시됩니다. 하나의 액션에
 correction finalization 행이 있으면 가장 높은 감사 순서만 권위 있는하며, 명시적
 검증 실패는 사라지지 않고 rejected 관측으로 유지됩니다.
- **명시적 메트릭 관측값**은 각 `event_id` 및 메트릭 키의 최신 행을 사용합니다. 하나의 이벤트에
 대한 재시도 또는 correction은 통계 가중치를 추가하지 않고 이전 값을 대체하며, 서로 다른 이벤트의
 관측값은 독립 표본으로 유지합니다.
- **MTTR(메트릭 3a)** 은 순수 집계기
 [`core/measurement/mttr.py`](../../../services/core-control-plane/src/fdai/core/measurement/mttr.py) 가 계산합니다. 해결된
 인시던트(`resolved_at - opened_at`)를 **mean, median, p90** 초로 접습니다. 미해결/무결성
 위반 인시던트는 카운트하되 계산에서 제외하며, 절대 `0` 이나 음수 소요 시간을 기여하지 않습니다.
 라이브 인시던트를 공급해 `/kpi/autonomy` 패널의 synthetic 데모값을 대체하는 전달 레이어
 배선은 후속 작업으로 추적합니다.
- **비용/사용 기록**(모델 토큰, 컴퓨트 시간, 저장소, 버스 처리량)이 메트릭 1의 소스.
 귀속 키는 지출을 발생 `event_id`에 연결합니다. 하나의 액션에 반복된 수명 주기 행이 있으면
 재시도를 가중하거나 합산하지 않고 최신 관측 절감 값을 한 번만 반영합니다.
- 모든 메트릭 입력은 영문, 시크릿 없음, 고객-비종속 - 저장소 범위 규칙 준수.

## 리뷰 주기(검토 Cadence)

- **승격마다**: 메트릭 + 가드 리뷰가 통과하지 않으면 그림자 → enforce로 이동하는 액션은 없음.
- **주간**: 선행 지표와 가드-메트릭 드리프트 대시보드 리뷰.
- **시나리오 세트 버전 갱신마다**: 목표가 오래된 것이 아닌 현재의 공정한 레퍼런스를 추적하도록
 전체 베이스라인 재측정.

## 목표 배수가 어디서 오는가

아래 메커니즘들은 목표 이득의 **가설(hypothesized)** 출처입니다. 각각은 베이스라인 대비
측정된 후에만 인정됩니다. 프레이밍은 의도적으로 "LLM을 더 잘 쓴다"가 아니라 "LLM을 **덜 쓴다**"
입니다.

| 목표 | 가설된 메커니즘 |
|------|-----------------|
| Auto-resolution ↑ | T0/T1이 이벤트의 ~85-90% 다수를 결정론적으로 종결; T2/HIL로의 에스컬레이션 감소. |
| MTTR / lead 시간 ↓ | T0/T1에는 LLM 라운드트립(ms-s)이 없음; auto-remediation PR이 사람 대기 시간을 제거. |
| Human intervention ↓ | 리스크 게이트가 저위험 액션을 자동 승인; 학습된 T1 액션이 반복 사람 터치를 회피. |
| 비용 per 단위 ↓ | 이벤트의 ~5-10%만 프론티어 모델에 도달; OSS/CSP-중립 스택; 이벤트-기반 scale-to-zero. |

> 핵심 통찰: 이득은 더 똑똑한 LLM이 아니라 **LLM을 덜 쓰는** 구조에서 온다는 가설이며 - 이
> 주장은 Phase 0 측정으로 살거나 죽습니다.

## 다음 단계

| 학습 대상 | 문서 |
|-----------|------|
| 베이스라인 계기화 방식 | [phases/phase-0-instrumentation-ko.md](../phases/phase-0-instrumentation-ko.md) |
| 티어별 커버리지 목표와 trust 라우터 | [../../.github/instructions/architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) |
| 가드 메트릭이 강제하는 안전 불변식 | [../../.github/instructions/coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md) |
| P0와 함께 배송되는 KPI 대시보드 | [../dashboards/phase-0-kpi.json](../../dashboards/phase-0-kpi.json) |
