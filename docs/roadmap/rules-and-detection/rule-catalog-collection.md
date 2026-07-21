---
title: Rule Catalog Collection
---
# Rule Catalog Collection

How FDAI **collects** checklists, best practices, policies, and baselines, and
**normalizes** them into machine-readable YAML for the T0 deterministic engine. This document
answers: *where do rules come from, how are they fetched, and what YAML shape do they take?*

It complements - and does not restate - the normalized schema and conflict handling in
[phase-1-rule-catalog-t0.md](../phases/phase-1-rule-catalog-t0.md) and the rule-catalog principles
in [architecture.instructions.md](../../../.github/instructions/architecture.instructions.md).
The continuous update pipeline is [phase-2-quality-and-t1.md](../phases/phase-2-quality-and-t1.md).

> Everything here is customer-agnostic. Examples use synthetic placeholders only, per
> [generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md).

> **Implementation status**: Source manifest/fetch/snapshot/watcher core; rule, Rego, Azure
> Policy, and kube-bench parsers; strict Rule/ActionType/resource-vocabulary loaders; collected
> Azure and kube-bench catalogs; continuous pipeline stages; and CandidateGuard are implemented.
> The current loader-backed normalized artifact in this document is `Rule`. Dedicated
> best-practice, config-baseline, and measurement-baseline schemas/loaders remain target shapes.
> Not every external connector/parser, production discovery schedule/PR delivery, or
> compliance/threat crosswalk listed below is complete.

## What We Collect

Four distinct artifact kinds, each normalized to its own YAML shape but sharing `provenance`:

| Kind | Examples | Used by |
|------|----------|---------|
| **Rule / check** | a single testable control (e.g. "storage must deny public access") | T0 policy evaluation |
| **Best practice** | a recommendation with rationale, often multi-check (e.g. WAF pillar guidance) | T0 checklist + grounding citations |
| **Config baseline** | a hardened reference set for a resource type (e.g. a cluster hardening baseline) | T0 drift / what-if |
| **Measurement baseline** | recorded KPI values for a reference agent on the frozen scenario set | goals-and-metrics comparison |

The first three feed the deterministic engine. The fourth is the **performance baseline** from
[phase-0-instrumentation.md](../phases/phase-0-instrumentation.md) - a different concept that shares
this document only because both are "baselines"; keep them separate in storage and schema.

## Collection Sources

Grouped by origin. Each source has a **collector** that maps its native format to the normalized
schema and stamps `provenance`. `resource-type` is normalized to a CSP-neutral vocabulary.

