---
title: WAF and CAF Evidence-Governed Assessment
---
# WAF and CAF Evidence-Governed Assessment

This design turns the pinned Azure Well-Architected Framework (WAF) and Microsoft Cloud Adoption
Framework (CAF) catalogs into scope-bound, replayable shadow assessments. It keeps advisory
guidance, observed evidence, human approval, and operational authority separate.

> **Scope:** This design owns WAF workload assessment and CAF estate assessment. The existing WARA
> runtime remains an independent, validated assessment because its APRL query and resource-type
> contracts are more specialized.
>
> **Initial mode:** Every assessment is read-only shadow work. An assessment result cannot authorize
> risk, approval, promotion, remediation, deployment, or execution.

## Design at a glance

The shared assessment boundary has six deterministic stages:

1. Load one pinned framework and its reviewed, content-addressed evidence specification catalog.
2. Admit one deployment-supplied profile that explicitly covers every framework control.
3. Bind the exact workload or estate scope, source generation, evaluation time, and evidence cutoff.
4. Evaluate each requirement independently and keep missing or invalid evidence unknown.
5. persist an immutable result and publish a no-authority event for the Operator projection.
6. Retain source changes as review-only proposals until mappings and evidence specifications pass
   independent review.

The protected shadow-assessment workflow runs cleanup only after protected-source verification
succeeds. A failed verifier cannot execute repository cleanup code with the job's identity.

The runtime shares evidence admission, replay, publication, and projection mechanics. WAF and CAF
retain different catalogs, scope contracts, provider adapters, and user-facing explanations.
The shared Operator PostgreSQL reader also serves unrelated operational families. Its scoped AKS
source-state and content-addressed diagnostic-receipt reads do not enter WAF or CAF scope,
evidence admission, replay, or results. Its generation-fenced runtime-call relationship decoder is
likewise outside both assessment families and cannot contribute assessment evidence. Its shared
source-state decoder admits only canonical machine-token reasons and cannot pass principal text or
provider details into any Operator family.
The shared Operator outbox lifecycle facade can also supervise the Incident intervention worker.
Its explicitly allowlisted logical topic, requests, and readiness state do not enter WAF or CAF
scope, evidence admission, replay, or results.

## Design decision and critique

### Rejected: copy the WARA runtime

Copying WARA for WAF and again for CAF would duplicate freshness, scope, conflict, replay, audit,
and projection rules. The three implementations would drift, and a safety fix could close one
framework while leaving another open.

The revised design adds one `framework-assessment` boundary for WAF and CAF. WARA remains unchanged
because an APRL GUID, admitted Azure Resource Graph query, exact resource type, and matching-row
semantics are not general framework concepts.

### Rejected: calculate status in the browser

The Console does not combine evidence or derive conformance. It renders one server-owned immutable
projection. This prevents stale tabs, partial pages, or display filters from becoming decision
logic.

### Rejected: report a framework compliance score

WAF and CAF are advisory guidance. Aggregate counts describe evidence coverage and evaluated state,
not certification or regulatory compliance. External scores remain supporting observations.

## Assessment catalog

Each catalog pins the framework version, source revision set, definition digest, evidence
specification digest, reviewer, and review state. Every framework control appears exactly once.

### WAF catalog

The WAF catalog derives 59 control specifications from the existing 59 `BestPractice` records.
Every typed requirement retains its exact reference and gains:

- an authoritative producer or explicit blocked dependency;
- an exact workload scope contract and inventory-generation requirement;
- a finite freshness ceiling and completeness contract;
- an accountable owner slot and approval role;
- a failure behavior of `unknown`; and
- a time-bounded, separately approved not-applicable contract.

Rule evidence can satisfy a requirement only when current inventory positively covers the exact
workload scope. A clean rule result with provider errors, unsupported resource types, incomplete
inventory, truncation, conflicts, or a stale generation remains unknown.

### CAF catalog

The CAF catalog contains the seven methodologies and eight landing-zone design areas. Each record
defines its estate scope, owner, cadence, evidence requirements, and crosswalk relationships.

Strategy, Plan, and Adopt each require both procedure evidence and execution evidence. Azure
configuration can support these controls, but it cannot satisfy them without governed human-process
evidence. Ready, Govern, Secure, and Manage combine exact estate observations with process evidence.

The crosswalk records exact references to Rule, WAF, MCSB, `ControlObjective`, Azure Policy,
provider observation, or manual evidence. Each relationship is `full`, `partial`,
`supporting_only`, or `unmapped`; similar wording never establishes equivalence.

## Deployment-supplied profile

A profile covers the catalog's complete control-id set. Every control is explicitly `applicable` or
`not_applicable`.

An applicable entry names its evidence owner and review cadence. A not-applicable entry also
requires a typed justification, approval identity, distinct requester identity, approval time, and
expiry. Missing evidence cannot manufacture a not-applicable decision.

WAF profiles bind a workload and current inventory generation. CAF profiles bind an estate scope,
the management hierarchy generation, operating model, environment classes, regulatory context, and
evidence owners. Deployment identities and values remain outside the upstream repository.

