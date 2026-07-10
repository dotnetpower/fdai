---
title: 운영 준비성 리뷰 (dev-to-ops 핸드오프 게이트)
translation_of: operational-readiness.md
translation_source_sha: 2ae1815de00c345e5fab34601a37fa02bcc9d385
translation_revised: 2026-07-11
---
# 운영 준비성 리뷰 (dev-to-ops 핸드오프 게이트)

dev 소유 scope (리소스 그룹, 워크로드, environment) 가 운영팀의 책임이 되기
전에 **운영 준비성 리뷰**(ORR, Operational Readiness Review) 가 자동으로
실행됩니다: scope 전체를 운영팀이 의존하는 governance, security, RBAC,
reliability 규칙에 대해 평가하고, 각 finding 을 그것을 만들어낸 정확한 규칙에
근거로 연결하며, ownership-transfer 이벤트에 연결된 하나의 verdict -
`clear`, `needs_review`, `blocked` - 를 반환합니다. 이것은
[deployment-preflight](deployment-preflight-ko.md) 패스와
[assurance-twin](assurance-twin-ko.md) posture assessment 를 하나의 핸드오프
게이트로 조합한 것으로, dev-to-ops 경계를 넘는 어떤 것도 리뷰되지 않은 채
넘어가지 못하게 합니다.

이것은 per-change 리뷰가 놓치는 실패 부류를 막습니다: 워크로드가 모든 머지에서
개별적으로는 준수하더라도, over-privileged 매니지드 아이덴티티, Owner 를 가진
guest principal, 진단 설정 없음, 백업 없음 상태로 운영팀에 도착할 수 있습니다 -
어떤 단일 변경도 그 gap 전체를 도입하지 않았기 때문입니다. ORR 은 하나의 diff 가
아니라 **핸드오프 시점의 scope 의 누적된 posture** 를 리뷰합니다.

> **고객 무관(Customer-agnostic)**: 트리거 라벨, 필수 규칙 집합, 핸드오프를
> gate 하는 severity 는 모두 config 이거나 fork 가 공급합니다. 업스트림은
> 기계장치와 generic ReadinessReport 형태를 제공하며, 특정 고객의 핸드오프 정책은
> 절대 담지 않습니다
> ([generic-scope.instructions.md](../../.github/instructions/generic-scope.instructions.md)).

> **위치**: ORR 은 assurance twin 위에 구축된 **읽기 전용 리뷰** 입니다. 특권
> 아이덴티티를 보유하지 않으며 아무것도 실행하지 않습니다. 제안된 모든 fix 는
> 여전히 `risk-gate -> executor -> delivery` 를 통과하여
> [app-shape.instructions.md](../../.github/instructions/app-shape.instructions.md)
> 의 읽기 전용 표면 규칙을 보존합니다.

## 왜 별도 게이트인가

조각들은 이미 존재합니다; 빠져 있던 것은 **first-class 마일스톤으로서의
핸드오프** 입니다. 세 표면이 겹치지만, 어느 것도 단독으로는 dev-to-ops 게이트가
아닙니다:

| 기존 표면 | 무엇을 리뷰하는가 | 왜 핸드오프 게이트가 아닌가 |
|-----------|-------------------|-----------------------------|
| [deployment-preflight](deployment-preflight-ko.md) | 하나의 배포: 이 변경이 대상 scope 에 착지할 수 있는가 | 단일 `terraform apply` / remediation PR 로 한정, 누적 posture 아님 |
| [assurance-twin](assurance-twin-ko.md) 선제 리뷰 | 하나의 변경 이벤트: 이 diff 가 규칙을 위반하는가 | per-diff; scope 가 모든 diff 를 통과하고도 전체로는 실패 가능 |
| [assurance-twin](assurance-twin-ko.md) `PostureAssessmentReport` | 온디맨드로 estate 전체 | ownership-transfer 이벤트에 묶이지 않음; 운영 인수 전에 실행이 강제되지 않음 |

ORR 은 전체 scope assessment 를 ownership-transfer 이벤트에 묶고, 그것을 필수,
감사됨, shadow-first 게이트로 만듭니다.

## 루프에서의 위치

ORR 은 폴링되지 않고 트리거됩니다. scope 가 핸드오프로 제안되면
`ownership_transfer` signal 이 `event-ingest` 에 진입하여 다른 이벤트처럼
정규화되고 하나의 리뷰 패스를 구동합니다:

```text
ownership_transfer signal
  -> event-ingest (normalize)
  -> assurance-twin: run every applicable rule over the scope projection
  -> deploy-preflight: run the feasibility probes over the scope
  -> compose -> ReadinessReport (clear | needs_review | blocked)
  -> blocked + enforce mode -> gate the handoff, route fixes to risk-gate/HIL
  -> audit (Saga)
```

두 입력 모두 **deterministic-first**(T0 성격) 입니다: twin projection 에 대한
정적 평가가 대부분의 finding 을 해결하고, 제한된 읽기 전용 프로브가 나머지를
확인합니다. 이 패스의 어떤 것도 아무것도 mutate 하지 않습니다.

