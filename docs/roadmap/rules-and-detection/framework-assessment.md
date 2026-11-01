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

The shared catalog materialization job that publishes this assessment's catalogs also seeds Built-in `WorkflowDefinition` rows from the reviewed workflow catalog, and the shared workflow family now commits principal-owned private drafts and bindings. Neither path grants assessment execution or promotion authority.
Semantic result-handle persistence reuses shared Operator semantic storage only for opaque
conversation references. It does not change WAF or CAF assessment evidence, results, or authority.

Readable titles in the shared rule catalog list come from the matching rule detail. They are
presentation metadata and do not change WAF or CAF control mappings, assessment evidence, or results.

## Design at a glance

The shared catalog materializer exposes WARA's exact query and Rule evaluator identities and
distinguishes required manual evidence from optional signed fallback. Its illustrated detail
guidance is an inert source-pinned shared record, not another assessment specification or evidence
writer. It may carry one reviewed Microsoft Learn image shipped as a packaged, digest-verified asset with its source document, license and attribution; the image is a reference, never an observation of the installation, and ships only after its byte-identical public repository copy and CC BY 4.0 notice are verified. The WARA list may also carry the guide's Korean title as display text and search text; it never changes the source title, mapping, evaluation or satisfaction. These WARA additions do not change WAF/CAF requirements, admission, results or authority.

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
Immutable records, row projections, and these evidence decoders are separate internal modules; the
split changes no WAF or CAF query, projection, evidence, replay, or authority contract.
The shared authenticator may pass a bounded verified username only to the IAM display projection.
It does not enter WAF or CAF identity, evidence admission, replay, or results.
The shared Operator outbox lifecycle facade can also supervise the Incident intervention worker.
Its explicitly allowlisted logical topic, requests, and readiness state do not enter WAF or CAF
scope, evidence admission, replay, or results.
The assignment outbox uses the same transport lifecycle with separate logical topics and immutable
request receipts. Its case review, role claims, and PR result cannot satisfy WAF/CAF evidence or
alter an assessment result; a goal observation is not admitted manual evidence. Post-turn review envelopes share transport mechanics only; they cannot satisfy framework evidence, change an assessment result, or activate remediation.

