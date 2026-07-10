---
title: 배포 프리플라이트 (배포 가능성 및 blocker 수집)
translation_of: deployment-preflight.md
translation_source_sha: 261b2e74ea0007bf8d3123accd798c316ffc1103
translation_revised: 2026-07-11
---
# 배포 프리플라이트 (배포 가능성 및 blocker 수집)

배포가 실행되기 전에(`terraform apply`, 또는 컨트롤 플레인 remediation PR),
**deploy-preflight** 패스는 대상 환경에서 배포를 막거나 저하시킬 수 있는 모든 요소를
수집하고, 각 항목을 그것을 만들어낸 정확한 규칙에 근거로 연결하며, 그것을 해소하는 구체적인
레버에 매핑합니다. 이것은
[what-if verifier](../../.github/instructions/architecture.instructions.md#llm-quality-gate-required-for-t2)
를 단일 액션에서 배포 전체로 일반화한 것입니다.

이는 반복적으로 발생하는 실패 클래스를 해결합니다 - 그 자체로는 올바르지만 대상 구독의
가드레일에 의해 거부되는 계획: 거부된 리소스 타입, 차단된 패키지 또는 이미지 소스, 누락된
role assignment, 소진된 쿼터, 또는 지원하는 리소스보다 먼저 존재해야 하는 의존성. 이런
것들을 `terraform apply`가 실패하면서 하나씩 발견하는 대신, 프리플라이트 패스는 이 모두를
사전에 한 번에 보고합니다.

> 고객-비종속: 아래의 모든 denylist, 차단 호스트, 미러 엔드포인트, 토글 값은 config 또는
> 포크가 공급합니다 - 상류는 기계 장치와 제네릭 분류법을 제공할 뿐, 고객의 특정 가드레일
> 값은 절대 넣지 않습니다
> ([generic-scope.instructions.md](../../.github/instructions/generic-scope.instructions.md)).

## 루프에서의 위치

패스는 하나의 analyzer를 공유하며 두 진입점에서 실행됩니다:

- **컨트롤 플레인**: [executor](project-structure-ko.md)가 remediation PR을 emit하기
  전에, analyzer는 그 변경이 실제로 대상 scope에 착지할 수 있는지 확인합니다. blocking
  finding은 정책을 실패시킬 PR을 여는 대신 액션을 `hil`로 격하시킵니다.
- **사람 배포**: 인프라 PR의 독립 CI 체크로서, 리포트가 PR 코멘트 / GitHub Check로
  게시되어 오퍼레이터가 `terraform apply` 이후가 아니라 이전에 blocker를 봅니다.

두 경로 모두 **deterministic-first**(T0 성격)입니다: 클라우드 호출 없는 정적 분석이 대부분의
finding을 해결하고, bounded·읽기 전용 라이브 프로브가 나머지(egress 도달성, 쿼터)를
확증합니다. 패스의 어떤 것도 무엇을 mutate하지 않습니다.

## 프로브 분류법

*프로브*는 `PreflightTarget`(scope에 더해 배포가 건드리려는 리소스 타입, egress 호스트,
필요한 링크)을 검사하고 한 카테고리의 근거 있는 finding을 반환합니다. 제네릭 카탈로그:

| 카테고리 | 대표 blocker | 탐지 (deterministic-first) |
|----------|------------------------|---------------------------------|
| `policy_guardrail` | disallowed resource types, NSG 필수, 인라인 디스크 deny, public IP deny | `terraform plan` JSON을 `policies/`(OPA)에 재검증 + Azure Policy deny 시뮬레이션 (정적) |
| `supply_chain_egress` | `docker.io` 차단, PyPI / npm / apt 차단, 외부 base image pull deny | NSG / Firewall / UDR 규칙 분석 (정적) + bounded egress 도달성 프로브 (라이브) |
| `identity_rbac` | executor 아이덴티티가 대상 scope에 role 없음; role assignment 생성 불가 | 인벤토리 그래프에서 scope role-assignment 확인 (정적) |
| `quota_capacity` | SKU / region 쿼터 초과, zone capacity 없음 | 쿼터 조회 (라이브, 캐시) |
| `dependency_ordering` | disk before VM, NSG before subnet, private endpoint before resource | policy + 모듈 의존성 그래프에서 도출한 순서 위반 (정적) |
| `secret_config` | Key Vault reference 해결 불가, 필수 시크릿 부재 | 시크릿 존재 / 도달성 확인 (정적) |

`policy_guardrail`과 `supply_chain_egress` 카테고리는 하드닝된 네트워크 고객이 가장 많이
부딪히는 둘입니다: 이들은 Azure Policy `deny` 가드레일(`Not allowed resource types` /
`Allowed resource types`)과 방화벽 egress denylist에 직접 매핑됩니다. 기저 규칙의 출처는
[rule-catalog-collection-ko.md](rule-catalog-collection-ko.md)를 참조하세요.

## Readiness 리포트

finding은 하나의 `DeploymentReadinessReport`
([core/deploy_preflight/report.py](../../src/fdai/core/deploy_preflight/report.py))
로 조립됩니다. 각 finding은 세 개의 필수 부분을 가집니다:

- **evidence** - 그것을 만들어낸 규칙의 CSP-neutral 인용
  (`policy:<neutral-id>`, `nsg:<neutral-id>/rule:<name>`). 출처를 인용할 수 없는
  프로브는 finding을 emit해서는 안 됩니다; 근거 없는 blocker는 결함이며, T2 verifier가
  따르는 규칙과 동일합니다.
- **severity** - `blocking`(enforce 모드 배포를 게이팅) 또는 `warning`(표면화하지만 절대
  게이팅하지 않음).
- **resolution** - 어떻게 해소하는지, 가능하면 구체적인 레버에 매핑됨 (아래 토글 표 참조).

### Verdict 의미론

| Verdict | 의미 |
|---------|---------|
| `clear` | finding 없음 |
| `needs_review` | finding은 있으나 blocking은 없음 (warning만) |
| `blocked` | 최소 하나의 blocking finding |

리포트는 항상 **진실한** verdict를 기록합니다. 그 verdict가 배포를 *게이팅*하는지는 별도의
플래그 `blocks_deploy`이며, 패스가 `enforce` 모드로 실행됐을 때만 true입니다.

### Shadow-First

모든 새 프로브는 **shadow 모드**로 출시됩니다: blocker를 진실하게 보고하지만
`blocks_deploy`는 `false`로 유지되어, 검증되지 않은 프로브가 false positive로 사람 배포를
잘못 막을 수 없습니다. 프로브는 frozen 시나리오 세트에서 false-positive율이 측정된 후에만
카테고리별로 `enforce`로 승격됩니다 - 자율 액션에
[ActionType contract](llm-strategy-ko.md)가 적용하는 것과 동일한 승격 규율입니다.

## Blocker에서 Terraform 토글로의 매핑

리포트는 단순한 문제 목록이 아닙니다; 각 `terraform_toggle` finding은 배포를 준수시키는
인프라 서브모듈과 변수 오버라이드를 지목합니다. 이것은 기존 `infra/modules/<seam>/` +
`var.<seam>_kind` 선택 패턴([project-structure-ko.md](project-structure-ko.md))을
리소스-프로비저닝 모드로 일반화한 것으로, 모듈 출력 계약은 고정된 채 내부 배선만 전환됩니다:

| 토글 | 값 | 효과 |
|--------|--------|--------|
| `disk_provisioning` | `inline` \| `attach_existing` | VM 디스크를 인라인 생성 vs 사전 프로비저닝된 디스크 attach (`var.existing_disk_ids`) |
| `nsg_provisioning` | `create` \| `byo` | NSG 생성 vs 기존 NSG 참조(`var.existing_nsg_id`), 가드레일이 요구하는 대로 attach |
| `registry_source` | `docker_io` \| `acr_mirror` | base image를 `docker.io` 대신 내부 registry 미러에서 pull |
| `python_index_url` | (string) | 패키지 설치를 내부 PyPI 미러 / artifact feed로 지정 |
| `dependency_ordering` | `strict` | 선행 리소스(disk, NSG, private endpoint)를 순서 있는 apply 단계로 분리 |

이 매핑이 거부된 리소스 타입을 비-문제로 만드는 요소입니다: 인라인 디스크 deny는
`disk_provisioning=attach_existing`으로 해소되어, 계획이 애초에 거부된 연산을 emit하지
않습니다. resolution이 `autofix`로 표시되면 analyzer가 사람 판단 없이 토글 변경을
remediation PR로 제안할 수 있습니다; 그렇지 않으면 guidance를 emit하고 review로 라우팅합니다.

## 서브시스템 레이아웃

| 조각 | 위치 | 역할 |
|-------|----------|------|
| 프로브 seam | [shared/providers/feasibility_probe.py](../../src/fdai/shared/providers/feasibility_probe.py) | `FeasibilityProbe` Protocol + finding / target dataclass |
| 제네릭 프로브 | [shared/providers/local/feasibility.py](../../src/fdai/shared/providers/local/feasibility.py) | 결정론적·config 주도 상류 기본값 (네트워크 없음) |
| 오케스트레이터 | [core/deploy_preflight/analyzer.py](../../src/fdai/core/deploy_preflight/analyzer.py) | 프로브에 fan out, 리포트 조립 (fail-closed) |
| 리포트 | [core/deploy_preflight/report.py](../../src/fdai/core/deploy_preflight/report.py) | 조립된 산출물 + verdict + `blocks_deploy` |

`core/`는 `FeasibilityProbe` Protocol만 봅니다; 프로브는
[composition root](../../src/fdai/composition.py) 에서 `Container.feasibility_probes`
seam을 통해 주입됩니다. 상류 기본값은 프로브를 바인딩하지 않습니다(denylist는 고객 config);
포크 또는 라이브 Azure 어댑터가 `core/`를 편집하지 않고 자체 구현을 등록합니다.

## 안전 자세

- **Fail-closed** - raise하는 프로브는 전파됩니다; 패스는 부분 실행에서 `clear`를 절대
  보고하지 않습니다. blocking finding은 컨트롤 플레인 액션을 게이팅되지 않은 auto-action이
  아니라 `hil`로 격하시킵니다.
- **읽기 전용** - 프로브는 절대 mutate하지 않습니다; 패스는 모든 배포에서 실행해도 안전합니다.
- **Idempotent** - finding은 결정론적으로 정렬되어(blocking 먼저, 그 다음 id 순), 같은
  입력에 대한 재실행은 바이트-동일한 리포트를 생성합니다.
- **근거 있음** - 출처 규칙을 인용하는 evidence 없이는 finding이 없습니다.
- **Discovery 피드백** - 여러 환경에 걸친 반복 blocker(예: 모든 scope가 `docker.io` 차단)는
  discovery loop가 새 기본 토글이나 규칙을 제안하도록 하는 신호입니다
  ([architecture.instructions.md § Rule Catalog](../../.github/instructions/architecture.instructions.md#rule-catalog)).

## 전달 증분

지금 출시됨: 프로브 seam, 제네릭 결정론적 프로브, analyzer + 리포트, composition 배선,
테스트. 다음 증분들은 각각 별도로 리뷰 가능하도록 단계화됨:

1. `delivery/azure/preflight/` 아래의 라이브 Azure 어댑터(Policy Insights, Resource
   Graph, Firewall / NSG, Quota), shadow 모드 우선.
2. 위 표의 `infra/modules/` capability-mode 토글.
3. 인프라 PR에 리포트를 게시하는 GitHub Check.
4. 캐시된 **Deployment Environment Profile**(어떤 가드레일이 scope에 적용되는지), Inventory
   delta 스트림으로 갱신되어 배포가 재프로빙 대신 캐시를 읽음.

## 참조

- [architecture.instructions.md](../../.github/instructions/architecture.instructions.md) - 컨트롤 루프, quality gate, safety invariant
- [project-structure-ko.md](project-structure-ko.md) - 모듈 경계, 인프라 서브모듈 패턴
- [risk-classification-ko.md](risk-classification-ko.md) - blocking finding이 `hil`로 라우팅되는 방식
- [rule-catalog-collection-ko.md](rule-catalog-collection-ko.md) - 기저 가드레일 규칙의 출처
