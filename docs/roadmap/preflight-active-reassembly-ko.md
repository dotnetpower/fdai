---
title: 프리플라이트 능동 플랜 재조립 (policy blocker에서 재렌더된 terraform으로)
translation_of: preflight-active-reassembly.md
translation_source_sha: c6bb14b73d9c817fd63eb078080f01b0ab814f65
translation_revised: 2026-07-10
---
# 프리플라이트 능동 플랜 재조립 (policy blocker에서 재렌더된 terraform으로)

[deployment-preflight](deployment-preflight-ko.md)가 등록된 capability-mode 토글을
가진 `policy_guardrail` 또는 `supply_chain_egress` blocker를 보고할 때, 시스템은
"여기 문제가 있다"에서 멈추지 않습니다. 시스템은 **terraform 플랜을 능동적으로
재렌더**하여 지원되는 대체 형태로 - 애초에 거부되는 연산을 emit하지 않는 형태로 -
바꾸고, 그 변경을 기존 [executor](project-structure-ko.md)를 통해 remediation PR로
전달합니다. 이것은 거부된 리소스 타입이나 차단된 패키지 소스를 하드 스톱에서 스스로
해소되는 finding으로 바꿉니다.

이 문서는 **능동 재조립 루프, 그 수렴과 stop-condition, 그것을 실어 나르는 ActionType,
그리고 무엇이 재조립될 수 있는지에 대한 정직한 한계**에 대해 권위를 가집니다. blocker
분류법, 토글 매핑 표, 리포트 형태는
[deployment-preflight-ko.md](deployment-preflight-ko.md)에 남습니다. 토글 모듈 자체는
[infra/modules/preflight-toggles/](../../infra/modules/preflight-toggles/README.md)에
있습니다.

> 고객-비종속: 어떤 denylist 값, 미러 엔드포인트, 토글 기본값도 상류에 하드코딩되지
> 않습니다. 상류는 재조립 기계 장치와 제네릭 토글 카탈로그를 제공합니다. 포크가 특정
> 가드레일 값과 consumer 배선을 공급합니다
> ([generic-scope.instructions.md](../../.github/instructions/generic-scope.instructions.md)).

## 왜 가능한가 (그리고 마법이 아닌가)

레일은 이미 존재합니다. 능동 재조립은 그것들을 끝에서 끝까지 잇습니다:

1. **탐지** - `FeasibilityProbe`가 근거 있는 `ProbeFinding`을 emit합니다
   ([feasibility_probe.py](../../src/fdai/shared/providers/feasibility_probe.py)).
2. **매핑** - finding이 정확한 infra 서브 모듈과 배포를 준수하게 만드는 변수 override를
   지명하는 `ProbeResolution(kind=TERRAFORM_TOGGLE, autofix, module, set_vars)`를
   실어 나릅니다.
3. **대체 렌더링** -
   [preflight-toggles](../../infra/modules/preflight-toggles/README.md) 모듈이 준수하는
   형태(`disk_provisioning=attach_existing`, `registry_source=acr_mirror`, ...)를
   data-only Terraform으로 인코딩합니다.

빠져 있던 - 그리고 이 설계가 추가하는 - 두 조각은:

- **토글-적용 executor**: `autofix` `terraform_toggle` finding을 받아 tfvars override를
  렌더하고 remediation PR을 여는 것. 오늘 resolution은 선언되어 있지만 실행되지 않으며,
  리포트는 PR에 *게시*되기만 합니다
  ([check_publish.py](../../src/fdai/core/deploy_preflight/check_publish.py)).
- **수렴 루프**: 재조립된 플랜 위에서 preflight를 다시 실행하여 한 blocker의 수정이 다른
  blocker를 조용히 도입하지 못하게 합니다.

## 재조립 루프

재조립은 단발이 아니라 bounded·deterministic 루프입니다 - 재렌더된 플랜은 토글이
blocker를 제거하는 대신 이동시킬 수 있으므로 다시 확인되어야 합니다.

```text
terraform plan (JSON)
  -> preflight.analyze
       -> CLEAR              -> 플랜 전달 / 머지
       -> BLOCKED + 모든 blocking finding에 autofix 토글 있음
                            -> tfvars override 렌더 (재조립)
                            -> 재-plan -> preflight.analyze로 복귀   (bounded)
       -> BLOCKED + 어떤 blocking finding에 autofix 토글 없음
                            -> hil (부분 autofix는 절대 적용 안 함)
```

- **패스당 all-or-nothing**: 재조립은 *모든* blocking finding이 `autofix` 토글을 가질
  때만 진행됩니다. 단 하나의 manual-resolution blocker가 전체 패스를 `hil`로
  라우팅합니다 - 루프는 여전히 apply를 실패시킬 부분 수정을 절대 적용하지 않습니다.
