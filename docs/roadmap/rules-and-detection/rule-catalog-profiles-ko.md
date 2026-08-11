---
title: Rule-catalog profile 및 collector
translation_of: rule-catalog-profiles.md
translation_source_sha: dde16ae7e74319d3590df1c022752cea8486bb15
translation_revised: 2026-08-11
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
- **업스트림 은 또한 265 개의 auto-imported 프로파일 을 ship**
 `rule-catalog/profiles/collected/` 아래 - Azure Policy built-in
 initiative 당 하나 (CIS Azure Foundations, NIST 800-53, PCI DSS,
 HIPAA HITRUST, ISO 27001, FedRAMP High / Moderate, GDPR, DORA,
 EU NIS2, CMMC 및 Microsoft 가 정책 집합 으로 publish 하는 모든
 regulatory framework). 각각 imported 룰 을 FDAI id 로 참조.
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
| Profiles - auto-imported compliance frameworks | 265 (CIS / NIST / HIPAA / PCI / ISO / FedRAMP / GDPR / DORA / ...) |

## 4. 포크 도입 playbook

Compliance 자세 활성화를 위한 포크 의 일반 흐름:

```yaml
# rule-catalog/profiles-overrides/customer-a.yaml
id: customer-a
title: (Customer A) posture
extends:
 - strict            # upstream base
 - compliance.regulatory-compliance.cis-azure-foundations-v3-0-0
parameters:
 tag.mandatory: [Environment, Owner, CostCenter, Confidentiality]
rules:
 - id: azure-builtin.object-storage.storage-account-should-require-secure-transfer
 mode: enforce
 - id: azure-builtin.sql-server.deprecated-audit-sql-servers-with-auditing-enabled
 disabled: true          # customer-specific exemption
```

목표 조립 계약은 `FDAI_PROFILE_ID=customer-a`를 읽고 resolved 프로파일을 시작 시
`ControlLoop` / `T0Engine` / `RiskGate`에 인계합니다. 기본값 조립은 아직 이 계약을
구현하지 않습니다.

> **배선 상태 (2026-07):** `ProfileRegistry` 라이브러리
> (`services/core-control-plane/src/fdai/core/rule_catalog_profiles/`) 는 shipped 되고 테스트
> 커버 완료. 하지만 조립 루트 는 아직 `FDAI_PROFILE_ID` 를
> 읽지 않는다. 이 knob 이 런타임에 효과를 내려면
> [`services/core-control-plane/src/fdai/composition/`](../../../services/core-control-plane/src/fdai/composition/) 에
> `resolve()` 호출이 추가되어야 한다. 지금 당장 프로파일 레이어가
> 필요한 포크 는 업스트림 기본값 연결기 가 배선되기 전까지
> wrapping factory 로 자체 resolved 프로파일 을 바인딩 가능.

## 5. 이 문서가 아닌 것

- Rule authoring guide 아님 - 그것은
 [`rule-catalog/RULE_AUTHORING_GUIDE.md`](../../../rule-catalog/RULE_AUTHORING_GUIDE.md)
 에 존재.
- 단계 계획 아님 - 단계 는
 [`docs/roadmap/phases/`](../phases) 아래 존재.
- 포크 템플릿 아님 - 포크 scaffolding 은
 [`downstream-fork-guide.md`](../fork-and-sequencing/downstream-fork-guide-ko.md) 아래 존재.