| Group | Sources | Native format | Fetch method |
|-------|---------|---------------|--------------|
| Azure-native | WAF checklists, AKS Baseline, MCSB, Azure Policy built-in initiatives, Advisor, Defender recommendations | JSON / ARM policy / docs | REST API, policy definitions export, docs repo |
| Cloud-neutral / OSS | CIS Benchmarks, OPA/Gatekeeper libraries, Cloud Custodian policies | PDF/spreadsheet, Rego, YAML | git clone, package registry, licensed download |
| IaC scanners | Checkov, tfsec, KICS, Trivy | built-in rule packs (YAML/JSON/Go) | git clone, package registry |
| Kubernetes | kube-bench, Gatekeeper constraint templates | YAML | git clone |
| Code quality | SonarQube rulesets, Roslyn analyzers, ESLint | XML/JSON | package registry, API |
| FinOps / cost | Advisor cost recommendations, cost-anomaly heuristics, FOCUS-aligned tagging/budget controls | JSON / authored | REST API, authored |
| DR / resilience | resiliency-review checklists, backup/replication controls, chaos-experiment templates | JSON / YAML / docs | REST API, git clone, docs repo |
| Detection / signals | anomaly baselines and thresholds, forecast targets, correlation keys (feed the detectors in observability-and-detection) | authored / JSON | authored |
| AWS / GCP (TBD) | AWS Well-Architected / Config managed rules, GCP Recommender / Policy Controller | JSON | REST API, git - **deferred**, non-Azure targets are TBD (see [Always-On Rules](../../../.github/copilot-instructions.md#always-on-rules-must)) |

The FinOps and DR/resilience rows exist because the control plane spans Resilience, Change
Safety, and Cost Governance; a sources table covering only security/config would leave two of
the three verticals uncollected. The Detection/signals row supplies the baselines, thresholds,
and correlation keys
consumed by [observability-and-detection.md](observability-and-detection.md) (anomaly, forecast,
correlation, RCA). Mapping controls to regulatory frameworks (NIST/PCI/ISO) is deferred - see
[Open Decisions](#open-decisions).

### Security Sources (deep)

Security is the highest-severity category and draws from more sources than any other, so it is
enumerated explicitly. Each still normalizes to the common schema with `category: security`.

| Layer | Sources | Native format | Fetch method |
|-------|---------|---------------|--------------|
| Cloud posture | MCSB, Defender for Cloud recommendations, Azure Security Benchmark, CIS cloud benchmarks | JSON / policy / docs | REST API, git, licensed download |
| Vulnerability / threat intel | NVD/CVE (with CVSS base score), CISA KEV catalog, EPSS, GitHub Advisory Database, OSV | JSON feed | REST API, git |
| Threat modeling | MITRE ATT&CK, MITRE D3FEND (technique → control mapping) | STIX / JSON | REST API, git |
| Standards / frameworks | NIST SP 800-53, ISO 27001, PCI-DSS, SOC 2, CIS Controls | spreadsheet / docs | docs / licensed download (redistribution per source) |
| Identity / access | least-privilege role baselines, context-based (conditional) access baselines, RBAC drift checks | authored / JSON | authored, REST API |
| Application / code | OWASP Top 10, OWASP ASVS, SAST/DAST rulesets, secret-scanning rules (gitleaks/trufflehog) | JSON / YAML | git, package registry |
| Supply chain | Trivy/Grype vuln DB, SBOM policy (CycloneDX/SPDX), signature policy (Sigstore/cosign), provenance attestation (SLSA/in-toto) | JSON / YAML | git, package registry |
| Network | NSG/firewall exposure rules, TLS/cipher policy, private-endpoint enforcement | authored / policy | authored, REST API |

Notes:

- **Freshness**: vulnerability sources (NVD/CVE, KEV, OSV, EPSS) are time-sensitive - they change
  daily and KEV entries carry remediation due-dates - so their manifests set the shortest watcher
  cadence and are the motivating case for the Phase 2 watcher. Phase 1 on-demand fetches are
  treated as potentially stale, not authoritative for currency.
- **Severity derivation is deterministic**, not ad hoc: for vulnerability rules `severity` is a
  pure function of the pinned **CVSS base score** (`>= 9.0` → `critical`, `>= 7.0` → `high`,
  `>= 4.0` → `medium`, else `low`), and **KEV presence escalates to `critical`**. The CVSS
  version used (v3.1 or v4.0) is recorded on the rule (e.g. `parameters.cvss_version`) so a score
  is reproducible. Non-vuln rules take a source/category default severity, not this mapping.
- **Threat mappings**: MITRE ATT&CK technique ids and D3FEND control ids attach to a rule as
  mapping tags via the compliance/threat crosswalk (see [Open Decisions](#open-decisions)), never
  as executable `check_logic`.
- **Standards licensing differs per source**: some are public-domain and redistributable
  (e.g. NIST SP 800-53), others are **reference-only** because their text is licensed (e.g. CIS,
  ISO 27001, PCI-DSS). For a reference-only standard we author the check and cite the control id
  via `provenance` and the compliance crosswalk; `redistribution` is set per-source, never
  assumed.

### Database Sources and Rules

Databases are **stateful**, so their rules span three concerns - security, DR, and
configuration - and must never be treated like stateless resources. This subsection is
enumerated because DB coverage is otherwise easy to under-specify.

| Concern | What is collected | Example sources |
|---------|-------------------|-----------------|
| DB security | encryption at rest (TDE/CMK), TLS-in-transit enforcement, auth mode (identity-only, no shared secrets), firewall / private endpoint, least-privilege DB roles, audit logging, secret rotation | CIS benchmarks per engine (SQL Server, PostgreSQL, MySQL, MongoDB, Oracle), cloud DB security baselines, MCSB data controls |
| DB DR / resilience | PITR enabled + retention window, geo-replication / read-replica present, backup schedule + evidence a restore rehearsal passed within a retention window, replication-lag threshold, RPO/RTO objective compliance, integrity-verification evidence after failover | resiliency-review checklists, backup/replication control catalogs, authored DR rules |
| DB configuration | parameter hardening, connection/session limits, logging/slow-query settings, version/patch currency, public-network-access disabled | CIS DB benchmarks, engine hardening guides |

DB rules use CSP-neutral `resource_type` values such as `sql-database`, `postgresql-server`,
`nosql-database`, and `cache`. These encode the **DB engine family** (engine-neutral across CSPs,
not a vendor resource path), so per-engine CIS controls stay reproducible without leaking an ARM
path; the DB-security concern maps to `category: security`, DB-DR to `category: reliability`, and
DB-configuration hardening to `category: config-drift`. DR rules are cross-linked to
[phase-3-integrated-loop.md](../phases/phase-3-integrated-loop.md) (deep DB-DR: restore-into-isolated-env,
integrity verification, RPO/RTO measurement) - the catalog encodes the *checks* over recorded
evidence; the phase-3 scheduler runs the *tests* (the rehearsal and failover themselves).

Two DB rule examples (customer-agnostic placeholders):

```yaml
schema_version: 1.0.0
id: sql-database.tde-required
version: 1.0.0
source: mcsb
severity: high
category: security
resource_type: sql-database
check_logic:
  kind: rego
  reference: policies/sql_database/tde_required.rego
remediation:
  template_ref: remediation/sql_database/enable_tde.tftpl
  cost_impact_monthly_usd: 0
remediates: remediate.enable-tde
provenance:
  source_url: https://example.com/db-benchmark/controls/2.1
  source_version: v1.0.0
  resolved_ref: "0000000000000000000000000000000000000000"
  content_hash: "sha256:0000000000000000000000000000000000000000000000000000000000000000"
  license: LicenseRef-reference-only
  redistribution: reference-only
  retrieved_at: 2026-07-03T00:00:00Z
  mapped_by: catalog-team
```

```yaml
schema_version: 1.0.0
id: postgresql-server.point-in-time-restore
version: 1.0.0
source: waf
severity: high
category: reliability
resource_type: postgresql-server
parameters:
  min_retention_days: 7
check_logic:
  kind: rego
  reference: policies/postgresql/point_in_time_restore.rego
remediation:
  template_ref: remediation/postgresql/raise_backup_retention.tftpl
  cost_impact_monthly_usd: 0
remediates: remediate.enable-backup-protection
provenance:
  source_url: https://example.com/dr-catalog/postgresql
  source_version: v1.0.0
  resolved_ref: "0000000000000000000000000000000000000000"
  content_hash: "sha256:0000000000000000000000000000000000000000000000000000000000000000"
  license: Apache-2.0
  redistribution: embeddable
  retrieved_at: 2026-07-03T00:00:00Z
  mapped_by: catalog-team
```

> DB DR rules encode *checks* (is PITR on within the retention window, is a geo-replica present,
> is lag within threshold); they never execute a failover. Executing and verifying failover is
> the phase-3 scheduler's job under its safety invariants. Each rule is a **single testable
> control** (per the definition at the top of this doc): geo-replica presence and
> replication-lag-within-`max_replica_lag_seconds` are **separate** rules, optionally grouped by
> a `config-baseline`, not folded into the PITR rule above. The `parameters` field shown here is
> set per-assignment by an administrator - see [rule-governance.md](rule-governance.md).

### Licensing (read before adding a source)

- Some sources (notably **CIS Benchmarks**) restrict redistribution of their content. The
  collector MUST **not** commit source text, PDFs, spreadsheets, screenshots, **derived excerpts,
  or embeddings / vector indexes built from that text**. Store only the **normalized rule logic
  we author** plus a `provenance` reference (URL, resolved commit/digest, version, retrieved-at,
  content hash) pointing back to the licensed source.
- Each manifest carries two independent fields: `license` - an **SPDX identifier** for OSS
  (e.g. `Apache-2.0`) or `LicenseRef-reference-only` for restricted sources - and
  `redistribution` (`embeddable` | `reference-only`). `redistribution`, not the license name,
  drives enforcement: a `reference-only` source may contribute authored logic plus provenance,
  but its raw content is blocked from the tree.
- **CI enforces this**, not review alone: the build fails if any file under a `reference-only`
  source's collector contains verbatim source text, and secret / customer-data scans run on all
  collected output
  ([generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)).
- **Untrusted content**: source-provided text (rationale, descriptions) is untrusted input - it
  may carry secrets or prompt-injection. It is stored as inert data, length-bounded and scanned,
  is never treated as instructions, and any downstream LLM use of it passes the T2 quality gate
  ([architecture.instructions.md](../../../.github/instructions/architecture.instructions.md)).
- No source content bypasses the customer-agnostic rule; collectors reject any imported text
  carrying customer identifiers.

## Collector Architecture

Each source is described by a **source manifest** (config, not code) and processed by a generic
pipeline, so adding a source is mostly declarative.

```text
source manifest ─► fetch ─► verify ─► parse ─► map to schema ─► provenance stamp ─► validate ─► dedupe ─► catalog
                   (pin+auth) (hash/sig) (parser plugin)                        (strict JSON Schema)  (by id)
```

- **fetch**: an adapter pulls from the source (REST, `git clone`, package registry, or licensed
  download). It MUST authenticate via an injected secret-store reference (never a committed
  credential); pin to an **immutable** revision (a git commit SHA or artifact digest, not a
  mutable tag/branch) and record the resolved revision; handle pagination and rate limits
  (respect `Retry-After`, back off) for REST sources; and apply a timeout with bounded retry.
  On fetch failure it **fails closed** - a partial fetch never produces a partial catalog.
  Cadence is on-demand in Phase 1; a scheduled watcher in Phase 2.
- **verify**: check the fetched artifact's integrity (checksum/signature where the source offers
  one) and record the computed `content_hash`; a mismatch aborts that source.
- **parse**: a format-specific reader (Rego, YAML, JSON, policy definition, docs), selected by
  the manifest `parser` key, → intermediate. Parsers are plugins behind one interface, so a new
  native format is additive; an unknown/unregistered `parser` fails validation.
- **map**: transform to the normalized schema; unmappable fields are dropped, not invented.
- **provenance stamp**: record `source_url`, `resolved_ref` (commit/digest), `source_version`,
  `retrieved_at`, `content_hash`, `license`, and `mapped_by`.
- **validate**: the candidate YAML MUST pass its per-kind JSON Schema (strict,
  `additionalProperties: false`, applied to the parsed YAML document) or it is rejected; one
  invalid entry fails the whole source run (fail-closed) rather than landing partially.
- **dedupe**: collapse by `id`, merging `provenance` for identical authored logic. This is
  **collection-time** dedup; **evaluation-time** conflict/precedence across distinct rules is a
  separate stage in
  [phase-1-rule-catalog-t0.md](../phases/phase-1-rule-catalog-t0.md#deduplication-conflict-and-precedence).
- **collect mode**: incremental by default (only controls whose `content_hash` changed); a
  control removed upstream is **tombstoned/retired** with a version bump, never silently
  dropped. A full re-collection is available for a from-scratch rebuild.

Authored Rego lives in the **top-level** `policies/` (consumed by T0 and the verifier) and is
referenced by `check_logic.reference`; source manifests live under `rule-catalog/sources/`, runtime
loaders/schemas under `src/fdai/rule_catalog/schema/` and `src/fdai/shared/contracts/`, and normalized output under `rule-catalog/catalog/`. This aligns
with [project-structure.md](../architecture/project-structure.md).

## YAML Normalization

Yes - the whole catalog is **YAML**, validated against JSON Schema (JSON Schema is the schema
language; the documents it validates are YAML) and stored as catalog-as-code. JSON is retained
only for wire formats (event/message schemas, API bodies) and runtime artifacts
(`resolved-models.json` materialized from a protected CI variable or supplied path); everything a human authors in `rule-catalog/` is YAML.

### Field Naming and Schema Conventions

YAML keys are **snake_case**; the normalized schema fields in
[phase-1-rule-catalog-t0.md](../phases/phase-1-rule-catalog-t0.md#normalized-schema) are written
kebab-case in prose. They are the **same fields** - the mapping is 1:1, so the two docs are not
contradictory:

| phase-1 field | YAML key |
|---------------|----------|
| `resource-type` | `resource_type` |
| `check-logic` | `check_logic` |
| `id`, `version`, `source`, `severity`, `category`, `remediation`, `provenance` | identical |

- `source` equals a registered manifest `source_id` (the phase-1 `source` enum).
- The current normalized `Rule` requires `schema_version` and has no `kind` discriminator. Its
  strict schema is `src/fdai/shared/contracts/rule/schema.json`. The other artifact kinds shown
  above are target shapes until dedicated schemas/loaders land.
- Enums: `severity` ∈ `critical | high | medium | low` (matching phase-1 precedence),
  `category` ∈ `security | reliability | cost | config_drift | compliance`, `redistribution` ∈
  `embeddable | reference-only`. `version` matches a semver pattern; all timestamps are
  RFC 3339 UTC (`...Z`).
- `parameters` is an **optional** object of typed inputs to `check_logic` (e.g. a retention
  threshold, a max replication-lag, a CVSS version tag). Defaults live on the rule; an
  administrator overrides them per-assignment without
  editing the rule - the authoring/assignment model is [rule-governance.md](rule-governance.md).
- **Ontology dispatch fields** are additive and CI-validated at load: `applies_to`,
  `triggered_by`, `evaluates`, `remediates`, `required_interfaces`, `submission_criteria`.
  They let the runtime traverse from a `Signal` to the exact matching rules with two index
  intersections instead of a scan; the full pipeline lives in
  [llm-strategy.md § Rule-to-Decision Lookup Pipeline](../architecture/llm-strategy.md#rule-to-decision-lookup-pipeline).
- **`remediates` vs `remediation` - two fields, one concept:** `remediates` is the
  **ActionType id** (M:1) declaring *which category of mutation* this rule proposes;
  `remediation` is the concrete *how*: `{ template_ref, cost_impact_monthly_usd }`. Both fields
  are required together on every `Rule`; the loader resolves `remediates` to a registered
  ActionType and can verify the template path on disk.
- **`alternatives[]` (optional):** a rule MAY declare alternative remediation ActionTypes
  ranked by preference; T0 always uses `remediates` (deterministic-first), and only the
  T2 quality gate - with grounding and mixed-model check - may swap in an alternative,
  never a cheaper tier. Each alternative points to a registered ActionType id, never to a
  free-form action.

  ```yaml
  # illustrative fragment
  remediates: remediate.disable-public-access          # primary, deterministic
  alternatives:
    - remediate.add-firewall-rule                       # T2 may prefer if a tag pins
    - remediate.add-private-endpoint                    #   "keep-public"
  ```
- `provenance` is a shared object on every rule-like kind:
  `{ source_url, source_version, resolved_ref, content_hash, license, redistribution, retrieved_at, mapped_by }`.
  It maps onto phase-1's "source URL/commit, imported-at timestamp, mapping author":
  `resolved_ref` = commit/digest, `retrieved_at` = imported-at, `mapped_by` = mapping author
  (a role/pipeline id, never a person).

### Source Manifest (how to collect one source)

```yaml
schema_version: "1.0.0"
id: example-oss-benchmark
name: Example OSS Benchmark
url_prefix: https://example.com/benchmark
license: LicenseRef-reference-only
redistribution: reference-only
fetch:
  kind: git
  repo: https://example.com/benchmark.git
  revision: "0000000000000000000000000000000000000000"
  subpath: controls/
parser: rule-yaml
cadence: on-demand
```

`fetch.revision` is the immutable commit/digest the fetch pins (shown as an all-zero placeholder).
Credentials are supplied to the fetch adapter through deployment configuration, never this
manifest.

### Rule / Check (normalized)

```yaml
schema_version: "1.0.0"
id: object-storage.public-access.deny
version: "1.0.0"
source: mcsb
severity: high
category: security
resource_type: object-storage
check_logic:
  kind: rego
  reference: policies/object_storage/public_access.rego
remediation:
  template_ref: remediation/object_storage/disable_public_access.tftpl
  cost_impact_monthly_usd: 0
remediates: remediate.disable-public-access
provenance:
  source_url: https://example.com/rules/object-storage-public-access
  resolved_ref: "0000000000000000000000000000000000000000"
  content_hash: "sha256:0000000000000000000000000000000000000000000000000000000000000000"
  license: LicenseRef-reference-only
  redistribution: reference-only
  retrieved_at: "2026-07-05T00:00:00Z"
```

> `remediates` is validated at load time against
> [`rule-catalog/action-types/`](../../../rule-catalog/action-types) by
> [`rule_catalog.schema.rule`](../../../src/fdai/rule_catalog/schema/rule.py) - an
> unknown ActionType id fails the load, so a rule can never quote a mutation category
> that has no `rollback_contract` / `promotion_gate` declared. Optional `alternatives`
> follows the same rule; the shipped
> [`rule-catalog/catalog/`](../../../rule-catalog/catalog) exercises the primary
> `remediates` on every entry (P1 W-2).

### Best Practice (multi-check recommendation)

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

### Config Baseline (hardened reference set)

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

### Measurement Baseline (performance reference - separate store)

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

> Values above are placeholder zeros - real numbers are recorded at measurement time per
> [goals-and-metrics.md](../architecture/goals-and-metrics.md); this repo never commits customer-measured values.
> Measurement-baseline entries live in a separate `id` namespace (`baseline.*`) and store
> (`baselines/`), never mixed with rule `id`s or rule schemas.

## Storage Layout

```
fdai/
├── policies/              # authored check-logic (OPA/Rego), consumed by T0 + verifier;
│                         #   referenced by check_logic.reference  (top-level, per project-structure)
└── rule-catalog/          # catalog-as-code (YAML)
    ├── schema/            # extension-kit/skill-bundle catalog-adjacent schemas
    ├── vocabulary/        # canonical CSP-neutral vocabularies (resource-types.yaml, ...)
    ├── action-types/      # ActionType instances quoted from rules' `remediates` field
    ├── sources/           # one folder per source: manifest (.yaml) + collector + parser
    │   └── <source>/
    ├── remediation/       # remediation templates referenced by remediation.ref
    ├── catalog/           # normalized, version-pinned YAML output (catalog-as-code)
    └── exemptions/        # time-boxed, audited exemption artifacts

  src/fdai/rule_catalog/
  ├── schema/                # source-manifest and catalog runtime loaders/schemas
  └── pipeline/              # watch → collect → parse → shadow-eval → promote/rollback
```

Authored Rego is **not** nested under `rule-catalog/`; it lives in the top-level `policies/`
consumed by T0 and the verifier, exactly as in
[project-structure.md](../architecture/project-structure.md). `src/fdai/rule_catalog/pipeline/` is the continuous updater.

- `vocabulary/resource-types.yaml` - the enumerated CSP-neutral `resource_type` identifier
  set every rule quotes from. Rename → catalog-wide migration; add → governance PR. Loader:
  `src/fdai/rule_catalog/schema/resource_type.py`, JSON Schema:
  `src/fdai/rule_catalog/schema/resource_types.schema.json`.
- `action-types/*.yaml` - one file per ontology `ActionType` instance. `default_mode`
  MUST be `shadow` in upstream and `promotion_gate` MUST be present. Loader:
  `src/fdai/rule_catalog/schema/action_type.py`; JSON Schema is the shared ontology
  schema at `src/fdai/shared/contracts/ontology/action-type.json`.

## Validation and Trust

- Every normalized entry MUST validate against its **strict** per-kind JSON Schema
  (`additionalProperties: false`) in CI; one invalid entry fails the source run (fail-closed)
  and blocks the merge.
- `provenance` is mandatory on every entry for auditability and rollback, and its
  `content_hash` is verified against the fetched artifact.
- **License / redistribution gate**: CI blocks verbatim `reference-only` source text and
  requires a valid `license` (SPDX or `LicenseRef-reference-only`) + `redistribution` value on
  each manifest.
- **Change-tracking**: a rule's `version` bumps when its resolved source content changes
  (a `content_hash` delta); an upstream removal is recorded as a tombstoned/retired entry, not a
  silent delete, so a rule set stays revertible.
- **Untrusted input**: collected source text is data, never instructions; it is length-bounded,
  secret/customer-data scanned, and only reaches an LLM through the T2 quality gate
  ([architecture.instructions.md](../../../.github/instructions/architecture.instructions.md)).
- Deduplication, conflict, and precedence are deterministic and defined in
  [phase-1-rule-catalog-t0.md](../phases/phase-1-rule-catalog-t0.md#deduplication-conflict-and-precedence);
  the continuous collect → shadow-eval → regression → promote/rollback gate is
  [phase-2-quality-and-t1.md](../phases/phase-2-quality-and-t1.md).
- Secret scanning and the customer-agnostic regex checks run on all collected fixtures and
  catalog output ([generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)).

## Autonomous Rule Discovery

Collection is not only "read upstream sources". The catalog also grows and self-corrects from
**operational signals**, so the deterministic layer keeps pace with the environment without a
human hand-crafting every rule. This is the "Living rules" principle in
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md).

### Loop

A long-horizon loop repeats indefinitely; every cycle keeps the same shared world model - the
normalized catalog, audit log, incident library, and provenance store - so cycles build on
each other rather than restart from scratch:

```text
sources + operational signals ─► observe ─► hypothesize ─► verify ─► integrate
                                                            (quality gate)
```

- **observe** - the loop reads three feeds side by side, not one at a time:
  1. **Upstream sources** via the collector pipeline above (new/changed controls).
  2. **Operational signals** - recent audit-log entries, HIL approval patterns, shadow-mode
     outcomes, rollbacks, and **override events** ([rule-governance.md](rule-governance.md)).
  3. **The current catalog** - existing rules, their provenance, their measured accuracy.
- **hypothesize** - an inference stage (an LLM stage, treated like any T2 output) proposes
  **candidate** entries in three shapes:
  - **new-rule**: a control not yet covered, motivated by a recurring incident/HIL pattern or a
    newly published upstream control.
  - **revision**: an existing rule whose upstream source changed (its `content_hash` moved)
    or whose shadow accuracy drifted below threshold.
  - **retirement**: an existing rule that is repeatedly overridden or whose shadow outcomes
    show it is a poor fit for real environments.
- **verify** - every candidate is inert data until it passes the standard **quality gate**:
  1. strict JSON Schema (`additionalProperties: false`);
  2. provenance check - `source_url`, `resolved_ref`, `content_hash`, `license`,
     `redistribution` all present and verifiable (a candidate with no grounded provenance is
     rejected outright);
  3. **mixed-model cross-check** - a second model (different family/vendor) re-derives or
     re-approves the same candidate; disagreement escalates to HIL, never auto-resolves
     ([architecture.instructions.md](../../../.github/instructions/architecture.instructions.md));
  4. deterministic verifier - Rego parses, no duplicate `id`, no conflict with existing rules
     that would silently weaken a stricter control;
  5. regression suite - existing fixtures still pass;
  6. shadow-mode dwell - the candidate runs judge-and-log-only on real traffic for a
     configured minimum period and sample size, with accuracy above threshold and zero
     policy-violation escapes.
- **integrate** - a candidate that clears the gate is promoted per the assignment/effect
  lifecycle in [rule-governance.md](rule-governance.md) (new-rule/revision lands as an audit
  effect first; a retirement lands as a tombstone). The catalog is only ever mutated by a
  merged catalog-as-code PR, never by the loop directly.

### Candidate Requirements (MUST)

- Every candidate MUST cite **grounded provenance** - an upstream document URL + resolved
  revision/hash, or a specific incident/HIL/override event id, or a specific
  vulnerability/advisory id. "The model thought of it" is not provenance.
- Every candidate MUST target the CSP-neutral `resource_type` vocabulary, never a vendor path.
- Reference-only source text MUST NOT be pasted into the candidate; only authored `check_logic`
  plus a citation, per the [Licensing](#licensing-read-before-adding-a-source) rules.
- A candidate that fails any gate step becomes an **abstain** - logged with the reason so the
  next cycle can revisit it, but never partially applied.

### Override Feedback

Overrides are a first-class input to the loop, not a dead-end. When a rule accumulates
long-lived or recurring overrides across scopes, the observe stage flags it and the
hypothesize stage proposes a **revision** (narrow the rule so the override becomes unnecessary)
or a **retirement** (the rule is systematically a poor fit). Either way the proposal still
passes the full quality gate. Overrides never mutate the catalog directly - they only supply
signal.

### Safety and Trust

- The loop is a **candidate generator**, not an executor. It cannot mutate the live catalog,
  cannot flip an assignment to enforce, and cannot bypass the promotion approvals in
  [rule-governance.md](rule-governance.md).
- Any LLM stage in this loop is a T2 call and obeys the T2 quality gate (mixed-model,
  verifier, grounding, abstain-when-unsupported) in
  [architecture.instructions.md](../../../.github/instructions/architecture.instructions.md).
- The loop's own throughput (candidates/cycle, gate pass rate, override-triggered proposal
  rate, retirement rate) is instrumented and reported in
  [goals-and-metrics.md](../architecture/goals-and-metrics.md) so it can be measured, not asserted.

### Candidate Guard (upstream implementation)

`fdai.agents._framework.candidate_guard.CandidateGuard` is the deterministic gate Mimir runs on every
`RuleCandidate` before it enters the pending list - the enforcement point for the Candidate
Requirements above and the discovery loop's poisoning defense. It never promotes anything (the
quality gate owns that); it decides **accept** vs **quarantine** and records a reason, so a
rejected candidate is preserved for audit rather than silently dropped. Checks are pure (no I/O,
no model call):

- **Provenance** - `proposed_by` and a known `proposal_kind`
  (`new` / `new-scenario` / `revision` / `retirement` / `threshold_adjustment`) are required.
- **Grounding** - a non-empty `evidence` mapping is required; an ungrounded candidate is
  quarantined ("the model thought of it" is not evidence).
- **Range sanity** - numeric evidence must be in range (a `rollback_rate` outside `[0, 1]` or a
  non-positive count is a corrupt or forged signal).
- **Flood detection** - identical candidate fingerprints beyond a repeat cap are quarantined as
  a suspected poisoning flood (Norns already dedups legitimate proposals, so a repeat burst is
  anomalous).

## Open Decisions

- [ ] Which sources are reference-only vs embeddable, confirmed against each license.
- [ ] Remaining parser plugins for docs, Checkov/tfsec/KICS/Trivy, and other vendor formats.
- [ ] Compliance-framework mapping (controls → NIST/PCI/ISO tags): a manifest field or a
      separate crosswalk artifact.
- [ ] Storage for MITRE ATT&CK technique / D3FEND control mappings: reuse the compliance
      crosswalk artifact or add a dedicated mapping-tag field on the rule.
- [ ] The deterministic CVSS+KEV → `severity` mapping and the CVSS version policy (v3.1 vs
      v4.0), and where the version tag is carried on the rule.
- [ ] Per-DB-engine control granularity: engine encoded in `resource_type` vs a
      `parameters.engine` discriminator on a shared neutral type.
- [ ] Tombstone/retirement record format when an upstream control is removed.
- [ ] Which sources expose a checksum/signature for integrity verification, and the fallback
      when none is available.
- [ ] Minimum shadow-dwell time and sample size for a loop-generated candidate before it can
      leave shadow, and the accuracy threshold that gates promotion.
- [ ] Cadence of the autonomous discovery loop (event-triggered vs scheduled) and its
      per-cycle candidate/token budget.
- [ ] Which operational signals feed the observe stage in Phase 2 vs Phase 3 (override events
      and HIL patterns are in scope from the moment the override artifact exists; rollback
      correlation may land later).
