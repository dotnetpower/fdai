---
title: Phase 1 - Rule Catalog and T0 Deterministic Engine
---
# Phase 1 - Rule Catalog and T0 Deterministic Engine

**Goal**: stand up the deterministic core (T0) that resolves the majority of events without any
LLM, and deliver the first autonomous vertical - Change Safety - entirely in **shadow mode**
(judge and log, never execute). This phase builds coverage and measurement, not enforcement;
promotion to enforce is out of scope and belongs to
[phase-2-quality-and-t1.md](phase-2-quality-and-t1.md).

This phase implements the T0 tier and rule catalog defined in
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md),
under the safety and coding rules in
[coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md)
and the customer-agnostic scope in
[generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md).
It consumes the telemetry, baseline, and identity/policy unblocking delivered by
[phase-0-instrumentation.md](phase-0-instrumentation.md) and feeds
[phase-2-quality-and-t1.md](phase-2-quality-and-t1.md).

> **Implementation status**: Authored rule, Rego, and remediation seeds; the ActionType catalog;
> T0 engine; OPA evaluator; control-loop orchestration; GitOps draft-PR adapter; Azure inventory
> snapshot/delta primitives; and frozen-scenario replay are implemented. This document's
> "shadow only" language is the phase boundary when P1 first lands, not the current mode of the
> whole runtime. The repository now also contains later-phase promotion, risk/HIL, and
> enforce-capable adapters. Production inventory and GitOps delivery require deployment-specific
> provider and credential bindings.

## Scope

- **In scope**: rule-catalog schema and collectors, the T0 deterministic engine (policy-as-code
  + what-if + drift), shadow-mode remediation-PR generation, and out-of-band change detection
  for Change Safety.
- **Out of scope**: any enforce-mode execution, auto-revert, the T1/T2 tiers, the LLM quality
  gate, and the continuous rule-update pipeline - all deferred to Phase 2.

## Deliverables

- **Rule catalog** (catalog-as-code) with a normalized, CSP-neutral schema and multi-source
  collectors that map each source into that schema. The first authored rules ship under
  [`rule-catalog/catalog/`](../../../rule-catalog/catalog) - one YAML per rule id, each
  exercising exactly one ActionType via the required `remediates` field:
  `object-storage.public-access.deny`, `object-storage.owner-tag.required`,
  `compute.vm-scale-set.over-provisioned`, `secret-store.rotation-overdue`,
  `sql-database.tde-required`. The loader
  [`src/fdai/rule_catalog/schema/rule.py`](../../../src/fdai/rule_catalog/schema/rule.py)
  cross-checks every rule's `remediates` / `alternatives` against the ActionType catalog,
  `resource_type` against the CSP-neutral vocabulary, **and** - when a `policies_root` is
  supplied - every `check_logic.reference` that starts with `policies/` against a Rego file
  that exists on disk at load time (fail-closed).
- **Authored Rego policies** - the five rules above ship with their `check_logic.reference`
  Rego bodies under [`policies/`](../../../policies) (one folder per resource-type family):
  `policies/object_storage/{public_access,owner_tag_required}.rego`,
  `policies/compute/vmss_over_provisioned.rego`,
  `policies/secret_store/rotation_overdue.rego`,
  `policies/sql_database/tde_required.rego`. Every module exports a
  `default deny := false` + `deny if { ... }` entrypoint and reads
  `input.parameters.<name>` with an authored default so per-assignment
  overrides ([rule-governance.md](../rules-and-detection/rule-governance.md)) flow through
  without editing the rule.
- **Canonical `resource_type` vocabulary** - [`rule-catalog/vocabulary/resource-types.yaml`](../../../rule-catalog/vocabulary/resource-types.yaml)
  enumerates the initial CSP-neutral identifier set covering the three verticals; loader +
  JSON Schema in `src/fdai/rule_catalog/schema/`.
