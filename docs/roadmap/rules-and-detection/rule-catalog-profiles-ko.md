---
title: Rule-catalog profile 및 collector
translation_of: rule-catalog-profiles.md
translation_source_sha: deef722c960e580777884a0587497dff3ee74ed2
translation_revised: 2026-08-29
---
# Rule-catalog 프로파일 및 수집기

FDAI 룰 카탈로그 는 세 계층 의 콘텐츠를 갖는다:

1. **Hand-authored 룰** [`rule-catalog/catalog/`](../../../rule-catalog/catalog)
   아래 - curated, T0-ready, real Rego 검사 와 PR-native 교정
   템플릿 을 ship. T0 엔진이 non-recursively 로드.
2. **Machine-imported 룰** [`rule-catalog/collected/`](../../../rule-catalog/collected)
   아래 - 수집기 파이프라인이 공개 업스트림 소스 (Azure Policy
   built-in library, kube-bench 등) 로부터 자동 생성. 각 항목 는
   `check_logic.kind: expression` 과 업스트림 정의로의 `reference:`
   를 carry; 포크 또는 업스트림 curator 가 real Rego 를 authoring
   하여 `catalog/` 아래에 re-land 할 때까지 *reference-only*.
3. **Profiles** [`rule-catalog/profiles/`](../../../rule-catalog/profiles)
   아래 - 두 계층 중 어디에서든 룰 id 를 참조하는 named 번들.
   Operator / 포크 가 curated subset 을 한 단계로 활성화하는 방법.

이 문서는 [scope-expansion.md § 3](../fork-and-sequencing/scope-expansion-ko.md) 의 전략적
결정에 따른 프로파일 계층 및 업스트림 이 ship 하는 모든 수집기 의
design 계약 이다.

## 1. Profiles

Design 계약: [scope-expansion.md § 3](../fork-and-sequencing/scope-expansion-ko.md),
프로파일 스키마:
[`shared/contracts/profile/schema.json`](../../../services/core-control-plane/src/fdai/shared/contracts/profile/schema.json).

- **업스트림 은 세 개의 정본 프로파일 을 ship**:
  - `baseline` - 최소 안전 자세, 10 룰, zero customization 으로
    어느 Azure 테넌트 에든 ship.
  - `recommended` `extends: [baseline]` - 표준 best-practice; 진단
    settings, 비공개 endpoints, 정리 protection, RBAC, 전체 tag 매트릭스
    추가. 현재 resolved 합계 44 룰.
  - `strict` `extends: [recommended]` - regulated / zero-trust;
    security-critical 룰 을 shadow 에서 `enforce` 로 이동. 현재 resolved 합계 45 룰.
- **업스트림은 검토된 가져온 프로파일 265개도 제공합니다.**
  `rule-catalog/profiles/collected/` 아래 - Azure Policy built-in
  initiative 당 하나 (CIS Azure Foundations, NIST 800-53, PCI DSS,
  HIPAA HITRUST, ISO 27001, FedRAMP High / Moderate, GDPR, DORA,
  EU NIS2, CMMC 및 Microsoft가 정책 집합으로 게시하는 모든 규정 준수 프레임워크).
  각 프로파일은 가져온 Rule을 FDAI id로 참조합니다. 이전 구체화 provenance는 재구성하지
  않았으며, 현재 승인된 소스 매니페스트는 오프라인 initiative-intent helper를 선택하지 않습니다.
  보존된 `provenance.authored_by`와 `review_cadence_days` 값은 과거 자체 설명이며 현재 예약
  collector의 근거가 아닙니다. 어떤 런타임 경로도 이 값을 권한으로 취급하지 않습니다.
- **포크 overrides** 는
  [`rule-catalog/profiles-overrides/`](../../../rule-catalog/profiles-overrides)
  아래 (업스트림 은 빈). 포크 는 `extends: [strict]` 와 자신의
  재정의 를 갖는 YAML 을 추가하고, fork-owned id 를 부여하고,
  composition-root 구성 를 그 id 로 가리킴.

### 해석

`ProfileRegistry.resolve(profile_id)` 는 `extends` DAG 를 walk 하고
하위 를 상위 위에 병합. 병합 규칙:

