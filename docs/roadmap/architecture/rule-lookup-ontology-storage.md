---
title: Rule Lookup Ontology Storage
---
# Rule Lookup Ontology Storage

This document owns the storage, relational schema, and boot/reload design for the
rule-to-decision lookup ontology. The layered lookup pipeline remains in
[llm-strategy.md](llm-strategy.md#rule-to-decision-lookup-pipeline).

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Versioned ontology and Rule catalog artifacts | implemented | `rule-catalog/vocabulary/`; `rule-catalog/catalog/`; `test_ontology_catalog.py`; `test_rule_catalog.py` | Catalog loaders validate ObjectType, LinkType, ActionType, Rule references, and dispatch semantics before startup. |
| Relational ontology instances and exact release pinning | implemented | `alembic/versions/20260713_0011_ontology_instances.py`; `20260801_0067_ontology_release_pinning.py`; `20260813_0081_ontology_release_registry.py`; `test_postgres_ontology_instance.py` | PostgreSQL stores typed instances and exact release metadata with direction and compatibility guards. |
| Single-store L2-L4 persistence surfaces | in-progress | `service-migrations/branches/core-control-plane/versions/20260809_core_runtime_role.py`; current `learned_action`, `ontology_embedding`, and `t2_cache` tables | The tables and service ownership exist, but this document does not yet cite one focused lifecycle check proving promotion invalidation, expiry, and rollback together. |
| Boot, reload, and dispatch-index lifecycle | in-progress | [Boot and Reload](#boot-and-reload); catalog loader tests under `tests/rule_catalog/` | Startup compilation and exact catalog loading are implemented. A retained reload receipt proving atomic index replacement and N/N-1 behavior remains absent from this owner document. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance and aligned the storage description with the current migration-owned schema. | `current change`; catalog, migration, and focused persistence evidence listed in the scope table. | Close the L2-L4 lifecycle and atomic reload evidence gaps below. |

### Remaining work

- [ ] Add one focused PostgreSQL lifecycle check that proves catalog-version invalidation, T2 cache expiry, learned-action retention, and rollback on the current service migration head.
- [ ] Retain an atomic catalog reload receipt showing that failed compilation preserves the prior dispatch indexes and that an accepted N/N-1 transition remains replayable.
- [ ] Replace or annotate any schema-sketch field that diverges from the authoritative Alembic head before treating the sketch as an exact operator reference.

## Ontology Storage Layout

The ontology adds **no new datastore**. Every artifact lands in one of three existing
surfaces the minimum inventory already provisions
([deploy-and-onboard.md](../deployment/deploy-and-onboard.md#azure-resource-inventory-minimum-set)):
**Git** (catalog-as-code), **PostgreSQL + pgvector**, and **Key Vault**.

| Artifact | Nature | Storage | Path / table |
|----------|--------|---------|--------------|
| `ObjectType` / `LinkType` / `ActionType` definitions | static, versioned, reviewed | **Git** | `shared/contracts/ontology/*.json`, `rule-catalog/schema/*.json` |
| `Rule` instances (with ontology dispatch fields) | static, versioned | **Git** | `rule-catalog/rules/*.yaml` |
| Assignments / Exemptions / Overrides | static, versioned | **Git** | `rule-catalog/{assignments,exemptions,overrides}/` |
| Compiled dispatch indexes (`applies_to`, `triggered_by`) | derived at boot | **In-memory** | `trust-router`, `t0-deterministic` sidecars |
| `Resource` instances (observed inventory) | discovered at runtime | **PostgreSQL** | `ontology_resource` |
| `Signal` instances (raw events) | transient | **Event Hubs Kafka topic** in flight; only correlation window state persists | queue + `signal_correlation` |
| `Finding` instances (rule matches) | audited, persistent | **PostgreSQL** | `ontology_finding` + `audit_log` |
| `Link` instances (Signal→Resource, Finding→Finding, Resource→Resource `contains` / `attached_to` / `depends_on`, ...) | runtime + audit | **PostgreSQL** | `ontology_link` |
| Learned actions (L2) | persistent, catalog-version scoped | **PostgreSQL** | `learned_action` |
| Embeddings (L3) | persistent, HNSW-indexed | **PostgreSQL + pgvector** | `ontology_embedding` |
| T2 result cache (L4) | TTL-bounded | **PostgreSQL** | `t2_cache` (partition by `catalog_version`) |
| Audit chain | append-only, hash-chained | **PostgreSQL** | `audit_log` |
| `resolved-models.json` | runtime config | **Key Vault** | (see [Model Provisioning and Lifecycle](llm-strategy.md#model-provisioning-and-lifecycle)) |

**Single-store default (MUST)**

PostgreSQL Flexible + pgvector is one store, one backup path, one operational surface.
A dedicated graph database (Neo4j / AGE) is **not** provisioned - the runtime traversals
we need (`Signal → Rule` via `triggered_by ∩ applies_to`) are two indexed intersections,
covered by B-tree + GIN indexes. Re-evaluate at Phase 4 only if measurement shows
multi-hop causal queries exceed relational latency budgets on the same scenario set.

**Schema sketch** (illustrative): the authoritative current shape is the Alembic head under
`alembic/versions/` plus the Core service migration branch. The sketch explains the ownership and
query model; operators should use the migrations for exact columns, constraints, and types.

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
  catalog_version    text NOT NULL DEFAULT 'legacy'
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

Notes on the schema:

- `ontology_resource.properties` is stored **redacted**; the raw payload lives as a pointer in
  `audit_log` under the same identity and privacy rules as
  [security-and-identity.md § Data Protection](security-and-identity.md#data-protection).
- `t2_cache` is partitioned by `catalog_version`, and `expires_at` is the TTL read guard.
  A catalog promotion changes the version used by readers, so prior entries are not reused.
  `learned_action` rows are retained and selected with their catalog version for replay and
  audit history.
- UUID primary keys are generated by PostgreSQL. `action_signature`, `input_hash`, and catalog
  digests provide the stable correlation keys used for idempotent writes and replay.

## Boot and Reload

![Boot and Reload. The main stages are Git: catalog-as-code, process start, load ObjectType/LinkType/ActionType + Rule YAMLs, compile OPA/Rego, build in-memory dispatch indexes / applies_to, triggered_by inverted lookup, ready, PostgreSQL: instance state, Key Vault: resolved-models.json.](../../diagrams/generated/fdai-roadmap-architecture-rule-lookup-ontology-storage-01.en.svg)

- **Static artifacts source of truth is Git; instance state source of truth is PostgreSQL.**
  The two layers never overlap.
- A catalog PR merge -> `catalog_version` bump -> candidate dispatch indexes compile before
  publication. The current and N-1 indexes remain available for replay; a failed compilation
  leaves the prior current index untouched. New L2 readers scope by `catalog_version`, while
  L4 readers also require `expires_at > now()`, so old entries are not reused after promotion.