- **Initial ActionType catalog** - five shadow-mode `ActionType` instances under
  [`rule-catalog/action-types/`](../../../rule-catalog/action-types): `remediate.disable-public-access`,
  `remediate.tag-add`, `remediate.right-size`, `remediate.rotate-secret`, `remediate.enable-tde`.
  Each declares `default_mode: shadow` + a measurable `promotion_gate`; the loader enforces the
  shadow-first invariant at load-time so an accidental `default_mode: enforce` cannot ship.
- **T0 deterministic engine**: policy-as-code gate (OPA/Rego) + what-if (dry-run) + drift
  detection, emitting a verdict and the citing rule ids for every event.
  [`src/fdai/core/tiers/t0_deterministic/`](../../../src/fdai/core/tiers/t0_deterministic)
  ships a `RuleIndex` keyed on `resource_type` (severity-desc ordered), a `T0Engine`
  orchestrator, and a `PolicyEvaluator` DI seam. Two evaluators land in P1:
  the fail-closed `AbstainEvaluator` (fallback when OPA is not installed) and
  [`OpaRegoEvaluator`](../../../src/fdai/core/tiers/t0_deterministic/opa_evaluator.py)
  - a subprocess-backed adapter that shells out to `opa eval --stdin-input --format json`
  under a bounded timeout, queries `data.fdai.<derived-path>`, and interprets
  `deny` + `deny_reason`. Fail-fast on missing binary; fail-close per rule on timeout,
  non-zero exit, or non-JSON output so one broken policy cannot silence the catalog. CI
  installs a checksum-pinned OPA build ([`.github/workflows/ci.yml`](../../../.github/workflows/ci.yml)).
- **Shadow remediation-PR** path via the GitOps delivery adapter (generated but not merged).
  Five Terraform patch templates ship under
  [`rule-catalog/remediation/`](../../../rule-catalog/remediation), one per shipped
  rule; the loader cross-checks that every `remediation.template_ref` exists on disk
  at load time (fail-closed, symmetric to the `check_logic.reference` gate). The
  executor
  ([`src/fdai/core/executor/`](../../../src/fdai/core/executor))
  enforces every safety invariant on the way out:
  per-resource serialization via `ResourceLockManager`, in-process dedup by
  `Action.idempotency_key`, blast-radius caps (`ExecutorConfig.max_affected_resources` /
  `max_rate_per_minute`), shadow-only mode invariant (an `enforce`-mode Action is
  rejected without any mutation), and an append-only audit entry on every terminal
  path - `PUBLISHED` / `ALREADY_EXISTED` / `ABSTAINED_BLAST_RADIUS` /
  `ABSTAINED_RENDER_ERROR` / `REJECTED_MODE` / `REJECTED_INVARIANT`. The delivery
  layer ships
  [`GitOpsPrAdapter`](../../../src/fdai/delivery/gitops_pr/adapter.py), a
  GitHub REST implementation of the CSP-neutral
  [`RemediationPrPublisher`](../../../src/fdai/shared/providers/remediation_pr.py)
  Protocol - Bearer-authed, probes for an existing open PR before writing,
  creates a shadow branch + commits the patch via the Contents API, opens the PR as
  a **draft** with the `shadow` label + `rule:<id>` + `action:<type>`. It never merges
  and never removes the `shadow` label; those paths are Phase 2 promotion territory.