- **모드**: 하위 재정의 승; 누락된 = inherit; 기본값 = `shadow`.
- **Parameters**: `profile.parameters` <- 상위 룰 params <- 하위
  룰 params 순서의 shallow 병합.
- **심각도 재정의**: 하위 승; 룰 의 authored 하한 아래로의
  downgrade 는 `ProfileResolutionError` 발생 (실패 시 차단 at 부하,
  not at 런타임).
- **비활성화된**: 하위 `disabled: true` 는 resolved 집합 에서 룰 제거.
- `extends` 그래프 의 **cycles** 는 `ProfileResolutionError` 발생.
- **알 수 없음 상위** 또는 **알 수 없음 룰 id** (`known_rule_ids` 가
  supplied 될 때) 는 `ProfileResolutionError` 발생.

Resolved 룰 목록 는 룰 id 로 정렬되어 두 해석 간 차이 가
byte-stable.

## 2. Collector 파이프라인

모든 출처 는
[`rule-catalog/sources/<id>/manifest.yaml`](../../../rule-catalog/sources)
아래에
[`source_manifest.schema.json`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/source_manifest.schema.json)
의 형태 로 declared. `parser` 필드는
[`services/core-control-plane/src/fdai/rule_catalog/pipeline/parse/`](../../../services/core-control-plane/src/fdai/rule_catalog/pipeline/parse)
아래 등록된 파서 플러그인 중 하나를 지정.

### Ship 된 업스트림 수집기

| 출처 id | 출처 | 파서 | Landed 룰 수 | 배치 |
|-----------|--------|--------|----------------:|--------|
| `fdai-p1-seed` | this repo | `rule-yaml` | 61 hand-authored | `rule-catalog/catalog/*.yaml` |
| `azure-policy-builtin` | `Azure/azure-policy` | `azure-policy-json` | 3628 | `rule-catalog/collected/azure-builtin/<Category>/*.yaml` |
| `kube-bench` | `aquasecurity/kube-bench` | `kube-bench` | 4859 | `rule-catalog/collected/kube-bench/<ruleset>/*.yaml` |
| `gatekeeper-library` | `open-policy-agent/gatekeeper-library` | `rego` | (schema-only; 수집기 배선 pending) | `rule-catalog/collected/gatekeeper/*.yaml` |

### Reserved-but-unimplemented 파서

[`ParserName`](../../../services/core-control-plane/src/fdai/rule_catalog/pipeline/parse/parser.py) 에
declared 되어 매니페스트 가 이를 참조하면 clear 한
`ParserNotImplementedError` 로 collect 시간 에 fail:

- `checkov-yaml` (Bridgecrew / Prisma Checkov IaC rulesets)
- `gatekeeper-templates` (OPA Gatekeeper `ConstraintTemplate` YAML)

새 파서 추가는 두 단계 변경: 등급 를 `parser.py` 의
`build_parser` 아래 등록하고, 매니페스트 를 `rule-catalog/sources/`
아래 추가.

## 3. "모든 정책 를 갖는다" 의 의미

업스트림 FDAI 는 산업에서 publish 하는 모든 정책 를 hand-author
**하지 않는다**. 대신 점유 하는 것:

1. **모든 공개 참조 framework 를 가져오기 할 수 있음**: 수집기
   파이프라인은 source-agnostic 이며 하나의 파서 플러그인 만으로 어떤
   well-formed JSON/YAML 말뭉치 도 추가 가능.
2. **가져오기 된 참조 가 업스트림 에 ship** 되어 포크 가 일 one
   에 full 말뭉치 를 inherit - 어떤 룰 이 있는지 확인하기 위한
   외부 tooling 불필요.
3. **Curation 은 수집 과 분리**: 가져오기 된 룰 은 curator 가
   real Rego 를 작성자 하기까지 `shadow`-only 유지되며 실패 시 차단
   `remediate.azure-policy-managed` ActionType 을 지점. 이것이 한
   번에 수천 룰 을 가져오기 해도 OK 하게 하는 안전성 불변식.

이 문서 시점의 커버리지:

| 계층 | 개수 |
|-------|------:|
| Hand-authored 룰 | 61 |
| Imported (Azure Policy built-in) | 3628 |
| Imported (kube-bench CIS Kubernetes) | 4859 |
| Profiles - 업스트림 curated | 3 (`baseline`, `recommended`, `strict`) |
| Profiles - 검토된 가져온 compliance frameworks | 265 (CIS / NIST / HIPAA / PCI / ISO / FedRAMP / GDPR / DORA / ...) |