[Alert noise governance](../operations/alert-noise-governance.md) adds distinct alert-quality routes,
operation-filtered outbox claims, and a signed result consumer to the shared host. Alert evidence,
preferences, and producer health cannot satisfy WAF/CAF evidence or readiness. Existing assessment
scope, catalog pins, admission, and readiness criteria are unchanged; no alert result updates them.
The shared governance Console catalog also labels operator-override promotions on the Promotion
gates view. An active capability recall forces that ActionType to shadow, removes it from the
promotion-ready count, and displays the bounded reason. Neither labels nor recalls change
assessment evidence, results, or readiness.
Alert request history selects its own outbox namespace, principal and exact scope; its signed
terminal and baseline detail are not framework-assessment receipts and never update WAF/CAF state.

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
The profile also pins the Rule activation generation, and a Rule receipt is admitted only when its
Rule provenance matches that pin exactly. See
[Framework Rule Evidence from T0](framework-rule-evidence.md#assessment-side-activation-pin).
A requirement can cite a Rule that the pinned generation doesn't activate, such as a newly shipped
check. Its receipt stays `unknown` with `rule_not_activated` until an approved activation change
adds the Rule.

### CAF catalog

The CAF catalog contains the seven methodologies and eight landing-zone design areas. Each record
defines its estate scope, owner, cadence, evidence requirements, and crosswalk relationships.

Strategy, Plan, and Adopt each require both procedure evidence and execution evidence. Azure
configuration can support these controls, but it cannot satisfy them without governed human-process
evidence. Ready, Govern, Secure, and Manage combine exact estate observations with process evidence.

The crosswalk records exact references to Rule, WAF, MCSB, `ControlObjective`, Azure Policy,
provider observation, or manual evidence. Each relationship is `full`, `partial`,
`supporting_only`, or `unmapped`; similar wording never establishes equivalence.

### MCSB catalog

The MCSB catalog uses the same runtime and workload scope as WAF. It decomposes all 86 imported v1
controls into one decisive manual control-evidence requirement plus reviewed Rule requirements, so
Rule evidence can fail an MCSB control but can't satisfy it alone. In every catalog, only decisive
requirements decide a control; a `supporting_only` requirement can neither fail nor block it. The
assessment job records MCSB results as no-authority audit receipts. When an MCSB assessment event
is published, the Operator keeps it in a separate `mcsb-assessment.list` projection and joins each
v1 control's server-owned state, and each requirement's evidence role, onto the MCSB catalog read.
The Console shows that state beside implementation coverage and never derives it. See
[Framework Rule Evidence from T0](framework-rule-evidence.md#mcsb-assessment).

## Control enablement and implementation guidance

Controls with `critical`, `high`, or `medium` severity start enabled for shadow assessment.
`low` and `informational` controls start disabled. An explicit reviewed profile choice takes
precedence over that default. Disabled controls remain in the complete result with
`not_evaluated`, `unknown`, and a `control_disabled` limitation; disabling is not an approved
not-applicable decision. Historical WARA recommendations remain disabled regardless of severity.

WAF retains each Best Practice's severity, and WARA normalizes its published impact. Where CAF or
MCSB doesn't publish a severity, FDAI uses an explicitly identified `medium` assessment priority;
this is an FDAI default, not a severity attributed to Microsoft. The immutable assessment binds
the resolved setting and any reviewed profile override. Rule activation remains independently
governed, and enabling a control can't activate an unreviewed Rule or change an ActionType mode.

All 59 WAF, 86 MCSB v1, and 15 CAF controls receive source-pinned English and Korean guidance.
The detail read attaches one identity- and revision-matched guide with applicability, illustrative
before/after state, implementation and verification steps, cautions, a directed diagram, and public
references. List reads don't embed the corpus. Guidance and its digest are presentation metadata,
not observed evidence, approval, or an assessment verdict.

The materializer validates the installed guidance against the reviewed assessment and the current
definition bytes before publishing its source pins. Detail fields `guidance_source_revision` and
`guidance_source_digest` retain the assessment's `source_revision_digest` and the selected control's
`specification_digest`, respectively. They never replace CAF's original `source_revision`.
Missing legacy pins produce an explicit unavailable guide; present mismatched pins fail the read.
MCSB v2-preview never inherits a v1 guide. A detail revision covers both its guide digest and any
authoritative Rule projection used to show inert action candidates.

Author changes in the control-specific source modules beside
[`framework_guidance_build.py`](../../../scripts/catalog/framework_guidance_build.py), not in the
packaged JSON. After a reviewed assessment change, regenerate the assessment catalogs first,
then run `uv run python scripts/catalog/framework_guidance_build.py`. Use the same command with
`--check` to verify exact accounting, source pins, and generated-file equality.

**Design critique and revision.** Filtering disabled controls out would hide the framework
denominator, while treating them as not applicable would invent approval. Keep them visible and
unknown instead. Reusing the existing WARA presentation primitives avoids three divergent
renderers, but WAF, MCSB, and CAF keep their own identities and assessment semantics. Remediation
guidance can identify reviewed Rule and ActionType connections; it cannot claim execution support
from a crosswalk alone. Actual changes continue through the existing risk, approval, promotion,
rollback, target-lock, dry-run, idempotency, audit, and independent effect-verification gates.

### Reviewed installation preferences

Both assessment jobs accept an optional deployment-owned JSON bundle through
`FDAI_CONTROL_ENABLEMENT_PROFILES_PATH`. Each entry pins the framework, source revision, exact
scope digest, reviewer, review time, ordered `{control_id, enabled}` overrides, and a canonical
profile digest. WAF, CAF, and MCSB use their assessment catalog's `source_revision_digest`;
WARA uses the pinned APRL source revision. Missing optional profiles retain severity defaults.
An unreadable, malformed, oversized, future-dated, wrong-scope, or wrong-revision profile fails
explicitly rather than silently reverting to defaults.

The configured framework reviewer also matches the preference reviewer. Resolved WAF, CAF, and
MCSB choices enter the existing immutable reviewed assessment profile and audit flow; WARA retains
the complete preference profile with its result. The Console displays these server-owned settings.
This input adds no browser mutation endpoint, Rule activation, or resource-execution permission.

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
Operator projection was published. A runtime whose identity has that sender role opts in with
`FDAI_FRAMEWORK_ASSESSMENT_PUBLISH=1` and `KAFKA_BOOTSTRAP_SERVERS`; the job then audits and
publishes WAF, CAF, and MCSB shadow events and records `publication_status: published`. Any other
value, or publication without a bootstrap server, fails before database work.

## Operator surface

The Operator API exposes the latest immutable projection and preserves catalog data when no
assessment exists. The Console shows:

- framework reference and exact source revision;
- selected scope and evaluation time;
- mapping, applicability, evaluation, and satisfaction as separate fields;
- evidence references, digests, freshness, completeness, conflicts, and limitations;
- owner, cadence, approved exception, and WAF tradeoff records; and
- unavailable and unknown states without a compliance label; and
- for a WAF `rule` requirement, server-owned scoped Rule coverage counts and activation state,
  shown only while their coverage record belongs to the current version 2 baseline.

WAF remains in the existing Controls view. CAF adds a sibling tab that uses the same quiet,
read-only interaction pattern. The Rules catalog rail links to that Controls view as presentation
navigation only; it does not merge Rule counts with WAF or CAF applicability, evaluation, or
satisfaction. The browser never writes evidence or approval.

Rule citations are navigation between definitions, not evidence. A WAF control's `rule` requirement
links to that rule's detail. `GET /best-practices?rule=<id>` returns only the controls whose
requirements cite that exact rule and echoes the applied `rule_filter`. The rule detail lists those
controls with their own server-owned status. A missing echo means the Console reports citations as
unavailable instead of showing every control.

## Source-change governance

The source watcher creates a deterministic review package containing additions, removals, semantic
changes, affected mappings, and stale evidence specifications. A proposed generation remains
pending until the exact package digest is approved. Validation failure preserves the prior valid
generation and records the failed revision and reason.
The shared local catalog materializer keeps framework projections separate from ontology evidence
health. If the active inventory and ontology projection generations differ, it publishes explicit
unavailable evidence instead of joining cross-generation timestamps or counts into the catalog set.
It builds Rule, framework, ontology, workflow, and stewardship projections in focused modules, then
publishes the complete projection set in one PostgreSQL transaction. A failed write publishes none
of the new generation. Referenced policy and remediation text is bounded and must be valid UTF-8;
invalid content fails materialization instead of entering a projection with replacement characters.
Repository mapping documents use PyYAML's compiled safe loader when available, with the Python safe
loader as the fallback. Each call reads the current file and retains mapping-root and typed catalog
validation; unsafe YAML tags remain rejected. Parser acceleration never grants evidence or authority.

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

The Operator dialogue-state snapshot and request field add no assessment source, finding, or framework mapping.
Packaged WAF, CAF, and MCSB v1 controls, MCSB v2-preview controls (with OWASP LLM Top 10 and MITRE
ATLAS references for `AI-1..AI-7`), MSRC CSAF advisories (with `P0`-`P3` priority tiers and attack
surface summaries), and Detection Rules attach bilingual titles (`title_ko`), 5-node relationship
diagrams, reviewed reference architecture images, and Command Deck view context (`selected_diagram_flow`,
`selected_verification`, `selected_caution`) as presentation metadata without changing assessment
evaluation, satisfaction, or execution authority.

## Related docs

| To learn about | Read |
|----------------|------|
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/rules-and-detection/framework-assessment.md) |
| Specialized WARA assessment | [WARA Evidence-Governed Assessment](wara-assessment.md) |
| Rule evidence from T0 for framework controls | [Framework Rule Evidence from T0](framework-rule-evidence.md) |
| Framework source collection | [Rule Catalog Collection](rule-catalog-collection.md) |
| Rule assignment and evidence governance | [Rule Governance](rule-governance.md) |
| Ontology authority boundary | [FDAI Operating Ontology](../architecture/operating-ontology.md) |
| Read-only operator behavior | [FDAI Console Conversations](../interfaces/operator-console.md) |
| Shared Workflow validation contracts | [Process Automation](../decisioning/process-automation.md#71-shared-validation-owner-design) |