## Evidence admission

One immutable evidence receipt includes:

- framework, control, requirement, evidence kind, and producer identity;
- exact scope digest plus inventory or hierarchy generation;
- event time, recorded time, freshness ceiling, and evidence digest;
- completeness, conflict, truncation, synthetic, and provider-error state;
- decisive or supporting-only role; and
- procedure or execution phase when a CAF process control requires it.

A decisive receipt is admissible only when all identities and generations match the request, its
timestamps are timezone-aware and within the independent cutoff, and every safety state is valid.
Multiple admissible receipts that disagree produce an explicit conflict and unknown satisfaction.

Supporting-only evidence can add context and limitations but cannot establish satisfaction by
itself. This rule applies to Microsoft Well-Architected Review reports, Azure Advisor, Defender for
Cloud Secure Score, and framework crosswalk neighbors.

## Tradeoffs and satisfaction

A WAF pillar tradeoff is an immutable, scope-bound, approved record. It names the affected controls,
decision owner, rationale digest, approval time, and expiry. The record is visible in the result,
but it never rewrites, suppresses, or downgrades another control's evidence state.

The runtime keeps five axes separate:

- reference presence;
- semantic mapping;
- applicability;
- evaluation;
- satisfaction.

Only complete decisive evidence can produce `satisfied` or `failed`. Missing, stale, inaccessible,
truncated, conflicting, synthetic, expired, or wrong-scope evidence produces `not_evaluated` and
`unknown`. Approved non-applicability produces `not_applicable` without implying satisfaction.

## Immutable snapshot and replay

Each snapshot binds the framework revision, definition and catalog digests, profile id and digest,
ontology release, scope digest, inventory or hierarchy generation, evidence digests, evaluation and
recorded times, approvals, tradeoffs, per-control results, limitations, and
`execution_authority: false`.

The snapshot digest excludes no decision-bearing field. Replay recomputes the complete snapshot and
rejects a digest mismatch. A later evaluation creates a new snapshot instead of updating history.

## Provider and event boundaries

Provider-neutral protocols return typed read-only observations. Azure adapters validate source
identity, exact scope, time, completeness, and pagination before creating a receipt. Provider
success proves collection only; the deterministic runtime still decides admissibility.

The assessment service appends an audit record before publishing a schema-versioned shadow event.
Operator consumers quarantine malformed, partial, wrong-framework, or authority-bearing events.
No assessment module imports an agent, risk gate, approval path, or executor.

The protected live-validation workflow deliberately uses an audit-only recorder because the deploy
runner has no assessment-topic sender role. It records `publication_status:
not_requested_validation_only` and retains a sanitized artifact instead of pretending that an
Operator projection was published.

## Operator surface

The Operator API exposes the latest immutable projection and preserves catalog data when no
assessment exists. The Console shows:

- framework reference and exact source revision;
- selected scope and evaluation time;
- mapping, applicability, evaluation, and satisfaction as separate fields;
- evidence references, digests, freshness, completeness, conflicts, and limitations;
- owner, cadence, approved exception, and WAF tradeoff records; and
- unavailable and unknown states without a compliance label.

WAF remains in the existing Controls view. CAF adds a sibling tab that uses the same quiet,
read-only interaction pattern. The browser never writes evidence or approval.

## Source-change governance

The source watcher creates a deterministic review package containing additions, removals, semantic
changes, affected mappings, and stale evidence specifications. A proposed generation remains
pending until the exact package digest is approved. Validation failure preserves the prior valid
generation and records the failed revision and reason.

## Validation and live evidence

Focused tests cover catalog completeness, profile coverage, evidence admission, process evidence,
rule-derived absence claims, external supporting evidence, tradeoffs, replay, ontology authority,
Operator decoding, localization, and projection quarantine.
Realtime inventory changes invalidate a WAF run only when they target a resource linked to the
selected workload. Unrelated subscription changes do not erase an otherwise stable workload
snapshot; a newer failed or abandoned full reconciliation still blocks assessment.

Local fixtures prove mechanics only. A validated WAF or CAF state additionally requires one
governed live-Azure shadow receipt from an exact pushed required-CI-green revision. The retained
receipt contains sanitized digests and counts, is independently reviewed, and grants no execution
authority. The validation workflow selects exactly one topology-bound Workload from the current
PostgreSQL ontology, then reads its current inventory generation and the Azure management hierarchy
from the private runner. Zero or multiple candidates fail before provider observation. The workflow
never runs Terraform apply.

## Related docs

| To learn about | Read |
|----------------|------|
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/rules-and-detection/framework-assessment.md) |
| Specialized WARA assessment | [WARA Evidence-Governed Assessment](wara-assessment.md) |
| Framework source collection | [Rule Catalog Collection](rule-catalog-collection.md) |
| Rule assignment and evidence governance | [Rule Governance](rule-governance.md) |
| Ontology authority boundary | [FDAI Operating Ontology](../architecture/operating-ontology.md) |
| Read-only operator behavior | [FDAI Console Conversations](../interfaces/operator-console.md) |