## 4. 포크 도입 playbook

Compliance 자세 활성화를 위한 포크 의 일반 흐름:

```yaml
# rule-catalog/profiles-overrides/customer-a.yaml
id: customer-a
title: (Customer A) posture
extends:
  - strict                                              # upstream base
  - compliance.regulatory-compliance.cis-azure-foundations-v3-0-0
parameters:
  tag.mandatory: [Environment, Owner, CostCenter, Confidentiality]
rules:
  - id: azure-builtin.object-storage.storage-account-should-require-secure-transfer
    mode: enforce
  - id: azure-builtin.sql-server.deprecated-audit-sql-servers-with-auditing-enabled
    disabled: true                                      # customer-specific exemption
```

조립 계약은 시작 시 `FDAI_PROFILE_ID=customer-a`를 읽어 한 번만 해석하고, 그 결과를 T0 색인이
담는 Rule 튜플에 반영합니다. 따라서 결정론 계층과 색인된 `Rule`을 평가하는 안전성 검토는 같은
불변 결과를 읽습니다.

> **배선 상태 (2026-08):** `ProfileRegistry` 라이브러리
> (`services/core-control-plane/src/fdai/core/rule_catalog_profiles/`)는 제공되고 테스트로
> 검증되며, 런타임 조립 루트는 이제
> [`services/core-control-plane/src/fdai/runtime/rule_profile.py`](../../../services/core-control-plane/src/fdai/runtime/rule_profile.py)에서
> `FDAI_PROFILE_ID`를 읽습니다. knob이 없거나 비어 있으면 전체 카탈로그를 적재하는 기본
> 동작을 유지합니다. 그 밖의 해석 실패는 모두 차단이므로, 시작 과정이 선택된 태세를 조용히
> 넓히지 않습니다. 프로파일은 Rule을 선택하고 등급만 조정합니다. 프로파일이 선언한 모드는
> 시작 진단에 보고될 뿐 실행 권한을 부여하지 않으며, 실행 권한은 정본 승격 레지스트리에
> 남습니다. 워크플로 guard 참조도 같은 활성 집합으로 검증되므로, guard Rule을 제외하는
> 프로파일은 첫 디스패치에서 실패하는 대신 부팅을 차단합니다.

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| 프로파일 계약 및 결정론적 해석 | implemented | `services/core-control-plane/src/fdai/core/rule_catalog_profiles/models.py`; `registry.py`; `services/core-control-plane/tests/core/rule_catalog_profiles/test_registry.py` | 상속, 재정의 우선순위, 순환 거부, 심각도 하한, 안정된 정렬을 검증합니다. |
| 정본 업스트림 프로파일 | implemented | `rule-catalog/profiles/baseline.yaml`; `recommended.yaml`; `strict.yaml`; `services/core-control-plane/tests/core/rule_catalog_profiles/test_full_profile_resolution.py` | 세 프로파일 모두 현재 알려진 Rule id를 기준으로 해석됩니다. |
| 가져온 규정 준수 프로파일 | implemented | `rule-catalog/profiles/collected/`; `services/core-control-plane/tests/core/rule_catalog_profiles/test_full_profile_resolution.py` | 수집된 프로파일은 참조 묶음으로 유지되며, 포함된 Rule은 구성원이라는 이유로 적용 권한을 얻지 않습니다. |
| 런타임 프로파일 선택 | implemented | `services/core-control-plane/src/fdai/runtime/rule_profile.py`; `services/core-control-plane/src/fdai/runtime/control_loop.py`; `services/core-control-plane/tests/runtime/test_rule_profile.py` | 시작 시 한 번의 해석이 T0 색인이 담는 Rule 튜플을 만들고, 결정론 계층과 안전성 검토가 같은 객체를 읽습니다. 배포 런타임 근거는 아직 남아 있습니다. |
| 예약된 파서 지원 | not-applicable | `rule-catalog/sources/*/manifest.yaml`; 파서 레지스트리 및 집중 선택 테스트 | 승인된 모든 제공 매니페스트는 구현된 파서를 선택합니다. `checkov-yaml`과 `gatekeeper-templates`는 향후 승인된 소스가 선택할 때까지 명시적인 차단 기본 자리표시자로 유지합니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-08-14 | in-progress | 이전 출처를 재구성하지 않고 구현 원장을 도입했습니다. | `current change`; 구현 범위 표의 현재 소스, 카탈로그, 집중 테스트. | 런타임 프로파일 선택을 연결하고 제공 대상으로 선택한 파서 플러그인만 구현합니다. |
| 2026-08-15 | implemented | 시작 시 `FDAI_PROFILE_ID`를 한 번 해석해 바인딩하고, 선택과 등급 조정을 차단 기본으로 처리하며, 프로파일 id와 다이제스트와 개수만 노출하는 시작 진단을 추가했습니다. | `current change`; `services/core-control-plane/src/fdai/runtime/rule_profile.py`; `services/core-control-plane/src/fdai/runtime/control_loop.py`; `pytest services/core-control-plane/tests/runtime/test_rule_profile.py` (12 passed). | 바인딩된 프로파일의 배포 런타임 근거. 예약 파서는 계속 미구현입니다. |
| 2026-08-29 | not-applicable | 승인된 모든 제공 소스 매니페스트를 파서 레지스트리와 대조했습니다. 예약 파서를 선택하는 소스가 없으므로 차단 기본 자리표시자가 미완성 구현이 아니라 현재 범위의 완전한 동작입니다. | `current change`; 소스 매니페스트, `parser.py`, 집중 파서 선택 검사. | 향후 승인된 소스 매니페스트와 함께만 예약 파서를 구현합니다. |
| 2026-08-29 | implemented | 수집된 프로파일 provenance 주장을 바로잡았습니다. 프로파일 265개는 검토된 정적 가져오기 결과이며 initiative-intent helper는 오프라인이고 등록되지 않았습니다. 실행 가능한 매니페스트-파서 선택 검사를 추가했습니다. | `current change`; `azure_policy_initiative.py`; `test_parse.py`; 집중 파서 및 프로파일 검사. | 향후 자동 initiative 새로 고침에는 승인된 소스와 GUID-to-Rule 컴파일러가 필요합니다. |
| 2026-08-29 | implemented | 하드닝 17-20차에서 프로파일 해석, 런타임 연결, 파서 선택, 과거 provenance를 검증했습니다. 도달할 수 없는 initiative helper 주장을 바로잡은 뒤 최종 검토에서 Low를 넘는 문제는 없었습니다. | `current change`; 집중 프로파일 및 파서 검사 58개 통과. | 배포 런타임 근거는 운영 검증으로 남습니다. |

