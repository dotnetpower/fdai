---
title: 운영 준비성 리뷰 (dev-to-ops 핸드오프 게이트)
translation_of: operational-readiness.md
translation_source_sha: 62f3c05e0a06f2f493fa35b30429ed913baf7b67
translation_revised: 2026-10-22
---
# 운영 준비 상태 검토 (dev-to-ops 인계 게이트)

개발팀이 담당하는 범위(리소스 그룹, 워크로드, 환경)를 운영팀에 넘기기 전에 자동화된
**운영 준비 상태 검토**(Operational Readiness Review, ORR)를 사용하세요. ORR은 운영팀에
필요한 거버넌스, 보안, RBAC, 안정성 규칙을 기준으로 전체 범위를 평가하고, 각 발견 사항을
해당 결과의 근거가 된 정확한 규칙과 연결합니다. 그런 다음 소유권 이전
(ownership-transfer) 이벤트에 연결된 단일 판정인 `clear`, `needs_review`, `blocked` 중
하나를 반환합니다. ORR은 [deployment-preflight](../deployment/deployment-preflight-ko.md)
검사와 [assurance-twin](assurance-twin-ko.md)의 상태 평가를 하나의 인계 게이트로 결합하여,
검토되지 않은 범위가 개발팀에서 운영팀으로 넘어가지 않도록 합니다.

ORR은 개별 변경 검토에서 놓칠 수 있는 문제를 해결합니다. 워크로드가 병합될 때마다 개별적으로 모든 규칙을 준수하더라도, 운영팀에 인계되는 시점에는 과도한 권한이 부여된 관리 ID, Owner 역할을 보유한 게스트 보안 주체, 진단 설정 누락 또는 백업 누락과 같은 문제가 남아 있을 수 있습니다. 이러한 문제는 특정 변경 하나에서 모두 발생한 것이 아니기 때문입니다. ORR은 개별 변경 사항이 아니라 **인계 시점에 해당 범위에 누적된 전체 상태**를 검토합니다.

> **고객 독립적(Customer-agnostic)**: 트리거 레이블, 필수 규칙 집합, 인계 허용 여부를 결정하는 심각도 기준은 모두 구성 또는 포크에서 제공됩니다. 업스트림은 실행 메커니즘과 범용 ReadinessReport 형식만 제공하며, 특정 고객의 인계 정책은 포함하지 않습니다
> ([generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)).

> **아키텍처상 위치**: ORR은 assurance twin을 기반으로 하는 **읽기 전용 검토**입니다. 높은 권한을 가진 ID를 보유하지 않으며 어떤 작업도 실행하지 않습니다. 제안된 모든 수정 사항은 여전히 `risk-gate -> executor -> delivery`를 거치므로
> [app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md)에 정의된 읽기 전용 인터페이스 규칙을 유지합니다.

## 별도의 게이트가 필요한 이유

필요한 구성 요소는 이미 존재합니다. 부족했던 것은 **인계 자체를 독립적인 주요 단계로 다루는 기능**입니다. 다음 세 기능은 서로 겹치는 부분이 있지만, 어느 것도 단독으로 개발팀에서 운영팀으로의 인계를 관리하는 게이트 역할을 하지 않습니다.

| 기존 표면 | 무엇을 리뷰하는가 | 왜 핸드오프 게이트가 아닌가 |
|-----------|-------------------|-----------------------------|
| [deployment-preflight](../deployment/deployment-preflight-ko.md) | 하나의 배포: 이 변경이 대상 범위 에 착지할 수 있는가 | 단일 `terraform apply` / 교정 PR 로 한정, 누적 자세 아님 |
| [assurance-twin](assurance-twin-ko.md) 선제 리뷰 | 하나의 변경 이벤트: 이 차이 가 규칙을 위반하는가 | per-diff; 범위 가 모든 차이 를 통과하고도 전체로는 실패 가능 |
| [assurance-twin](assurance-twin-ko.md) `PostureAssessmentReport` | 온디맨드로 estate 전체 | ownership-transfer 이벤트에 묶이지 않음; 운영 인수 전에 실행이 강제되지 않음 |