## 트리거

`ownership_transfer` signal 은 리뷰를 시작하는 CSP-neutral 이벤트입니다. fork 가
핸드오프 순간으로 연결한 무엇이든지에 의해 emit 됩니다:

- IaC repo 의 pull-request 라벨(`ops-handoff-requested`), 또는
- scope 에 적용된 리소스 태그(`lifecycle-stage: handoff`), 또는
- 콘솔을 통한 명시적 operator 요청(`request_ops_handoff`).

signal 은 대상 scope (resource-group 등가 또는 그보다 좁게,
[rule-governance](rule-governance-ko.md) override 가 사용하는 동일한 scope
계층), submitter 아이덴티티, 대상 environment 를 실습니다. 절대 role 이나 특권
토큰을 싣지 않습니다.

## 리뷰 차원

ORR 은 scope 전체에 대해 적용 가능한 규칙 집합을 실행하지만, 네 개 차원이
운영팀이 가장 의존하고 per-change 리뷰가 가장 자주 놓치는 것입니다:

| 차원 | 대표 체크 | 출처 |
|------|-----------|------|
| `policy_guardrail` | 허용되지 않은 리소스 타입, 공개 액세스, 암호화 누락 | [rule-catalog-collection.md](rule-catalog-collection-ko.md) |
| `identity_rbac` | over-privileged 워크로드 아이덴티티, Owner 를 가진 guest, standing 특권 액세스, wildcard-action role, 한도 초과 Owner 수 | 워크로드 RBAC 최소권한 규칙 팩(`managed-identity.role-assignment.*`, `subscription.role-assignment.*`, `resource-group.role-assignment.*`) |
| `reliability` | 백업 / PITR 없음, 진단 설정 없음, 존 이중화 없음 | 카탈로그 reliability 규칙 |
| `dependency_ordering` | 핸드오프 전 필수 링크(private endpoint, NSG, 진단 설정) 존재 | [deployment-preflight](deployment-preflight-ko.md) 프로브 |