### 남은 작업

- [x] 시작 바인더가 관리되는 프로파일 id를 한 번 읽고, 안전성 검토도 함께 읽는 T0 색인에 해석된 Rule 튜플을 전달합니다. `services/core-control-plane/tests/runtime/test_rule_profile.py`가 이를 증명합니다.
- [x] 시작 진단은 프로파일 id와 다이제스트와 개수만 노출합니다. Rule 매개변수는 다이제스트에는 기여하지만 로그 레코드에는 남지 않으며, 같은 집중 테스트 모듈이 이를 증명합니다.
- [ ] 고정된 리비전에서 바인딩된 프로파일 id와 다이제스트를 보여 주는 배포 런타임 영수증을 확보합니다.
- [x] 승인된 모든 제공 소스는 구현된 파서를 선택합니다. 예약 파서 이름은
  `ParserNotImplementedError`를 계속 반환하며 향후 승인된 소스 매니페스트와 집중 픽스처가
  함께 있을 때만 구현을 시작합니다.

## 5. 이 문서가 아닌 것

- Rule authoring guide 아님 - 그것은
  [`rule-catalog/RULE_AUTHORING_GUIDE.md`](../../../rule-catalog/RULE_AUTHORING_GUIDE.md)
  에 존재.
- 단계 계획 아님 - 단계 는
  [`docs/roadmap/phases/`](../phases) 아래 존재.
- 포크 템플릿 아님 - 포크 scaffolding 은
  [`downstream-fork-guide.md`](../fork-and-sequencing/downstream-fork-guide-ko.md) 아래 존재.