- **verifier가 authority**: 재조립된 플랜은 토글이 적용되었다는 이유로 신뢰되는 것이
  아니라 동일한 deterministic preflight(OPA 재검증 + what-if)에 의해 다시 확인됩니다.
  이것은
  [quality-gate 규칙](../../.github/instructions/architecture.instructions.md#llm-quality-gate-required-for-t2)을
  반영합니다: 실행 자격은 수정 생성기가 아니라 검증에 의해 부여됩니다.

### 수렴과 Stop-Condition

루프는 반드시 종료되어야 합니다. 그 stop-condition은 최적화가 아니라 안전 불변식입니다:

| Stop-condition | 효과 |
|----------------|--------|
| `max_reassembly_iterations` (기본 3) 초과 | `hil`로 라우팅, 마지막 리포트 첨부 |
| 동일 finding id에 대해 동일 토글이 두 번 제안됨 | 비수렴 -> `hil` (flip-flop / 무한 루프 방지) |
| 재조립 패스가 이전 패스보다 *더 많은* blocking finding을 생성 | 회귀 -> `hil` |
| 어떤 프로브라도 raise | fail-closed -> `hil` (부분 패스 위에서 절대 재조립 안 함) |

반복 카운터, finding별 토글 이력, 캡은 하드코딩 리터럴이 아니라 config이므로 포크가
`core/`를 편집하지 않고 튜닝할 수 있습니다.

## ActionType: `remediate.apply-preflight-toggle`

능동 재조립은 **새로운** 특권 경로가 **아닙니다**. 일급 온톨로지 `ActionType`을 등록하여
기존 [executor](../../src/fdai/core/executor/executor.py)를 재사용하므로, 네 개의 안전
불변식, shadow-first 게이팅, append-only 감사 항목이 공짜로 따라옵니다 (콘솔 어휘가 모든
액션을 타입드 파이프라인으로 라우팅하는 것과 같은 이유,
[architecture.instructions.md](../../.github/instructions/architecture.instructions.md#action-ontology-and-console-vocabulary)
참조).

선언 (`rule-catalog/action-types/` 아래에서 작성):

- `category: remediation`
- `trigger_kind: both` - preflight 루프가 blocking finding에 대해 자동으로
  개시하며, 오퍼레이터가 특정 토글을 요청할 수 있습니다. 파라메트릭합니다
  (`argument_schema`: `scope`, `finding_id`, `toggle_module`, `set_vars`,
  `reason`), 따라서 정적 리소스-posture 규칙이 아닙니다.
- `execution_path: pr_native` - 변경은 infra 리포에 대한 tfvars-override PR이며, 직접
  substrate mutation이 아닙니다.
- `rollback_contract: pr_revert` - PR을 revert하면 이전 tfvars가 복원됩니다. 재조립은
  완전히 되돌릴 수 있으므로 `irreversible: false`.
- `default_mode: shadow` - 첫 출시는 판단하고 PR을 `shadow` 라벨의 draft로 렌더하며,
  절대 자동 머지하지 않습니다.
- `promotion_gate` - enforce로의 카테고리별 승격 전에 frozen 시나리오 셋에서 측정됨
  (토글 매핑의 false-positive rate).
- `preconditions` - `graph_fresh_within_seconds`(플랜과 환경 프로파일이 최신이어야 함)
  및 `no_conflicting_open_action_on_resource`.
- `stop_conditions` - 위의 수렴 캡, 그리고 표준 `time_box_exceeded_seconds`와
  `provider_api_error_streak`.
- `blast_radius` - override가 건드리는 infra 변수의 집합. 캡보다 많은 토글을 뒤집을
  재조립은 `hil`로 abstain합니다.

### Autofix 자격 게이트

`autofix` PR은 다음이 모두 성립할 때만 자동 제안됩니다. 그렇지 않으면 finding은
guidance + `hil`로 격하됩니다:

1. resolution `kind`가 `autofix: true`인 `TERRAFORM_TOGGLE`이다;
2. 토글이 **deterministic** data-only 모듈이다 (경로에 LLM 없음);
3. 재조립된 플랜이 preflight를 다시 통과한다 (verifier 재검증);
4. override가 선언된 `blast_radius` 안에 머문다.

`autofix: false` 토글은 여전히 *제안된* diff를 렌더하지만, 자동으로 열리는 remediation이
아니라 PR 위의 리뷰 guidance로서입니다 - 오퍼레이터가 변수를 뒤집습니다.

## 무엇을 재조립할 수 있고 없는가

경계에 대한 정직함은 부수 조건이 아니라 안전 속성입니다:

- **재조립 가능** - 등록된 대체 렌더링을 가진 blocker: 인라인 disk deny ->
  `attach_existing`; 차단된 `docker.io` egress -> `acr_mirror`; NSG create deny ->
  `byo`; PyPI egress deny -> 내부 `python_index_url`; 순서 위반 ->
  `dependency_ordering=strict`.
- **재조립 불가 (`hil`로 라우팅)** - 지원되는 대체가 없는 정책: 완전히 금지된 region,
  강제-태그 정책, 대체 SKU가 없는 거부된 SKU, 또는 유일한 해결책이 scoped exemption이나
  거버넌스 결정인 가드레일. 이들은 `MANUAL` resolution을 emit하며 절대 자동 재조립하지
  않습니다.

discovery 루프는 환경 전반에서 반복되는 `MANUAL` blocker를 **새로운** 토글(새 기본 대체
렌더링)을 제안하라는 신호로 취급하며, 이는 표준 quality gate를 통해 카탈로그에
진입합니다
([architecture.instructions.md § Rule Catalog](../../.github/instructions/architecture.instructions.md#rule-catalog)).

## 안전 불변식

모든 재조립 액션은 그것이 재사용하는 executor에 의해 강제되어 네 개의 불변식을 모두
만족합니다:

- **Stop-condition** - ActionType에 선언된 위의 수렴 캡.
- **Rollback path** - `pr_revert`; override PR은 이전 플랜에서 단일 커밋 revert 거리에
  있으며, rollback reference가 PR 본문에 삽입됩니다.
- **Blast-radius limit** - 재조립은 선언된 infra 변수만 건드립니다. 캡 초과는 `hil`로
  abstain합니다.
- **Audit-log entry** - 모든 종단 결과(재조립 + PR 게시, 수렴-clear, 비수렴 -> hil,
  부분-blocker -> hil, 프로브 raise -> fail-closed)는 하나의 해시 체인 감사 레코드를
  씁니다.

재조립은 **shadow-first**로 출시됩니다: 토글 매핑의 false-positive rate가 측정되고
카테고리가 enforce로 명시적으로 승격되기 전까지, PR은 판단·렌더되지만 머지되지 않는
draft입니다.

## 서브시스템 레이아웃

| 조각 | 위치 | 상태 |
|-------|----------|--------|
| finding 위의 토글 resolution | [feasibility_probe.py](../../src/fdai/shared/providers/feasibility_probe.py) | 완료 |
| capability-mode 토글 모듈 | [infra/modules/preflight-toggles/](../../infra/modules/preflight-toggles/README.md) | 완료 (data-only) |
| Readiness 리포트 + verdict | [core/deploy_preflight/report.py](../../src/fdai/core/deploy_preflight/report.py) | 완료 |
| 리포트 -> PR 체크 게시 | [core/deploy_preflight/check_publish.py](../../src/fdai/core/deploy_preflight/check_publish.py) | 완료 (리포트만) |
| 수렴 루프 + stop-condition | [core/deploy_preflight/reassemble.py](../../src/fdai/core/deploy_preflight/reassemble.py) | 완료 |
| `remediate.apply-preflight-toggle` ActionType | [rule-catalog/action-types/](../../rule-catalog/action-types/remediate.apply-preflight-toggle.yaml) | 완료 |
| 참조 consumer 배선 (토글 하나) | [infra/modules/preflight-toggles/reference-disk-consumer/](../../infra/modules/preflight-toggles/reference-disk-consumer/README.md) | 완료 (포크가 복사) |
| **overrides -> executor `Action` 렌더 + PR 오픈** | `core/deploy_preflight/` + composition root | **남음** |

`core/`는 `FeasibilityProbe` Protocol과 `RemediationPrPublisher` seam만 봅니다.
재조립 루프는 어떤 클라우드 SDK도 구성하지 않고 PR을 직접 열지 않습니다 - override를
결정하고 (ActionType을 통해) executor에 넘기며, executor가 게시와 불변식을 소유합니다.

## 전달 증분

각각은 개별적으로 리뷰 가능합니다:

1. **Docs-first** (이 문서) - 루프, ActionType, 한계. *(완료)*
2. `remediate.apply-preflight-toggle` ActionType YAML + 스키마 검증. *(완료)*
3. bounded 수렴 루프, shadow-mode, property 테스트와 함께: "동일 토글은 절대 두 번
   적용 안 함", "부분 blocker -> hil", "재조립된 플랜은 재검증됨", "회귀 -> hil",
   "raise하는 reanalyze에 fail-closed". *(완료)*
4. `infra/` 아래 참조 consumer 배선 하나(`disk_provisioning` 토글)로 포크가 복사-붙여넣기
   시작점을 갖게 함. *(완료)*
5. overrides-to-executor 단계: 누적된 override를 `remediate.apply-preflight-toggle`
   `Action`으로 렌더하고 executor를 통해 tfvars-override PR을 엽니다 (shadow-first).
   *(남음)*
6. 실제 policy finding을 루프에 공급하는 라이브 Azure 어댑터 (preflight 라이브 어댑터
   착지 후, shadow-first).

## 참조

- [deployment-preflight-ko.md](deployment-preflight-ko.md) - 프로브 분류법, 토글 매핑 표, 리포트 형태
- [infra/modules/preflight-toggles/README.md](../../infra/modules/preflight-toggles/README.md) - capability-mode 토글 모듈
- [architecture.instructions.md](../../.github/instructions/architecture.instructions.md) - 컨트롤 루프, quality gate, 안전 불변식, 액션 온톨로지
- [project-structure-ko.md](project-structure-ko.md) - executor, 모듈 경계, infra 서브 모듈 패턴
- [risk-classification-ko.md](risk-classification-ko.md) - blocking finding이 `hil`로 라우팅되는 방식
- [coding-conventions.instructions.md](../../.github/instructions/coding-conventions.instructions.md) - 네 개의 안전 불변식, shadow-first, ActionType 계약
