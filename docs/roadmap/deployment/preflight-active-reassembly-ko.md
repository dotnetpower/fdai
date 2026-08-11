---
title: 프리플라이트 능동 플랜 재조립 (policy blocker에서 재렌더된 terraform으로)
translation_of: preflight-active-reassembly.md
translation_source_sha: a06b01451999e51de370c52c4eab6e7647bc34f4
translation_revised: 2026-08-11
---
# 프리플라이트 능동 플랜 재조립 (정책 차단 요인에서 재렌더된 terraform으로)

[deployment-preflight](deployment-preflight-ko.md)가 등록된 capability-mode 토글을
가진 `policy_guardrail` 또는 `supply_chain_egress` 차단 요인을 보고할 때, 시스템은
shipped pure 루프는 **terraform 플랜을 능동적으로 재렌더**할 재정의를 계산하고 재검증할 수
있습니다. 지원되는 대체 형태는 애초에 거부되는 연산을 발행하지 않습니다. 기존
[실행기](../architecture/project-structure-ko.md)를 통한 교정 PR 전달은 실제 운영 조립
배선이 완료된 뒤 활성화됩니다.

이 문서는 **능동 재조립 루프, 그 수렴과 stop-condition, 그것을 실어 나르는 ActionType,
그리고 무엇이 재조립될 수 있는지에 대한 정직한 한계**에 대해 권위를 가집니다. 차단 요인
분류법, 토글 매핑 표, 리포트 형태는
[deployment-preflight-ko.md](deployment-preflight-ko.md)에 남습니다. 토글 모듈 자체는
[infra/modules/preflight-toggles/](../../../infra/modules/preflight-toggles/README.md)에
있습니다.

> 고객-비종속: 어떤 denylist 값, 미러 엔드포인트, 토글 기본값도 상류에 하드코딩되지
> 않습니다. 상류는 재조립 기계 장치와 제네릭 토글 카탈로그를 제공합니다. 포크가 특정
> 가드레일 값과 소비자 배선을 공급합니다
> ([generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)).
>
> **구현 상태.** 범위가 제한된 convergence 루프, 토글 제안 빌더, ActionType, data-only 토글
> modules와 참조 소비자는 배포됐습니다. 실제 정책 발견 사항 트리거, 계획 렌더러,
> `ProposalSink` -> Huginn 연결, PR 발행기 및 감사 쓰기는 아직 배선되지 않았습니다.

## 왜 가능한가 (그리고 마법이 아닌가)

레일은 이미 존재합니다. 능동 재조립은 그것들을 끝에서 끝까지 잇습니다:

1. **탐지** - `FeasibilityProbe`가 근거 있는 `ProbeFinding`을 발행합니다
 ([feasibility_probe.py](../../../services/core-control-plane/src/fdai/shared/providers/feasibility_probe.py)).
2. **매핑** - 발견 사항이 정확한 infra 서브 모듈과 배포를 준수하게 만드는 변수 재정의를
 지명하는 `ProbeResolution(kind=TERRAFORM_TOGGLE, autofix, module, set_vars)`를
 실어 나릅니다.
3. **대체 렌더링** -
 [preflight-toggles](../../../infra/modules/preflight-toggles/README.md) 모듈이 준수하는
 형태(`disk_provisioning=attach_existing`, `registry_source=acr_mirror`, ...)를
 data-only Terraform으로 인코딩합니다.

설계가 추가한 두 조각의 현재 상태는 다음과 같습니다:

- **토글 제안 빌더(완료)**: cleared 결과의 `autofix` 토글을 토글별 타입이 지정된 제안으로
 렌더합니다. 실제 운영 싱크/발행기 배선은 아직 없어 교정 PR을 열지는 않습니다
 ([check_publish.py](../../../services/core-control-plane/src/fdai/core/deploy_preflight/check_publish.py)).
- **수렴 루프(완료)**: 호출자가 제공한 계획 렌더러와 reanalyzer를 통해 재조립된 플랜을
 다시 검사하여 한 차단 요인의 수정이 다른 차단 요인을 조용히 도입하지 못하게 합니다.

## 재조립 루프

재조립은 단발이 아니라 범위가 제한된·결정론적 루프입니다 - 재렌더된 플랜은 토글이
차단 요인을 제거하는 대신 이동시킬 수 있으므로 다시 확인되어야 합니다.

