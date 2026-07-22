---
title: 용량과 성능
description: FDAI가 측정된 수요와 예측을 범위가 제한된 용량 문제와 통제된 확장 제안으로 바꾸는 방법입니다.
translation_of: capacity-and-performance.md
translation_source_sha: 8c971692b24b6c29efedbfb3dcab34101307c1ba
translation_revised: 2026-07-22
---

# 용량과 성능

용량 관리는 resource가 비용을 낭비하거나 dependency를 고갈시키지 않고 측정된 demand를
충족할 수 있는지 판단합니다. FDAI는 scaling action을 제안하기 전에 현재 utilization,
forecast evidence, minimum floor, dependency check, promotion state를 결합합니다.

## 용량 증거

- Resource 및 window별 현재 utilization과 saturation.
- Demand trend, forecast horizon, uncertainty, expected breach time.
- Minimum 및 maximum capacity와 warm-capacity floor.
- Quota, regional availability, dependent-resource constraint.
- Workload SLO 및 error-budget impact.
- Cost estimate와 rollback 또는 scale-back path.

Telemetry가 없거나 오래되면 unavailable 또는 판단 보류 evidence가 됩니다. Demand가 0이라고
가정하지 않습니다.

## Specialist 충돌 판단

Freyr는 capacity를 평가하고 Njord는 cost를 평가합니다. Reliability를 위해 scale up하고
efficiency를 위해 scale down하는 것처럼 advice가 충돌할 수 있습니다. Specialist는 advisory
역할을 유지하며 Forseti와 안전성 검토가 설정된 precedence와 autonomy ceiling을 적용합니다.

Advice가 충돌하면 Forseti가 cross-vertical arbitration request를 생성합니다. Odin은
rule catalog의 버전 관리되는 priority policy를 적용하고, Forseti가 결정을 만들기 전에
재현 가능한 arbitration result 하나를 반환합니다. 기본 policy는 cost 및 architecture
advice보다 SLO 보호를 우선하지만 배포 환경에서 agent code를 변경하지 않고 검토된 policy를
제공할 수 있습니다. Arbitration result는 증거이며 안전성 검토 ceiling을 완화할 수 없습니다.

예시: 낮은 utilization은 scale-down을 제안하지만 SLO forecast는 임박한 capacity breach를
표시 -> 설정된 priority policy가 SLO floor를 유지 -> what-if가 quota와 dependency를 계속
검사 -> 안전성 검토가 shadow, approval, promoted execution 중 하나를 결정.

## Scaling proposal 흐름

1. Detector 또는 scheduled evaluation이 capacity 발견된 문제를 생성합니다.
2. 발견된 문제를 workload SLO, current change, incident와 연계합니다.
3. What-if가 quota, dependency, floor, expected effect를 검증합니다.
4. Typed scale proposal이 scope, batch, rate, stop condition, rollback을 포함합니다.
5. Shadow evidence와 promotion state가 approval 또는 promoted auto 경로 도달 여부를 정합니다.

## 보호 장치

선언된 safety floor 아래로 scale하거나 dependency를 고립시키거나 quota를 초과하지 않습니다.
Forecast를 실행 권한으로 취급하지 않습니다. Per-resource lock과 bounded batch change가 서로
경쟁하는 scale action의 race를 방지합니다.

| Runtime 검사 | 통과 시 | 실패 또는 unknown 시 |
|--------------|---------|----------------------|
| Demand 및 SLO evidence가 fresh | What-if로 진행 | Unavailable evidence로 보류 |
| Quota 및 dependency 검사 통과 | Typed proposal 생성 | Proposal 생성 안 함 |
| Floor, batch, rate limit 충족 | 안전성 검토로 진행 | Deny 또는 scope 축소 |
| Lock 및 idempotency claim 성공 | 최대 한 번 적용 | 안전하게 retry 또는 no-op |
| Stop condition이 정상 유지 | 제한된 batch 계속 | 중지 후 rollback policy 적용 |

## 다음 단계

| 학습 대상 | 문서 |
|-----------|------|
| Forecast가 만들어지는 방법 | [관측성, 감지, 예측](observability-detection-and-forecasting-ko.md) |
| Workload impact를 측정하는 방법 | [SLO와 오류 예산](slos-and-error-budgets-ko.md) |
| Cost와 capacity가 상호 작용하는 방법 | [비용 거버넌스](../capabilities/cost-governance-ko.md) |
| Action을 승격하는 방법 | [Shadow 후 enforce](../concepts/shadow-then-enforce-ko.md) |
