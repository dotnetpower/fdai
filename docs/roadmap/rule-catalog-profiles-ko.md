---
title: Rule-catalog profile 및 collector
translation_of: rule-catalog-profiles.md
translation_source_sha: 0cc11eb1881431f4a0536827f22032ffd7aad3d4
translation_revised: 2026-07-11
---
# Rule-catalog profile 및 collector

FDAI rule catalog 는 세 tier 의 콘텐츠를 갖는다:

1. **Hand-authored rules** [`rule-catalog/catalog/`](../../rule-catalog/catalog/)
   아래 - curated, T0-ready, real Rego check 와 PR-native remediation
   template 을 ship. T0 엔진이 non-recursively 로드.
2. **Machine-imported rules** [`rule-catalog/collected/`](../../rule-catalog/collected/)
   아래 - collector 파이프라인이 공개 upstream 소스 (Azure Policy
   built-in library, kube-bench 등) 로부터 자동 생성. 각 entry 는
   `check_logic.kind: expression` 과 upstream 정의로의 `reference:`
   를 carry; fork 또는 upstream curator 가 real Rego 를 authoring
   하여 `catalog/` 아래에 re-land 할 때까지 *reference-only*.
3. **Profiles** [`rule-catalog/profiles/`](../../rule-catalog/profiles/)
   아래 - 두 tier 중 어디에서든 rule id 를 참조하는 named bundle.
   Operator / fork 가 curated subset 을 한 단계로 활성화하는 방법.

이 문서는 [scope-expansion.md § 3](scope-expansion-ko.md) 의 전략적
결정에 따른 profile 계층 및 upstream 이 ship 하는 모든 collector 의
design contract 이다.

## 1. Profiles

Design contract: [scope-expansion.md § 3](scope-expansion-ko.md),
profile schema:
[`shared/contracts/profile/schema.json`](../../src/fdai/shared/contracts/profile/schema.json).

- **Upstream 은 세 개의 canonical profile 을 ship**:
  - `baseline` - 최소 안전 posture, ~10 rules, zero customization 으로
    어느 Azure tenant 에든 ship.
  - `recommended` `extends: [baseline]` - 표준 best-practice; diagnostic
    settings, private endpoints, purge protection, RBAC, 전체 tag matrix
    추가. 총 ~30 rules.
  - `strict` `extends: [recommended]` - regulated / zero-trust;
    security-critical rule 을 shadow 에서 `enforce` 로 이동. 총 ~40
    rules.
- **Upstream 은 또한 ~225 개의 auto-imported profile 을 ship**
  `rule-catalog/profiles/collected/` 아래 - Azure Policy built-in
  initiative 당 하나 (CIS Azure Foundations, NIST 800-53, PCI DSS,
  HIPAA HITRUST, ISO 27001, FedRAMP High / Moderate, GDPR, DORA,
  EU NIS2, CMMC 및 Microsoft 가 policy set 으로 publish 하는 모든
  regulatory framework). 각각 imported rule 을 FDAI id 로 참조.
- **Fork overrides** 는
  [`rule-catalog/profiles-overrides/`](../../rule-catalog/profiles-overrides/)
  아래 (upstream 은 empty). Fork 는 `extends: [strict]` 와 자신의
  override 를 갖는 YAML 을 추가하고, fork-owned id 를 부여하고,
  composition-root config 를 그 id 로 가리킴.

### Resolution

`ProfileRegistry.resolve(profile_id)` 는 `extends` DAG 를 walk 하고
child 를 parent 위에 merge. Merge 규칙:

- **Mode**: child override 승; missing = inherit; default = `shadow`.
- **Parameters**: `profile.parameters` <- parent rule params <- child
  rule params 순서의 shallow merge.
- **Severity override**: child 승; rule 의 authored floor 아래로의
  downgrade 는 `ProfileResolutionError` 발생 (fail-closed at load,
  not at runtime).
- **Disabled**: child `disabled: true` 는 resolved set 에서 rule 제거.
- `extends` graph 의 **cycles** 는 `ProfileResolutionError` 발생.
- **Unknown parent** 또는 **unknown rule id** (`known_rule_ids` 가
  supplied 될 때) 는 `ProfileResolutionError` 발생.

Resolved rule list 는 rule id 로 정렬되어 두 resolution 간 diff 가
byte-stable.

## 2. Collector 파이프라인

모든 source 는
[`rule-catalog/sources/<id>/manifest.yaml`](../../rule-catalog/sources/)
아래에
[`source_manifest.schema.json`](../../src/fdai/rule_catalog/schema/source_manifest.schema.json)
의 shape 로 declared. `parser` 필드는
[`src/fdai/rule_catalog/pipeline/parse/`](../../src/fdai/rule_catalog/pipeline/parse/)
아래 등록된 parser plugin 중 하나를 지정.

