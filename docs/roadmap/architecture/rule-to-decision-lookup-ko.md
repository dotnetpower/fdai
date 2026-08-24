---
title: Rule-to-Decision 조회
translation_of: rule-to-decision-lookup.md
translation_source_sha: 9168b51a9b0e52899dd69248931efec1b62a445d
translation_revised: 2026-08-24
---
# Rule-to-Decision 조회

이 문서는 결정론적 Rule 전달 온톨로지와 계층화된 T0, 재사용, 유사도, 캐시 및 잔여 T2 조회
경로를 소유합니다. 의미 서명과 감사 계보를 정의하지만 판단 또는 실행 권한을 부여하지 않으며,
저장소는 [Rule 조회 온톨로지 저장소](rule-lookup-ontology-storage-ko.md)가 소유합니다.

## Rule-to-Decision 조회 파이프라인

[모델 티어](llm-strategy-ko.md#모델-티어) 의 티어 백분율은 의도적인 **계층 조회 파이프라인** 의 *결과* : 들어오는
이벤트가 저렴-비싼 레이어를 traverse하고, 프론티어 LLM(L5) 은 모든 저렴 레이어가 abstain할 때만
도달. 파이프라인은 타입된 **온톨로지** 에 빌드: 규칙, 리소스, 신호, 액션이 온톨로지 엔티티,
매칭은 텍스트-유사도 추측이 아니라 결정론 그래프 탐색.

온톨로지 프레이밍은 이전 AGI 온톨로지 설계(cardinality-aware 링크 있는 타입 객체, `required_
interfaces` 와 `submission_criteria` 통해 액션에 통합된 함수) 로부터 object-type / link-type
/ action-type 분리를 차용, CSP 리소스와 규칙에 적용. 이것이 모든 규칙에 결정론 전달 경로와
모든 재사용에 정본, hashable 서명을 부여.

### 온톨로지 기반

저수준 rule-dispatch 기반은 네 **ObjectType**으로 시작하며 [FDAI 운영 온톨로지](operating-ontology-ko.md)가 서비스, 목표, 결정, 효과 의미를 소유함.
확장 가능한 레지스트리는 프로세스, 대화, ReviewCase 같은 product 객체와 ResourceType, SignalType, Property, ActionType 같은 meta 객체를 일급으로 둠.
선언은 `rule-catalog/vocabulary/`에 있고 런타임 인스턴스는 shared 온톨로지 저장소를 사용함.

| ObjectType | 의미 | 백업 |
|------------|------|------|
| `Resource` | 거버넌스 아래의 대상(Azure 리소스; CSP-중립 스키마, 프로바이더 어댑터가 채움) | `shared/providers/` |
| `Rule` | 의도 있는 결정론 컨트롤(`applies_to`, `evaluates`, `remediates`) | `rule-catalog/` |
| `Signal` | 타입된 관찰(Activity Log 라인, 표류 차이, 비용 이상, canary 결과) - `event-ingest` 에 진입하는 기본형 | `shared/contracts/event` |
| `Finding` | 시점의 리소스에 대한 규칙 매칭, 컨텍스트와 심각도 포함 | 런타임에 파생; 감사 저장소에 지속 |

meta ObjectType은 LinkType 엔드포인트를 정직하게 만듦. `applies_to`는 `ResourceType`,
`triggered_by`는 `SignalType`, `evaluates`는 `Property`, `remediates`는 `ActionType`을 대상으로
함. 해당 카탈로그를 직접 읽는 배포에서는 런타임 인스턴스가 0개일 수 있지만, 선언 자체가
ActionType을 Rule로 모델링하는 엔드포인트 별칭을 방지함.

shipped ObjectType, LinkType, ActionType 선언은 모두 evidence-governed임. 출처 URL과
resolved 선언 버전을 인용하고 license와 수집 시간을 기록하며 로더가 검증하는
정본 내용 해시를 운반함. 출처 이력이 없거나 stale이면 카탈로그 조립을 차단함.

관계는 cardinality 메타데이터 있는 **타입된 LinkType** - 그래서 탐색은 스캔이 아니라
O(인덱스 조회). 각 선언은 `is_transitive`, `is_causal`, `temporal_order` 플래그도 함께
운반하므로 탐색 엔진이 재귀 확장이 안전한 시점과 쿼리가 시간을 존중해야 하는 시점을
알 수 있음. 시간 LinkType은 대상 ObjectType의 정렬 가능한 속성으로 해석해야 하는
`order_by_property`도 선언함. 인스턴스 저장소는 모든 링크 쓰기 전에 cardinality를 강제하고,
`is_transitive`가 true일 때만 같은 LinkType을 반복해서 순회하며, 시간 링크를 대상 속성
순서로 반환함. 이 값들은 시각화 힌트가 아니라 런타임 불변식임.

| LinkType | Cardinality | Transitive | 의미 |
|----------|-------------|:---------:|------|
| `applies_to` | Rule → ResourceType (M:M) | - | 규칙이 매칭할 수 있는 리소스 타입 |
| `triggered_by` | Rule → SignalType (M:M) | - | 규칙 평가를 유발하는 신호 |
| `evaluates` | Rule → Property (M:M) | - | 규칙이 읽는 리소스 속성 |
| `remediates` | Rule → ActionType (M:1) | - | 매칭 시 규칙이 제안하는 온톨로지 액션 |
| `resource_of` | 신호 → Resource (M:1) | - | 신호가 관한 리소스 |
| `overrides` | 재정의 → Rule (M:1) | - | 재정의가 이 규칙 대상([rule-governance-ko.md](../rules-and-detection/rule-governance-ko.md#override) 참조) |
| `causes` / `prevents` | Rule → 결과 (M:M, causal) | - | T2가 추론할 수 있는 causal 메타데이터(드묾) |
| `precedes` / `follows` | 발견 사항 → 발견 사항 (M:M, temporal) | - | 하나의 인시던트에 대한 관련 발견 사항 상관관계 |
| `contains` | Resource -> Resource (1:M, 부모 -> 자식) | ✓ | 소유/스코프 포함: 구독 -> resource-group -> 리소스, VNet -> 서브넷, 클러스터 -> node-pool입니다. 재귀 탐색은 저장된 parent-to-child direction을 따릅니다. [인벤토리 어댑터](csp-neutrality-ko.md#5-인벤토리-계약--리소스-그래프)가 채웁니다. |
| `attached_to` | Resource → Resource (M:1) | - | 수명 결합 첨부: NIC→VM, disk→VM, private-endpoint→대상. 부모 삭제 시 자식이 깨짐. |
| `depends_on` | Resource → Resource (M:M) | - | 정상 동작에 필요한 논리적 참조: ContainerApp→Key-Vault / ACR / Postgres, managed-identity→앱. 끊긴 엣지는 대상 이 아니라 dependent 를 degrade. |
| `peered_with` | Resource ↔ Resource (M:M, symmetric) | - | Independently supported directed 기록 두 개로 표현하는 네트워크 peer이며 기록 하나는 reverse를 imply하지 않습니다. |
| `routes_to` | Resource → Resource (M:1) | - | UDR next 홉 같은 directed 트래픽 경로 또는 참조이며 absence는 unreachable을 입증하지 않습니다. |

탐색은 방향적이고 캐시됨; 타입 `R` 의 `Resource` 에 대한 타입 `T` 의 `Signal` 은 두 인덱스
교집합을 통해 `triggered_by ∋ T` 및 `applies_to ∋ R` 인 정확한 규칙 세트로 해결 - 텍스트 검색
없음, 모델 호출 없음.

Resource→Resource 링크(`contains`, `attached_to`, `depends_on`, `peered_with`, `routes_to`)는
risk-gate가 [risk-classification-ko.md](../decisioning/risk-classification-ko.md)의 3-값
enum 대신 *실제* 영향 범위 를 계산할 수 있게 하고, T2 가 대상 리소스 주변 **depth-2 이웃
서브그래프** 를 프롬프트로 받을 수 있게 하는 것 - 벌거벗은 리소스 id 가 아니라 근거 있고
인용 가능한 컨텍스트. 권위 있는 출처 는
[인벤토리 계약](csp-neutrality-ko.md#5-인벤토리-계약--리소스-그래프); `core/` 는 절대 클라우드
SDK 로 조회하지 않음. 새 링크 종류는 어댑터가 발행 하기 전에
`shared/contracts/ontology/link-type.json` 에 먼저 추가해야 함 - 미인식 `ResourceType` 과
동일하게, 미인식 링크는 자동 등록이 아니라 이슈 오픈 (self-extending 온톨로지,
[포크 확장](#포크-확장-self-extending-온톨로지) 참조).

런타임 ObjectType 속성과 LinkType 속성은 정본 JSON 데이터여야 함. 대응 키는
문자열이고, 숫자는 finite이며, datetime은 timezone-aware이고 RFC 3339 UTC로 정규화됨.
지원하지 않는 Python 객체는 쓰기 경계에서 거부함. in-memory와 PostgreSQL 저장소가
같은 정규화를 적용하므로 재생은 선택한 어댑터에 따라 달라지지 않음.

### 구체적인 Rule 의미 규칙

제공되는 Rule은 와일드카드 온톨로지 관계를 사용하지 않습니다. `triggered_by`는 검토된
`SignalType`을 참조하고, `evaluates`는 정본 `Property` ID를 참조하며,
`implemented_by_policy`는 Rule을 1급 `PolicyArtifact`에 연결합니다. 범위가 제한된 OPA AST
동기화 도구는 카탈로그를 구성하기 전에 Rego 패키지 ID와 속성 읽기를 검증합니다.

원시 이벤트는 `vocabulary/signal-types.yaml`을 통해 해석됩니다. 정확한 pattern 일치는 전문화된
형식을 선택하고, 일치하지 않는 이벤트는 검토된 단일 구성 기준선 형식을 선택합니다. 의미
수집은 후보 Rule의 순위를 매길 수 있지만 정확한 ID와 그래프 링크가 전달 및 근거 확인의
권위로 유지됩니다.

### 온톨로지 아티팩트로서의 규칙

[rule-catalog-collection-ko.md](../rules-and-detection/rule-catalog-collection-ko.md)의 Rule 스키마 v2는
파이프라인이 전달하는 온톨로지 필드를 운반함. 이전 `applies_to` scope-map 의미는
`scope_predicates`로 이행하며 모든 전달 필드는 로드 시 CI로 검증함.

```yaml
# rule-catalog/rules/example.yaml (illustrative fragment; full schema in rule-catalog-collection.md)
id: object-storage.public-access.deny
version: 1.2.0
source: authored
severity: high
category: security
resource_type: object-storage
check_logic: <opa-package-ref>            # 결정론 평가기
remediation: <action-ref>                 # 온톨로지 ActionType 인스턴스 가리킴

# ── ontology fields (new; CI-validated) ──
applies_to:    [object-storage]
triggered_by:  [property.public_access.changed, config.public_access.enabled]
evaluates:     [object-storage.public_access]
scope_predicates: {}                         # 선택 labels/tags/scope filter
remediates:    remediate.disable-public-access
required_interfaces: [Evaluable, Remediable]   # submission_criteria enforced at load
submission_criteria:
  - kind: resource_type_registered
    value: object-storage
provenance: { ... }
```

`required_interfaces` 와 `submission_criteria` 는 참조된 온톨로지 설계의 같은
Functions-plus-Interfaces 패턴 따름: 규칙은 인터페이스 계약이 런타임 객체에서 충족될 때만
dispatchable, 스키마 레지스트리에 대해 `applies_to` / `triggered_by` 가 해결될 수 없는 규칙을
CI가 거부.

`resource_type`은 기존 정책과 교정 코드가 사용하는 정본 단일 대상으로
유지하며 `applies_to`에 반드시 포함해야 함. `scope_predicates`는 이전 라벨/tag 범위 지도를
담아 타입 축과 혼동되지 않게 함. 업스트림 출처가 더 좁은 메타데이터를 제공하지 않을 때만 기존
및 신규 수집 룰을 `triggered_by: ["*"]`, `evaluates: ["*"]`로 backfill함. 와일드카드는 명시적
catch-all이지 추론된 신호가 아님. TrustRouter와 T0는 같은 `applies_to` x (`triggered_by` exact
또는 `*`) 교집합을 사용함.

### 파이프라인 스테이지와 ActionType (구분되는 개념)

이 시스템에서 "액션" 이라 불리는 두 가지는 **혼동 금지**:

- **PipelineStage** - 계층적 조회에서 결정이 이뤄진 위치. **감사 어휘** 이지 스키마 아티팩트가
  아님. 모든 audit-log 엔트리는 `pipeline_stage` 필드를 기록해서 결정 경로가 종단 간 로
  재구성 가능. `remediate` 제외 모든 스테이지는 실행기 관점에서 읽기 전용 (CSP 변경
  없음).
- **ActionType** - 롤백 계약 있는 **CSP-중립 변경 카테고리**. `shared/contracts/ontology/action-type.json`
  에 선언; 인스턴스(예: `remediate.disable-public-access`) 는 카탈로그에 존재하며 규칙의
  `remediates` 필드에서 참조됨. 이게 스키마 아티팩트.

`remediate` 만이 둘을 커플링: PipelineStage(실행기 스텝) 이면서 그 출력이 Resource에
적용되는 ActionType **인스턴스**. `escalate` / `abstain` / `deny` 는 ActionType을 절대
발동하지 않는 종단 스테이지.

**PipelineStage 어휘** (`audit_log.pipeline_stage` 에 기록):

| PipelineStage | 레이어 | 비용 | 전제조건 | 종단? |
|---------------|--------|------|---------|:---:|
| `L1_evaluate` | L1 (T0) | 순수 함수, 인메모리 OPA/Rego | 규칙의 `applies_to` 가 Resource와 매칭; `check_logic` 컴파일 | - |
| `L1_simulate` (what-if) | L1 (T0) | 선언적 상태에 대한 순수 함수 | 리소스 상태 스냅샷 이용 가능 | - |
| `L2_reuse` | L2 | O(1) 인덱스 선택 | 학습된-액션 저장소의 `(signature, rule_id, catalog_version)` 적중 | - |
| `L3_similarity` | L3 (T1) | 임베딩 1 + pgvector kNN | 이웃의 컨텍스트 호환성 검사 통과 | - |
| `L4_cache_hit` | L4 | O(1) 키 조회 | TTL과 카탈로그/모델 버전 내 서명 매칭 | - |
| `L5_reason` | L5 (T2) | 프론티어 LLM (기본 + 보조; 불일치 시 escalated) | quality-gate가 권위 | - |
| `remediate` | risk-gate ⇒ 실행기 ⇒ 전달 | ActionType 인스턴스를 Resource에 적용 | policy-as-code 검증기 통과; 모든 ActionType 전제조건 성립 | - |
| `escalate` | risk-gate ⇒ ChatOps | HIL 요청 | 어떤 저렴 레이어도 케이스 해결 못함 | ✓ |
| `abstain` | 어떤 레이어 | 감사된 no-op | grounding 없음 또는 검증기 abstain | ✓ |
| `deny` | 어떤 레이어 | 감사된 no-op | risk-classification이 액션 차단 | ✓ |

`L5_reason` 만 LLM 호출. 다른 모든 스테이지는 결정론이며 마이크로초-밀리초에 실행.

### ActionType 계약

**ActionType** ([스키마](../../../services/core-control-plane/src/fdai/shared/contracts/ontology/action-type.json)) 는
하나의 CSP-중립 변경 카테고리와 그 카테고리의 모든 인스턴스에 대한 안전 불변식을 선언.
`preconditions` / `stop_conditions` / `blast_radius` / `description` 을 제외한 모든 필드는
필수.

- `name` - 안정 id (예: `remediate.disable-public-access`).
- `operation` - 아래 enum의 CSP-중립 동사.
- `interfaces` - 실행기 가 지켜야 하는 런타임 계약; risk-gate 는 이 집합으로 feature 벡터
  구성.
- `rollback_contract` - 인스턴스를 되돌리는 방법. **`none` 은 유효 값 아님**; 모든 ActionType 은
  최선 노력 라도 undo 경로를 선언해야 함. 정말로 되돌릴 수 없는 변경 은
  `irreversible: true` (아래) 를 설정하고 risk-classification 이 HIL+정족수 으로 라우팅 -
  롤백 을 침묵시키는 방식이 아님.
- `irreversible` - 액션 이전 상태가 완전히 복원 불가능할 때만 true (예: soft-delete 된 리소스의
  `purge`). Rollback_contract 은 여전히 필수이며 최선 노력 복구를 기술.
- `default_mode` - 모든 업스트림 ActionType은 반드시 `shadow`로 출시합니다. 강제 적용로의
  승격은 승격 게이트 통과 후 별도 통제된 액션으로 수행합니다.
- `promotion_gate` - 어사인먼트가 shadow-mode ActionType 을 강제 적용 로 승격시키기 전에 고정
  시나리오 세트에서 통과해야 할 측정 기준 (`min_shadow_days`, `min_samples`, `min_accuracy`,
  `max_policy_escapes`). Rule 배정 는 이 값을 tighten 만 가능, loosen 불가.
- `preconditions[]` - 액션이 risk-gate 에 도달하기 **전에** T0 검증기 가 결정론적으로 평가하는
  검사. 실패하는 전제조건은 abstain, 부분 적용 절대 금지.
- `stop_conditions[]` - 적용 **도중 또는 이후에** 실행기 가 결정론적으로 평가하는 조건. 참
  값이 하나라도 나오면 자동 halt + `rollback_contract` 로 롤백 트리거.
- `blast_radius` - risk-gate 가 이 ActionType 인스턴스의 blast-radius 분류 차원을 계산하는
  방법. `static_enum` 은 고정 버킷; `graph_derived` 는 Resource → Resource 링크 (기본:
  `contains` + 역방향 `depends_on`, 깊이 2) 를 walk 하여 영향받는 Resource 수를 개수. 인스턴스가
  `max_affected_resources` 초과 시 abstain + escalate. 실제 탐색 구현은 risk-gate 와
  함께 P2 에 랜딩; P1 은 선언만 기록.

#### 연산 동사

`operation` enum 은 CSP-중립. 각 동사 는 고정 의미를 가지므로 규칙 저자와 프로바이더 어댑터가
의도를 합의.

| 동사 | 의미 | 기본 롤백 |
|------|-----|---------------|
| `create` | 새 Resource 프로비저닝 | `pr_revert` (같은 PR에서 destroy) |
| `update` | in-place 속성 변경 (non-destructive) | `pr_revert` (차이 에 이전 속성값) |
| `delete` | CSP 수준 Resource 제거 | `snapshot_restore` (삭제 전 스냅샷) |
| `disable` | 삭제 없이 끄기 | `state_forward_only` via `enable` |
| `enable` | `disable` 의 역 | `state_forward_only` via `disable` |
| `tag` | 메타데이터 전용 변경 | `pr_revert` |
| `drop` | DB-DDL 제거 (스키마 / 객체) | `pitr` |
| `purge` | soft-delete 후 hard-delete; `irreversible: true` | 최선 노력 `snapshot_restore` |
| `scale` | 개수 / SKU 조정 | 이전 spec 으로 `pr_revert` |
| `restart` | in-place 프로세스/파드 bounce | 프로바이더 계약에 따라 `scripted` 또는 `state_forward_only` |
| `failover` | 관리형 장애 조치 트리거; `RequiresMaintenanceWindow` | `scripted` (failback) |
| `rotate` | 시크릿 / 인증서 로테이션 | `snapshot_restore` (이전 버전 유지) |
| `revert` | 이전 액션 인스턴스의 명시적 롤백 | revert PR 자체에 `pr_revert` |
| `attach` | Resource → Resource 링크 생성 (PE→대상, MI→App, disk→VM) | `state_forward_only` via `detach` |
| `detach` | 그런 링크 제거 | `state_forward_only` via `attach` |
| `quarantine` | 삭제 없는 네트워크/정책 격리 | `state_forward_only` (격리 정책 해제) |

#### Interface

ActionType 의 `interfaces` 집합은 실행기 가 지켜야 하는 런타임 계약을 명명. 인터페이스 누락은
"뭐든 허용" 이 아님 - risk-gate 는 인터페이스 집합이 그 `operation` 의 안전 불변식 요건을
커버하지 못하는 ActionType 을 자동 실행하지 않음.

| Interface | 의미 |
|-----------|-----|
| `ControlPlane` | CSP 메타데이터/설정만 건드림 (사용자 데이터 절대 안 건드림). Auto 후보의 기준선. |
| `DataPlaneMutating` | 사용자 데이터 건드림. **영향 범위 무관하게 기본 HIL**. |
| `IdempotentByKey` | 동일 멱등성 키로 재시도 안전; 실행기 의 dedup 이 이 키 사용. |
| `RateLimited` | 버킷 상한(per-resource, per-tier, global) 준수 필수; 오버플로우는 HIL 로 degrade. |
| `RequiresInventoryFresh` | 대상 Resource 의 인벤토리 레코드가 `freshness_ttl` 초과 stale 이면 실행 금지. 유령 리소스 액션 방지 - 인벤토리 계약 ([csp-neutrality-ko.md § 5](csp-neutrality-ko.md#5-인벤토리-계약--리소스-그래프)) 이 최신성 커서 공급. |
| `GraphTraversalRequired` | blast-radius 계산이 Resource → Resource 링크 (`contains` / `attached_to` / `depends_on`) 트래버설에 의존. 그래프 없으면 ActionType abstain. |
| `CrossResource` | 여러 Resource 를 변경; 실행기 가 deadlock-free 결정론적 순서로 N 개 per-resource 락 획득. |
| `AsymmetricRollback` | 롤백 경로 가 정확한 역이 아님 (예: PITR 이 Δ-data 유실). auto → HIL demotion 강제; 다른 차원 무관하게 auto 선택 안 됨. |
| `RequiresMaintenanceWindow` | 승인된 구간 안에서만 실행 (P3 chaos / DR). 구간 스케줄러 없으면 abstain, 그냥 실행 금지. |

### 계층 조회 파이프라인

![계층 조회 파이프라인. 주요 단계는 Signal arrives, L0. event-ingest / normalize + dedup + correlate into incident, no-op, audited, L1. T0 rule match / ontology traversal: applies_to ∩ triggered_by / run each rule's evaluate action (OPA/Rego, in-memory), risk-gate, L2. Learned-action lookup / (signature, rule_id, catalog_version) → verified action, L3. Embedding similarity (T1) / 1 embedding call → pgvector kNN / reuse neighbor.action iff cos > threshold and context compatible, L4. T2 result cache / signature includes catalog_version + model_config_version + mode, L5. T2 cascade / primary → agree? → done / disagree? → escalated / quality-gate authoritative, writeback: promote verified outcome / into L2 (learned action) + L4 (result cache)입니다.](../../diagrams/generated/fdai-roadmap-architecture-llm-strategy-03.ko.svg)

**예상 적중 분포** (설계 목표, [goals-and-metrics-ko.md](goals-and-metrics-ko.md) 에 따라 측정
대상):

| 레이어 | 적중당 비용 | 들어오는 이벤트의 설계 비율 |
|--------|-----------|--------------------------|
| L0 dedup / correlate | µs | N 이벤트 → 1 인시던트로 접힘(압축, 커버리지 수치 아님) |
| L1 T0 | µs, 인메모리 | ~70-80% |
| L2 learned-action | ms, 인덱스 선택 | L5 결과가 아래로 distill되면서 시간에 걸쳐 성장 |
| L3 임베딩 유사도 | 임베딩 1 + kNN | T1 ~15-20% 밴드의 나머지 |
| L4 T2 캐시 | O(1) 키 | 미해결이지만 최근 케이스의 반복 흡수 |
| L5 T2 cascade | 프론티어 LLM | **~5-10%만** - 실제 토큰 지출 |

두 구조적 결과:

- **LLM 사용은 시간에 걸쳐 감소** , 증가 아님. 모든 L5 검증된 결과가 L2에 writeback, 그래서 지난
  주 전체 T2 cascade가 든 반복 케이스는 이번 주 해시 조회. 이것이 "LLM을 덜 쓴다" 원칙 뒤의
  구체 메커니즘.
- **규칙 변경이 올바른 행을 자동으로 무효화** (아래 참조). 수동 캐시 bust 없음; stale 재사용은
  승격이나 강등에서 살아남지 않음.

### 서명 구성

L2와 L4를 키하는 서명은 온톨로지-타입된 필드에 대한 정본 해시 - 기록과 재사용이 문자열-
유사가 아니라 semantics-aware.

```text
signature = sha256(
  Signal.type,
  canonical(Signal.params),                # sorted, redacted, typed
  Resource.type,
  canonical(Resource.props),               # only props referenced by evaluates
  Rule.id, Rule.version,
  Catalog.version,
  Model.config.version,                    # L4 only; L2 omits (model-independent reuse)
  Mode                                     # shadow | enforce
)
```

- **민감정보 제거가 해시 전 실행** - 그래서 시크릿이 절대 서명에 진입 못함.
- **`evaluates` 에 명명된 속성만** 참여, 그래서 관련 없는 리소스 churn이 재사용을 무효화하지 않음.
- **카탈로그 / 모델 버전 bump** 와 **shadow ↔ 강제 적용 전이** 는 새 서명 강제, 별도 cache-flush
  스텝 없이 [비용 통제 수단](llm-strategy-ko.md#비용-컨트롤비용-통제-수단) 의 무효화 규칙 적용 보장.

### 재사용 감사 (모든 레이어, 적중 포함)

자율성은 결정 - 재사용으로 생산된 것 포함 - 이 완전히 귀속 가능함을 요구. 모든 레이어가 감사
엔트리 씀:

- `layer` (L1..L5)
- 발동한 `rule_id` 와 `rule_version`
- `signature` 와 매칭 방법(정확 적중 / cos 유사도 + 스코어 / 캐시 age)
- `reused_from`: 결과가 재사용된 audit_id로의 back-reference (L2/L4)
- `mode` (shadow / 강제 적용) 와 결과 risk-gate 결정

Resolvable `reused_from` 없는 재사용은 결함 - 감사 체인은 원래 그것을 검증한 L5 결과로 어떤
결정에서든 walkable하고 유효한 규칙/모델 버전으로 forward해야 함.

### 포크 확장 (self-extending 온톨로지)

온톨로지는 **코어에서 도메인-비종속** 이며 **포크별 확장 가능**합니다. 포크는 자체 패키지에
`ObjectType`과 `LinkType` 카탈로그 항목을 추가하고 해당 정의를 따르는 기록을 발행하는
프로바이더를 연결합니다. `core/`나 업스트림 계약 패키지는 편집하지 않습니다.
- 새 `Resource` 하위타입은 검토된 카탈로그 항목으로 등록하고 파이프라인을 자동 상속 -
  `evaluate`, `reuse`, `similarity` 가 `core/` 의 코드 변경 없이 그들 위에서 작동.
- 새 `LinkType` (예: 포크-특이 causal 관계) 은 자체 cardinality, transitivity, 추론 메타데이터
  선언; 미사용 링크는 inert 유지.
- 새 `ActionType` (예: 포크-특이 딜리버리 어댑터) 은 자체 `required_interfaces` 와
  `submission_criteria` 선언; 미등록 액션을 참조하는 규칙은 런타임이 아니라 카탈로그 로드에서
  실패.
- Autoprovisioning: 신호에서 관찰된 인식되지 않은 ResourceType은 이슈 오픈(절대 auto-register
  아님), 그래서 온톨로지는 표류가 아니라 리뷰로 확장.

### 온톨로지 저장 레이아웃

전체 저장소, 스키마, 부트/리로드 설계는
[rule-lookup-ontology-storage-ko.md](rule-lookup-ontology-storage-ko.md)에서 관리합니다.

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| 티어 경계, 비용 통제 및 품질 게이트 | [LLM 전략](llm-strategy-ko.md) |
| 런타임 저장소 및 다시 로드 동작 | [Rule 조회 온톨로지 저장소](rule-lookup-ontology-storage-ko.md) |
| 공유 운영 의미 | [FDAI 운영 온톨로지](operating-ontology-ko.md) |
| 통제된 변경 어휘 | [액션 온톨로지](../decisioning/action-ontology-ko.md) |
| 구현 상태 및 남은 작업 | [구현 원장](../../roadmap-implementation/architecture/rule-to-decision-lookup.md) |
