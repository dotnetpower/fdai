---
title: 규칙 카탈로그 수집(Rule Catalog Collection)
translation_of: rule-catalog-collection.md
translation_source_sha: cf8f7cb9783c244b13970c3c69d97486721bb7ee
translation_revised: 2026-07-07
---

# 규칙 카탈로그 수집(Rule Catalog Collection)

AIOpsPilot가 체크리스트, 모범 사례, 정책, 베이스라인을 어떻게 **수집** 하고 T0 결정론 엔진을
위해 기계 판독 가능 YAML로 **정규화** 하는가. 이 문서가 답하는 것: *규칙은 어디서 오는가,
어떻게 fetch되는가, 어떤 YAML 형상을 취하는가?*

[phase-1-rule-catalog-t0-ko.md](phases/phase-1-rule-catalog-t0-ko.md) 의 정규화 스키마 및 충돌
처리와
[architecture.instructions.md](../../.github/instructions/architecture.instructions.md) 의
규칙 카탈로그 원칙을 재진술하지 않고 보완. 지속 업데이트 파이프라인은
[phase-2-quality-and-t1-ko.md](phases/phase-2-quality-and-t1-ko.md).

> 여기 모든 것은 고객-비종속.
> [generic-scope.instructions.md](../../.github/instructions/generic-scope.instructions.md) 에
> 따라 합성 placeholder만 사용.

## 무엇을 수집하는가

네 별개 아티팩트 종류, 각각 자체 YAML 형상으로 정규화되지만 `provenance` 공유:

| 종류 | 예시 | 사용처 |
|------|------|--------|
| **Rule / check** | 하나의 테스트 가능한 컨트롤(예: "storage는 public access를 거부해야 함") | T0 정책 평가 |
| **Best practice** | 근거 있는 권고, 종종 다중-check(예: WAF pillar 가이드) | T0 체크리스트 + grounding 인용 |
| **Config baseline** | 리소스 타입의 하드닝된 reference 세트(예: 클러스터 하드닝 베이스라인) | T0 drift / what-if |
| **Measurement baseline** | 고정 시나리오 세트의 reference agent에 대한 기록된 KPI 값 | goals-and-metrics 비교 |

처음 셋은 결정론 엔진에 공급. 넷째는
[phase-0-instrumentation-ko.md](phases/phase-0-instrumentation-ko.md) 의 **성능 베이스라인** -
다른 개념이며 이 문서는 둘 다 "베이스라인" 이라는 이유로만 공유; 저장소와 스키마에서 분리 유지.

## 수집 소스

원본별로 그룹화. 각 소스는 네이티브 포맷을 정규화 스키마로 매핑하고 `provenance` 를 스탬프하는
**컬렉터** 가짐. `resource-type` 은 CSP-중립 어휘로 정규화.