### Ship 된 upstream collector

| Source id | Origin | Parser | Landed rule 수 | Layout |
|-----------|--------|--------|----------------:|--------|
| `fdai-p1-seed` | this repo | `rule-yaml` | 55 hand-authored | `rule-catalog/catalog/*.yaml` |
| `azure-policy-builtin` | `Azure/azure-policy` | `azure-policy-json` | ~5000 | `rule-catalog/collected/azure-builtin/<Category>/*.yaml` |
| `kube-bench` | `aquasecurity/kube-bench` | `kube-bench` | ~4800 | `rule-catalog/collected/kube-bench/<ruleset>/*.yaml` |
| `gatekeeper-library` | `open-policy-agent/gatekeeper-library` | `rego` | (schema-only; collector wiring pending) | `rule-catalog/collected/gatekeeper/*.yaml` |

### Reserved-but-unimplemented parser

[`ParserName`](../../src/fdai/rule_catalog/pipeline/parse/parser.py) 에
declared 되어 manifest 가 이를 참조하면 clear 한
`ParserNotImplementedError` 로 collect time 에 fail:

- `checkov-yaml` (Bridgecrew / Prisma Checkov IaC rulesets)
- `gatekeeper-templates` (OPA Gatekeeper `ConstraintTemplate` YAML)

새 parser 추가는 두 단계 change: class 를 `parser.py` 의
`build_parser` 아래 등록하고, manifest 를 `rule-catalog/sources/`
아래 추가.

## 3. "모든 policy 를 갖는다" 의 의미

Upstream FDAI 는 산업에서 publish 하는 모든 policy 를 hand-author
**하지 않는다**. 대신 claim 하는 것:

1. **모든 공개 reference framework 를 import 할 수 있음**: collector
   파이프라인은 source-agnostic 이며 하나의 parser plugin 만으로 어떤
   well-formed JSON/YAML corpus 도 추가 가능.
2. **Import 된 reference 가 upstream 에 ship** 되어 fork 가 day one
   에 full corpus 를 inherit - 어떤 rule 이 있는지 확인하기 위한
   external tooling 불필요.
3. **Curation 은 collection 과 분리**: import 된 rule 은 curator 가
   real Rego 를 author 하기까지 `shadow`-only 유지되며 fail-closed
   `remediate.azure-policy-managed` ActionType 을 point. 이것이 한
   번에 수천 rule 을 import 해도 OK 하게 하는 safety invariant.

이 문서 시점의 coverage:

| Layer | Count |
|-------|------:|
| Hand-authored rules | 55 |
| Imported (Azure Policy built-in) | ~5000 |
| Imported (kube-bench CIS Kubernetes) | ~4800 |
| Profiles - upstream curated | 3 (`baseline`, `recommended`, `strict`) |
| Profiles - auto-imported compliance frameworks | ~225 (CIS / NIST / HIPAA / PCI / ISO / FedRAMP / GDPR / DORA / ...) |

## 4. Fork adoption playbook

Compliance posture 활성화를 위한 fork 의 일반 흐름:

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

Composition root 는 `FDAI_PROFILE_ID=customer-a` 를 읽고 resolved
profile 을 startup 시 `ControlLoop` / `T0Engine` / `RiskGate` 에
handoff.

> **배선 상태 (2026-07):** `ProfileRegistry` 라이브러리
> (`src/fdai/core/rule_catalog_profiles/`) 는 shipped 되고 테스트
> 커버 완료. 하지만 composition root 는 아직 `FDAI_PROFILE_ID` 를
> 읽지 않는다. 이 knob 이 런타임에 효과를 내려면
> [`src/fdai/composition.py`](../../src/fdai/composition.py) 에
> `resolve()` 호출이 추가되어야 한다. 지금 당장 profile 레이어가
> 필요한 fork 는 upstream default binder 가 배선되기 전까지
> wrapping factory 로 자체 resolved profile 을 바인딩 가능.

## 5. 이 문서가 아닌 것

- Rule authoring guide 아님 - 그것은
  [`rule-catalog/RULE_AUTHORING_GUIDE.md`](../../rule-catalog/RULE_AUTHORING_GUIDE.md)
  에 존재.
- Phase plan 아님 - phase 는
  [`docs/roadmap/phases/`](phases/) 아래 존재.
- Fork template 아님 - fork scaffolding 은
  [`downstream-fork-guide.md`](downstream-fork-guide-ko.md) 아래 존재.
