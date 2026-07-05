# Phase 1 — Rule Catalog and T0 Deterministic Engine

**Goal**: stand up the deterministic core (T0) that resolves the majority of events without any
LLM, and deliver the first autonomous vertical — Change Safety — entirely in **shadow mode**
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

## Scope

- **In scope**: rule-catalog schema and collectors, the T0 deterministic engine (policy-as-code
  + what-if + drift), shadow-mode remediation-PR generation, and out-of-band change detection
  for Change Safety.
- **Out of scope**: any enforce-mode execution, auto-revert, the T1/T2 tiers, the LLM quality
  gate, and the continuous rule-update pipeline — all deferred to Phase 2.

## Deliverables

- **Rule catalog** (catalog-as-code) with a normalized, CSP-neutral schema and multi-source
  collectors that map each source into that schema.
- **T0 deterministic engine**: policy-as-code gate (OPA/Rego) + what-if (dry-run) + drift
  detection, emitting a verdict and the citing rule ids for every event.
- **Shadow remediation-PR** path via the GitOps delivery adapter (generated but not merged).
- **Out-of-band change detection** for console/manual changes, with an explicit
  false-positive-suppression strategy.
- **Fixtures and a regression suite** covering the initial rule set and the detection paths.

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
detailed in [rule-catalog-collection.md](../rule-catalog-collection.md).

### Deduplication, Conflict, and Precedence

Multiple sources routinely emit overlapping rules for one event. Resolution is deterministic:

1. **Deduplicate** by `id`; identical logic from multiple sources collapses to one rule with
   merged `provenance`.
2. **Precedence** when distinct rules match the same event: order by `severity`, then by
   `source` priority rank; break remaining ties by the higher `version`.
3. **Unresolved ties or contradictory remediations** (one rule would revert what another
   applies) **abstain and escalate to HIL** rather than auto-selecting — fail toward safety.

Conflict outcomes are logged with the competing rule ids so precedence decisions are auditable.

### Versioning

The catalog is stored as **catalog-as-code**; each promotion pins a rule-set version, and a bad
set is revertible by version. (The *continuous* collect → shadow-eval → regression → promote
pipeline is Phase 2; Phase 1 loads a versioned, manually reviewed catalog.)

## T0 Engine

The engine evaluates each normalized, deduplicated event (post `event-ingest`) and produces a
verdict plus the citing rule ids. Three deterministic checks:

- **Policy evaluation** — run `check-logic` (OPA/Rego) and checklists against the event; a match
  yields a violation with its rule id(s).
- **What-if (dry-run)** — simulate the candidate remediation's predicted effect *without
  applying it*, to confirm it resolves the violation and to compute the blast radius (scope,
  count, and rate of affected resources).
- **Drift detection** — compare observed resource state against the declared IaC/desired state;
  report the drift delta (added/removed/changed attributes).

On violation the engine emits a **remediation PR** (see below) rather than executing directly;
audit, rollback, and approval come free from git. In Phase 1 every verdict is **shadow only** —
no PR is merged and no state is mutated.

## Remediation PR (shadow mode)

Even though nothing merges in Phase 1, each generated PR MUST already carry the four safety
invariants from
[coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md),
so the artifact is enforce-ready when Phase 2 promotes it:

- **Idempotency** — keyed to the event's stable idempotency key; regenerating for the same event
  produces the same diff and never a duplicate change.
- **Rollback path** — the PR references the prior desired-state revision so the change is
  revertible by a single follow-up PR.
- **Blast-radius limit** — the what-if-computed scope/count/rate is recorded in the PR and
  capped; a change exceeding the cap is marked HIL-only.
- **Audit entry** — every generated PR (including no-op and abstain outcomes) writes an
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
- A property-level invariant holds for this phase: **shadow mode never mutates state** — no PR
  is merged and no resource is changed, and this is asserted in tests.

## Testability

- **Fixtures** follow the normalized rule schema and the `event-ingest` event schema; they are
  English and secret-free per repo scope rules. Include multi-source overlap fixtures that
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
  false-positive suppression rate recorded — establishing the detection baseline Phase 2 must
  not regress.
- Every terminal path (violation, no-op, abstain, HIL-route) writes an audit entry; audit
  completeness is asserted.

## Dependencies

- **Phase 0** ([phase-0-instrumentation.md](phase-0-instrumentation.md)): telemetry backbone
  (event schema, audit/state/KPI store), the frozen scenario set and reference baseline, and the
  resolved identity/authorization and policy-exemption blockers
  ([security-and-identity.md](../security-and-identity.md)). T0 shadow decisions are logged
  through the Phase 0 audit store; without it, exit criteria are unmeasurable.