```text
terraform plan (JSON)
 -> preflight.analyze
  -> CLEAR    -> 플랜 전달 / 머지
  -> BLOCKED + 모든 blocking finding에 autofix 토글 있음
       -> tfvars override 렌더 (재조립)
       -> 재-plan -> preflight.analyze로 복귀 (bounded)
  -> BLOCKED + 어떤 blocking finding에 autofix 토글 없음
       -> hil (부분 autofix는 절대 적용 안 함)
```

- **패스당 all-or-nothing**: 재조립은 *모든* 차단 발견 사항이 `autofix` 토글을 가질
 때만 진행됩니다. 단 하나의 manual-resolution 차단 요인이 전체 패스를 `hil`로
 라우팅합니다 - 루프는 여전히 적용을 실패시킬 부분 수정을 절대 적용하지 않습니다.
- **검증기가 권한**: 재조립된 플랜은 토글이 적용되었다는 이유로 신뢰되는 것이
 아니라 동일한 결정론적 preflight(OPA 재검증 + what-if)에 의해 다시 확인됩니다.
 이것은
 [quality-gate 규칙](../../../.github/instructions/architecture.instructions.md#llm-quality-gate-required-for-t2)을
 반영합니다: 실행 자격은 수정 생성기가 아니라 검증에 의해 부여됩니다.

### 수렴과 Stop-Condition

루프는 반드시 종료되어야 합니다. 그 stop-condition은 최적화가 아니라 안전 불변식입니다:

| Stop-condition | 효과 |
|----------------|--------|
| `max_reassembly_iterations` (기본 3) 초과 | `hil`로 라우팅, 마지막 리포트 첨부 |
| 동일 발견 사항 id에 대해 동일 토글이 두 번 제안됨 | 비수렴 -> `hil` (flip-flop / 무한 루프 방지) |
| 재조립 패스가 이전 패스보다 *더 많은* 차단 발견 사항을 생성 | 회귀 -> `hil` |
| 어떤 프로브라도 raise | 실패 시 차단 -> `hil` (부분 패스 위에서 절대 재조립 안 함) |

반복 카운터, 발견 사항별 토글 이력, 캡은 하드코딩 리터럴이 아니라 구성이므로 포크가
`core/`를 편집하지 않고 튜닝할 수 있습니다.

## ActionType: `remediate.apply-preflight-toggle`

능동 재조립은 **새로운** 특권 경로가 **아닙니다**. 일급 온톨로지 `ActionType`을 등록하여
기존 [실행기](../../../services/core-control-plane/src/fdai/core/executor/executor.py)를 재사용하므로, 네 개의 안전
7개 안전조건, shadow-first 게이팅, 추가 전용 감사 항목이 공짜로 따라옵니다 (콘솔 어휘가 모든
액션을 타입드 파이프라인으로 라우팅하는 것과 같은 이유,
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md#action-ontology-and-console-vocabulary)
참조).

선언 (`rule-catalog/action-types/` 아래에서 작성):

- `category: remediation`
- `trigger_kind: both` - preflight 루프가 차단 발견 사항에 대해 자동으로
 개시하며, 오퍼레이터가 특정 토글을 요청할 수 있습니다. 파라메트릭합니다
 (`argument_schema`: `scope`, `finding_id`, `toggle_module`, `set_vars`,
 `reason`), 따라서 정적 리소스-posture 규칙이 아닙니다.
- `execution_path: pr_native` - 변경은 infra 리포에 대한 tfvars-override PR이며, 직접
 기반 변경이 아닙니다.
- `rollback_contract: pr_revert` - PR을 revert하면 이전 tfvars가 복원됩니다. 재조립은
 완전히 되돌릴 수 있으므로 `irreversible: false`.
- `default_mode: shadow` - 첫 출시는 판단하고 PR을 `shadow` 라벨의 초안으로 렌더하며,
 절대 자동 머지하지 않습니다.
- `promotion_gate` - 강제 적용로의 카테고리별 승격 전에 고정된 시나리오 셋에서 측정됨
 (토글 매핑의 false-positive 비율).
- `preconditions` - `graph_fresh_within_seconds`(플랜과 환경 프로파일이 최신이어야 함)
 및 `no_conflicting_open_action_on_resource`.
- `stop_conditions` - 위의 수렴 캡, 그리고 표준 `time_box_exceeded_seconds`와
 `provider_api_error_streak`.
- `blast_radius` - 재정의가 건드리는 infra 변수의 집합. 캡보다 많은 토글을 뒤집을
 재조립은 `hil`로 abstain합니다.

### Autofix 자격 게이트

`autofix` PR은 다음이 모두 성립할 때만 자동 제안됩니다. 그렇지 않으면 발견 사항은
지침 + `hil`로 격하됩니다:

1. 해석 `kind`가 `autofix: true`인 `TERRAFORM_TOGGLE`이다;
2. 토글이 **결정론적** data-only 모듈이다 (경로에 LLM 없음);
3. 재조립된 플랜이 preflight를 다시 통과한다 (검증기 재검증);
4. 재정의가 선언된 `blast_radius` 안에 머문다.

`autofix: false` 토글은 제안이나 차이를 제출하지 않습니다. 보고의 수동 지침으로
남고 전체 통과는 에스컬레이션되며, 오퍼레이터가 변수를 검토해 적용합니다.

### 액션 입도: 토글당 액션 1개

하나의 재조립은 여러 토글을 적용할 수 있습니다(여러 발견 사항·여러 반복). 적용된 각
토글은 패스당 묶음 액션이 아니라 **각자** `remediate.apply-preflight-toggle` 액션이
됩니다. 이렇게 하면 ActionType의 `argument_schema`가 단일 토글(`finding_id` +
`toggle_module` + `set_vars`)로 유지되어, 감사·롤백(`pr_revert`)·blast-radius가 토글
입도로 남고 각 토글이 해소하는 발견 사항에 1:1로 매핑됩니다. 루프는 토글별 출처 이력을
유지하며(`AppliedToggle`: `finding_id`, `module`, `set_vars`, `scope`), 제안
빌더([reassembly_proposals.py](../../../services/core-control-plane/src/fdai/core/deploy_preflight/reassembly_proposals.py))가
토글당 제안 하나를 렌더하여, 오퍼레이터 명령이 재진입하는 것과 같은 타입드 파이프라인
경계(`ProposalSink` -> Huginn -> Forseti -> Thor)을 통해 shadow-first로 제출합니다.
escalate된 결과는 제안을 내지 않습니다 - 호출자가 `hil`로 라우팅합니다.

## 무엇을 재조립할 수 있고 없는가

경계에 대한 정직함은 부수 조건이 아니라 안전 속성입니다:

- **재조립 가능** - 등록된 대체 렌더링을 가진 차단 요인: 인라인 disk 거부 ->
 `attach_existing`; 차단된 `docker.io` egress -> `acr_mirror`; NSG 생성 거부 ->
 `byo`; PyPI egress 거부 -> 내부 `python_index_url`; 순서 위반 ->
 `dependency_ordering=strict`.
- **재조립 불가 (`hil`로 라우팅)** - 지원되는 대체가 없는 정책: 완전히 금지된 지역,
 강제-태그 정책, 대체 SKU가 없는 거부된 SKU, 또는 유일한 해결책이 scoped exemption이나
 거버넌스 결정인 가드레일. 이들은 `MANUAL` 해석을 발행하며 절대 자동 재조립하지
 않습니다.

Preflight 조립은 범위가 제한된 발견 사항 id, category, 근거 출처, 범위와 함께 반복되는
`MANUAL` 차단 요인을 Norns에 보고할 수 있습니다. Norns는 범위 다이제스트를 deduplicate하고 기본
세 개의 서로 다른 범위 이후 inert `preflight-toggle-gap` 후보 하나를 제안합니다. 후보는
**새로운** 검토된 alternate 렌더링을 제안하고 표준 quality 게이트에 진입하지만 토글을
만들거나 배포 권한을 높이지 않습니다
([architecture.instructions.md § Rule 카탈로그](../../../.github/instructions/architecture.instructions.md#rule-catalog)).

## 안전 불변식

모든 재조립 액션은 그것이 재사용하는 실행기에 의해 강제되어 7개 안전조건을 모두
만족합니다:

- **Stop-condition** - ActionType에 선언된 위의 수렴 캡.
- **Rollback 경로** - `pr_revert`; 재정의 PR은 이전 플랜에서 단일 커밋 revert 거리에
 있으며, 롤백 참조가 PR 본문에 삽입됩니다.
- **Blast-radius 한도** - 재조립은 선언된 infra 변수만 건드립니다. 캡 초과는 `hil`로
 abstain합니다.
- **Audit-log 항목** - pure 루프는 audit-grade 최종 사유와 토글 출처 이력을
 반환합니다. 실제 운영 조립이 이를 실행기에 제출할 때 해시 체인 감사 레코드를 쓰며,
 현재 unwired 코어 기본 요소 자체는 감사 저장소를 호출하지 않습니다.

재조립은 **shadow-first**로 출시됩니다: 토글 매핑의 false-positive 비율이 측정되고
카테고리가 강제 적용으로 명시적으로 승격되기 전까지, PR은 판단·렌더되지만 머지되지 않는
초안입니다.

## 서브시스템 레이아웃

| 조각 | 위치 | 상태 |
|-------|----------|--------|
| 발견 사항 위의 토글 해석 | [feasibility_probe.py](../../../services/core-control-plane/src/fdai/shared/providers/feasibility_probe.py) | 완료 |
| capability-mode 토글 모듈 | [infra/modules/preflight-toggles/](../../../infra/modules/preflight-toggles/README.md) | 완료 (data-only) |
| 준비 상태 리포트 + 판정 | [core/deploy_preflight/report.py](../../../services/core-control-plane/src/fdai/core/deploy_preflight/report.py) | 완료 |
| 리포트 -> PR 체크 게시 | [core/deploy_preflight/check_publish.py](../../../services/core-control-plane/src/fdai/core/deploy_preflight/check_publish.py) | 완료 (리포트만) |
| 수렴 루프 + stop-condition | [core/deploy_preflight/reassemble.py](../../../services/core-control-plane/src/fdai/core/deploy_preflight/reassemble.py) | 완료 |
| `remediate.apply-preflight-toggle` ActionType | [rule-catalog/action-types/](../../../rule-catalog/action-types/remediate.apply-preflight-toggle.yaml) | 완료 |
| overrides -> 액션 제안 (토글당 하나) | [core/deploy_preflight/reassembly_proposals.py](../../../services/core-control-plane/src/fdai/core/deploy_preflight/reassembly_proposals.py) | 완료 |
| 반복 수동 차단 요인 -> inert 후보 | [agents/norns.py](../../../services/core-control-plane/src/fdai/agents/norns.py) | 완료 (caller-supplied 관측) |
| 참조 소비자 배선 (토글 하나) | [infra/modules/preflight-toggles/reference-disk-consumer/](../../../infra/modules/preflight-toggles/reference-disk-consumer/README.md) | 완료 (포크가 복사) |
| **조립 배선: `ProposalSink` + 라이브 트리거** | 조립 루트 + `delivery/azure/preflight/` | **남음** |

`core/`는 `FeasibilityProbe` 프로토콜과 caller-supplied `ProposalSink` callable만 봅니다.
재조립 루프는 어떤 클라우드 SDK도 구성하지 않고 PR을 직접 열지 않습니다 - 재정의를
결정하고 (ActionType을 통해) 실행기에 넘기며, 실행기가 게시와 불변식을 소유합니다.

## 전달 증분

각각은 개별적으로 리뷰 가능합니다:

1. **Docs-first** (이 문서) - 루프, ActionType, 한계. *(완료)*
2. `remediate.apply-preflight-toggle` ActionType YAML + 스키마 검증. *(완료)*
3. 범위가 제한된 수렴 루프, shadow-mode, 속성 테스트와 함께: "동일 토글은 절대 두 번
 적용 안 함", "부분 차단 요인 -> hil", "재조립된 플랜은 재검증됨", "회귀 -> hil",
 "raise하는 reanalyze에 실패 시 차단". *(완료)*
4. `infra/` 아래 참조 소비자 배선 하나(`disk_provisioning` 토글)로 포크가 복사-붙여넣기
 시작점을 갖게 함. *(완료)*
5. overrides-to-executor 단계: 적용된 각 토글을 `remediate.apply-preflight-toggle`
 제안으로 렌더하고(토글당 액션 1개, granularity A) 타입드 파이프라인 경계를 통해
 제출합니다. *(완료)*
6. 조립 배선(`ProposalSink`을 Huginn ingest에 연결) + 실제 정책 발견 사항을
 루프에 공급하고 tfvars-override PR을 여는 라이브 Azure 어댑터 (preflight 라이브
 어댑터 착지 후, shadow-first). *(남음)*

## 참조

- [deployment-preflight-ko.md](deployment-preflight-ko.md) - 프로브 분류법, 토글 매핑 표, 리포트 형태
- [infra/modules/preflight-toggles/README.md](../../../infra/modules/preflight-toggles/README.md) - capability-mode 토글 모듈
- [architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) - 컨트롤 루프, quality 게이트, 안전 불변식, 액션 온톨로지
- [project-structure-ko.md](../architecture/project-structure-ko.md) - 실행기, 모듈 경계, infra 서브 모듈 패턴
- [risk-classification-ko.md](../decisioning/risk-classification-ko.md) - 차단 발견 사항이 `hil`로 라우팅되는 방식
- [coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md) - 7개 안전조건, shadow-first, ActionType 계약
