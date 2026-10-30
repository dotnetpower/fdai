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

The shared workflow family that serves WARA projections now also commits principal-owned private Workflow drafts and bindings through a separate authoring store. That write path grants no WARA read, execution, or promotion authority.
Semantic result-handle persistence reuses shared Operator semantic storage only for opaque
conversation references. It does not change WARA scope, APRL measurement, assessment admission, or
authority.

Readable titles in the shared rule catalog list come from the matching rule detail. They are
presentation metadata and do not change WARA scope, APRL measurements, or assessment results.

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
The shared Operator PostgreSQL reader can decode bounded scoped source states for other read
families. WARA does not consume AKS fleet states, and this shared capability does not change WARA
scope, evidence admission, or assessment results. The same boundary applies to the reader's
content-addressed AKS diagnostic receipt lookup and generation-fenced runtime-call relationship
decoder; WARA never joins or interprets either evidence family.
The shared source-state decoder also accepts only canonical machine-token reasons, so principal
text and provider details cannot enter WARA through that storage path.
Immutable records, row projections, and these evidence decoders are separate internal modules; the
split changes no WARA scope, query, projection, evidence, replay, or authority contract.
Assignment request/result topics share the Operator transport but not WARA's evidence or state.
An accepted human review, ownership PR, or handover goal observation is not an APRL measurement
and cannot change recommendation applicability, assessment admission, or operational authority. Post-turn review envelopes are also excluded from WARA scope, APRL measurement, assessment admission, and authority.

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
provider mapping selects the provider-neutral resource type or its explicit candidate set when
one provider type legitimately represents several semantic types. Reviewed source aliases preserve
the original APRL identity and require an independently observed exact target; a subscription alias
never expands a workload subset into a complete subscription. Every other type remains
`unsupported` or `ambiguous`; it is never broadened to all resources. Subscription-scoped WAF and
specialized-workload recommendations additionally require matching workload tags. Parent and child
provider identities remain distinct, and a child-resource recommendation can match only the exact
child scope.

## Query admission

External Azure Resource Graph query bodies are stored separately from framework metadata and bound
by SHA-256 digest. All published strings are retained: 143 automated bodies and 229 inert manual
reference bodies, with 21 explicit null references. Reference preservation never enables execution.
Static review lexes comments, strings and identifiers before classifying commands; malformed
lexical structures remain blocked. Static review rejects mutation or control commands, dynamic endpoints,
undeclared tables, unsupported joins, and missing result bounds. Accepted syntax produces only a
provider-neutral read plan containing:

- the APRL GUID and query digest;
- the exact workload and resource scope;
- declared provider resource types and inventory generation;
- a timeout and maximum row count;
- required completeness, truncation, time, and provenance fields.

The Azure adapter renders the exact resource ids as a bounded case-insensitive `in~` literal list,
which Azure Resource Graph supports directly. It does not depend on unsupported dynamic-array
membership functions.

Static safety does not prove product semantics. Until an exact evaluator is reviewed, the
recommendation remains blocked even when its query is read-only. Query success is an observation
receipt, not a satisfaction result or operational success.
Exact bindings additionally pin required values and region, SKU or array eligibility. An independent
bounded coverage read must observe those prerequisites for every target; missing values, unknown
eligibility or incomplete/duplicate array members keep an empty finding result unknown.

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

Automated records also declare a separate manual-review fallback. It never changes the upstream
automation flag, admits a blocked query, or counts as automatic implementation coverage. A current
trusted manual attestation can decide a held recommendation; conflicting automatic and manual
outcomes remain unknown.

The scheduled job can read signed manual receipts from a deployment-installed producer trust
binding. Ed25519 verification, key revocation/validity, workload scope, source revision, crosswalk,
inventory generation and per-recommendation producer/kind checks precede ordinary runtime
qualification. An authentic signature never makes stale, conflicting or synthetic evidence valid.
The [evidence and export runbook](../../runbooks/wara-assessment-evidence.md) documents this input.

The initial Operator catalog projection preserves that requirement as structured read-only data.
The Console detail view shows the evidence kind, authoritative producer, exact scope contract,
freshness ceiling, accountable owner slot, and blocked reason. It does not provide a receipt-writing
control. Until a separately authorized producer supplies admissible evidence, the recommendation
remains `not_evaluated` with `manual_evidence_required`.

## Control assessment selection