- **Pipeline orchestrator** -
  [`ControlLoop`](../../../src/fdai/core/control_loop/orchestrator.py) wires the P1 stages
  end-to-end: [`EventIngest`](../../../src/fdai/core/event_ingest/__init__.py)
  (normalize + dedup by `idempotency_key`) →
  [`TrustRouter`](../../../src/fdai/core/trust_router/__init__.py) (route to T0
  when a rule matches the event's `resource_type`, otherwise abstain) → `T0Engine` →
  [`ActionBuilder`](../../../src/fdai/core/executor/action_builder.py) (Finding
  → `Action` with the safety invariants derived from the ActionType) → `ShadowExecutor`.
  Every terminal outcome (`DEDUPED` / `ABSTAINED_ROUTING` / `ABSTAINED_T0` / `EXECUTED`
  / `ABSTAINED_ACTION_BUILD`) writes an append-only audit record; the shipped rules +
  Rego + IaC templates fire end-to-end in
  [`tests/pipeline/test_control_loop_e2e.py`](../../../tests/pipeline/test_control_loop_e2e.py)
  under real OPA (skipped gracefully when `opa` is absent).
- **Out-of-band change detection** for console/manual changes, with an explicit
  false-positive-suppression strategy.
- **Inventory adapter (Azure)** - the Azure implementation of the
  [inventory contract](../architecture/csp-neutrality.md#5-inventory-contract--resource-graph): an initial
  **parallelized full-scan** against Azure Resource Graph (sharded by `resource_type` with
  bounded concurrency) plus an **Activity-Log-driven delta** consumed off the event bus.
  Populates `ontology_resource` + `ontology_link` (`contains`, `attached_to`, `depends_on`) so
  T0 can cite CSP-neutral resource ids and the risk-gate can compute a real blast radius over
  the graph. The Protocol scaffold ships in
  [`src/fdai/shared/providers/inventory.py`](../../../src/fdai/shared/providers/inventory.py);
  the Azure adapter in
  [`src/fdai/delivery/azure/inventory.py`](../../../src/fdai/delivery/azure/inventory.py)
  provides the bounded-concurrency parallel-shard structure, the `final=True`
  atomic-promote fence, and the idempotent-upsert dedup pre-condition; the real
  Kusto-over-ARG REST wiring lives beside it in
  [`src/fdai/delivery/azure/arg_query.py`](../../../src/fdai/delivery/azure/arg_query.py)
  as an `AzureArgQueryFactory` that resolves the CSP-neutral `resource_type` to
  its `azure_arm_type` from the vocabulary, calls
  `POST /providers/Microsoft.ResourceGraph/resources` under an OIDC token from
  the injected `WorkloadIdentity`, follows `$skipToken` pagination under a
  bounded page cap, and truncates untrusted vendor properties before returning
  CSP-neutral records. The scheduled collector uses a separate read-only
  identity, falls back to direct paged ARM lists, stages immutable candidates in
  PostgreSQL, and swaps the active pointer only after the final fence and whole-graph
  validation. `contains` / `attached_to` / `depends_on` extraction is live; the
  production read API serves only the active last-known-good generation.
- **Fixtures and a regression suite** covering the initial rule set and the detection paths.
- **Frozen scenario replay harness** -
  [`tests/scenarios/test_v2026_07_replay.py`](../../../tests/scenarios/test_v2026_07_replay.py)
  parametrizes every scenario under
  [`tests/scenarios/v2026.07/`](../../../tests/scenarios/v2026.07) through
  the real `ControlLoop.process(...)` using the shipped catalog + Rego +
  IaC templates. Each frozen scenario is either paired with a
  concrete-payload overlay under
  [`tests/scenarios/enrichment/v2026.07/`](../../../tests/scenarios/enrichment/v2026.07)
  (P1-replayable) or marked `xfail` with an in-code reason (T1/T2 or
  risk-gate not wired yet). A guard test ensures no scenario is silently
  skipped without an explicit reason.

## Rule Catalog

### Normalized Schema

Every rule normalizes to a common, CSP-neutral schema so sources can be merged, deduplicated,
and versioned. Required fields:

| Field | Type | Meaning |
|-------|------|---------|
| `id` | stable string | globally unique, source-independent rule identity (basis for dedup) |
| `version` | semver | changes are traceable and reversible; a rule set pins rule versions |
| `source` | enum | originating catalog (see Sources) with a fixed source-priority rank |
| `severity` | enum | `critical` > `high` > `medium` > `low` (drives precedence) |
| `category` | enum | domain grouping (e.g. `security`, `reliability`, `cost`, `config-drift`) |
| `resource-type` | CSP-neutral string | normalized target type, not a vendor-specific ARM path |
| `check-logic` | ref/expr | deterministic predicate (OPA/Rego module ref or expression) |
| `remediation` | ref | remediation template producing an IaC/PR diff |
| `remediates` | ActionType id (M:1) | ontology dispatch: the `ActionType` this rule proposes on match. Cross-checked at load against [`rule-catalog/action-types/`](../../../rule-catalog/action-types); optional `alternatives[]` ranks alternates that only the T2 quality gate may swap in |
| `provenance` | object | source URL/commit, imported-at timestamp, mapping author |

`provenance` is mandatory for auditability and rollback; `version` is mandatory so a bad rule
set can be reverted (see Versioning). Fields carry no customer-identifying values; examples use
placeholders only per
[generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md).

### Sources

Azure WAF / AKS Baseline / MCSB / Azure Policy / Advisor, CIS Benchmarks, OPA/Gatekeeper
libraries, IaC scanners (Checkov, tfsec, KICS, Trivy), kube-bench, and static analyzers. Each
source has a collector that maps its native format into the normalized schema and records
`provenance`. `resource-type` is normalized to a CSP-neutral vocabulary so a rule authored for
one provider can be evaluated against an equivalent resource on another; vendor specifics stay
behind the provider adapter, not in the rule.

Where each source lives, how it is fetched, its license constraints, and the YAML shapes are
detailed in [rule-catalog-collection.md](../rules-and-detection/rule-catalog-collection.md).

### Deduplication, Conflict, and Precedence

Multiple sources routinely emit overlapping rules for one event. Resolution is deterministic:

1. **Deduplicate** by `id`; identical logic from multiple sources collapses to one rule with
   merged `provenance`.
2. **Precedence** when distinct rules match the same event: order by `severity`, then by
   `source` priority rank; break remaining ties by the higher `version`.
3. **Unresolved ties or contradictory remediations** (one rule would revert what another
   applies) **abstain and escalate to HIL** rather than auto-selecting - fail toward safety.

Conflict outcomes are logged with the competing rule ids so precedence decisions are auditable.

### Versioning

The catalog is stored as **catalog-as-code**; each promotion pins a rule-set version, and a bad
set is revertible by version. (The *continuous* collect → shadow-eval → regression → promote
pipeline is Phase 2; Phase 1 loads a versioned, manually reviewed catalog.)

## T0 Engine

The engine evaluates each normalized, deduplicated event (post `event-ingest`) and produces a
verdict plus the citing rule ids. Three deterministic checks:

- **Policy evaluation** - run `check-logic` (OPA/Rego) and checklists against the event; a match
  yields a violation with its rule id(s).
- **What-if (dry-run)** - simulate the candidate remediation's predicted effect *without
  applying it*, to confirm it resolves the violation and to compute the blast radius (scope,
  count, and rate of affected resources).
- **Drift detection** - compare observed resource state against the declared IaC/desired state;
  report the drift delta (added/removed/changed attributes).

On violation the engine emits a **remediation PR** (see below) rather than executing directly;
audit, rollback, and approval come free from git. In Phase 1 every verdict is **shadow only** -
no PR is merged and no state is mutated.

## Remediation PR (shadow mode)

Even though nothing merges in Phase 1, each generated PR MUST already carry the four safety
invariants from
[coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md),
so the artifact is enforce-ready when Phase 2 promotes it:

- **Idempotency** - keyed to the event's stable idempotency key; regenerating for the same event
  produces the same diff and never a duplicate change.
- **Rollback path** - the PR references the prior desired-state revision so the change is
  revertible by a single follow-up PR.
- **Blast-radius limit** - the what-if-computed scope/count/rate is recorded in the PR and
  capped; a change exceeding the cap is marked HIL-only.
- **Audit entry** - every generated PR (including no-op and abstain outcomes) writes an
  append-only audit record: event id, tier (`T0`), decision, citing rule ids, idempotency key,
  mode (`shadow`), and rollback reference.

PRs are labeled `shadow` and opened as draft (or against a shadow branch) so they are reviewable
but cannot be merged by the normal flow.

## Out-of-Band Detection (Change Safety)

- **Signals**: Activity Log, Resource Graph, Change Analysis, Deployment Stacks deny-assignment
  events, and IaC drift. Correlate across signals rather than trusting a single feed.
- **Attribution**: classify each detected change as authorized (originating from a merged
  remediation PR / known pipeline principal) or out-of-band (manual/console), using the actor
  identity and correlation id so pipeline-driven changes are not misflagged.
- **False-positive control**: suppress eventually-consistent and reconciliation noise
  (propagation lag, provider-side auto-heal, tag/system-metadata churn) via a debounce/settling
  window before a change is declared out-of-band; record the suppression reason.
- **False negatives**: signal feeds can lag or drop; detection completeness is a measured guard
  (see Exit Criteria), not assumed.
- **Response (shadow)**: an out-of-band change on a policy-violating resource generates a
  *shadow* revert-or-reconcile PR and an alert; it is **judged and logged only**. Auto-revert
  and reconcile-to-IaC execution are gated off until Phase 2 validation.

## Autonomy Level

- Everything ships in **shadow mode**: the engine judges and logs; there is no enforce path.
- Low-risk auto-merge/reconcile and high-risk HIL routing are wired through the `risk-gate` but
  gated off until Phase 2 promotion.
- A property-level invariant holds for this phase: **shadow mode never mutates state** - no PR
  is merged and no resource is changed, and this is asserted in tests.

## Testability

- **Fixtures** follow the normalized rule schema and the `event-ingest` event schema; they are
  free of secrets and customer values. Stable keys, identifiers, and paths remain ASCII/English;
  natural-language values may be English or Korean. Include multi-source overlap fixtures that
  exercise dedup and precedence, and contradictory-remediation fixtures that must escalate.
- **Regression suite** covers: policy verdicts, what-if blast-radius computation, drift deltas,
  conflict/precedence resolution, out-of-band attribution, and false-positive suppression.
- **Safety-core coverage**: the deterministic engine and `risk-gate` paths meet the high
  coverage bar required by coding-conventions.
- **Property tests**: "shadow never mutates", "remediation is idempotent (re-apply is a no-op)",
  and "unresolved rule conflict never auto-selects".

## Exit Criteria

Each criterion is measurable against the Phase 0 telemetry and scenario set, not narrative:

- The Change gate runs in **shadow** against the frozen Phase 0 scenario set with every decision
  logged (event id, tier, verdict, citing rule ids, mode).
- The rule catalog covers a defined initial target set (enumerated per source) and is
  version-pinned; dedup/precedence resolves the fixture conflict cases with zero unresolved
  auto-selections.
- Remediation PRs are generated, carry all four safety invariants, and are reviewable; no PR is
  mergeable in shadow.
- Out-of-band detection reports **precision and recall against a labeled fixture set**, with the
  false-positive suppression rate recorded - establishing the detection baseline Phase 2 must
  not regress.
- Every terminal path (violation, no-op, abstain, HIL-route) writes an audit entry; audit
  completeness is asserted.
- The **inventory graph is populated** before any T0 verdict fires: the parallel full-scan
  completes atomically (fail-closed on partial failure), links land under the CSP-neutral
  vocabulary, and re-running the scan is a no-op idempotent upsert. Between scans, Azure resource
  changes enter through Huginn and an ordered durable overlay applies resource, link, and tombstone
  deltas. Graph-dependent actions read snapshot plus overlay freshness at the RiskGate and route
  to HIL when freshness or coverage is unknown, degraded, or stale.

## Dependencies

- **Phase 0** ([phase-0-instrumentation.md](phase-0-instrumentation.md)): telemetry backbone
  (event schema, audit/state/KPI store), the frozen scenario set and reference baseline, and the
  resolved identity/authorization and policy-exemption blockers
  ([security-and-identity.md](../architecture/security-and-identity.md)). T0 shadow decisions are logged
  through the Phase 0 audit store; without it, exit criteria are unmeasurable.
