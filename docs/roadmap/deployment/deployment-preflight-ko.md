---
title: 배포 프리플라이트 (배포 가능성 및 blocker 수집)
translation_of: deployment-preflight.md
translation_source_sha: 0c90d15b2a4d001d2bbb506f688a1cdae501ef66
translation_revised: 2026-08-14
---
# 배포 프리플라이트 (배포 가능성 및 차단 요인 수집)

배포가 실행되기 전에(`terraform apply`, 또는 컨트롤 플레인 교정 PR),
**deploy-preflight** 패스는 대상 환경에서 배포를 막거나 저하시킬 수 있는 모든 요소를
수집하고, 각 항목을 그것을 만들어낸 정확한 규칙에 근거로 연결하며, 그것을 해소하는 구체적인
레버에 매핑합니다. 이것은
[what-if 검증기](../../../.github/instructions/architecture.instructions.md#llm-quality-gate-required-for-t2)
를 단일 액션에서 배포 전체로 일반화한 것입니다.

이는 반복적으로 발생하는 실패 클래스를 해결합니다 - 그 자체로는 올바르지만 대상 구독의
가드레일에 의해 거부되는 계획: 거부된 리소스 타입, 차단된 패키지 또는 이미지 소스, 누락된
역할 배정, 소진된 쿼터, 또는 지원하는 리소스보다 먼저 존재해야 하는 의존성. 이런
것들을 `terraform apply`가 실패하면서 하나씩 발견하는 대신, 프리플라이트 패스는 이 모두를
사전에 한 번에 보고합니다.

> 고객-비종속: 아래의 모든 denylist, 차단 호스트, 미러 엔드포인트, 토글 값은 구성 또는
> 포크가 공급합니다 - 상류는 기계 장치와 제네릭 분류법을 제공할 뿐, 고객의 특정 가드레일
> 값은 절대 넣지 않습니다
> ([generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)).

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| 프로브 계약, 결정론적 프로브, 분석기 및 리포트 | implemented | `services/core-control-plane/src/fdai/core/deploy_preflight/`, `services/core-control-plane/src/fdai/shared/providers/feasibility_probe.py` 및 배포 프리플라이트 집중 테스트 | 안정적인 발견 사항, 실패 시 차단되는 프로브 실행, 판정 및 shadow와 enforce 동작이 테스트되어 있습니다. |
| 읽기 전용 Azure 프로브 및 보호된 계획 근거 | implemented | `scripts/deployment/azure/run_live_preflight.py`, `.github/workflows/deploy-dev.yml` 및 `tests/integration/scripts/test_run_live_preflight.py` | 보호된 실행기는 독립 실행형 스크립트를 호출하고 실제 검사 범주 네 개를 모두 요구하며, 근거를 정제하고 그 다이제스트를 계획에 연결합니다. |
| Terraform 토글 및 환경 프로파일 기본 요소 | implemented | `infra/modules/preflight-toggles/`와 집중 `test_environment_profile.py` 및 `test_reassembly_proposals.py` 검사 | 루트 앱 그래프 소비자와 영속 프로파일 새로 고침 작업은 조립되지 않았습니다. |
| 검사 발행 기본 요소 | implemented | `services/core-control-plane/src/fdai/core/deploy_preflight/check_publish.py` 및 `test_check_publish.py` | 순수 리포트 발행기와 메모리 내 어댑터가 테스트되어 있습니다. GitHub Checks 어댑터는 없습니다. |
| 컨트롤 루프의 PR 전 게이트 및 GitHub 전달 | not-started | 이 문서의 계획된 경계 | 교정 PR 전에 분석기를 호출하거나 결과를 GitHub Checks에 발행하는 실제 경로가 없습니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-08-14 | in-progress | 구현 원장을 도입했으며 이전 출처 이력은 재구성하지 않았습니다. 보호된 실행기 경로를 현재 독립 실행형 프리플라이트 진입점으로 바로잡았습니다. | 현재 변경과 구현 범위 표에 기재한 코어 프리플라이트 및 실제 스크립트 집중 검사 | 루트 토글 소비자, 영속 프로파일 새로 고침, GitHub 발행기 및 컨트롤 루프 게이트를 조립해야 합니다. |

### 남은 작업

- [ ] 루트 앱 그래프를 지원되는 프리플라이트 토글에 연결하고, 재렌더된 계획에서 거부된 형태가 사라졌음을 입증하는 집중 Terraform 테스트를 통과합니다.
- [ ] Inventory 변경에 따른 무효화를 포함하는 영속 환경 프로파일 새로 고침 작업을 추가하고 재시작 및 만료 테스트를 통과합니다.
- [ ] 교정 PR 발행 전에 분석기를 호출하고 차단 발견 사항을 사람 검토로 낮추며, 차단된 리포트에서는 PR이 열리지 않음을 통합 테스트로 입증합니다.
- [ ] 정제된 리포트를 GitHub Checks 어댑터로 발행하고 정보 제거와 전달 실패에 대한 집중 계약 테스트를 남깁니다.

## 루프에서의 위치

설계는 하나의 분석기를 공유하는 두 진입점을 정의합니다. 보호된 사람 배포 경로는 독립
실행형 실행기 스크립트로 제공되며 컨트롤 플레인 경로는 현재 경계만 있습니다:

- **컨트롤 플레인(계획됨)**: [실행기](../architecture/project-structure-ko.md)가 교정 PR을 발행하기
  전에, analyzer는 그 변경이 실제로 대상 범위에 착지할 수 있는지 확인합니다. 차단
  발견 사항은 정책을 실패시킬 PR을 여는 대신 액션을 `hil`로 격하시킵니다.
- **사람 배포(배포됨)**: 비공개 실행기 작업 흐름이 계획 전에 리포트를 생성하고 exact-plan
  메타데이터에 근거 다이제스트를 연결합니다. PR comment/GitHub 검사 전송은 후속입니다.

두 경로 모두 **deterministic-first**(T0 성격)입니다: 클라우드 호출 없는 정적 분석이 대부분의
발견 사항을 해결하고, 범위가 제한된·읽기 전용 라이브 프로브가 나머지(egress 도달성, 쿼터)를
확증합니다. 패스의 어떤 것도 무엇을 mutate하지 않습니다.

## 프로브 분류법

*프로브*는 `PreflightTarget`(범위에 더해 배포가 건드리려는 리소스 타입, egress 호스트,
필요한 링크)을 검사하고 한 카테고리의 근거 있는 발견 사항을 반환합니다. 제네릭 카탈로그:

| 카테고리 | 대표 차단 요인 | 탐지 (deterministic-first) |
|----------|------------------------|---------------------------------|
| `policy_guardrail` | disallowed 리소스 types, NSG 필수, 인라인 디스크 거부, 공개 IP 거부 | `terraform plan` JSON을 `policies/`(OPA)에 재검증 + Azure Policy 거부 시뮬레이션 (정적) |
| `supply_chain_egress` | `docker.io` 차단, PyPI / npm / apt 차단, 외부 base 이미지 pull 거부 | NSG / Firewall / UDR 규칙 분석 (정적) + 범위가 제한된 egress 도달성 프로브 (라이브) |
| `identity_rbac` | 실행기 아이덴티티가 대상 범위에 역할 없음; 역할 배정 생성 불가 | 인벤토리 그래프에서 범위 role-assignment 확인 (정적) |
| `quota_capacity` | SKU / 지역 쿼터 초과, 영역 용량 없음 | 쿼터 조회 (라이브, 캐시) |
| `dependency_ordering` | disk before VM, NSG before 서브넷, 비공개 엔드포인트 before 리소스 | 정책 + 모듈 의존성 그래프에서 도출한 순서 위반 (정적) |
| `secret_config` | Key Vault 참조 해결 불가, 필수 시크릿 부재 | 시크릿 존재 / 도달성 확인 (정적) |

`policy_guardrail`과 `supply_chain_egress` 카테고리는 하드닝된 네트워크 고객이 가장 많이
부딪히는 둘입니다: 이들은 Azure Policy `deny` 가드레일(`Not allowed resource types` /
`Allowed resource types`)과 방화벽 egress denylist에 직접 매핑됩니다. 기저 규칙의 출처는
[rule-catalog-collection-ko.md](../rules-and-detection/rule-catalog-collection-ko.md)를 참조하세요.

## 준비 상태 리포트

발견 사항은 하나의 `DeploymentReadinessReport`
([core/deploy_preflight/report.py](../../../services/core-control-plane/src/fdai/core/deploy_preflight/report.py))
로 조립됩니다. 각 발견 사항은 세 개의 필수 부분을 가집니다:

- **근거** - 그것을 만들어낸 규칙의 CSP-neutral 인용
  (`policy:<neutral-id>`, `nsg:<neutral-id>/rule:<name>`). 출처를 인용할 수 없는
  프로브는 발견 사항을 발행해서는 안 됩니다; 근거 없는 차단 요인은 결함이며, T2 검증기가
  따르는 규칙과 동일합니다.
- **심각도** - `blocking`(강제 적용 모드 배포를 게이팅) 또는 `warning`(표면화하지만 절대
  게이팅하지 않음).
- **해석** - 어떻게 해소하는지, 가능하면 구체적인 레버에 매핑됨 (아래 토글 표 참조).

### 결정 의미론

| Verdict | 의미 |
|---------|---------|
| `clear` | 발견 사항 없음 |
| `needs_review` | 발견 사항은 있으나 차단은 없음 (경고만) |
| `blocked` | 최소 하나의 차단 발견 사항 |

리포트는 항상 **진실한** 판정을 기록합니다. 그 판정이 배포를 *게이팅*하는지는 별도의
플래그 `blocks_deploy`이며, 패스가 `enforce` 모드로 실행됐을 때만 true입니다.

### Shadow-First

모든 새 프로브는 **shadow 모드**로 출시됩니다: 차단 요인을 진실하게 보고하지만
`blocks_deploy`는 `false`로 유지되어, 검증되지 않은 프로브가 false 긍정으로 사람 배포를
잘못 막을 수 없습니다. 프로브는 고정된 시나리오 세트에서 false-positive율이 측정된 후에만
카테고리별로 `enforce`로 승격됩니다 - 자율 액션에
[ActionType 계약](../architecture/llm-strategy-ko.md)가 적용하는 것과 동일한 승격 규율입니다.

## 차단 요인에서 Terraform 토글로의 매핑

리포트는 단순한 문제 목록이 아닙니다; 각 `terraform_toggle` 발견 사항은 배포를 준수시키는
인프라 서브모듈과 변수 오버라이드를 지목합니다. 이것은 기존 `infra/modules/<seam>/` +
`var.<seam>_kind` 선택 패턴([project-structure-ko.md](../architecture/project-structure-ko.md))을
리소스-프로비저닝 모드로 일반화한 것으로, 모듈 출력 계약은 고정된 채 내부 배선만 전환됩니다:

| 토글 | 값 | 효과 |
|--------|--------|--------|
| `disk_provisioning` | `inline` \| `attach_existing` | VM 디스크를 인라인 생성 vs 사전 프로비저닝된 디스크 첨부 (`var.existing_disk_ids`) |
| `nsg_provisioning` | `create` \| `byo` | NSG 생성 vs 기존 NSG 참조(`var.existing_nsg_id`), 가드레일이 요구하는 대로 첨부 |
| `registry_source` | `docker_io` \| `acr_mirror` | base 이미지를 `docker.io` 대신 내부 레지스트리 미러에서 pull |
| `python_index_url` | (문자열) | 패키지 설치를 내부 PyPI 미러 / 산출물 피드로 지정 |
| `dependency_ordering` | `strict` | 선행 리소스(disk, NSG, 비공개 엔드포인트)를 순서 있는 적용 단계로 분리 |

이 매핑이 거부된 리소스 타입을 비-문제로 만드는 요소입니다: 인라인 디스크 거부는
`disk_provisioning=attach_existing`으로 해소되어, 계획이 애초에 거부된 연산을 발행하지
않습니다. 해석이 `autofix`로 표시되면 analyzer가 사람 판단 없이 토글 변경을
교정 PR로 제안할 수 있습니다; 그렇지 않으면 지침을 발행하고 검토로 라우팅합니다.

## 서브시스템 레이아웃

| 조각 | 위치 | 역할 |
|-------|----------|------|
| 프로브 경계 | [shared/providers/feasibility_probe.py](../../../services/core-control-plane/src/fdai/shared/providers/feasibility_probe.py) | `FeasibilityProbe` 프로토콜 + 발견 사항 / 대상 데이터 클래스 |
| 제네릭 프로브 | [shared/providers/local/feasibility.py](../../../services/core-control-plane/src/fdai/shared/providers/local/feasibility.py) | 결정론적·구성 주도 상류 기본값 (네트워크 없음) |
| 오케스트레이터 | [core/deploy_preflight/analyzer.py](../../../services/core-control-plane/src/fdai/core/deploy_preflight/analyzer.py) | 프로브에 동시 확산, 리포트 조립 (실패 시 차단) |
| 리포트 | [core/deploy_preflight/report.py](../../../services/core-control-plane/src/fdai/core/deploy_preflight/report.py) | 조립된 산출물 + 판정 + `blocks_deploy` |

`core/`는 `FeasibilityProbe` 프로토콜만 봅니다; 프로브는
[조립 루트](../../../services/core-control-plane/src/fdai/composition/__init__.py) 에서 `Container.feasibility_probes`
경계를 통해 주입됩니다. 상류 기본값은 프로브를 바인딩하지 않습니다(denylist는 고객 구성);
포크 또는 라이브 Azure 어댑터가 `core/`를 편집하지 않고 자체 구현을 등록합니다.

## 안전 자세

- **실패 시 차단** - raise하는 프로브는 전파됩니다; 패스는 부분 실행에서 `clear`를 절대
  보고하지 않습니다. 차단 발견 사항은 컨트롤 플레인 액션을 게이팅되지 않은 auto-action이
  아니라 `hil`로 격하시킵니다.
- **읽기 전용** - 프로브는 절대 mutate하지 않습니다; 패스는 모든 배포에서 실행해도 안전합니다.
- **멱등적** - 발견 사항은 결정론적으로 정렬되어(차단 먼저, 그 다음 id 순), 같은
  입력에 대한 재실행은 바이트-동일한 리포트를 생성합니다.
- **근거 있음** - 출처 규칙을 인용하는 근거 없이는 발견 사항이 없습니다.
- **발견 피드백** - 여러 환경에 걸친 반복 차단 요인(예: 모든 범위가 `docker.io` 차단)는
  발견 루프가 새 기본 토글이나 규칙을 제안하도록 하는 신호입니다
  ([architecture.instructions.md § Rule 카탈로그](../../../.github/instructions/architecture.instructions.md#rule-catalog)).

## 전달 상태

배포됨: 프로브 경계, 제네릭 결정론적 프로브, 분석기와 리포트, 독립 실행형 Azure
프리플라이트 스크립트, 배포 작업 흐름의 보호된 계획 근거 연결 및 테스트.

1. **Azure 탐색과 protected-plan 근거(배포됨)**: `delivery/azure/preflight/`의 공유 읽기 전용 ARM
   클라이언트(`AzureArmClient`, 주입된 `httpx.AsyncClient` + `WorkloadIdentity` bearer
   토큰, 실패 시 차단)와 `AzurePolicyGuardrailProbe`(실제 Azure Policy `deny` 가드레일 -
   `Not allowed` / `Allowed resource types`), `AzureQuotaProbe`(구독 + 위치별 Compute
  사용량)가 mock-HTTP 유닛 테스트와 함께 landed. Policy 파서는 모든 형제가 정본
  type-exists 가드인 경우에만 built-in `allOf` 타입 제약을 허용하며 알 수 없음 형제는
  실패 시 차단으로 유지합니다. 격리된 실제 운영 검증에서 RG-scoped disk 거부는
  `disk_provisioning=attach_existing`로 매핑됐고 실제 할당량 부족은 수동 차단 요인으로 남았으며,
  temporary 배정은 검토된 롤백으로 제거됐습니다. `scripts/deployment/azure/run_live_preflight.py`는
  Azure CLI 워크로드 신원, 범위가 제한된 읽기 전용 ARM 전송 계층,
  neutral-to-ARM 타입 대응, 정제된 실패 시 차단 오류와 함께 두 탐색을 같은 analyzer에
  조립합니다. 기존 Resource Graph 역할 관찰기도 `AzureIdentityRbacProbe`를 통해 조립되어
  principal 또는 role-definition id를 출력하지 않고 누락된 event-bus 및 secret-reader
  실행기 역할을 보고합니다. `AzureSecretConfigProbe`는 상태만으로 필수 Key Vault
  참조를 검사하고 응답 본문 또는 시크릿 값을 읽지 않으며 hashed 참조를
  출력합니다. 보고는 clear인 경우에도 정제된 per-category 검사 커버리지를 기록합니다.
  비공개 실행기는 강제 적용 모드에서 Azure category 네 개를 모두 요구하고 범위가 제한된 TLS egress
  근거와 결합합니다. 정제된 보고만 비공개 Blob 저장소에 저장하고 두 근거 다이제스트를
  exact-plan 검증에 연결합니다. Firewall / NSG 토폴로지 어댑터는 별도 future
  enhancement이며 direct 실행기 도달 가능성 근거에는 필요하지 않습니다.
  2. **Capability-mode 토글 scaffold(배포됨)**: `infra/modules/preflight-toggles/`와 disk
    참조 소비자가 계약을 검증합니다. 루트 앱 그래프의 실제 소비자 배선은 계획됨.
  3. **검사 발행 기본 요소(배포됨)**: 코어 함수, 프로바이더 프로토콜, in-memory
    발행기가 있습니다. GitHub 검사 어댑터와 infra PR 작업 흐름 배선은 계획됨.
  4. **배포 환경 프로파일 기본 요소(배포됨)**: 범위가 제한된 in-memory 캐시, TTL,
    Inventory-delta invalidation 보조 로직이 있습니다. 조립 새로 고침 작업과 영속 캐시
    배선은 계획됨.
  5. **Control-loop pre-PR 게이트(계획됨)**: 실행기가 교정 PR을 만들기 전에 같은
    analyzer를 호출하고 차단 발견 사항을 `hil`로 낮추는 실제 운영 경로.

## 참조

- [architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) - 컨트롤 루프, quality 게이트, 안전성 불변식
- [project-structure-ko.md](../architecture/project-structure-ko.md) - 모듈 경계, 인프라 서브모듈 패턴
- [risk-classification-ko.md](../decisioning/risk-classification-ko.md) - 차단 발견 사항이 `hil`로 라우팅되는 방식
- [rule-catalog-collection-ko.md](../rules-and-detection/rule-catalog-collection-ko.md) - 기저 가드레일 규칙의 출처
