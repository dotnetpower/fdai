---
title: WARA Evidence-Governed Assessment
---
# WARA Evidence-Governed Assessment

This design turns the pinned Azure Well-Architected Reliability Assessment (WARA) and Azure
Proactive Resiliency Library (APRL) inventory into a scope-aware, read-only assessment. It keeps
guidance, evidence, and authority separate: a recommendation can produce a shadow finding, but it
cannot grant approval, policy, risk, promotion, mutation, or execution authority.

> **Scope:** This design consumes the existing pinned `azure-wara` framework catalog. It does not
> recreate the CAF, WAF, or WARA source catalogs.
>
> **Initial mode:** Assessment is shadow-only. A live Azure observation requires a separately
> authorized provider binding and a governed runtime receipt.

## Design at a glance

The assessment has five deterministic stages:

1. Load the pinned WARA framework and a content-addressed crosswalk.
2. Resolve an exact workload and resource scope against reviewed resource-type mappings.
3. Admit only bounded evidence whose source, freshness, completeness, conflict, truncation, and
   synthetic state are explicit.
4. Produce one replayable result per active recommendation and aggregate counts without a
   compliance score.
5. Materialize a read-only Operator projection and an audit event. No remediation is dispatched.

Disabled APRL recommendations remain searchable catalog history and never enter the evaluated set.

## Crosswalk and applicability

The machine-readable crosswalk is keyed by APRL GUID and accounts for every active recommendation
exactly once. Its accounting gate pins the source inventory: 393 active GUIDs across exactly 80
case-normalized resource types, 63 disabled GUIDs excluded from evaluation, and an independent
143 automated plus 250 non-automated split. Any count, overlap, omission, or source-digest drift
fails closed.

Each record keeps `automation_available` independent from its reviewed disposition:

| Disposition | Meaning |
|-------------|---------|
| `existing_rule` | An exact active FDAI Rule evaluates the same semantics. |
| `new_rule_candidate` | Deterministic evaluation is possible, but normal Rule governance is still required. |
| `manual_evidence` | A document, metric, drill, approval record, or expert assessment is required. |
| `conditional_not_applicable` | Typed current scope facts can exclude the recommendation, with a separate justification and approver. |
| `ambiguous_or_blocked` | Meaning, identity, query safety, or evidence requirements are insufficient. |

Similarity in titles never proves equivalence. WAF umbrella controls relate to APRL recommendations
through explicit relationship records and do not replace, merge, or double-count APRL GUIDs.

All case-normalized APRL resource types have one reviewed result. An exact match to the canonical
provider mapping selects the provider-neutral resource type. Every other type remains
`unsupported` or `ambiguous`; it is never broadened to all resources. Subscription-scoped WAF and
specialized-workload recommendations additionally require matching workload tags. Parent and child
provider identities remain distinct, and a child-resource recommendation can match only the exact
child scope.

## Query admission

External Azure Resource Graph query bodies are stored separately from framework metadata and bound
by SHA-256 digest. Static review rejects mutation or control commands, dynamic endpoints,
undeclared tables, unsupported joins, and missing result bounds. Accepted syntax produces only a
provider-neutral read plan containing:

- the APRL GUID and query digest;
- the exact workload and resource scope;
- declared provider resource types and inventory generation;
- a timeout and maximum row count;
- required completeness, truncation, time, and provenance fields.

Static safety does not prove product semantics. Until an exact evaluator is reviewed, the
recommendation remains blocked even when its query is read-only. Query success is an observation
receipt, not a satisfaction result or operational success.

Every one of the 143 records with `automation_available: true` carries the pinned query body
reference and digest, static safety classification, and either an exact evaluator binding or a
blocked reason regardless of its crosswalk disposition.

## Manual evidence contracts

Every non-automated recommendation has either a typed requirement or an explicit blocked reason.
A requirement records:

- evidence kind and authoritative producer slot;
- workload and resource scope contract;
- freshness ceiling;
- content digest and observation time;
- completeness, conflict, truncation, and synthetic state;
- failure behavior and accountable owner slot.

Missing or invalid evidence produces `unknown`. A placeholder, inaccessible artifact, stale metric,
or unassigned owner never produces a satisfied result.

Every one of the 250 records with `automation_available: false` carries a typed manual evidence
requirement or an explicit blocked reason regardless of its crosswalk disposition.

The initial Operator catalog projection preserves that requirement as structured read-only data.
The Console detail view shows the evidence kind, authoritative producer, exact scope contract,
freshness ceiling, accountable owner slot, and blocked reason. It does not provide a receipt-writing
control. Until a separately authorized producer supplies admissible evidence, the recommendation
remains `not_evaluated` with `manual_evidence_required`.

## Shadow assessment contract

