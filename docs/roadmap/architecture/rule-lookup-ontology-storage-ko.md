---
title: 규칙 조회 온톨로지 저장소
translation_of: rule-lookup-ontology-storage.md
translation_source_sha: 633c218e686a0bf9105028bb0b9cc29bbeb9652e
translation_revised: 2026-10-30
---

# 규칙 조회 온톨로지 저장소

이 문서는 규칙-결정 조회 온톨로지의 저장소, 관계형 스키마, 부트/리로드 설계를 관리합니다.
계층 조회 파이프라인은
[llm-strategy-ko.md](llm-strategy-ko.md#rule-to-decision-lookup-파이프라인)에서 계속 관리합니다.

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| 정확한 키 기반 T2 캐시 저장과 범위가 제한된 만료 정리 | implemented | `20261030_core_cache_storage_efficiency.py`; `postgres_t2_cache.py`; 새로 채택한 분리 검증 데이터베이스의 `test_postgres_t2_cache.py`: 23개 통과; 집중 단위·CLI 검사 | 만료·생성 시각 우선순위를 유지하고 롤백 바인딩을 임의로 만들지 않은 채 첫 카탈로그도 지원합니다. 만료 행과 이전 파티션의 정리 범위를 제한하고 불변 증적과 분리된 레거시 데이터를 보존합니다. 운영 배포나 레거시 폐기 완료를 주장하지 않습니다. |
| 버전이 지정된 온톨로지와 Rule 카탈로그 산출물 | implemented | `rule-catalog/vocabulary/`; `rule-catalog/catalog/`; `test_ontology_catalog.py`; `test_rule_catalog.py` | 카탈로그 로더는 시작 전에 ObjectType, LinkType, ActionType, Rule 참조 및 전달 의미 체계를 검증합니다. |
| 관계형 온톨로지 인스턴스와 정확한 릴리스 고정 | implemented | `alembic/versions/20260713_0011_ontology_instances.py`; `20260801_0067_ontology_release_pinning.py`; `20260813_0081_ontology_release_registry.py`; `test_postgres_ontology_instance.py` | PostgreSQL은 방향 및 호환성 가드와 함께 타입이 지정된 인스턴스와 정확한 릴리스 메타데이터를 저장합니다. |
| 단일 저장소 L2-L4 영속성 표면 | implemented | `service-migrations/branches/core-control-plane/versions/20260829_core_catalog_lifecycle.py`; `services/core-control-plane/tests/persistence/test_catalog_lifecycle_integration.py` | 현재 서비스 헤드는 학습된 액션을 카탈로그 버전으로 범위 지정하고, 서로 다른 버전에서 같은 signature를 허용하며, T2 항목을 만료시킵니다. 라이브 검사는 로컬 PostgreSQL 채택이 가능할 때 legacy backfill, 버전 무효화, 보존 및 migration 롤백도 확인합니다. |
| 부트, 리로드 및 전달 인덱스 수명 주기 | implemented | `services/core-control-plane/src/fdai/core/tiers/t0_deterministic/index.py`; `services/core-control-plane/tests/core/tiers/t0_deterministic/test_index.py`; [부트와 리로드](#부트와-리로드) | 카탈로그 후보는 전이 lock 아래 게시 전에 컴파일됩니다. 컴파일 실패 시 현재 및 N-1 인덱스가 변경되지 않고, 보존된 버전의 충돌하는 내용은 거부되며, 승인된 N/N-1 인덱스는 replay할 수 있습니다. |

### 구현 이력

T2 캐시 용량 개선의 최신 검증 이력은
[영문 구현 이력](rule-lookup-ontology-storage.md#implementation-history)에서 관리합니다.

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-08-14 | in-progress | 이전 이력을 재구성하지 않고 구현 원장을 도입했으며 저장소 설명을 현재 migration 소유 스키마에 맞췄습니다. | `current change`; 구현 범위 표의 카탈로그, migration 및 집중 영속성 근거입니다. | 아래의 L2-L4 수명 주기와 원자적 리로드 근거 미비점을 해결합니다. |
| 2026-08-27 | implemented | 서비스 헤드 카탈로그 수명 주기 migration, 라이브 PostgreSQL 수명 주기 검사, N/N-1 replay 및 롤백을 보존하는 원자적 전달 인덱스 수명 주기를 추가했습니다. 스키마 스케치를 migration 소유 열에 맞췄습니다. | `current change`; `test_catalog_lifecycle_integration.py`; `test_index.py`; 서비스 migration inventory 및 집중 pytest 검사입니다. | 라이브 증적을 얻으려면 로컬 PostgreSQL 채택이 필요합니다. 원격 또는 Azure 증적은 주장하지 않습니다. |
| 2026-08-27 | implemented | 동시 reload 및 rollback 전이를 직렬화하고, 보존된 N-1 버전의 충돌하는 내용을 거부했으며, legacy backfill 및 안전한 downgrade 검사를 포함하도록 학습된 액션의 유일성을 버전 기준으로 변경했습니다. | `current change`; `test_index.py`; `test_catalog_lifecycle_integration.py`; 서비스 migration inventory 및 집중 pytest 검사입니다. | 라이브 증적을 얻으려면 로컬 PostgreSQL 채택이 필요합니다. 원격 또는 Azure 증적은 주장하지 않습니다. |
| 2026-08-27 | implemented | bounded 카탈로그 digest tombstone을 추가하여 제거된 버전을 다른 규칙으로 재바인딩할 수 없게 했으며, 카탈로그 버전에 걸친 signature 충돌이 있으면 실행 가능한 preflight 오류로 downgrade를 거부하도록 했습니다. | `current change`; `test_index.py`; `test_catalog_lifecycle_integration.py`; 집중 PostgreSQL 수명 주기 검사입니다. | 라이브 증적을 얻으려면 로컬 PostgreSQL 채택이 필요합니다. 원격 또는 Azure 증적은 주장하지 않습니다. |

### 남은 작업

- [x] 롤백 바인딩이 없는 첫 카탈로그를 포함한 정확한 키 기반 캐시 쓰기와 만료 정리는 위의 집중 단위·CLI 검사와 분리된 PostgreSQL 검증으로 확인했습니다.

- [x] 내부 구현을 완료했습니다. 서비스 헤드 migration, 집중 수명 주기 검사, 원자적 리로드 및 롤백 동작, 권위 있는 스키마 스케치는 범위 및 이력 표의 근거로 다룹니다. 라이브 PostgreSQL 증적은 검증되지 않은 로컬 주장이 아니라 운영 증적으로 남겨 둡니다.

## 온톨로지 저장 레이아웃

온톨로지는 **새 datastore 추가 안 함**. 모든 아티팩트가 최소 인벤토리가 이미 프로비저닝한 세
기존 표면([deploy-and-onboard-ko.md](../deployment/deploy-and-onboard-ko.md#azure-resource-inventory-minimum-set))
중 하나에 랜딩: **Git** (catalog-as-code), **PostgreSQL + pgvector**, **Key Vault**.

| 아티팩트 | 성격 | 저장 | 경로 / 테이블 |
|---------|------|------|-------------|
| `ObjectType` / `LinkType` / `ActionType` 정의 | 정적, 버전됨, 리뷰됨 | **Git** | `shared/contracts/ontology/*.json`, `rule-catalog/schema/*.json` |
| 온톨로지 전달 필드 있는 `Rule` 인스턴스 | 정적, 버전됨 | **Git** | `rule-catalog/rules/*.yaml` |
| 배정 / Exemption / 재정의 | 정적, 버전됨 | **Git** | `rule-catalog/{assignments,exemptions,overrides}/` |
| 컴파일된 전달 인덱스 (`applies_to`, `triggered_by`) | 부트에서 파생 | **In-memory** | `trust-router`, `t0-deterministic` 사이드카 |
| `Resource` 인스턴스(관찰된 인벤토리) | 런타임에 발견 | **PostgreSQL** | `ontology_resource` |
| `Signal` 인스턴스(원시 이벤트) | 일시 | in-flight는 **Event Hubs Kafka 토픽**; 상관관계 윈도우 상태만 지속 | 큐 + `signal_correlation` |
| `Finding` 인스턴스(규칙 매칭) | 감사, 지속 | **PostgreSQL** | `ontology_finding` + `audit_log` |
| `Link` 인스턴스(신호→Resource, 발견 사항→발견 사항, Resource→Resource `contains` / `attached_to` / `depends_on`, ...) | 런타임 + 감사 | **PostgreSQL** | `ontology_link` |
| 학습된 액션 (L2) | 지속, 카탈로그-버전 범위 | **PostgreSQL** | `learned_action` |
| 임베딩 (L3) | 지속, HNSW-인덱스 | **PostgreSQL + pgvector** | `ontology_embedding` |
| T2 결과 캐시 (L4) | TTL-bounded | **PostgreSQL** | `t2_cache` (파티션 by `catalog_version`) |
| 감사 체인 | 추가 전용, hash-chained | **PostgreSQL** | `audit_log` |
| `resolved-models.json` | 런타임 구성 | **Key Vault** | ([모델 프로비저닝 and 수명 주기](llm-strategy-ko.md#모델-프로비저닝과-라이프사이클) 참조) |

**단일-저장소 기본 (MUST)**

PostgreSQL Flexible + pgvector는 하나의 저장소, 하나의 백업 경로, 하나의 운영 표면. 전용 그래프
데이터베이스(Neo4j / AGE) 는 **프로비저닝 안 됨** - 우리가 필요한 런타임 탐색
(`Signal → Rule` via `triggered_by ∩ applies_to`) 은 B-tree + GIN 인덱스로 커버되는 두 인덱스
교집합. 측정이 같은 시나리오 세트에서 multi-hop causal 쿼리가 관계형 지연 예산 초과함을 보일 때만
단계 4에서 재평가.

**스키마 스케치** (설명용): 권위 있는 현재 형태는 `alembic/versions/` 아래의 Alembic
헤드와 Core 서비스 migration 가지입니다. 이 스케치는 소유권과 조회 모델을 설명하며, 운영자는
정확한 열, 제약 및 타입을 migration에서 확인하는 것이 좋습니다.

```sql
CREATE TABLE ontology_object_type (
  name               text PRIMARY KEY,
  version            text NOT NULL,
  key_field          text NOT NULL,
  properties         jsonb NOT NULL,
  description        text,
  created_at         timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE ontology_link_type (
  name               text PRIMARY KEY,
  version            text NOT NULL,
  from_type          text NOT NULL REFERENCES ontology_object_type(name),
  to_type            text NOT NULL REFERENCES ontology_object_type(name),
  cardinality        text NOT NULL,
  description        text,
  created_at         timestamptz NOT NULL DEFAULT now(),
  is_transitive      boolean NOT NULL DEFAULT false,
  is_causal          boolean NOT NULL DEFAULT false,
  temporal_order     boolean NOT NULL DEFAULT false,
  order_by_property  text
);

CREATE TABLE ontology_resource (
  id                 text PRIMARY KEY,
  object_type        text NOT NULL REFERENCES ontology_object_type(name),
  properties         jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  revision           bigint NOT NULL DEFAULT 1,
  type_version       text,
  catalog_digest     text
);
CREATE INDEX idx_ontology_resource_object_type ON ontology_resource(object_type);

CREATE TABLE ontology_finding (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  rule_id            text NOT NULL,
  resource_ref       text NOT NULL REFERENCES ontology_resource(id),
  severity           text NOT NULL,
  state              text NOT NULL,
  details            jsonb NOT NULL DEFAULT '{}'::jsonb,
  detected_at        timestamptz NOT NULL,
  resolved_at        timestamptz
);
CREATE INDEX idx_ontology_finding_rule_id ON ontology_finding(rule_id);
CREATE INDEX idx_ontology_finding_resource_ref ON ontology_finding(resource_ref);
CREATE INDEX idx_ontology_finding_state ON ontology_finding(state);

CREATE TABLE ontology_link (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  link_type          text NOT NULL REFERENCES ontology_link_type(name),
  from_id            text NOT NULL,
  to_id              text NOT NULL,
  properties         jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at         timestamptz NOT NULL DEFAULT now(),
  type_version       text,
  catalog_digest     text
);
CREATE INDEX idx_ontology_link_from ON ontology_link(from_id);
CREATE INDEX idx_ontology_link_to ON ontology_link(to_id);

CREATE TABLE learned_action (             -- L2
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  rule_id            text NOT NULL,
  action_signature   text NOT NULL UNIQUE,
  action_payload     jsonb NOT NULL,
  success_count      integer NOT NULL DEFAULT 0,
  rollback_count     integer NOT NULL DEFAULT 0,
  last_used_at       timestamptz,
  created_at         timestamptz NOT NULL DEFAULT now(),
  catalog_version    text NOT NULL DEFAULT 'legacy',
  UNIQUE (catalog_version, action_signature)
);
CREATE INDEX idx_learned_action_rule_id ON learned_action(rule_id);
CREATE INDEX idx_learned_action_rule_catalog ON learned_action(rule_id, catalog_version);

CREATE TABLE ontology_embedding (         -- L3
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  resource_ref      text NOT NULL REFERENCES ontology_resource(id) ON DELETE CASCADE,
  model             text NOT NULL,
  embedding         vector(1536) NOT NULL,
  created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_ontology_embedding_resource_ref ON ontology_embedding(resource_ref);
CREATE INDEX idx_ontology_embedding_hnsw
  ON ontology_embedding USING hnsw (embedding vector_cosine_ops);

CREATE TABLE t2_cache (                   -- L4
  id                uuid NOT NULL DEFAULT gen_random_uuid(),
  catalog_version   text NOT NULL,
  input_hash        text NOT NULL,
  output            jsonb NOT NULL,
  model             text NOT NULL,
  created_at        timestamptz NOT NULL DEFAULT now(),
  expires_at        timestamptz NOT NULL,
  PRIMARY KEY (catalog_version, id),
  UNIQUE (catalog_version, input_hash)
) PARTITION BY LIST (catalog_version);
CREATE INDEX idx_t2_cache_lookup
  ON t2_cache(catalog_version, input_hash, expires_at DESC, created_at DESC);
CREATE INDEX idx_t2_cache_expiry_cleanup
  ON t2_cache(expires_at, catalog_version, id);
```

### 캐시 용량과 유지관리

수명주기 관리 경로가 카탈로그별 파티션을 관리합니다.
분리된 `t2_cache_legacy_default`는 쓰기용 기본 파티션이 아니라 롤백 자료로 유지합니다.
각 `(catalog_version, input_hash)`에는 결과를 최대 하나만 저장합니다.
동시 쓰기에서도 중복 결과를 누적하지 않고 만료 시각과 생성 시각에 따른 기존 조회
우선순위를 유지합니다.

회전 작업은 활성 카탈로그와 등록된 롤백 카탈로그를 포함해 만료 행을 최대 1,000개 정리합니다.
카탈로그 바인딩과 불변 전환 증적은 삭제하지 않습니다.
전체 제한 시간 15초 안에서 이전 파티션을 최대 32개 검토합니다.
행 정리의 기준 시점은 데이터베이스의 현재 시각을 넘지 않으며 잠긴 행은 건너뜁니다.
일반적인 DELETE 권한 대신 Core 전용 유지관리 함수를 사용합니다.
정리 건수와 기준 시점을 회전 증적에 함께 기록하므로 같은 증적을 재생해도 정리를
다시 실행하지 않습니다.

첫 카탈로그의 권위 있는 바인딩이 `None`일 때만 CLI의 `--rollback`을 생략합니다.
롤백 카탈로그가 있으면 바인딩을 임의로 만들거나 무시하지 않고 생략을 차단합니다.

마이그레이션은 중복 행을 최대 10,000개까지 원자적으로 정리합니다.
누적량이 더 많으면 유지관리가 필요하다는 오류와 함께 실패합니다.
분리된 레거시 데이터를 폐기하거나 롤백 보존 기간을 임의로 정하지 않습니다.
배포별 보존 정책이나 레거시 폐기를 결정하기 전에
[데이터베이스 저장 공간 진단](../../runbooks/database-storage-efficiency-ko.md)을 확인하세요.

스키마 노트:

- `ontology_resource.properties` 는 **민감정보가 제거된** 저장; 원시 페이로드는
  [security-and-identity-ko.md § 데이터 Protection](security-and-identity-ko.md#데이터-보호) 과
  같은 아이덴티티와 프라이버시 규칙 하 `audit_log` 에 포인터로 존재.
- `t2_cache` 는 `catalog_version` 으로 파티션되고 `expires_at` 은 TTL 읽기 가드입니다.
  카탈로그 승격은 리더가 사용하는 버전을 변경하므로 이전 항목을 재사용하지 않습니다.
  `learned_action` 행은 보존되며 replay 및 감사 이력을 위해 카탈로그 버전과 함께 선택됩니다.
- UUID 기본 키는 PostgreSQL이 생성합니다. `action_signature`은 `catalog_version` 내에서
  유일하며 `input_hash` 및 카탈로그 digest가 idempotent 쓰기와 replay에 사용하는 안정적인
  상관관계 키를 제공합니다.
- bounded digest tombstone 집합은 용량이 소진되면 승인된 identity를 잊는 대신 새 버전을
  거부합니다.
- 서비스 migration downgrade는 카탈로그 버전에 걸쳐 중복된 `action_signature` 값이 있을 때
  버전 인식 유일성 제거를 거부합니다. 유효한 학습된 액션을 조용히 삭제하지 않도록 먼저
  충돌을 해결해야 합니다.

## 부트와 리로드

![부트와 리로드. 주요 단계는 Git: catalog-as-code, process start, load ObjectType/LinkType/ActionType + Rule YAMLs, compile OPA/Rego, build in-memory dispatch indexes / applies_to, triggered_by inverted lookup, ready, PostgreSQL: instance state, Key Vault: resolved-models.json입니다.](../../diagrams/generated/fdai-roadmap-architecture-rule-lookup-ontology-storage-01.ko.svg)

- **정적 아티팩트 진실 원본은 Git; 인스턴스 상태 진실 원본은 PostgreSQL.** 두 레이어는 절대
  겹치지 않음.
- 카탈로그 PR 머지 -> `catalog_version` bump -> 후보 전달 인덱스를 게시 전에 컴파일합니다.
  현재 및 N-1 인덱스는 replay에 사용할 수 있고 컴파일 실패 시 이전 현재 인덱스를 그대로 둡니다.
  새 L2 리더는 `catalog_version`으로 범위를 지정하고 L4 리더는 `expires_at > now()`도 요구하므로
  승격 후 오래된 항목을 재사용하지 않습니다.