ORR은 전체 범위 평가를 ownership-transfer 이벤트에 결합해, 감사 기록을 남기는 필수
shadow-first 게이트로 만듭니다.

## 루프에서의 위치

ORR은 폴링하지 않고 이벤트로 시작합니다. 범위의 핸드오프를 제안하면
`ownership_transfer` 신호가 `event-ingest`에 진입하여 다른 이벤트처럼
정규화되고 검토를 한 번 실행합니다:

```text
ownership_transfer signal
  -> event-ingest (normalize)
  -> assurance-twin: run every applicable rule over the scope projection
  -> deploy-preflight: run the feasibility probes over the scope
  -> checklist evidence: rule, artifact, metric, drill 및 approval 평가
  -> compose -> ReadinessReport (clear | needs_review | blocked)
  -> blocked + enforce mode -> gate the handoff, route fixes to risk-gate/HIL
  -> audit (Saga)
```

두 입력 모두 **deterministic-first**(T0 성격)입니다. twin 변환 결과에 대한
정적 평가로 대부분의 발견 사항을 처리하고, 범위가 제한된 읽기 전용 프로브로 나머지를
확인합니다. 이 검토 과정에서는 어떤 대상도 변경하지 않습니다.

## 트리거

`ownership_transfer` 신호는 검토를 시작하는 CSP 중립 이벤트입니다. 포크가 핸드오프 시점으로
연결한 다음과 같은 계기로 발행합니다:

- IaC 저장소의 PR 레이블(`ops-handoff-requested`), 또는
- 범위에 적용된 리소스 태그(`lifecycle-stage: handoff`), 또는
- 콘솔을 통한 명시적 운영자 요청(`request_ops_handoff`).

신호는 대상 범위(리소스 그룹과 같거나 더 좁은 범위이며,
[rule-governance](../rules-and-detection/rule-governance-ko.md) 재정의 가 사용하는 동일한 범위
계층), 제출자 신원, 대상 환경을 전달합니다. 역할이나 특권
토큰은 전달하지 않습니다.

## 리뷰 차원

ORR은 범위 전체에 적용 가능한 규칙 집합을 실행합니다. 운영팀이 가장 의존하지만 변경별
검토에서 가장 자주 놓치는 다섯 가지 차원은 다음과 같습니다:

| 차원 | 대표 체크 | 출처 |
|------|-----------|------|
| `policy_guardrail` | 허용되지 않은 리소스 타입, 공개 액세스, 암호화 누락 | [rule-catalog-collection.md](../rules-and-detection/rule-catalog-collection-ko.md) |
| `identity_rbac` | over-privileged 워크로드 아이덴티티, Owner 를 가진 게스트, standing 특권 액세스, wildcard-action 역할, 한도 초과 Owner 수 | 워크로드 RBAC 최소권한 규칙 팩(`managed-identity.role-assignment.*`, `subscription.role-assignment.*`, `resource-group.role-assignment.*`) |
| `reliability` | 백업 / PITR 없음, 진단 설정 없음, 존 이중화 없음 | 카탈로그 reliability 규칙 |
| `dependency_ordering` | 핸드오프 전 필수 링크(비공개 엔드포인트, NSG, 진단 설정) 존재 | [deployment-preflight](../deployment/deployment-preflight-ko.md) 프로브 |
| `best_practice` | 명시적인 룰, 탐색, 산출물, 메트릭, 훈련 및 승인 요구사항이 있는 framework 컨트롤 | `rule-catalog/best-practices/` 및 ARB 연결 |

