---
title: 규칙 조회 온톨로지 저장소
translation_of: rule-lookup-ontology-storage.md
translation_source_sha: b6ef983b70180169c39f855a1ab15821e01badf8
translation_revised: 2026-08-27
---

# 규칙 조회 온톨로지 저장소

이 문서는 규칙-결정 조회 온톨로지의 저장소, 관계형 스키마, 부트/리로드 설계를 관리합니다.
계층 조회 파이프라인은
[llm-strategy-ko.md](llm-strategy-ko.md#rule-to-decision-lookup-파이프라인)에서 계속 관리합니다.

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| 버전이 지정된 온톨로지와 Rule 카탈로그 산출물 | implemented | `rule-catalog/vocabulary/`; `rule-catalog/catalog/`; `test_ontology_catalog.py`; `test_rule_catalog.py` | 카탈로그 로더는 시작 전에 ObjectType, LinkType, ActionType, Rule 참조 및 전달 의미 체계를 검증합니다. |
| 관계형 온톨로지 인스턴스와 정확한 릴리스 고정 | implemented | `alembic/versions/20260713_0011_ontology_instances.py`; `20260801_0067_ontology_release_pinning.py`; `20260813_0081_ontology_release_registry.py`; `test_postgres_ontology_instance.py` | PostgreSQL은 방향 및 호환성 가드와 함께 타입이 지정된 인스턴스와 정확한 릴리스 메타데이터를 저장합니다. |
| 단일 저장소 L2-L4 영속성 표면 | implemented | `service-migrations/branches/core-control-plane/versions/20260829_core_catalog_lifecycle.py`; `services/core-control-plane/tests/persistence/test_catalog_lifecycle_integration.py` | 현재 서비스 헤드는 학습된 액션을 카탈로그 버전으로 범위 지정하고, 서로 다른 버전에서 같은 signature를 허용하며, T2 항목을 만료시킵니다. 라이브 검사는 로컬 PostgreSQL 채택이 가능할 때 legacy backfill, 버전 무효화, 보존 및 migration 롤백도 확인합니다. |
| 부트, 리로드 및 전달 인덱스 수명 주기 | implemented | `services/core-control-plane/src/fdai/core/tiers/t0_deterministic/index.py`; `services/core-control-plane/tests/core/tiers/t0_deterministic/test_index.py`; [부트와 리로드](#부트와-리로드) | 카탈로그 후보는 전이 lock 아래 게시 전에 컴파일됩니다. 컴파일 실패 시 현재 및 N-1 인덱스가 변경되지 않고, 보존된 버전의 충돌하는 내용은 거부되며, 승인된 N/N-1 인덱스는 replay할 수 있습니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-08-14 | in-progress | 이전 이력을 재구성하지 않고 구현 원장을 도입했으며 저장소 설명을 현재 migration 소유 스키마에 맞췄습니다. | `current change`; 구현 범위 표의 카탈로그, migration 및 집중 영속성 근거입니다. | 아래의 L2-L4 수명 주기와 원자적 리로드 근거 미비점을 해결합니다. |
| 2026-08-27 | implemented | 서비스 헤드 카탈로그 수명 주기 migration, 라이브 PostgreSQL 수명 주기 검사, N/N-1 replay 및 롤백을 보존하는 원자적 전달 인덱스 수명 주기를 추가했습니다. 스키마 스케치를 migration 소유 열에 맞췄습니다. | `current change`; `test_catalog_lifecycle_integration.py`; `test_index.py`; 서비스 migration inventory 및 집중 pytest 검사입니다. | 라이브 증적을 얻으려면 로컬 PostgreSQL 채택이 필요합니다. 원격 또는 Azure 증적은 주장하지 않습니다. |
| 2026-08-27 | implemented | 동시 reload 및 rollback 전이를 직렬화하고, 보존된 N-1 버전의 충돌하는 내용을 거부했으며, legacy backfill 및 안전한 downgrade 검사를 포함하도록 학습된 액션의 유일성을 버전 기준으로 변경했습니다. | `current change`; `test_index.py`; `test_catalog_lifecycle_integration.py`; 서비스 migration inventory 및 집중 pytest 검사입니다. | 라이브 증적을 얻으려면 로컬 PostgreSQL 채택이 필요합니다. 원격 또는 Azure 증적은 주장하지 않습니다. |
| 2026-08-27 | implemented | bounded 카탈로그 digest tombstone을 추가하여 제거된 버전을 다른 규칙으로 재바인딩할 수 없게 했으며, 카탈로그 버전에 걸친 signature 충돌이 있으면 실행 가능한 preflight 오류로 downgrade를 거부하도록 했습니다. | `current change`; `test_index.py`; `test_catalog_lifecycle_integration.py`; 집중 PostgreSQL 수명 주기 검사입니다. | 라이브 증적을 얻으려면 로컬 PostgreSQL 채택이 필요합니다. 원격 또는 Azure 증적은 주장하지 않습니다. |

### 남은 작업

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
  expires_at        timestamptz NOT NULL DEFAULT (now() + interval '1 hour'),
  PRIMARY KEY (catalog_version, id)
) PARTITION BY LIST (catalog_version);
CREATE TABLE t2_cache_default PARTITION OF t2_cache DEFAULT;
CREATE INDEX idx_t2_cache_input_hash ON t2_cache(catalog_version, input_hash);
CREATE INDEX idx_t2_cache_expires_at ON t2_cache(expires_at);
```

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