An assessment request pins the framework revision, crosswalk digest, ontology release, inventory
generation, exact workload id, resource ids, evaluation time, and evidence receipts. The runtime
rejects an empty or duplicate scope and a pin mismatch.

Each per-recommendation result keeps these states independent:

- catalog state: `active` or `disabled`;
- mapping state: `full`, `partial`, or `unmapped`;
- applicability: `applicable`, `not_applicable`, or `unknown`;
- evaluation: `evaluated`, `not_evaluated`, or `blocked`;
- satisfaction: `satisfied`, `failed`, or `unknown`.

Only complete, current, non-conflicting, non-truncated, non-synthetic evidence for the exact scope
can produce `satisfied` or `failed`. A provider or observation failure produces `not_evaluated` and
`unknown`. `not_applicable` additionally requires a reviewed conditional disposition and a separate
approval receipt. All other cases remain `unknown` or `blocked`.

The result includes source and implementation digests, evaluated GUIDs, evidence references,
event and recorded times, aggregate counts, limitations, and `execution_authority: false`.
Deterministic replay recomputes the result digest from the same request and evidence set.

## Ontology and authority boundary

Reviewed mappings can project `FrameworkControl -> ControlObjective` links with explicit full,
partial, or unmapped state. Assessment results are projection-owned observations, not framework
definition edits.

Framework, FrameworkControl, and WARA assessment objects cannot connect to `AccessGrant`,
`AuthorizationRequirement`, approval, risk, promotion, `ActionType`, or execution paths. A catalog
mapping, product-group verification flag, recommendation impact, or query receipt cannot cross
that negative invariant.

## Operator surface

The Operator API exposes a read-only WARA inventory and optional evaluated results. The Console
supports filters for resource type, recommendation control, impact, lifecycle, product-group
verification, automation, mapping, applicability, evaluation, and satisfaction.

Every row shows scope, evaluation time, source revision, evidence completeness, and limitations.
Catalog presence and `product_group_verified` are metadata, never a satisfied badge. Optional
projection absence renders as unavailable; malformed or unexpected responses remain visible errors.
Truncated identifiers use the shared Tooltip for the full value instead of native title attributes.
The initial catalog projection also exposes the exact pinned APRL source URL, source path, version,
revision, digest, retrieval time, license, optional Microsoft Learn link, query digest, exact
evaluator reference, and structured manual-evidence requirement. The Console renders 50 controls
per page while preserving all 456 lifecycle records through explicit previous and next navigation;
it never hides the remaining catalog behind a client-only row limit.

## Review-only source updates

The updater accepts an exact APRL commit and published WARA object, then validates schema, GUID
uniqueness, active-set equality, source digests, source-set digest, license, and inventory counts.
It emits a deterministic semantic diff for additions, updates, disables, and reactivations.

The output is an inert review package. It cannot change active mappings, evaluator admission, or
assessment authority. Collection or validation failure preserves the last valid generation and
records an explicit failure.

## Exact evaluator overlay and Azure observation

The generated source crosswalk stays immutable. A separate content-addressed evaluator overlay
binds a reviewed APRL GUID and exact query digest to one deterministic evaluator. The loader rejects
source, crosswalk, query, safety, resource-type, or blocker drift before the binding can remove
`missing_exact_evaluator`.

The first overlay binds three read-only queries whose reviewed semantics are "matching rows are
failures." The Azure Resource Graph adapter adds the exact resource-id allowlist and row bound to
the pinned query, accepts only approved Azure management hosts and audiences, rejects out-of-scope
or truncated rows, and records a deterministic evidence digest. Zero matching rows mean satisfied;
one or more matching rows mean failed. Both remain shadow observations without execution authority.

## Validation and release boundary

Focused checks cover schema, importer parity, crosswalk accounting, evaluator-overlay identity,
query safety, exact scope and endpoint enforcement, manual evidence, runtime failure cases, replay,
ontology invariants, Operator API decoding, Console localization, and deterministic update diffs.
Full-catalog validation proves the pinned inputs and derived artifacts agree.

Local and synthetic checks can establish `implemented`. `validated` requires a governed live-Azure
shadow receipt for a representative multi-resource workload. That separate operation needs explicit
authorization, provider identity, exact scope, network access, and audit retention.
Local and deployed profiles use the same pinned crosswalk, bounded read plan, shadow topic, Operator
consumer group, and PostgreSQL projection; neither profile substitutes provider evidence.

## Related docs

| To learn about | Read |
|----------------|------|
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/rules-and-detection/wara-assessment.md) |
| Pinned source collection | [Rule Catalog Collection](rule-catalog-collection.md) |
| Framework ontology projection | [FDAI Operating Ontology](../architecture/operating-ontology.md) |
| Read-only operator behavior | [FDAI Console Conversations](../interfaces/operator-console.md) |
