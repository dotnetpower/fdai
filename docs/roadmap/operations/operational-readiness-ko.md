---
title: 운영 준비성 리뷰 (dev-to-ops 핸드오프 게이트)
translation_of: operational-readiness.md
translation_source_sha: 7424236aadc5e4e8235cf1cf0b70f8c09c73cada
translation_revised: 2026-08-13
---
# 운영 준비성 리뷰 (dev-to-ops 핸드오프 게이트)

dev 소유 범위 (리소스 그룹, 워크로드, 환경) 가 운영팀의 책임이 되기
전에 **운영 준비성 리뷰**(ORR, Operational 준비 상태 검토) 가 자동으로
실행됩니다: 범위 전체를 운영팀이 의존하는 거버넌스, security, RBAC,
reliability 규칙에 대해 평가하고, 각 발견 사항 을 그것을 만들어낸 정확한 규칙에
근거로 연결하며, ownership-transfer 이벤트에 연결된 하나의 판정 -
`clear`, `needs_review`, `blocked` - 를 반환합니다. 이것은
[deployment-preflight](../deployment/deployment-preflight-ko.md) 패스와
[assurance-twin](assurance-twin-ko.md) 자세 평가 를 하나의 핸드오프
게이트로 조합한 것으로, dev-to-ops 경계를 넘는 어떤 것도 리뷰되지 않은 채
넘어가지 못하게 합니다.

이것은 per-change 리뷰가 놓치는 실패 부류를 막습니다: 워크로드가 모든 머지에서
개별적으로는 준수하더라도, over-privileged 매니지드 아이덴티티, Owner 를 가진
게스트 principal, 진단 설정 없음, 백업 없음 상태로 운영팀에 도착할 수 있습니다 -
어떤 단일 변경도 그 공백 전체를 도입하지 않았기 때문입니다. ORR 은 하나의 차이 가
아니라 **핸드오프 시점의 범위 의 누적된 자세** 를 리뷰합니다.