Published `High` and `Medium` impact recommendations start enabled for shadow assessment, while
`Low` recommendations start disabled. Their catalog lifecycle stays `active`; all 393 active
recommendations still appear in the result. A disabled recommendation stays `not_evaluated` and
`unknown` with `control_disabled`, and its automatic observation query isn't dispatched.
The 63 historical recommendations remain lifecycle-disabled regardless of assessment preference.

An optional reviewed installation profile can explicitly enable or disable an active control.
Its exact source revision, workload scope, review time, control identities, and digest are checked
before provider collection, and the complete profile is retained in the immutable result.
See [reviewed installation preferences](framework-assessment.md#reviewed-installation-preferences).
This choice neither approves non-applicability nor changes query admission, Rule activation,
ActionType promotion, or execution authority. The detail may show inert action candidates from
an exact active Rule binding; a candidate still needs the ordinary execution capability and gates.

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
approval receipt. If separately admissible receipts disagree, the runtime marks the evidence set as
conflicting and returns `not_evaluated` with `unknown`. All other cases remain `unknown` or `blocked`.

The result includes source and implementation digests, evaluated GUIDs, evidence references,
event and recorded times, aggregate counts, limitations, and `execution_authority: false`.
Deterministic replay recomputes the result digest from the same request and evidence set.

## Ontology and authority boundary

The scheduled report sink exports the same complete 393-control result as JSON, CSV, XLSX and
PPTX, retaining unknowns, limitations and source/time/digest identity. Native WARA Collector
Advisor, outage, retirement, support-ticket and Service Health inputs are bounded subscription
context only: unsigned imports remain unverified, expose counts rather than private ticket
content, and never satisfy a recommendation. Unconnected sources remain explicitly unavailable.

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
The shared physical transport may also carry the separate WAF and CAF framework-assessment logical
topic. Topic filtering, consumer groups, projection keys, and catalog pins remain independent, so a
framework assessment event cannot update WARA state or satisfy WARA evidence.
The Operator composition root imports both projection bridges through one assessment-projection
facade to preserve its reviewed fanout ceiling. The facade shares no state or assessment authority.
The shared Operator composition may register unrelated read projections in `/system/data-sources`;
those registrations don't add a WARA source, widen WARA scope, or change its shadow-only authority.
The same shared authenticator may pass a bounded verified username only to the IAM display
projection. That value does not enter WARA identity, evidence, projections, or assessment
authority.
Its outbox lifecycle facade may also supervise the unrelated Incident intervention worker. That
worker's explicitly allowlisted logical topic, requests, and readiness state cannot enter WARA
evidence, projections, or assessment authority.

[Alert noise governance](../operations/alert-noise-governance.md) uses separate alert-quality routes,
operation-filtered outbox claims, and a signed result consumer. Its private evidence, preferences,
and producer health do not update WARA projections or satisfy its evidence/readiness requirements.
WARA's existing scope, pinned queries, consumer isolation, and readiness criteria remain unchanged.
Operator-override promotion labels in the shared governance Console catalog don't change WARA
projections, evidence, or readiness. An active capability recall forces the ActionType to shadow,
removes it from the promotion-ready count, and displays the bounded reason without changing WARA.
The alert request-history query selects only its own outbox namespace, principal and exact scope.
Its signed terminal and baseline detail cannot satisfy or update any WARA assessment state.

Every row shows scope, evaluation time, source revision, evidence completeness, and limitations.
Catalog presence and `product_group_verified` are metadata, never a satisfied badge. Optional
projection absence renders as unavailable; malformed or unexpected responses remain visible errors.
Truncated identifiers use the shared Tooltip for the full value instead of native title attributes.
The shared Operator composition can add principal-scoped conversation document and T1 health
readers without changing WARA's pinned crosswalk, shadow consumer, projection ownership, or no-authority contract.
Multiplexed WARA and other non-request payloads add their logical-topic marker before one bounded
encode; semantic request payloads still pass their versioned producer codec first.
It delegates resolved-model source construction to focused lifecycle composition and starts the
resulting revision fence before the WARA projection bridge. When local Azure narration is enabled,
the same ordered lifecycle validates narrator targets from that revision before WARA starts.
A model digest mismatch or invalid required narrator target therefore blocks all later lifecycle
services without changing WARA evidence, assessment, projection, or remediation authority. Startup
failure cleanup attempts every acquired service, so one failing close cannot leave an earlier WARA
dependency running.
The same boundary applies to the shared [recorded Resource state query](../interfaces/recorded-resource-state.md).
Its inventory facts are operator context, not WARA assessment receipts. A retained `Running` or
`Succeeded` value, particularly one with unknown freshness, cannot populate recommendation
applicability, evaluation, or satisfaction. Assessment evidence still enters through the pinned
query and manual-evidence admission paths above, not through Dashboard colors or instance status.
The shared family store fences WARA to the committed manifest; its effective realtime overlay is
operator context only and cannot satisfy or widen assessment evidence.

The initial catalog projection also exposes the exact pinned APRL source URL, source path, version,
revision, digest, retrieval time, license, optional Microsoft Learn link, query digest, exact
evaluator reference, and structured manual-evidence requirement. The Console renders 50 controls
per page while preserving all 456 lifecycle records through explicit previous and next navigation;
it never hides the remaining catalog behind a client-only row limit.
The table keeps the recommendation title as the primary text, with the resource type and an
eight-character GUID prefix as secondary text. Advisory impact, mapping disposition, evaluation, and
satisfaction each have their own column, so no state is compressed into one cell. Framework tables
own their column tracks; the Rule catalog table's column widths never apply to them. On a phone,
the table shows the recommendation and satisfaction columns without horizontal scrolling.
The Rules catalog rail reaches this Controls destination without interpreting WARA state. Its
labels and counts remain catalog navigation; only the server-owned WARA projection can report
applicability, evaluation, satisfaction, or evidence limitations.
The rail lists Controls under a framework-assessment group, separate from detection rules, in both
catalog views. Rule citation navigation covers only Azure WAF requirements. WARA recommendations use
admitted Azure Resource Graph queries or manual evidence, so no Rule detail lists a WARA
recommendation as a citing control.

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
or truncated rows, applies `timeout_seconds` to the complete paginated observation, and records a
deterministic evidence digest. Before evaluating violations, a companion `Resources` query must
observe every exact target id under the same identity and deadline. Only then can zero matching
violation rows mean satisfied; one or more matching rows mean failed. Missing scope coverage is
unknown, never satisfied. All outcomes remain shadow observations without execution authority.

`WaraAssessmentObservationRunner` walks only recommendations that can produce an exact admitted
read plan. It preserves caller-supplied manual receipts, collects provider observations, converts
matching receipts into runtime evidence, and records one bounded `observed` or `unavailable`
attempt per eligible recommendation. `WaraAssessmentService` evaluates and publishes only after
that collection phase. The enriched request advances its evaluation and recorded cutoffs to include
the latest admitted observation, so a freshly collected receipt cannot be rejected as future
evidence. Only receipts returned by the provider during that collection can advance the cutoffs;
caller-supplied evidence remains subject to the original independent cutoff. Provider
unavailability remains `unknown` and is visible in audit evidence. At collection start, caller
receipts beyond the original cutoff are marked `caller_evidence_after_original_cutoff`; later
provider timing cannot make them admissible for another recommendation.

### Rule-backed evaluation

A second content-addressed overlay, `rule-bindings.json`, binds a reviewed APRL GUID and exact query
digest to one activated catalog Rule revision instead of a query evaluator. A recommendation can
have only one binding kind. A `t0_rule` binding carries a capability matrix: the canonical resource
type, child-resource behavior, the inventory source and fields the check reads, parameters, the
eligible set, and the failure semantics. Each binding pins the Rule version and the exact Rule
digest the review compared. The loader admits a binding only when the record is canonical,
`missing_exact_evaluator` is its only blocker, the pinned query and the Rule read the same fields of
the same type, the release Rule matches the pinned digest, and the Rule takes no parameters. A
receipt is produced only when the activated member has that same digest, and it is observed at the
inventory snapshot's completion time.

The job projects Forseti's verified version 2 baseline onto the WARA workload scope through the
same scoped coverage contract as WAF, then emits one `rule` receipt per binding whose producer is
`t0-rule-evaluator:<rule>@<version>`. A receipt is decisive only when the activated member is that
revision, every eligible pair has exactly one terminal outcome, and at least one resource is
eligible: any violated pair is `failed`, and every pair compliant is `satisfied`. Held, missing,
duplicate, conflicting, or drifted coverage emits no receipt, so the recommendation stays
`unknown`. The bound query is never executed, and a provider observation receipt can't satisfy a
Rule-bound recommendation. The request and result pin the overlay digest.

The first overlay binds one recommendation, Key Vault purge protection, whose query and Rule both
treat an absent or non-`true` value as a failure over every vault. Zone, high-availability, and SQL
redundancy recommendations restrict their query to zonal regions or treat an absent value as
passing, so they keep their query or manual evidence path.

### Scheduled deployment binding

The one-shot WARA job receives one deployment-owned umbrella `Workload` id and its reviewed
workload-class tags. One workload per run matches the existing single Operator projection; a future
multi-workload surface needs a versioned keyed projection instead of last-write replacement. A
PostgreSQL scope reader joins `workload_runs_on` relationships to the active inventory snapshot
under one repeatable read. It accepts only a current effective workload, one matching ontology
release, a fresh active observed inventory generation, complete linked `Resource` objects, and
exact Azure Resource Manager (ARM) ids. A newer failed collection, pending real-time resource
overlay, missing provider identity, duplicate identity, or resource bound overflow blocks the pass.

The Container Apps Job resolves the scope before provider observation. It then uses the existing
exact evaluator overlay, shadow assessment service, PostgreSQL audit store, and the logical WARA
topic multiplexed over the provisioned `fdai.pantheon.objects` Event Hub. Its read-only identity has
sender access only to that physical topic. Terraform admits only matching hourly or UTC-midnight
daily schedules and run slots. The upstream variables contain no workload or tenant values; each
deployment supplies its own id, keyed tags, cadence, and freshness ceiling.

## Validation and release boundary

Focused checks cover schema, importer parity, crosswalk accounting, evaluator-overlay identity,
query safety, exact scope and endpoint enforcement, manual evidence, runtime failure cases, replay,
ontology invariants, Operator API decoding, Console localization, and deterministic update diffs.
Full-catalog validation proves the pinned inputs and derived artifacts agree.
The shared PostgreSQL family store validates ontology relationship candidate counts independently
from WARA scope reads. Its inventory invalidation watermark reader remains a separate no-payload
stream and cannot satisfy, widen, or replace WARA evidence.
Immutable request, evidence, status, control, and result contracts remain in `core/wara/models.py`.
The runtime module owns evaluation, observation collection, audit, and publication and re-exports
those contracts so existing imports remain compatible.

Local and synthetic checks can establish `implemented`. `validated` requires a governed live-Azure
shadow receipt for a representative multi-resource workload. That separate operation needs explicit
authorization, provider identity, exact scope, network access, and audit retention.
Local and deployed profiles use the same pinned crosswalk, bounded read plan, shadow topic, Operator
consumer group, and PostgreSQL projection; neither profile substitutes provider evidence.
The shared Operator Kafka adapter may also publish notification-receipt logical records on the same
physical transport. Topic filtering keeps those records outside the WARA consumer and grants no
assessment authority. Multiplexed publication resolves one configured non-null physical topic
before encoding or sending any logical record.

The shared conversation transport accepts request version `1.7.0` and projection version `1.6.0`.
Its general explanations and goal-local support remain advisory, not WARA observations, assessment
receipts, or satisfaction results. Default conversation relationship binding does not change WARA
scope, consumer filtering, evidence admission, or the shadow-only assessment lifecycle.
The same Operator composition may emit an authority-free runtime-call witness after broker
acceptance. That telemetry does not enter WARA scope, evidence admission, or assessment results.

The Operator dialogue-state snapshot and request field add no assessment source, finding, or WARA mapping.

## Related docs

| To learn about | Read |
|----------------|------|
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/rules-and-detection/wara-assessment.md) |
| Source-bound explanations and diagrams | [Illustrated WARA guidance](wara-illustrated-guidance.md) |
| Pinned source collection | [Rule Catalog Collection](rule-catalog-collection.md) |
| Framework ontology projection | [FDAI Operating Ontology](../architecture/operating-ontology.md) |
| Read-only operator behavior | [FDAI Console Conversations](../interfaces/operator-console.md) |
| Shared Workflow validation contracts | [Process Automation](../decisioning/process-automation.md#71-shared-validation-owner-design) |
| Rule-backed WARA evaluation and the shared requirement limitation labels | [Framework Rule Evidence from T0](framework-rule-evidence.md) |