`identity_rbac` 차원은 기존 preflight와 변경별 검토가 다루지 않던 영역으로 ORR이
추가합니다. preflight의 `identity_rbac` 프로브는 배포할 **실행기의**
권한을 검사하지만, ORR은 작성된 RBAC 규칙으로 **워크로드 자체의**
최소 권한 상태를 검사합니다.
[architecture.instructions.md § Rule 카탈로그](../../../.github/instructions/architecture.instructions.md#rule-catalog)
참조.

## ReadinessReport

검토는 발견 사항을 `ReadinessReport`로 조합합니다. 이는
`PostureAssessmentReport`([assurance-twin.md](assurance-twin-ko.md))를 소유권 이전
이벤트에 결합하도록 일반화한 것입니다. 각 발견 사항에는 다음 세 항목이 필요합니다:

- **근거** - 발견 사항을 만든 룰, 탐색 또는 Best Practice 컨트롤의 CSP-neutral 인용입니다.
  Checklist 발견 사항은 `control_id`와 충족되지 않은 `requirement_refs`도 유지합니다. 출처를
  인용할 수 없는 발견 사항은 defect이며 T2 검증기와 preflight 프로브가 따르는 동일한
  규칙입니다.
- **심각도** - 자세의 `low`부터 `critical`, 또는 preflight의 `warning` / `blocking`처럼
  출처 값을 보존합니다. 조정기는 resolved 게이트를 발견 사항의 별도 `blocking` boolean에
  기록합니다.
- **해석** - 그것을 해소하는 방법으로, 구체적 교정 ActionType (RBAC
  차원의 경우 `remediate.right-size-role`) 또는 autofix 가 없을 때는 가이던스에
  매핑됩니다.

### 결정 의미

| Verdict | 의미 |
|---------|------|
| `clear` | 발견 사항 없음 |
| `needs_review` | 발견 사항 은 있지만 차단 은 없음(경고 만) |
| `blocked` | 최소 하나의 차단 발견 사항 |

보고서는 항상 **실제 평가에 따른 판정**을 기록합니다. 그 판정으로 핸드오프를
*통제할지*는 별도 플래그 `blocks_handoff`로 나타내며, ORR이 `enforce` 모드로
실행될 때만 true입니다. [deployment-preflight](../deployment/deployment-preflight-ko.md)의
`blocks_deploy` 플래그와 마찬가지로, 실제 판정과 게이트 적용 여부를 분리합니다.

### Shadow-first

모든 ORR은 **shadow 모드**로 출시합니다. 차단 요인은 실제대로 보고하지만
`blocks_handoff`는 `false`로 유지하므로, 검증되지 않은 검토의 오탐으로 실제
핸드오프를 잘못 중단할 수 없습니다. `enforce`로의 승격은 환경별로 이루어지며,
고정된 시나리오 집합에서 측정한 오탐 비율로 통제합니다.
[ActionType 계약](../architecture/llm-strategy-ko.md)과 preflight 프로브에 적용하는 것과
같은 승격 원칙입니다.

## 액션 bridging

`blocked` ORR은 문제를 나열하는 데 그치지 않습니다. assurance twin과 마찬가지로,
자동 수정이 가능한 각 발견 사항은 규칙의 교정 ActionType으로 만든 **shadow remediation-PR
제안**을 포함합니다. 신원 차원에서는 과도한 권한을 최소 권한으로 줄이는
`remediate.right-size-role`을 사용합니다. RBAC 변경은 `resource_group` 영향 범위와
`AsymmetricRollback`을 가지므로
[risk-classification.md](../decisioning/risk-classification-ko.md)를 통해 HIL로 라우팅하며
자동으로 실행하지 않습니다. ORR은 제안하고, 사람이 승인하며, 실행기가
적용합니다. Console과 ChatOps는 읽기 전용 표면으로 유지됩니다.

### 제안 계약

제안 빌더는 결정론적이며 다음 불변 조건을 유지합니다:

| 불변 조건 | 동작 |
|-----------|------|
| 근거가 있을 때만 | 발견 사항이 인용한 컨트롤 또는 규칙이 호출자가 제공한 lever 맵에서 교정 ActionType 으로 연결될 때만 제안이 생성됩니다. 연결되지 않은 발견 사항은 제안을 만들지 않으며, ORR 은 lever 를 지어내는 대신 abstain 합니다. |
| shadow 전용 | ORR 게이트 자체가 `enforce` 로 실행되더라도 모든 제안은 `shadow` 를 싣습니다. 리뷰는 ActionType 을 자신의 승격 상태 위로 올릴 수 없습니다. |
| 구별된 승인자 | 핸드오프 submitter 는 자신의 교정을 승인할 수 없습니다. 주체는 Unicode NFKC 정규화 후 비교하므로 submitter 의 인코딩 변형도 여전히 self-approval 시도입니다. 그러한 시도는 제안이 만들어지기 전에 거부되고 감사됩니다. |
| 실행기 아이덴티티 없음 | 제안은 submitter 와 승인자를 책임 사실로만 기록합니다. 자격 증명, 토큰, 실행기 principal 을 싣지 않습니다. |
| 결정론적 identity | 동일한 범위, 환경, 인용 근거, 리소스, ActionType 은 항상 동일한 멱등성 키를 파생하므로 재전달된 제안은 하위에서 no-op 입니다. |

전달은 2단계로 감사됩니다: 서비스는 승인자 신원과 함께 제안 의도를 기록하고,
`RemediationProposalPublisher` 연결부를 통해 각 제안을 발행한 뒤 전달을 기록합니다.
발행기 실패는 전달된 개수와 함께 실패한 전달을 기록하고 오류를 전파합니다.
조용한 성공을 보고하지 않으며 직접 호출로 대체하지도 않습니다.

## 환경 승격

ORR은 환경 승격(dev -> staging -> prod)을 통제하는 지점입니다.
`ownership_transfer` 신호는 대상 환경을 전달하며, 게이트는 해당 환경에 맞게
엄격해집니다. `prod`로 승격할 때는 프로필 기본값과 관계없이 모든 `critical`
발견 사항을 차단 요인으로 취급합니다. 대상을 변경하는 모든 ActionType이 이미 선언한
prod-downgrade 동작을 재사용합니다
([risk-classification.md](../decisioning/risk-classification-ko.md)). 환경 분류기와 그것이
사용하는 승격 순서는
[환경 승격 계약](../decisioning/risk-classification-ko.md#환경-승격환경-승격-핸드오프-대상)
에 정의되어 있습니다. ORR은 이 계약을 사용하며 별도로 정의하지 않습니다.

## 모듈 배치

ORR 은 새로운 특권 표면을 도입하지 않고 최소한의 새 코드만 도입합니다: 기존
`core/assurance_twin/` 과 `core/deploy_preflight/` 서브시스템을 조합하고 얇은
조정기 와 하나의 정규화된 신호 을 추가합니다.

| 컴포넌트 | 책임 |
|----------|------|
| `ownership_transfer` 신호 | 리뷰를 트리거하는 정규화된 이벤트(범위 + submitter + 대상 환경); 포크 가 연결한 핸드오프 순간에 발행 |
| `core/assurance_twin/report` | 범위 변환 결과 에 대해 적용 가능한 모든 규칙 실행 (재사용) |
| `core/deploy_preflight` | 범위 에 대해 feasibility 프로브 실행 (재사용) |
| `core/readiness/checklist` | 누락 근거를 통과로 취급하지 않고 명시적인 요구사항 결과 조합 |
| ORR 조정기 | 자세, preflight 및 checklist 결과를 `ReadinessReport`로 조합하고 환경 게이트와 `blocks_handoff` 적용 |
| `composition/readiness.py` | 자세, preflight 및 선택적 checklist 근거를 동시에 실행하고 성공/실패를 감사한 뒤 serialized 보고 publish |
| `composition/readiness_evidence.py` | ARB 산출물, 근거 만료 및 소유자 연결을 타입이 지정된 결과로 변환 결과 |
| `core/readiness/remediation` | 결정론적이고 근거가 있는 shadow 전용 교정 제안을 파생하고 self-approval 을 거부 |
| `fdai-service-contracts/readiness_remediation` | 내용 주소 기반이며 권한을 부여하지 않는 shadow 요청과 생성된 JSON Schema를 정의 |
| `core/control_loop/readiness_remediation` | 정확한 이벤트 출처, ActionType 트리거와 인자, 활성 온톨로지 릴리스 다이제스트를 검증하고 실행 없이 통합 risk-gate를 호출 |
| `runtime/consumers.py` 및 부트스트랩 | 표준 `ownership_transfer` 이벤트를 검증하고 중복을 제거한 뒤 시작 준비 상태 이후 Forseti가 최종 책임을 지는 검토를 호출하며, 잘못된 페이로드는 배달 못 한 메시지 큐로 보냅니다. |
| `runtime/bootstrap_readiness.py` | 완전한 자세/보고 쌍이 활성화되면 활성 온톨로지 릴리스와 활성 Rule 교정 선언을 바탕으로 업스트림 EventBus 교정 어댑터를 선택합니다. 릴리스가 불완전하거나 레버 맵이 비어 있으면 교정 기능은 사용할 수 없는 상태로 유지됩니다. |
| 전달 의도 | 포크는 `ReadinessReportPublisher`를 Checks API 주석 또는 Console `ReadPanel`에 연결합니다. Core는 업스트림 `RemediationProposalPublisher`를 기계적으로 선택하지만, 배포는 이 선택을 통해 승인, 승격 또는 실행 권한을 제공하지 않습니다. |

조정기는 다른 모든 코어 하위 시스템처럼 `shared/` 계약과 프로바이더만
가져옵니다([project-structure.md](../architecture/project-structure-ko.md#module-boundaries)).
클라우드 SDK나 특권 신원은 보유하지 않습니다.
## 안전 자세

- **읽기 전용 검토, 게이트로 통제하는 실행**: ORR과 모든 발견 사항은 읽기 전용입니다.
  변경으로 이어지는 유일한 경로는 `risk-gate -> executor`에 진입하는 제안이며, 7개
  안전조건(stop-condition, 롤백, blast-radius 한도, 예행 실행, 리소스 잠금,
  멱등성, 감사 항목)이 거기서 강제됩니다.
- **승인과 실행은 구별 유지**: `HandoffApproval` 은 구별된 principal 의 결정을 싣고,
  `OperationalReadinessService.propose_remediations` 는 제안을 만들기 전에 self-approval
  시도를 거부하고 감사 기록을 남깁니다. 제안 발행기는 아직 실제 risk gate 에 연결되지 않았으므로
  종단 간 Var 승인 흐름은 미해결로 남아 있습니다.
- **실패 시 차단**: twin이 오래된 상태이면(인벤토리 최신성이 `freshness_ttl`을 초과하면)
  그 상태로 인계를 인증하지 않고 인증을 거부합니다. 근거를 확보할 수 없는 발견 사항은
  판단을 보류하며, 검증되지 않은 검토는 shadow로 유지합니다.
- **감사됨**: 현재 서비스는 ORR 판정, `blocks_handoff`, submitter, 대상 범위,
  환경, 작업 흐름 식별자, 최종 책임자 Forseti 귀속 및 전달/평가 실패를 추가 전용
  state-store 감사 항목으로 기록합니다.
  교정 항목은 승인자 신원, shadow 모드, 제안 개수, 실패 시 전달된 개수를 추가로
  기록합니다. Saga 에이전트 귀속은 향후 이벤트 기반 승인 작업 흐름 연결에서 추가해야 합니다.

## Next 단계

| 학습 주제 | 읽기 |
|-----------|------|
| ORR 이 조합하는 전체 그래프 리뷰 | [assurance-twin.md](assurance-twin-ko.md) |
| 재사용하는 단일 배포 feasibility 패스 | [deployment-preflight.md](../deployment/deployment-preflight-ko.md) |
| 아이덴티티 차원이 발동하는 RBAC 최소권한 규칙 | [rule-catalog-collection.md](../rules-and-detection/rule-catalog-collection-ko.md) |
| 게이트를 실행하는 cross-agent 워크플로우 | [운영 준비 상태 인계](../agents/agent-workflows-ko.md#11-operational-준비-상태-인계) |
| 게이트가 consume 하는 환경 모델 | [환경 승격 계약](../decisioning/risk-classification-ko.md#환경-승격환경-승격-핸드오프-대상) |
| 제안된 각 fix 가 해석 하는 risk 분류 | [risk-classification.md](../decisioning/risk-classification-ko.md) |

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| 구현 상태 및 남은 작업 | [구현 원장](../../roadmap-implementation/operations/operational-readiness.md) |