> **구현 상태**: 결정론적 검토와 주입형 오케스트레이션은 구현되어 있지만, 업스트림
> 런타임은 아직 이를 자동으로 호출하지 않습니다. 근거와 남은 통합 작업은
> [구현 상태](#구현-상태)를 참조하세요.

> **고객 무관(Customer-agnostic)**: 트리거 라벨, 필수 규칙 집합, 핸드오프를
> 게이트 하는 심각도 는 모두 구성 이거나 포크 가 공급합니다. 업스트림은
> 기계장치와 범용 ReadinessReport 형태를 제공하며, 특정 고객의 핸드오프 정책은
> 절대 담지 않습니다
> ([generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)).

> **위치**: ORR 은 assurance twin 위에 구축된 **읽기 전용 리뷰** 입니다. 특권
> 아이덴티티를 보유하지 않으며 아무것도 실행하지 않습니다. 제안된 모든 fix 는
> 여전히 `risk-gate -> executor -> delivery` 를 통과하여
> [app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md)
> 의 읽기 전용 표면 규칙을 보존합니다.

## 왜 별도 게이트인가

조각들은 이미 존재합니다; 빠져 있던 것은 **일급 마일스톤으로서의
핸드오프** 입니다. 세 표면이 겹치지만, 어느 것도 단독으로는 dev-to-ops 게이트가
아닙니다:

| 기존 표면 | 무엇을 리뷰하는가 | 왜 핸드오프 게이트가 아닌가 |
|-----------|-------------------|-----------------------------|
| [deployment-preflight](../deployment/deployment-preflight-ko.md) | 하나의 배포: 이 변경이 대상 범위 에 착지할 수 있는가 | 단일 `terraform apply` / 교정 PR 로 한정, 누적 자세 아님 |
| [assurance-twin](assurance-twin-ko.md) 선제 리뷰 | 하나의 변경 이벤트: 이 차이 가 규칙을 위반하는가 | per-diff; 범위 가 모든 차이 를 통과하고도 전체로는 실패 가능 |
| [assurance-twin](assurance-twin-ko.md) `PostureAssessmentReport` | 온디맨드로 estate 전체 | ownership-transfer 이벤트에 묶이지 않음; 운영 인수 전에 실행이 강제되지 않음 |

ORR 은 전체 범위 평가 를 ownership-transfer 이벤트에 묶고, 그것을 필수,
감사됨, shadow-first 게이트로 만듭니다.

## 루프에서의 위치

ORR 은 폴링되지 않고 트리거됩니다. 범위 가 핸드오프로 제안되면
`ownership_transfer` 신호 이 `event-ingest` 에 진입하여 다른 이벤트처럼
정규화되고 하나의 리뷰 패스를 구동합니다:

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

두 입력 모두 **deterministic-first**(T0 성격) 입니다: twin 변환 결과 에 대한
정적 평가가 대부분의 발견 사항 을 해결하고, 제한된 읽기 전용 프로브가 나머지를
확인합니다. 이 패스의 어떤 것도 아무것도 mutate 하지 않습니다.

## 트리거

`ownership_transfer` 신호 은 리뷰를 시작하는 CSP-neutral 이벤트입니다. 포크 가
핸드오프 순간으로 연결한 무엇이든지에 의해 발행 됩니다:

- IaC repo 의 pull-request 라벨(`ops-handoff-requested`), 또는
- 범위 에 적용된 리소스 태그(`lifecycle-stage: handoff`), 또는
- 콘솔을 통한 명시적 운영자 요청(`request_ops_handoff`).

신호 은 대상 범위 (resource-group 등가 또는 그보다 좁게,
[rule-governance](../rules-and-detection/rule-governance-ko.md) 재정의 가 사용하는 동일한 범위
계층), submitter 아이덴티티, 대상 환경 를 실습니다. 절대 역할 이나 특권
토큰을 싣지 않습니다.

## 리뷰 차원

ORR 은 범위 전체에 대해 적용 가능한 규칙 집합을 실행합니다. 다섯 개 차원이
운영팀이 가장 의존하고 per-change 리뷰가 가장 자주 놓치는 것입니다:

| 차원 | 대표 체크 | 출처 |
|------|-----------|------|
| `policy_guardrail` | 허용되지 않은 리소스 타입, 공개 액세스, 암호화 누락 | [rule-catalog-collection.md](../rules-and-detection/rule-catalog-collection-ko.md) |
| `identity_rbac` | over-privileged 워크로드 아이덴티티, Owner 를 가진 게스트, standing 특권 액세스, wildcard-action 역할, 한도 초과 Owner 수 | 워크로드 RBAC 최소권한 규칙 팩(`managed-identity.role-assignment.*`, `subscription.role-assignment.*`, `resource-group.role-assignment.*`) |
| `reliability` | 백업 / PITR 없음, 진단 설정 없음, 존 이중화 없음 | 카탈로그 reliability 규칙 |
| `dependency_ordering` | 핸드오프 전 필수 링크(비공개 엔드포인트, NSG, 진단 설정) 존재 | [deployment-preflight](../deployment/deployment-preflight-ko.md) 프로브 |
| `best_practice` | 명시적인 룰, 탐색, 산출물, 메트릭, 훈련 및 승인 요구사항이 있는 framework 컨트롤 | `rule-catalog/best-practices/` 및 ARB 연결 |

`identity_rbac` 차원은 preflight 도 per-change 리뷰도 이전에 커버하지 않던, ORR 이
추가하는 것입니다: preflight 의 `identity_rbac` 프로브는 배포할 **실행기 의**
권한을 체크하는 반면, ORR 은 authored RBAC 규칙을 사용해 **워크로드 자신의**
최소권한 자세 를 체크합니다.
[architecture.instructions.md § Rule 카탈로그](../../../.github/instructions/architecture.instructions.md#rule-catalog)
참조.

## ReadinessReport

패스는 발견 사항 을 `ReadinessReport` 로 조립합니다 - ownership-transfer 이벤트에
묶인 `PostureAssessmentReport`([assurance-twin.md](assurance-twin-ko.md)) 의
일반화입니다. 각 발견 사항 은 동일한 세 필수 부분을 유지합니다:

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

리포트는 항상 **진실된(truthful)** 판정 를 기록합니다. 그 판정 가 핸드오프를
*게이트 하는지* 는 별도 플래그 `blocks_handoff` 이며, ORR 이 `enforce` 모드로
실행되었을 때만 true 입니다 - [deployment-preflight](../deployment/deployment-preflight-ko.md)
의 `blocks_deploy` 플래그가 사용하는 동일한 truthful-verdict / 별도-gate 분리입니다.

### Shadow-first

모든 ORR 은 **shadow 모드** 로 ship 됩니다: 차단 요인 를 진실되게 보고하지만
`blocks_handoff` 는 `false` 로 유지되므로, 검증되지 않은 리뷰가 false 긍정 로
실제 핸드오프를 잘못 멈추게 할 수 없습니다. `enforce` 로의 승격 은
환경 별이며 고정된 시나리오 집합 에서 측정된 false-positive 비율 로
게이트 됩니다 - [ActionType 계약](../architecture/llm-strategy-ko.md) 과 preflight 프로브가 적용하는
동일한 승격 규율입니다.

## 액션 bridging

`blocked` ORR 은 단지 문제를 나열하는 데 그치지 않습니다. autofix 가 있는 각
발견 사항 은 규칙의 교정 ActionType 으로 구축된 **shadow remediation-PR
제안** 을 실으며, assurance twin 과 정확히 동일합니다. 아이덴티티 차원의 경우
그것은 over-broad 권한 부여 를 최소권한으로 좁히는 `remediate.right-size-role` 이며,
RBAC 변경은 `resource_group` 영향 범위 와 `AsymmetricRollback` 을 지니므로
[risk-classification.md](../decisioning/risk-classification-ko.md) 를 통해 HIL 로 라우팅되고 절대
auto-execute 되지 않습니다. ORR 은 제안하고, 사람이 승인하며, 실행기 가
적용합니다. 콘솔과 ChatOps 는 읽기 전용 표면으로 유지됩니다.

## 환경 승격

ORR 은 환경 승격(dev -> staging -> prod) 의 강제 지점입니다.
`ownership_transfer` 신호 은 대상 환경 를 싣고, 게이트는 그것과 함께
조여집니다: `prod` 로의 승격 은 프로파일 기본값과 무관하게 어떤 `critical`
발견 사항 도 차단 으로 취급하며, 모든 mutating ActionType 이 이미 선언하는
prod-downgrade 자세 를 재사용합니다
([risk-classification.md](../decisioning/risk-classification-ko.md)). 환경 분류기와 그것이
consume 하는 승격 순서는
[risk-classification.md § 환경 승격](../decisioning/risk-classification-ko.md#환경-승격environment-promotion-핸드오프-대상)
에 명세됩니다; ORR 은 그것을 consume 하며, 정의하지 않습니다.

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
| 전달 의도 | 포크가 `ReadinessReportPublisher`를 Checks API annotation / 콘솔 `ReadPanel`에 연결 |

조정기 는 다른 모든 코어 서브시스템처럼 `shared/` 계약과 프로바이더 만
가져오기 합니다([project-structure.md](../architecture/project-structure-ko.md#module-boundaries)).
클라우드 SDK 도, 특권 아이덴티티도 보유하지 않습니다.

## 구현 상태

이 저장소에는 결정론적 검토와 주입형 애플리케이션 서비스가 구현되어 있습니다. 그러나
실행 중인 컨트롤 플레인에는 아직 이 구성 요소가 조합되어 있지 않으므로, 현재 근거로는
운영 `validated` 상태가 아니라 `implemented` 상태까지만 입증할 수 있습니다.

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| 소유권 이전 신호, 보고서 모델, 발견 사항 축약, 환경 게이트 및 Best Practice 체크리스트 평가 | implemented | [`core/readiness/`](../../../services/core-control-plane/src/fdai/core/readiness), [`test_coordinator.py`](../../../services/core-control-plane/tests/core/readiness/test_coordinator.py), [`test_checklist.py`](../../../services/core-control-plane/tests/core/readiness/test_checklist.py) | 순수 조정기는 근거가 있는 발견 사항을 보존하고 알 수 없는 심각도에서 안전하게 실패하며, 실제 판정과 `blocks_handoff`를 분리합니다. |
| 추가 전용 감사와 보고서 전달을 포함하는 자세, preflight 및 체크리스트의 동시 오케스트레이션 | implemented | [`composition/readiness.py`](../../../services/core-control-plane/src/fdai/composition/readiness.py), [`test_readiness_service.py`](../../../services/core-control-plane/tests/composition/test_readiness_service.py), [`test_readiness_checklist_service.py`](../../../services/core-control-plane/tests/composition/test_readiness_checklist_service.py) | 서비스는 주입된 프로바이더를 사용합니다. 평가와 전달 실패를 감사한 뒤 오류를 전파합니다. |
| Architecture Review Board (ARB) 산출물, 담당자, 최신성 및 만료 정보를 체크리스트 결과로 변환 | implemented | [`composition/readiness_evidence.py`](../../../services/core-control-plane/src/fdai/composition/readiness_evidence.py), [`test_readiness_evidence.py`](../../../services/core-control-plane/tests/composition/test_readiness_evidence.py) | 누락된 연결은 `unknown`으로 유지되고 만료된 근거는 `failed`가 됩니다. 어느 상태도 통과로 처리하지 않습니다. |
| 자동 `ownership_transfer` 수집과 운영 자세, 체크리스트 및 보고서 발행기 연결 | not-started | [`shared/providers/readiness.py`](../../../services/core-control-plane/src/fdai/shared/providers/readiness.py)의 프로바이더 연결부와 위의 주입형 서비스 | 현재 런타임과 부트스트랩은 `OperationalReadinessService`를 생성하거나 등록하지 않습니다. 호출자는 자체 구성에서만 서비스를 실행할 수 있습니다. |
| 교정 제안, 분리된 Var 승인 및 거버넌스가 적용된 작업 연결 | not-started | 현재 [`OwnershipTransfer`](../../../services/core-control-plane/src/fdai/core/readiness/signal.py)와 [`OperationalReadinessService`](../../../services/core-control-plane/src/fdai/composition/readiness.py) 계약 | 두 계약 모두 승인 결정이나 승인자 신원을 포함하지 않으며, 서비스는 교정 제안 또는 작업 이벤트를 발행하지 않습니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-08-13 | in-progress | 구현 원장을 도입했으며 이전 근거 이력은 재구성하지 않았습니다. 구현된 결정론적 기능 및 오케스트레이션 표면과 연결되지 않은 런타임 작업 흐름을 분리해 기록했습니다. | 현재 변경, 위에 인용한 core 및 composition 테스트 파일 5개의 `48 passed` 결과 | 이벤트, 프로바이더, 발행기, 승인 및 교정 경로를 연결한 뒤 거버넌스가 적용된 런타임 근거를 수집합니다. |

### 남은 작업

- [ ] event ingest에서 `ownership_transfer`를 등록하고 정규화한 뒤 책임 에이전트의
  이벤트 기반 작업 흐름을 통해 검토를 호출하고, 재생해도 안전한 전달을 통합 테스트로 입증합니다.
- [ ] 운영 자세, 체크리스트 근거 및 보고서 발행기 구현을 composition root에 연결한 뒤
  하나의 완전한 shadow 검토에 대한 거버넌스 적용 런타임 증적을 기록합니다.
- [ ] 근거가 있는 교정 제안을 risk gate와 Var 승인 흐름을 통해 발행하고, 승인자 신원이
  기록되며 자체 승인이 차단되고 검토 서비스가 관리 리소스 변경을 실행하지 않음을 테스트합니다.
- [ ] 고정 시나리오의 shadow 근거가 구성된 false-positive 임계값을 충족하고 권한 있는
  승격 레지스트리가 전환을 기록할 때까지 적용 모드를 비활성화 상태로 유지합니다.

## 안전 자세

- **읽기 전용 리뷰, 게이트 된 실행**: ORR 과 모든 발견 사항 은 읽기 전용입니다;
  변경 으로의 유일한 경로는 `risk-gate -> executor` 에 진입하는 제안이며, 7개
  안전조건(stop-condition, 롤백, blast-radius 한도, 예행 실행, 리소스 잠금,
  멱등성, 감사 항목)이 거기서 강제됩니다.
- **승인과 실행은 구별 유지**: 핸드오프는 submitter 가 요청하고 구별된
  principal이 승인하고 절대 self-approve하지 않는 것이 목표 작업 흐름 계약입니다. 현재
  `OwnershipTransfer`와 `OperationalReadinessService`는 승인 결정 또는 승인자 신원을
  받지 않으므로 Var 승인은 아직 연결되지 않았습니다.
- **실패 시 차단**: stale twin (인벤토리 신선도가 `freshness_ttl` 초과) 은 stale
  상태로 certify 하기보다 핸드오프 certify 를 거부합니다; ungroundable 발견 사항 은
  abstain 하고; 검증되지 않은 리뷰는 shadow 로 유지됩니다.
- **감사됨**: 현재 서비스는 ORR 판정, `blocks_handoff`, submitter, 대상 범위,
  환경 및 전달/평가 실패를 추가 전용 state-store 감사 항목으로 기록합니다.
  Approver 신원과 Saga 에이전트 귀속은 향후 승인 작업 흐름 연결에서 추가해야 합니다.

## Next 단계

| 학습 주제 | 읽기 |
|-----------|------|
| ORR 이 조합하는 전체 그래프 리뷰 | [assurance-twin.md](assurance-twin-ko.md) |
| 재사용하는 단일 배포 feasibility 패스 | [deployment-preflight.md](../deployment/deployment-preflight-ko.md) |
| 아이덴티티 차원이 발동하는 RBAC 최소권한 규칙 | [rule-catalog-collection.md](../rules-and-detection/rule-catalog-collection-ko.md) |
| 게이트를 실행하는 cross-agent 워크플로우 | [agent-workflows.md § 11](../agents/agent-workflows-ko.md#11-operational-readiness-handoff) |
| 게이트가 consume 하는 환경 모델 | [risk-classification.md § 환경 승격](../decisioning/risk-classification-ko.md#환경-승격environment-promotion-핸드오프-대상) |
| 제안된 각 fix 가 해석 하는 risk 분류 | [risk-classification.md](../decisioning/risk-classification-ko.md) |