| 그룹 | 소스 | 네이티브 포맷 | Fetch 방법 |
|------|------|--------------|-----------|
| Azure-네이티브 | WAF checklists, AKS Baseline, MCSB, Azure Policy built-in initiatives, Advisor, Defender recommendations | JSON / ARM policy / docs | REST API, policy definitions export, docs repo |
| Cloud-중립 / OSS | CIS Benchmarks, OPA/Gatekeeper libraries, Cloud Custodian policies | PDF/spreadsheet, Rego, YAML | git clone, package registry, licensed download |
| IaC 스캐너 | Checkov, tfsec, KICS, Trivy | 내장 rule pack (YAML/JSON/Go) | git clone, package registry |
| Kubernetes | kube-bench, Gatekeeper constraint templates | YAML | git clone |
| 코드 품질 | SonarQube rulesets, Roslyn analyzers, ESLint | XML/JSON | package registry, API |
| FinOps / 비용 | Advisor 비용 권고, 비용-이상 휴리스틱, FOCUS-정렬 tagging/budget 컨트롤 | JSON / authored | REST API, authored |
| DR / resilience | resiliency-review checklist, backup/replication 컨트롤, chaos-experiment 템플릿 | JSON / YAML / docs | REST API, git clone, docs repo |
| Detection / signals | 이상 베이스라인과 임계, 예보 대상, 상관관계 키(observability-and-detection의 감지기에 공급) | authored / JSON | authored |
| AWS / GCP (TBD) | AWS Well-Architected / Config managed rules, GCP Recommender / Policy Controller | JSON | REST API, git - **연기**, 비-Azure 대상은 TBD ([Implementation Focus](../../.github/copilot-instructions.md#implementation-focus-must) 참조) |

FinOps와 DR/resilience 행은 컨트롤 플레인이 Resilience, Change Safety, Cost Governance에
걸쳐 있기 때문에 존재;
security/config만 커버하는 소스 테이블은 세 버티컬 중 둘을 미수집 상태로 남김. Detection/signals
행은 [observability-and-detection-ko.md](observability-and-detection-ko.md) (이상, 예보,
상관관계, RCA) 가 소비하는 베이스라인, 임계, 상관관계 키를 공급. 컨트롤을 규제 프레임워크
(NIST/PCI/ISO) 에 매핑하는 것은 연기 - [Open Decisions](#open-decisions) 참조.

### 보안 소스 (심층)

보안은 가장 높은 심각도 카테고리이며 다른 어떤 것보다 많은 소스를 끌어옴, 그래서 명시적으로 열거.
각각은 여전히 `category: security` 로 공통 스키마로 정규화.

| 레이어 | 소스 | 네이티브 포맷 | Fetch 방법 |
|--------|------|--------------|-----------|
| Cloud posture | MCSB, Defender for Cloud recommendations, Azure Security Benchmark, CIS cloud benchmarks | JSON / policy / docs | REST API, git, licensed download |
| Vulnerability / threat intel | NVD/CVE (CVSS base score 있음), CISA KEV 카탈로그, EPSS, GitHub Advisory Database, OSV | JSON feed | REST API, git |
| Threat modeling | MITRE ATT&CK, MITRE D3FEND (technique → control mapping) | STIX / JSON | REST API, git |
| Standards / 프레임워크 | NIST SP 800-53, ISO 27001, PCI-DSS, SOC 2, CIS Controls | spreadsheet / docs | docs / licensed download (소스별 재배포) |
| Identity / access | 최소권한 롤 베이스라인, context-based (conditional) access 베이스라인, RBAC drift 검사 | authored / JSON | authored, REST API |
| Application / code | OWASP Top 10, OWASP ASVS, SAST/DAST ruleset, secret-scanning 규칙 (gitleaks/trufflehog) | JSON / YAML | git, package registry |
| Supply chain | Trivy/Grype vuln DB, SBOM 정책 (CycloneDX/SPDX), 서명 정책 (Sigstore/cosign), provenance attestation (SLSA/in-toto) | JSON / YAML | git, package registry |
| 네트워크 | NSG/firewall exposure 규칙, TLS/cipher 정책, private-endpoint 강제 | authored / policy | authored, REST API |

노트:

- **신선도**: 취약성 소스(NVD/CVE, KEV, OSV, EPSS) 는 시간-민감 - 매일 변경되고 KEV 엔트리는
  remediation due-date 운반 - 그래서 그 manifest는 가장 짧은 watcher 주기를 설정하고 Phase 2
  watcher의 동기 케이스. Phase 1 on-demand fetch는 잠재적으로 stale로 취급, 현재성에 대해 권위
  아님.
- **심각도 파생은 결정론적** , ad hoc 아님: 취약성 규칙의 경우 `severity` 는 고정된 **CVSS base
  score** 의 순수 함수 (`>= 9.0` → `critical`, `>= 7.0` → `high`, `>= 4.0` → `medium`, else
  `low`), **KEV 존재는 `critical` 로 escalate**. 사용된 CVSS 버전(v3.1 또는 v4.0) 은 규칙에
  기록됨(예: `parameters.cvss_version`) - 스코어가 재현 가능. 비-취약성 규칙은 이 매핑이 아니라
  source/category 기본 severity 취함.
- **위협 매핑**: MITRE ATT&CK technique id와 D3FEND control id는 컴플라이언스/위협 crosswalk
  ([Open Decisions](#open-decisions) 참조) 를 통해 매핑 태그로 규칙에 부착, 절대 실행 가능한
  `check_logic` 이 아님.
- **표준 라이선스는 소스마다 다름**: 일부는 public-domain 및 재배포 가능(예: NIST SP 800-53),
  다른 것은 텍스트가 라이선스됐기 때문에 **reference-only** (예: CIS, ISO 27001, PCI-DSS).
  Reference-only 표준의 경우 우리는 check를 작성하고 `provenance` 와 컴플라이언스 crosswalk를
  통해 컨트롤 id를 인용; `redistribution` 은 per-source로 설정, 절대 가정 아님.

### 데이터베이스 소스와 규칙

데이터베이스는 **stateful** 이므로 규칙이 세 관심사(보안, DR, 설정) 에 걸쳐 있으며 stateless
리소스처럼 절대 취급되어선 안 됨. 이 하위 섹션은 DB 커버리지가 그렇지 않으면 under-specify되기
쉬워 열거됨.

| 관심사 | 수집되는 것 | 예시 소스 |
|--------|-----------|----------|
| DB 보안 | 저장 시 암호화(TDE/CMK), TLS-in-transit 강제, 인증 모드(identity-only, shared secret 없음), 방화벽 / private endpoint, 최소권한 DB 롤, 감사 로깅, 시크릿 로테이션 | 엔진별 CIS 벤치마크(SQL Server, PostgreSQL, MySQL, MongoDB, Oracle), cloud DB security 베이스라인, MCSB data 컨트롤 |
| DB DR / resilience | PITR 활성 + retention 윈도우, geo-replication / read-replica 존재, 백업 스케줄 + retention 윈도우 내 restore rehearsal 통과 증거, replication-lag 임계, RPO/RTO 목표 준수, failover 후 무결성-검증 증거 | resiliency-review checklist, backup/replication 컨트롤 카탈로그, authored DR 규칙 |
| DB 설정 | 파라미터 하드닝, 연결/세션 상한, 로깅/slow-query 설정, 버전/패치 현재성, public-network-access 비활성 | CIS DB 벤치마크, 엔진 하드닝 가이드 |

DB 규칙은 `sql-database`, `postgresql-server`, `nosql-database`, `cache` 같은 CSP-중립
`resource_type` 값 사용. 이들은 **DB 엔진 패밀리** (CSP 간 엔진-중립, 벤더 리소스 경로 아님) 를
인코딩, 그래서 엔진별 CIS 컨트롤이 ARM 경로를 유출하지 않고 재현 가능; DB-보안 관심사는
`category: security`, DB-DR은 `category: reliability`, DB-설정 하드닝은 `category:
config-drift` 로 매핑. DR 규칙은
[phase-3-integrated-loop-ko.md](phases/phase-3-integrated-loop-ko.md) (deep DB-DR:
restore-into-isolated-env, 무결성 검증, RPO/RTO 측정) 에 크로스 링크 - 카탈로그는 기록된 증거
위의 *check* 를 인코딩; phase-3 스케줄러가 *테스트* (rehearsal와 failover 자체) 를 실행.

두 DB 규칙 예시(고객-비종속 placeholder):

```yaml
id: sql-database.encryption.tde-required
version: 1.0.0
kind: rule
source: example-db-benchmark
severity: high
category: security
resource_type: sql-database
check_logic:
  engine: rego
  ref: policies/sql_database/tde_required.rego
  entrypoint: deny_tde_disabled
remediation:
  kind: iac-patch
  ref: remediation/sql_database/enable_tde.tftpl
provenance:
  source_url: https://example.com/db-benchmark/controls/2.1
  source_version: v1.0.0
  resolved_ref: "0000000000000000000000000000000000000000"
  content_hash: "sha256:0000000000000000000000000000000000000000000000000000000000000000"
  license: LicenseRef-reference-only
  retrieved_at: 2026-07-03T00:00:00Z
  mapped_by: catalog-team
```

```yaml
id: postgresql-server.dr.pitr-required
version: 1.0.0
kind: rule
source: example-dr-catalog
severity: high
category: reliability
resource_type: postgresql-server
parameters:
  min_backup_retention_days: 7
check_logic:
  engine: rego
  ref: policies/postgresql/dr_pitr.rego
  entrypoint: deny_pitr_disabled_or_short_retention
remediation:
  kind: iac-patch
  ref: remediation/postgresql/enable_pitr.tftpl
provenance:
  source_url: https://example.com/dr-catalog/postgresql
  source_version: v1.0.0
  resolved_ref: "0000000000000000000000000000000000000000"
  content_hash: "sha256:0000000000000000000000000000000000000000000000000000000000000000"
  license: Apache-2.0
  retrieved_at: 2026-07-03T00:00:00Z
  mapped_by: catalog-team
```

> DB DR 규칙은 *check* 를 인코딩(PITR이 retention 윈도우 내에 켜져 있는가, geo-replica가 있는가,
> lag가 임계 내인가); 절대 failover를 실행하지 않음. Failover를 실행하고 검증하는 것은 phase-3
> 스케줄러의 안전 불변식 하 작업. 각 규칙은 **하나의 테스트 가능한 컨트롤** (이 문서 상단 정의에
> 따라): geo-replica 존재와 `max_replica_lag_seconds` 내의 replication-lag는 **별개** 규칙,
> 선택적으로 `config-baseline` 으로 그룹화되며 위 PITR 규칙에 folded되지 않음. 여기 보인
> `parameters` 필드는 관리자가 할당별로 설정 -
> [rule-governance-ko.md](rule-governance-ko.md) 참조.

### 라이선싱 (소스 추가 전 읽기)

- 일부 소스(특히 **CIS Benchmarks**) 는 컨텐트 재배포 제한. 컬렉터는 소스 텍스트, PDF, 스프레드
  시트, 스크린샷, **파생 발췌, 또는 그 텍스트로 빌드된 임베딩 / 벡터 인덱스** 를 커밋해선 **안**
  됨. **우리가 작성한 정규화된 규칙 로직** + 라이선스 소스로 다시 가리키는 `provenance` 참조
  (URL, resolved commit/digest, 버전, retrieved-at, content hash) 만 저장.
- 각 manifest는 두 독립 필드 운반: `license` - OSS의 **SPDX 식별자**(예: `Apache-2.0`) 또는
  제한된 소스에 대한 `LicenseRef-reference-only` - 와 `redistribution` (`embeddable` |
  `reference-only`). 강제를 주도하는 것은 라이선스 이름이 아니라 `redistribution` : `reference-
  only` 소스는 authored 로직 + provenance를 기여할 수 있지만, 원시 컨텐트는 트리에서 블록됨.
- **CI가 이를 강제** , 리뷰만이 아님: `reference-only` 소스의 컬렉터 아래 어떤 파일이 verbatim
  소스 텍스트를 포함하면 빌드 실패, secret / 고객-데이터 스캔이 모든 수집된 출력에 실행됨
  ([generic-scope.instructions.md](../../.github/instructions/generic-scope.instructions.md)).
- **Untrusted 컨텐트**: 소스 제공 텍스트(rationale, 설명) 는 untrusted 입력 - 시크릿이나
  프롬프트-인젝션을 운반할 수 있음. inert 데이터로 저장, 길이-bounded 및 스캔, 절대 지시로
  취급되지 않으며, 어떤 하류 LLM 사용도 T2 quality gate 통과
  ([architecture.instructions.md](../../.github/instructions/architecture.instructions.md)).
- 어떤 소스 컨텐트도 고객-비종속 규칙을 우회하지 않음; 컬렉터는 고객 식별자를 운반하는 어떤
  임포트된 텍스트도 거부.

## 컬렉터 아키텍처

각 소스는 **source manifest**(설정, 코드 아님) 로 기술되고 범용 파이프라인에 의해 처리 -
소스 추가는 대부분 선언적.

```text
source manifest ─► fetch ─► verify ─► parse ─► map to schema ─► provenance stamp ─► validate ─► dedupe ─► catalog
                   (pin+auth) (hash/sig) (parser plugin)                        (strict JSON Schema)  (by id)
```

- **fetch**: 어댑터가 소스에서 pull(REST, `git clone`, package registry, licensed download).
  주입된 secret-store 참조를 통해 인증(절대 커밋된 자격증명 아님); **불변** revision(git commit
  SHA 또는 아티팩트 digest, mutable 태그/브랜치 아님) 에 고정하고 resolved revision 기록; REST
  소스의 pagination과 rate limit 처리(`Retry-After` 존중, 백오프); bounded 재시도 있는 timeout
  적용. Fetch 실패 시 **fail closed** - 부분 fetch는 절대 부분 카탈로그를 산출하지 않음. 주기는
  Phase 1에서 on-demand; Phase 2에서 스케줄된 watcher.
- **verify**: fetch된 아티팩트의 무결성 검사(소스가 제공하는 곳에서 체크섬/서명) 및 계산된
  `content_hash` 기록; mismatch는 그 소스 abort.
- **parse**: manifest `parser` 키로 선택된 포맷-특이 리더(Rego, YAML, JSON, policy definition,
  docs) → 중간. 파서는 하나의 인터페이스 뒤의 플러그인, 그래서 새 네이티브 포맷은 추가적;
  알려지지 않은/미등록 `parser` 는 검증 실패.
- **map**: 정규화 스키마로 변환; 매핑 불가 필드는 드롭, 발명 안 함.
- **provenance 스탬프**: `source_url`, `resolved_ref` (commit/digest), `source_version`,
  `retrieved_at`, `content_hash`, `license`, `mapped_by` 기록.
- **validate**: 후보 YAML은 자체 per-kind JSON Schema (엄격, `additionalProperties: false`,
  파싱된 YAML 문서에 적용) 통과해야 함, 아니면 거부; 하나의 잘못된 엔트리가 전체 소스 실행
  실패(fail-closed) - 부분 랜딩이 아니라.
- **dedupe**: `id` 로 접기, 동일한 authored 로직에 대해 `provenance` 병합. 이것은 **수집 시점**
  dedup; distinct 규칙 간 **평가 시점** 충돌/우선순위는
  [phase-1-rule-catalog-t0-ko.md](phases/phase-1-rule-catalog-t0-ko.md#deduplication-conflict-and-precedence)
  의 별개 스테이지.
- **collect 모드**: 기본 incremental (`content_hash` 가 변경된 컨트롤만); 상류에서 제거된 컨트롤은
  버전 bump로 **tombstone/retire** , 절대 조용히 드롭되지 않음. 처음부터 재빌드를 위한 전체
  재수집 사용 가능.

Authored Rego는 **top-level** `policies/`(T0와 verifier가 소비) 에 살고 `check_logic.ref` 로
참조; 컬렉터는 `rule-catalog/sources/<source>/`, 스키마는 `rule-catalog/schema/`, 정규화 출력은
`rule-catalog/catalog/`. 이는 [project-structure-ko.md](project-structure-ko.md) 와 정렬.

## YAML 정규화

네 - 전체 카탈로그가 **YAML** , JSON Schema로 검증(JSON Schema는 스키마 언어; 검증되는 문서는
YAML) 되고 catalog-as-code로 저장. JSON은 오직 와이어 포멿(event/message 스키마, API body)과
런타임 아티팩트(Key Vault의 `resolved-models.json`) 에만 유지; `rule-catalog/` 에서 사람이
저작하는 모든 것은 YAML.

### 필드 명명과 스키마 관례

YAML 키는 **snake_case** ;
[phase-1-rule-catalog-t0-ko.md](phases/phase-1-rule-catalog-t0-ko.md#정규화-스키마) 의 정규화
스키마 필드는 산문에서 kebab-case로 작성. 그것들은 **같은 필드** - 매핑은 1:1, 그래서 두 문서는
모순되지 않음:

| phase-1 필드 | YAML 키 |
|-------------|--------|
| `resource-type` | `resource_type` |
| `check-logic` | `check_logic` |
| `id`, `version`, `source`, `severity`, `category`, `remediation`, `provenance` | 동일 |

- `source` 는 등록된 manifest `source_id` (phase-1 `source` enum) 와 같음.
- `kind` 는 추가된 discriminator (`rule` \| `best-practice` \| `config-baseline` \|
  `measurement-baseline`), phase-1의 9개 필수 필드 중 하나가 **아님** ; 어떤 per-kind 스키마가
  적용되는지 선택.
- 각 kind는 `$schema` (draft 2020-12), 안정 `$id`, `additionalProperties: false` 있는
  `rule-catalog/schema/` 의 스키마로 검증. **필수 필드는 kind별**: `rule` 은 `check_logic` +
  `remediation` 필요; `best-practice` / `config-baseline` 은 대신 `checks` / `controls` 참조,
  둘을 생략.
- Enums: `severity` ∈ `critical | high | medium | low` (phase-1 우선순위와 매칭),
  `category` ∈ `security | reliability | cost | config-drift`, `redistribution` ∈
  `embeddable | reference-only`. `version` 은 semver 패턴 매칭; 모든 타임스탬프는 RFC 3339
  UTC (`...Z`).
- `parameters` 는 `check_logic` 에 대한 타입된 입력의 **선택** 객체(예: retention 임계, max
  replication-lag, CVSS 버전 태그). 기본값은 규칙에 존재; 관리자가 규칙 편집 없이 할당별로
  오버라이드 - 저작/할당 모델은 [rule-governance-ko.md](rule-governance-ko.md).
- **온톨로지 dispatch 필드** 는 추가적이고 로드 시 CI-검증: `applies_to`, `triggered_by`,
  `evaluates`, `remediates`, `required_interfaces`, `submission_criteria`. 이들은 런타임이
  `Signal` 에서 정확한 매칭 규칙으로 스캔 대신 두 인덱스 교집합으로 traverse 가능하게 함; 전체
  파이프라인은 [llm-strategy-ko.md § Rule-to-Decision Lookup Pipeline](llm-strategy-ko.md#rule-to-decision-lookup-pipeline)
  에 있음.
- **`remediates` vs `remediation` - 두 필드, 하나의 개념:** `remediates` 는 이 규칙이 제안하는
  *mutation 카테고리* 를 선언하는 **ActionType id** (M:1); `remediation` 은 구체적 *how* -
  `{ kind, ref, parameters, cost_impact_monthly }` 블록이며 그 `kind` (`iac-patch`,
  `scripted`, ...) 는 ActionType 의 `operation` 과 호환되어야 함. 두 필드는 모든 `rule` 에
  함께 필수. CI 는 `remediates` 가 미인식 ActionType 을 가리키거나 `remediation.kind` 가
  ActionType 의 `operation` 과 호환 안 되는 규칙을 거부 (예: `delete` operation 이 `tag` 모양
  패치로 배송).
- **`alternatives[]` (선택):** 규칙은 선호도 순으로 랭크된 대안 remediation ActionType 을
  선언 가능; T0 는 항상 `remediates` 사용 (deterministic-first), grounding + mixed-model
  체크를 거친 T2 quality gate 만 대안으로 스왑 가능 - 더 저렴한 티어는 절대 스왑 안 함. 각
  대안은 등록된 ActionType id 를 가리켜야 하며 free-form 액션은 불가.

  ```yaml
  # 예시 프래그먼트
  remediates: remediate.disable-public-access          # primary, deterministic
  alternatives:
    - remediate.add-firewall-rule                       # 태그로 "keep-public" 이면 T2 선호
    - remediate.add-private-endpoint
  ```
- `provenance` 는 모든 rule-like kind의 공유 객체:
  `{ source_url, source_version, resolved_ref, content_hash, license, retrieved_at, mapped_by }`.
  phase-1의 "source URL/commit, imported-at 타임스탬프, mapping author" 에 매핑:
  `resolved_ref` = commit/digest, `retrieved_at` = imported-at, `mapped_by` = mapping author
  (롤/파이프라인 id, 절대 사람 아님).

### Source Manifest (하나의 소스 수집법)

```yaml
source_id: example-oss-benchmark
display_name: Example OSS Benchmark
license: LicenseRef-reference-only
redistribution: reference-only
priority_rank: 40
fetch:
  method: git
  location: https://example.com/benchmark.git
  ref: v1.4.0
  resolved_ref: "0000000000000000000000000000000000000000"
  path: controls/
  auth:
    secret_ref: SOURCE_EXAMPLE_TOKEN
  rate_limit:
    max_rps: 1
    respect_retry_after: true
  paginate: true
  timeout_seconds: 30
  max_retries: 3
parser: yaml-benchmark
cadence: on-demand
collect_mode: incremental
resource_type_map:
  ExampleObjectStore: object-storage
  ExampleCluster: kubernetes-cluster
```

`ref` 는 요청된 human-readable 태그; `resolved_ref` 는 fetch가 고정하고 기록한 **불변**
commit/digest (all-zero placeholder로 표시). `auth.secret_ref` 는 secret-store **키** 를 명명,
절대 자격증명 값 아님.

### Rule / Check (정규화)

```yaml
id: object-storage.public-access.deny
version: 1.2.0
kind: rule
source: example-oss-benchmark
severity: high
category: security
resource_type: object-storage
check_logic:
  engine: rego
  ref: policies/object_storage/public_access.rego
  entrypoint: deny_public_access
remediation:
  kind: iac-patch
  ref: remediation/object_storage/disable_public_access.tftpl
remediates: remediate.disable-public-access          # M:1 온톨로지 dispatch (필수)
provenance:
  source_url: https://example.com/benchmark/controls/5.1
  source_version: v1.4.0
  resolved_ref: "0000000000000000000000000000000000000000"
  content_hash: "sha256:0000000000000000000000000000000000000000000000000000000000000000"
  license: LicenseRef-reference-only
  retrieved_at: 2026-07-03T00:00:00Z
  mapped_by: catalog-team
```

> `remediates` 는 load 시점에
> [`rule_catalog.schema.rule`](../../src/aiopspilot/rule_catalog/schema/rule.py) 이
> [`rule-catalog/action-types/`](../../rule-catalog/action-types/) 에 대해 검증 -
> 알려지지 않은 ActionType id 는 load 를 실패시켜, 규칙이 `rollback_contract` /
> `promotion_gate` 를 선언하지 않은 mutation 카테고리를 인용할 수 없도록 강제. 선택적
> `alternatives` 도 같은 규칙; 배송된
> [`rule-catalog/catalog/`](../../rule-catalog/catalog/) 는 모든 항목에서 primary
> `remediates` 를 exercise (P1 W-2).

### Best Practice (다중-check 권고)

```yaml
id: reliability.multi-zone.recommend
version: 1.0.0
kind: best-practice
source: example-waf-checklist
severity: medium
category: reliability
resource_type: kubernetes-cluster
rationale: Spreading nodes across zones reduces single-zone failure blast radius.
checks:
  - kubernetes-cluster.zones.count-gte-2
provenance:
  source_url: https://example.com/waf/reliability
  source_version: "2026.06"
  resolved_ref: "0000000000000000000000000000000000000000"
  content_hash: "sha256:0000000000000000000000000000000000000000000000000000000000000000"
  license: LicenseRef-reference-only
  retrieved_at: 2026-07-03T00:00:00Z
  mapped_by: catalog-team
```

### Config Baseline (하드닝된 reference 세트)

```yaml
id: kubernetes-cluster.hardening.baseline
version: 3.1.0
kind: config-baseline
source: example-baseline
resource_type: kubernetes-cluster
controls:
  - kubernetes-cluster.rbac.enabled
  - kubernetes-cluster.api-server.no-public-ip
  - kubernetes-cluster.audit-log.enabled
provenance:
  source_url: https://example.com/baseline/kubernetes
  source_version: v3.1.0
  resolved_ref: "0000000000000000000000000000000000000000"
  content_hash: "sha256:0000000000000000000000000000000000000000000000000000000000000000"
  license: Apache-2.0
  retrieved_at: 2026-07-03T00:00:00Z
  mapped_by: catalog-team
```

### Measurement Baseline (성능 reference - 별도 저장)

```yaml
id: baseline.reference-agent.2026-07
kind: measurement-baseline
scenario_set: v2026.07
reference_agent: reference-agent@1.0.0
window: P30D
metrics:
  cost_per_incident_usd: 0.0
  auto_resolution_rate: 0.0
  mttr_seconds: 0
  human_touchpoints_per_100_events: 0.0
sample_size: 0
provenance:
  measured_at: 2026-07-03T00:00:00Z
  measured_by: phase-0
```

> 위 값들은 placeholder zero - 실제 숫자는 [goals-and-metrics-ko.md](goals-and-metrics-ko.md)
> 에 따라 측정 시점에 기록; 이 리포는 절대 고객-측정 값을 커밋하지 않음. Measurement-baseline
> 엔트리는 별도 `id` 네임스페이스 (`baseline.*`) 와 저장소 (`baselines/`) 에 존재, 절대 규칙
> `id` 나 규칙 스키마와 혼합 안 됨.

## 저장 레이아웃

```
aiopspilot/
├── policies/              # authored check-logic (OPA/Rego), T0 + verifier가 소비;
│                         #   check_logic.ref로 참조  (top-level, project-structure에 따라)
└── rule-catalog/          # catalog-as-code (YAML)
    ├── schema/            # per-kind JSON Schema (검증 언어) 가 YAML 문서에 적용:
    │                      #   source-manifest, rule, best-practice, config-baseline
    ├── vocabulary/        # canonical CSP-중립 어휘 (resource-types.yaml, ...)
    ├── action-types/      # 규칙의 `remediates` 필드가 인용하는 ActionType 인스턴스
    ├── sources/           # 소스당 하나의 폴더: manifest (.yaml) + collector + parser
    │   └── <source>/
    ├── pipeline/          # watch → collect → shadow-eval → regression → promote/rollback (Phase 2)
    ├── remediation/       # remediation.ref로 참조되는 remediation 템플릿
    ├── catalog/           # 정규화, 버전-고정 YAML 출력 (catalog-as-code)
    ├── exemptions/        # 시간-바운드 감사된 예외 아티팩트
    └── baselines/         # measurement 베이스라인 (YAML; 규칙과 별도 네임스페이스 + 저장소)
```

Authored Rego는 `rule-catalog/` 아래에 **중첩되지 않음** ; T0와 verifier가 소비하는 top-level
`policies/` 에 존재, [project-structure-ko.md](project-structure-ko.md) 와 정확히 같음.
`pipeline/` 은 Phase 2 지속 업데이터.

- `vocabulary/resource-types.yaml` - 모든 규칙이 인용하는 CSP-중립 `resource_type` 식별자
  집합. 이름 변경 → 카탈로그 전역 마이그레이션; 추가 → 거버넌스 PR. Loader:
  `src/aiopspilot/rule_catalog/schema/resource_type.py`, JSON Schema:
  `src/aiopspilot/rule_catalog/schema/resource_types.schema.json`.
- `action-types/*.yaml` - 온톨로지 `ActionType` 인스턴스 파일당 하나. Upstream 에서 `default_mode`
  는 **반드시** `shadow` 여야 하고 `promotion_gate` 필수. Loader:
  `src/aiopspilot/rule_catalog/schema/action_type.py`; JSON Schema 는 공유 온톨로지 스키마
  `src/aiopspilot/shared/contracts/ontology/action-type.json`.

## 검증과 신뢰

- 모든 정규화 엔트리는 CI에서 자체 **엄격** per-kind JSON Schema
  (`additionalProperties: false`) 로 검증되어야 함; 하나의 잘못된 엔트리가 소스 실행 실패
  (fail-closed) 시키고 머지 블록.
- `provenance` 는 감사가능성과 롤백을 위해 모든 엔트리에 필수, `content_hash` 는 fetch된
  아티팩트에 대해 검증.
- **License / redistribution 게이트**: CI가 verbatim `reference-only` 소스 텍스트 블록, 각
  manifest에 유효한 `license` (SPDX 또는 `LicenseRef-reference-only`) + `redistribution` 값
  요구.
- **변경 추적**: 규칙의 `version` 은 resolved 소스 컨텐트가 바뀔 때 bump (`content_hash` 델타);
  상류 제거는 tombstoned/retired 엔트리로 기록, 조용한 삭제 아님, 그래서 rule set이 revertible
  유지.
- **Untrusted 입력**: 수집된 소스 텍스트는 데이터, 절대 지시 아님; 길이-bounded, secret/고객-데이터
  스캔, T2 quality gate 통해서만 LLM에 도달
  ([architecture.instructions.md](../../.github/instructions/architecture.instructions.md)).
- 중복제거, 충돌, 우선순위는 결정론적이며
  [phase-1-rule-catalog-t0-ko.md](phases/phase-1-rule-catalog-t0-ko.md#deduplication-conflict-and-precedence)
  에 정의; 지속적 collect → shadow-eval → regression → promote/rollback 게이트는
  [phase-2-quality-and-t1-ko.md](phases/phase-2-quality-and-t1-ko.md).
- Secret 스캔과 고객-비종속 regex 검사가 모든 수집된 픽스처와 카탈로그 출력에 실행
  ([generic-scope.instructions.md](../../.github/instructions/generic-scope.instructions.md)).

## 자율 규칙 발견(Autonomous Rule Discovery)

수집은 "상류 소스 읽기" 뿐이 아님. 카탈로그는 **운영 신호** 에서도 성장하고 self-correct,
그래서 결정론 레이어가 사람이 모든 규칙을 손으로 만들지 않고 환경에 발맞춤. 이것은
[architecture.instructions.md](../../.github/instructions/architecture.instructions.md) 의
"Living rules" 원칙.

### 루프

Long-horizon 루프가 무한 반복; 모든 사이클이 같은 공유 세계 모델(정규화된 카탈로그, 감사 로그,
인시던트 라이브러리, provenance 저장소) 을 유지 - 사이클이 처음부터 재시작하지 않고 서로 위에
빌드:

```text
sources + operational signals ─► observe ─► hypothesize ─► verify ─► integrate
                                                            (quality gate)
```

- **observe** - 루프는 하나씩이 아니라 세 피드를 나란히 읽음:
  1. **상류 소스** 위 컬렉터 파이프라인 경유(새/변경 컨트롤).
  2. **운영 신호** - 최근 감사 로그 엔트리, HIL 승인 패턴, shadow-mode 결과, 롤백, **override
     이벤트** ([rule-governance-ko.md](rule-governance-ko.md)).
  3. **현재 카탈로그** - 기존 규칙, provenance, 측정된 정확도.
- **hypothesize** - 추론 스테이지(LLM 스테이지, 어떤 T2 출력처럼 취급) 가 세 형상의 **후보**
  엔트리 제안:
  - **new-rule**: 아직 커버되지 않은 컨트롤, 반복되는 인시던트/HIL 패턴 또는 새로 발행된 상류
    컨트롤에 의해 동기.
  - **revision**: 상류 소스가 바뀌었거나(그 `content_hash` 가 이동) shadow 정확도가 임계
    아래로 drift한 기존 규칙.
  - **retirement**: 반복적으로 override되거나 shadow 결과가 실제 환경에 poor fit임을 보이는
    기존 규칙.
- **verify** - 모든 후보는 표준 **quality gate** 통과할 때까지 inert 데이터:
  1. 엄격 JSON Schema (`additionalProperties: false`);
  2. Provenance 검사 - `source_url`, `resolved_ref`, `content_hash`, `license`,
     `redistribution` 모두 존재하고 검증 가능 (grounded provenance 없는 후보는 즉시 거부);
  3. **Mixed-model 교차 검사** - 두 번째 모델(다른 패밀리/벤더) 이 같은 후보를 재도출하거나 재
     승인; 불일치는 HIL로 escalate, 절대 auto-resolve 아님
     ([architecture.instructions.md](../../.github/instructions/architecture.instructions.md));
  4. 결정론 verifier - Rego 파싱, 중복 `id` 없음, 더 엄격한 컨트롤을 조용히 약화시킬 기존 규칙과
     충돌 없음;
  5. 회귀 스위트 - 기존 픽스처가 여전히 통과;
  6. Shadow-mode dwell - 후보가 설정된 최소 기간과 표본 크기 동안 실제 트래픽에 judge-and-log-only
     실행, 임계 위 정확도와 정책 위반 escape 0.
- **integrate** - 게이트 통과한 후보는 [rule-governance-ko.md](rule-governance-ko.md) 의 할당/
  effect 라이프사이클에 따라 승격(new-rule/revision은 먼저 audit effect로 랜딩; retirement는
  tombstone으로 랜딩). 카탈로그는 오직 머지된 catalog-as-code PR로만 변형, 절대 루프에 의해
  직접 아님.

### 후보 요건 (MUST)

- 모든 후보는 **grounded provenance** 인용해야 함 - 상류 문서 URL + resolved revision/hash,
  또는 특정 인시던트/HIL/override 이벤트 id, 또는 특정 취약성/권고 id. "모델이 그것을 생각했음"
  은 provenance가 아님.
- 모든 후보는 CSP-중립 `resource_type` 어휘 대상, 절대 벤더 경로 아님.
- Reference-only 소스 텍스트는 후보에 붙여넣기되어선 안 됨; [Licensing](#라이선싱-소스-추가-전-읽기)
  규칙에 따라 authored `check_logic` + 인용만.
- 어떤 게이트 스텝을 실패하는 후보는 **abstain** 이 됨 - 사유와 함께 로그되어 다음 사이클이
  revisit할 수 있지만, 절대 부분적으로 적용되지 않음.

### Override 피드백

Override는 루프의 first-class 입력, dead-end 아님. 규칙이 스코프에 걸쳐 long-lived 또는 반복
override를 누적할 때, observe 스테이지가 플래그하고 hypothesize 스테이지가 **revision** (override
가 불필요하도록 규칙 좁힘) 또는 **retirement** (규칙이 체계적으로 poor fit) 제안. 어느 쪽이든
제안은 여전히 전체 quality gate 통과. Override는 카탈로그를 직접 변형하지 않음 - 신호만 공급.

### 안전과 신뢰

- 루프는 **후보 생성기** , executor 아님. 라이브 카탈로그를 변형할 수 없고, 할당을 enforce로
  flip할 수 없으며, [rule-governance-ko.md](rule-governance-ko.md) 의 승격 승인을 우회할 수
  없음.
- 이 루프의 어떤 LLM 스테이지도 T2 호출이며
  [architecture.instructions.md](../../.github/instructions/architecture.instructions.md) 의
  T2 quality gate(mixed-model, verifier, grounding, abstain-when-unsupported) 준수.
- 루프 자체의 처리량(사이클당 후보, gate 통과율, override-트리거된 제안률, retirement률) 은
  계측되고 [goals-and-metrics-ko.md](goals-and-metrics-ko.md) 에 보고 - 측정 가능, assert
  아님.

## Open Decisions

- [ ] 정본 `resource-type` 어휘와 Azure를 위한 매핑 테이블(비-Azure 매핑 테이블은 TBD;
      [Implementation Focus](../../.github/copilot-instructions.md#implementation-focus-must)
      참조).
- [ ] 어떤 소스가 reference-only vs embeddable, 각 라이선스에 대해 확인.
- [ ] 초기 소스 리스트를 위한 파서 세트(Rego, YAML-benchmark, policy-definition, docs).
- [ ] `check_logic` 저장 포맷: 인라인 표현식 vs 외부 Rego 모듈 참조.
- [ ] 컴플라이언스-프레임워크 매핑(컨트롤 → NIST/PCI/ISO 태그): manifest 필드 또는 별도 crosswalk
      아티팩트.
- [ ] MITRE ATT&CK technique / D3FEND control 매핑 저장: 컴플라이언스 crosswalk 아티팩트 재사용
      또는 규칙에 전용 매핑-태그 필드 추가.
- [ ] 결정론 CVSS+KEV → `severity` 매핑과 CVSS 버전 정책(v3.1 vs v4.0), 그리고 버전 태그가
      규칙에 어디에 운반되는지.
- [ ] Per-DB-엔진 컨트롤 granularity: 엔진이 `resource_type` 에 인코딩 vs 공유 중립 타입의
      `parameters.engine` discriminator.
- [ ] 상류 컨트롤이 제거될 때 tombstone/retirement 기록 포맷.
- [ ] 어떤 소스가 무결성 검증을 위해 체크섬/서명을 노출하고 그것이 없을 때 fallback.
- [ ] 루프-생성 후보가 shadow를 떠날 수 있기 전 최소 shadow-dwell 시간과 표본 크기, 승격을
      게이트하는 정확도 임계.
- [ ] 자율 discovery 루프의 주기(이벤트-트리거 vs 스케줄) 와 사이클당 후보/토큰 예산.
- [ ] Phase 2와 Phase 3에서 observe 스테이지에 어떤 운영 신호가 공급되는지(override 이벤트와
      HIL 패턴은 override 아티팩트가 존재하는 순간부터 범위 내; 롤백 상관관계는 나중에 랜딩
      가능).