`identity_rbac` 차원은 preflight 도 per-change 리뷰도 이전에 커버하지 않던, ORR 이
추가하는 것입니다: preflight 의 `identity_rbac` 프로브는 배포할 **executor 의**
권한을 체크하는 반면, ORR 은 authored RBAC 규칙을 사용해 **워크로드 자신의**
최소권한 posture 를 체크합니다.
[architecture.instructions.md § Rule Catalog](../../.github/instructions/architecture.instructions.md#rule-catalog)
참조.

## ReadinessReport

패스는 finding 을 `ReadinessReport` 로 조립합니다 - ownership-transfer 이벤트에
묶인 `PostureAssessmentReport`([assurance-twin.md](assurance-twin-ko.md)) 의
일반화입니다. 각 finding 은 동일한 세 필수 부분을 유지합니다:

- **evidence** - 그것을 만들어낸 규칙의 CSP-neutral 인용. 출처를 인용할 수 없는
  finding 은 defect 이며, T2 verifier 와 preflight 프로브가 따르는 동일한
  규칙입니다.
- **severity** - `blocking`(enforce 모드 핸드오프를 gate) 또는
  `warning`(표면화하지만 절대 gate 하지 않음).
- **resolution** - 그것을 해소하는 방법으로, 구체적 remediation ActionType (RBAC
  차원의 경우 `remediate.right-size-role`) 또는 autofix 가 없을 때는 가이던스에
  매핑됩니다.

### Verdict 의미

| Verdict | 의미 |
|---------|------|
| `clear` | finding 없음 |
| `needs_review` | finding 은 있지만 blocking 은 없음(warning 만) |
| `blocked` | 최소 하나의 blocking finding |

리포트는 항상 **진실된(truthful)** verdict 를 기록합니다. 그 verdict 가 핸드오프를
*gate 하는지* 는 별도 플래그 `blocks_handoff` 이며, ORR 이 `enforce` 모드로
실행되었을 때만 true 입니다 - [deployment-preflight](deployment-preflight-ko.md)
의 `blocks_deploy` 플래그가 사용하는 동일한 truthful-verdict / 별도-gate 분리입니다.

### Shadow-first

모든 ORR 은 **shadow 모드** 로 ship 됩니다: blocker 를 진실되게 보고하지만
`blocks_handoff` 는 `false` 로 유지되므로, 검증되지 않은 리뷰가 false positive 로
실제 핸드오프를 잘못 멈추게 할 수 없습니다. `enforce` 로의 promotion 은
environment 별이며 frozen scenario set 에서 측정된 false-positive rate 로
gate 됩니다 - [ActionType 계약](llm-strategy-ko.md) 과 preflight 프로브가 적용하는
동일한 promotion 규율입니다.

## Action bridging

`blocked` ORR 은 단지 문제를 나열하는 데 그치지 않습니다. autofix 가 있는 각
finding 은 규칙의 remediation ActionType 으로 구축된 **shadow remediation-PR
제안** 을 실으며, assurance twin 과 정확히 동일합니다. 아이덴티티 차원의 경우
그것은 over-broad grant 를 최소권한으로 좁히는 `remediate.right-size-role` 이며,
RBAC 변경은 `resource_group` blast radius 와 `AsymmetricRollback` 을 지니므로
[risk-classification.md](risk-classification-ko.md) 를 통해 HIL 로 라우팅되고 절대
auto-execute 되지 않습니다. ORR 은 제안하고, 사람이 승인하며, executor 가
적용합니다. 콘솔과 ChatOps 는 읽기 전용 표면으로 유지됩니다.

## Environment promotion

ORR 은 environment promotion(dev -> staging -> prod) 의 강제 지점입니다.
`ownership_transfer` signal 은 대상 environment 를 싣고, 게이트는 그것과 함께
조여집니다: `prod` 로의 promotion 은 프로파일 기본값과 무관하게 어떤 `critical`
finding 도 blocking 으로 취급하며, 모든 mutating ActionType 이 이미 선언하는
prod-downgrade posture 를 재사용합니다
([risk-classification.md](risk-classification-ko.md)). environment 분류기와 그것이
consume 하는 promotion 순서는
[risk-classification.md § Environment Promotion](risk-classification-ko.md#환경-승격environment-promotion-핸드오프-대상)
에 명세됩니다; ORR 은 그것을 consume 하며, 정의하지 않습니다.

## 모듈 배치

ORR 은 새로운 특권 표면을 도입하지 않고 최소한의 새 코드만 도입합니다: 기존
`core/assurance_twin/` 과 `core/deploy_preflight/` 서브시스템을 조합하고 얇은
coordinator 와 하나의 정규화된 signal 을 추가합니다.

| 컴포넌트 | 책임 |
|----------|------|
| `ownership_transfer` signal | 리뷰를 트리거하는 정규화된 이벤트(scope + submitter + 대상 environment); fork 가 연결한 핸드오프 순간에 emit |
| `core/assurance_twin/report` | scope projection 에 대해 적용 가능한 모든 규칙 실행 (재사용) |
| `core/deploy_preflight` | scope 에 대해 feasibility 프로브 실행 (재사용) |
| ORR coordinator | 둘을 `ReadinessReport` 로 조합, environment 게이트 적용, `blocks_handoff` 설정 |
| delivery intent | 리포트를 Checks API annotation / 콘솔 `ReadPanel` 로 게시; shadow remediation-PR 제안 첨부 |

coordinator 는 다른 모든 core 서브시스템처럼 `shared/` 계약과 provider 만
import 합니다([project-structure.md](project-structure-ko.md#module-boundaries)).
클라우드 SDK 도, 특권 아이덴티티도 보유하지 않습니다.

## 안전 posture

- **읽기 전용 리뷰, gate 된 실행**: ORR 과 모든 finding 은 읽기 전용입니다;
  mutation 으로의 유일한 경로는 `risk-gate -> executor` 에 진입하는 제안이며, 네
  가지 안전 불변식(stop-condition, rollback, blast-radius 한도, audit entry) 이
  거기서 강제됩니다.
- **승인과 실행은 구별 유지**: 핸드오프는 submitter 가 요청하고 구별된
  principal(Var) 이 승인하며, 절대 self-approve 되지 않습니다 - 컨트롤 플레인의
  나머지가 지키는 동일한 no-self-approval 규칙입니다.
- **Fail closed**: stale twin (inventory 신선도가 `freshness_ttl` 초과) 은 stale
  상태로 certify 하기보다 핸드오프 certify 를 거부합니다; ungroundable finding 은
  abstain 하고; 검증되지 않은 리뷰는 shadow 로 유지됩니다.
- **감사됨**: 모든 ORR verdict, 그 `blocks_handoff` 플래그, submitter, approver,
  대상 scope 는 Saga 를 통한 append-only audit entry 입니다.

## Next steps

| 학습 주제 | 읽기 |
|-----------|------|
| ORR 이 조합하는 전체 그래프 리뷰 | [assurance-twin.md](assurance-twin-ko.md) |
| 재사용하는 단일 배포 feasibility 패스 | [deployment-preflight.md](deployment-preflight-ko.md) |
| 아이덴티티 차원이 발동하는 RBAC 최소권한 규칙 | [rule-catalog-collection.md](rule-catalog-collection-ko.md) |
| 게이트를 실행하는 cross-agent 워크플로우 | [agent-workflows.md § 11](agent-workflows-ko.md#11-operational-readiness-handoff) |
| 게이트가 consume 하는 environment 모델 | [risk-classification.md § Environment Promotion](risk-classification-ko.md#환경-승격environment-promotion-핸드오프-대상) |
| 제안된 각 fix 가 resolve 하는 risk classification | [risk-classification.md](risk-classification-ko.md) |
