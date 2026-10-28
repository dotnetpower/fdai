---
title: Rule Governance
---
# Rule Governance

How an administrator **controls** rules - authoring, parameterizing, scoping, enabling, and
exempting them - the way Azure Policy lets an operator manage definitions, assignments, and
exemptions. This is the human-facing control surface over the rule catalog.

It builds on the collected/normalized rules in
[rule-catalog-collection.md](rule-catalog-collection.md) and the deterministic evaluation in
[phase-1-rule-catalog-t0.md](../phases/phase-1-rule-catalog-t0.md). It obeys the app-shape rule that
the Console submits typed requests through the non-privileged Operator API and never receives
managed-resource execution identity
([app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md)). Rule
activation may use a reviewed pull request, an authenticated direct request, or a signed offline
package, while every path retains the shadow-before-enforce and safety invariants in
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md).
The observation-first product default loads rules for audit, replay, and advisory evidence only; enforcement construction requires the explicit governed-execution add-on and all ordinary authority.

> Customer-agnostic: all identifiers, scopes, and values below are synthetic placeholders per
> [generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md).

The OPA builder stage is part of every Rule revision identity, but a Go patch release or the pinned `github.com/klauspost/compress@v1.18.7` security override is not a policy change. The identity gate hashes the Go pin of a minor series as the baseline that the retained revisions recorded and strips that exact security override line set, so a patch release keeps every identity. A new Go minor series, an OPA version change, or any other builder change still requires a Rule version bump, and a new series joins the baseline table only together with that bump.

## Catalog retrieval

Rule search is an A0 read projection and grants no policy, approval, or execution authority. The
production `CatalogSemanticIndex` adapter stores grounded Rule documents in PostgreSQL with
`pgvector` and combines case-insensitive exact Rule id, `tsvector` lexical rank, vector cosine
rank, and typed-neighbor similarity through deterministic reciprocal rank fusion (RRF). Stable
Rule id ordering resolves score ties.

The lexical projection includes both the reviewed active catalog and the recursively imported
collected corpus. Every entry retains an `active` or `collected` origin. Collected entries remain
inert reference records and don't join the active Catalog topology, T0 evaluation, or Workflow
inputs.

The index is built off the request and Operator API startup paths. A mechanical worker loads exact
Rule, ActionType, Rego, ontology-release, and promoted-surface evidence, stages one complete
generation, and changes the active corpus pointer only after an independent validation receipt.
Missing or mismatched evidence leaves the prior generation active. The read-only `/rules` route
uses semantic ranking only when the active generation matches the current Git catalog; otherwise
it returns the current lexical projection with an explicit stale or unavailable state. The full
contract is [Rule Semantic Retrieval](rule-semantic-retrieval.md).

## Model (three layers, like Azure Policy)

Azure Policy separates *definition* from *assignment* from *exemption*. FDAI mirrors that
so administrators get a familiar mental model:

| Azure Policy concept | FDAI artifact | What it is |
|----------------------|-----------------------|------------|
| policy definition | **rule** | a single testable control ([rule-catalog-collection.md](rule-catalog-collection.md)) |
| initiative (policy set) | **rule set** | a named, versioned group of rules (e.g. a security baseline) |
| assignment | **assignment** | a rule/rule-set applied to a scope, with parameters and an effect |
| assignment `enforcementMode` | **enforcement flag** | `enforce` vs `do-not-enforce` (shadow); orthogonal to effect |
| exemption (waiver / mitigated) | **exemption** | a time-boxed, justified suppression of a rule on a bounded Azure scope; assignment/category metadata is future schema work |
| effect (audit/deny/...) | **effect / mode** | what happens on violation (see Effects) |

A rule is inert until an **assignment** binds it to a **scope** with an **effect**. This is the
key to administrator control: authors write rules once; operators decide *where*, *how strict*,
and *with what parameters* they apply.

## Effects (Mode)

The effect is the safety dial. It maps onto the shadow→enforce lifecycle, not just a label:

| Effect | Azure Policy analog | Meaning | Safety tier |
|--------|---------------------|---------|-------------|
| `disabled` | `disabled` | rule/assignment is off | inert |
| `audit` | `audit` / `auditIfNotExists` | judge and log only, no change (equivalent to **shadow mode**) | safe default |
| `deny` | `deny` / `denyAction` | block the non-compliant change at the PR/admission gate | enforce (gated) |
| `remediate` | `modify` / `deployIfNotExists` | generate an auto-remediation PR (never auto-merged; always via risk gate / HIL) | enforce (gated) |

Effect (what to do on violation) is orthogonal to **enforcement mode** (whether to act at all),
mirroring Azure Policy's `enforcementMode`. An assignment carries both: `effect` plus
`enforcement: enforce | do-not-enforce`. `do-not-enforce` runs the check what-if only and is the
mechanism behind `audit`/shadow; promotion to enforce flips this flag under the promotion gate.
A **rule set** may declare a `default_effect` per rule and an **assignment** may override it per
rule (`effect_overrides`), like an initiative setting effects that an assignment tunes; the
assignment's top-level `effect` is the default for rules without an override.

**Allowed effect/enforcement transitions** (any transition not listed is rejected in CI):

| From | To | Gate |
|------|----|----|
| `disabled` | `audit` | standard review |
| `audit` (shadow) | `deny` / `remediate` (enforce) | **separate enforce-promotion approval** |
| `deny` / `remediate` | `audit` | standard review (demotion always allowed - fail toward safety) |
| any active state | `disabled` | standard review (records why) |

- **New assignments default to `audit` (shadow) with `enforcement: do-not-enforce`.** Promotion to
  `deny`/`remediate` is an explicit, separately reviewed change gated on (1) a minimum shadow dwell
  time and sample size, (2) measured shadow accuracy above threshold, and (3) zero policy-violation
  escapes ([architecture.instructions.md](../../../.github/instructions/architecture.instructions.md)).
- The observation-first profile cannot consume that evidence as activation authority. It records advisory quality and drift; only the explicit governed-execution add-on can enter this gate.
- A regression **auto-demotes** the assignment back to `audit`; demotion never needs the promotion
  gate, so safety degradation is always fast.
- The **absence** of an assignment means the rule is unenforced on that scope (governance is
  default-audit, not default-deny); this does not fail open at runtime - an unmatched or ambiguous
  event still routes to HIL per
  [architecture.instructions.md](../../../.github/instructions/architecture.instructions.md).
- `deny`/`remediate` actions carry the seven safeguards (stop-condition, rollback,
  blast-radius limit, dry-run, resource lock, idempotency, audit entry) from
  [coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md).
  A misfiring `deny` is recoverable via the global kill-switch or a time-boxed exemption (its blast
  radius is *blocking legitimate change*); a `remediate` PR is idempotent - a re-evaluated finding
  updates the open PR rather than opening duplicates.

## Scope

Scope selects which resources an assignment covers, CSP-neutrally:

- **Hierarchy**: organization → account/subscription → resource-group → resource.
- **Selectors**: by resource-type, by tag/label, or by an explicit resource-id allowlist.
- **Exclusions**: a scope may exclude child scopes (e.g. apply org-wide but exclude a sandbox).
- Scope is data; the executor still holds only its least-privilege identity and action whitelist
  ([security-and-identity.md](../architecture/security-and-identity.md)) - a broad scope never widens execution
  privilege.
- **Scope precedence**: when nested scopes both bind the same rule, the **most-specific scope
  wins** for parameters; for conflicting *effects* the **strictest effect wins**
  (`deny` > `remediate` > `audit` > `disabled`), and a genuine tie escalates to HIL - consistent
  with the deterministic order in
  [phase-1-rule-catalog-t0.md](../phases/phase-1-rule-catalog-t0.md#deduplication-conflict-and-precedence).
- **Conflicting assignments** on the same rule+scope resolve by that same strictest-effect-wins
  rule; the losing assignment is recorded in the audit trail so the resolution is reviewable, and a
  time-boxed exemption is the only sanctioned way to relax the strict outcome.

## Administrator Control Flow

Administrators can use the delivery channel available in their environment. Connected
installations may review a catalog-as-code pull request. An installation without GitHub access may
submit an authenticated direct change through the Operator API. A network without public artifact
egress may import the same change contract in a signed offline package.

The three channels converge before authority changes:

1. The channel produces a versioned `RuleActivationChange` with an expected generation, stable
  idempotency key, requested membership diff, reason, scope, source evidence, and authenticated
  requester.
2. The server validates the complete candidate generation, checks current approval evidence, and
  rejects stale, ambiguous, self-approved, or authority-raising input.
3. Mimir is the accountable Rule lifecycle owner. It atomically installs one immutable generation
  in Core PostgreSQL and changes the current pointer only after validation succeeds.
4. Saga records the request, approval, prior and resulting generation digests, actor identities,
  source channel, and terminal result in the append-only audit chain.
5. The runtime reads back the exact current generation before reporting the change as applied. A
  conflict or failed readback leaves the prior generation active.

The PostgreSQL current-generation pointer is the deployment-local source of truth for Rule
membership. Git and signed packages are authenticated authoring and transport channels, not
runtime dependencies. A direct request never means browser SQL access: the Console sends a typed
request to the Operator API, which persists an inert proposal and publishes it through the event
bus for Core-owned validation and application.

Every Core replica runs a bounded reconciliation loop against that pointer. A replica replaces
its in-memory Rule membership only when its generation digest differs, and it resolves every
member against the exact installed Rule artifact before replacement. Approval replay also performs
this reconciliation, so a runtime swap that fails after the durable pointer commit is recoverable
without replaying or reverting the authority transition.

Membership is independent from execution authority. Adding a Rule to an activation generation
makes it eligible for T0 evaluation in observation mode. It does not change an assignment's
effect, flip `do-not-enforce` to `enforce`, satisfy a promotion gate, grant approval, or give the
Operator API an executor identity. A membership removal lowers capability. An enforce promotion
continues to use its separate approval and promotion registry.

The connected pull-request channel retains the existing reviewed flow:

A reviewed profile rollout supplies `FDAI_PROFILE_ID`, `FDAI_RULE_ACTIVATION_SOURCE`,
`FDAI_RULE_ACTIVATION_SOURCE_REF`, `FDAI_RULE_ACTIVATION_PACKAGE_DIGEST`, and
`FDAI_RULE_ACTIVATION_SOURCE_RECORDED_AT` to Core. Pull-request and offline sources require all
five values. Core compares the resolved profile membership with the current database generation
and applies the exact diff through the same CAS ledger. Missing or ambiguous source metadata blocks
startup reconciliation instead of widening membership.

![Administrator pull-request channel. The main stages are administrator, draft change: rule / assignment / exemption, catalog-as-code PR, CI: schema + policy-as-code + shadow eval, review + approval, blocked, separate enforce-promotion approval, merge -> activation change, T0 loads the committed database generation.](../../diagrams/generated/fdai-roadmap-rules-and-detection-rule-governance-01.en.svg)

Direct and offline changes use the same validation policy as the pull-request channel. Their
approval evidence is stored in PostgreSQL rather than inferred from a repository. Requester and
approver identities come from verified principals, remain distinct, and are bound to the exact
candidate digest. Concurrent changes use compare-and-set against the expected generation; the
server returns a conflict and never rebases or retries an authority-bearing change implicitly.

Each successful generation stores its immediate predecessor as the rollback target. Rollback is
another audited, approval-bound pointer transition. A running decision pins the generation it
used, so a later activation cannot change the Rule identity or semantics midway through that
decision.

## Custom Rules and Precedence

Administrators can add **custom rules** alongside collected (built-in) rules, just as Azure Policy
allows custom definitions beside built-ins:

- A custom rule uses the same schema, with `source: custom` and full shipped `provenance`
  (`source_url`, immutable ref/hash, license/redistribution, retrieval time, and optional mapper).
- **Precedence** when a custom and a built-in rule overlap follows the deterministic order in
  [phase-1-rule-catalog-t0.md](../phases/phase-1-rule-catalog-t0.md#deduplication-conflict-and-precedence)
  (severity, then source priority, ties → HIL). A custom source is given an explicit
  `priority_rank` so overrides are intentional and auditable, never accidental. Custom does **not**
  automatically outrank built-in: a custom rule that would *weaken* a built-in `deny` is flagged in
  CI and requires explicit review, so a control is never silently relaxed.
- Custom rules follow the same shadow-before-enforce lifecycle; a custom `deny` is not exempt
  from the promotion gate.
- **Untrusted authored input**: a custom rule's `check-logic`, `remediation`, and any parameter
  values are validated against schema at load and evaluated **only** through the sandboxed policy
  engine (OPA) - never string-interpolated into shell or provider API calls - closing the
  injection path from rule text or parameters
  ([coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md)).

## Exemptions

An exemption waives an assignment for a scope, like an Azure Policy exemption:

- Current required fields are `rule_id`, an Azure-shaped `scope` bounded to a resource group or
  resource, **justification**, distinct `requested_by` / `approved_by` UUIDs, `state`, `created_at`,
  and `expires_at`. The loader enforces no self-exemption, explicit UTC timestamps,
  `expires_at > created_at`, and consistent terminal revocation metadata.
- The exemption artifact remains independent from assignment storage. Scheduled expiry accepts an
  exact reviewed `ExemptionAssignmentBinding` from deployment composition. A missing or ambiguous
  binding produces an audited hold; the coordinator never guesses an assignment from a rule id or
  provider scope.
- A configured **maximum exemption duration** and **ahead-of-expiry alert lead time**
  (`AppConfig.rule_governance.exemption_max_duration_days` /
  `exemption_alert_lead_days`, cross-validated so the lead time is always shorter than the
  maximum) are enforced: the governance catalog loader rejects any exemption whose
  `expires_at - created_at` exceeds the configured maximum, failing the catalog load closed.
- Runtime startup loads reviewed exemption JSON into the same immutable governance catalog and
  binds a subscription- and scope-verifying registry to the safety check. Invalid or duplicate
  data, unknown rules, malformed ARM resource ids, expired state, and revoked state fail closed or
  do not match.
- Auto-renew isn't supported. `fdai.rule_catalog.schema.exemption_lifecycle.plan_exemption_lifecycle`
  is the pure, deterministic decision core for **scheduled expiry mechanics** and **ahead-of-expiry
  alerts**: it decides, for every active exemption, whether it is already past `expires_at`
  (`expire`) or inside the configured alert lead time (`alert_ahead_of_expiry`).
  `fdai.delivery.exemption_lifecycle.ExemptionLifecycleCoordinator` combines that decision with an
  injectable `ExemptionLifecycleNotifier` (contract in `shared/providers/exemption_lifecycle.py`;
  the shipped default only logs - no network) and the standard append-only audit boundary. It groups
  newly due lookahead items into a versioned digest that names each exact exemption revision and
  requester. Atomic state claims make each item safe across replays or replicas.
- The Core runtime schedules that coordinator. `fdai.runtime.exemption_lifecycle` runs one sweep per
  interval (`FDAI_EXEMPTION_LIFECYCLE_INTERVAL_SECONDS`, default 3600; disabled by
  `FDAI_EXEMPTION_LIFECYCLE_ENABLED=false`) only when the installed catalog holds an exemption, and
  delivers the digest through the workload's own notification router as one A2 operational alert.
  The alert's audit id derives from the exact exemption revisions, so a restart, a second replica,
  or a retried sweep never sends the same digest twice, and a digest that no channel delivered is
  retried on the next sweep. This scheduled sweep publishes no expiry command and changes no
  catalog; it grants no authority.
- Expiry never calls a cloud provider. The coordinator binds the active and expected expired
  exemption revisions to an exact assignment id, version, and scope, then publishes a replay-stable
  `governance.reapply-rule-assignment` proposal through the provider-neutral `EventBus`. Broker
  acceptance is recorded as `broker_accepted_not_executed`; it is not execution success. The
  ActionType starts in shadow mode, requires human approval at T0, and retains the normal Forseti,
  Var, Thor, Saga, and Vidar boundaries plus target lock, rollback, and independent effect
  verification. A consumer must revalidate the expected terminal exemption revision before any
  reapply. Revocation or revision conflict therefore holds instead of mutating.
- The initial alternative was a discovery-loop signal that directly re-evaluated the scope. That
  path had no registered mutation contract and could blur observation with authority. The revised
  design uses the existing typed action pipeline and treats missing binding, unavailable publisher,
  and unknown broker outcome as audited holds. `scripts/governance/exemption-expire.py` still updates
  only the reviewed catalog artifact; it never mutates managed resources.
- Every exemption and its expiry is audited; an exemption never suppresses the audit record of the
  underlying finding - it records *why* it was accepted, not that it did not occur.

## Overrides

> **Current status**: Implemented. `fdai.rule_catalog.schema.override.Override` +
> `override.schema.json` + `load_override_from_mapping` + the `<root>/overrides/` directory
> loader (`GovernanceCatalog.overrides`) enforce every MUST rule below at the catalog-load
> boundary, and `resolve_override` + `apply_governance_override_to_rule` apply the resolved
> override at T0 runtime, on top of assignment resolution. A parameter-relaxation override's keys
> and bounds are checked against the separately reviewed
> [`rule-catalog/override-parameter-bounds.yaml`](../../../rule-catalog/override-parameter-bounds.yaml)
> policy; an unlisted key or an out-of-bound value fails the catalog load closed - there is no
> runtime HIL fallback for a policy violation, only a load-time rejection. The upstream
> distribution ships no active override and no relaxable rule (the policy file is empty by
> default).

An **override** is the human control surface *above* the automated quality gate: an operator
declares that a rule is too aggressive in a specific environment and narrows, downgrades, or
disables it - without editing the rule. Overrides are what
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md#human-override)
means by "human override on top". They complement, not replace, exemptions.

### When to Use Which

| Situation | Use |
|-----------|-----|
| A specific resource has an accepted-risk or mitigated waiver for a bounded time | **exemption** (time-boxed) |
| The rule itself is systematically too aggressive for a resource-group, indefinitely | **override** (may be permanent) |
| The rule is a poor fit everywhere and should not exist | **rule retirement** via the catalog pipeline, not an override |

An override is not a waiver of an individual finding - it is a scoped policy stance that the
rule's shipped behavior does not match this environment.

### Rules (MUST)

- **Policy-as-code, separate artifact**. An override is its own catalog-as-code entry
  (`kind: override`); it never edits the target rule's text. Removing the override restores
  the rule automatically, and an upstream rule update flows through untouched.
- **Scope MUST be resource-group-equivalent or narrower** - the `resource-group` layer of the
  scope hierarchy above, or a specific `resource`. Organization- and account/subscription-wide
  overrides are rejected in CI; disabling a rule everywhere is a **rule retirement**, which
  goes through the catalog pipeline, not an override.
- **Permitted modes**: `disabled` (rule off in the scope), `severity-downgrade`
  (e.g. `critical -> medium`), and `parameter-relaxation` (widen a threshold within the range
  the rule's schema declares). Any other broadening is rejected.
- **No forced expiry**: an override MAY be long-lived; `expires_at` is optional. This is the
  key difference from an exemption. A justification is always required.
- **Distinct approver**: the requester MUST NOT be the approver (no self-override), mirroring
  the exemption rule and the approval≠execution boundary in
  [security-and-identity.md](../architecture/security-and-identity.md).
- **Shadow keeps running**: an override disables *execution* on the scope, not detection. The
  evaluator continues to record what the rule would have flagged and feeds those findings to
  the autonomous discovery loop in
  [rule-catalog-collection.md](rule-catalog-collection.md#autonomous-rule-discovery).
- **Audit-first**: every override create/modify/remove event is an append-only audit entry
  (actor, reason, target rule, scope, mode). An override never suppresses the audit record of
  the underlying finding - it records *why* execution was suppressed on that scope.

### Precedence

- An override wins over an assignment's effect **on the scope it covers**. If a rule has
  `effect: deny` from a promotion approval but an override on resource-group `R` sets
  `mode: disabled`, the rule is inert in `R` and enforced everywhere else.
- Outside the override's scope, the standard scope-precedence in [Scope](#scope) applies
  unchanged (most-specific scope wins, strictest effect wins, ties → HIL).
- Overrides do **not** stack: at most one active override per (rule, scope) pair. A second
  override on the same pair replaces the first, and both create and replace events are
  audited.

### Feedback Loop

- Overrides are inputs to the discovery loop
  ([rule-catalog-collection.md](rule-catalog-collection.md#override-feedback)). When a rule
  accumulates recurring or long-lived overrides across scopes, the loop proposes a
  **revision** (narrow the rule) or a **retirement** (rule is a systemic poor fit); either
  proposal still passes the quality gate before it can enter the catalog.
- Every T0 override resolution writes a `governance.override_resolved` append-only audit entry
  (`rule_id`, `override_id`, `override_mode`, `override_scope`) - the concrete evidence source a
  `DiscoverySignalKind.OVERRIDE` signal (`operational_learning/discovery_contracts.py`)
  eventually queries to recognize a recurring or long-lived override. No `object.override` bus
  topic exists for this (agent-pantheon.instructions.md); the signal thresholds themselves (number
  of distinct scopes, dwell time, shadow-hit rate before proposing a revision/retirement) remain
  the open decision below, and a concrete `DiscoverySignalSource` binding for this evidence is
  the same composition-root seam every discovery signal kind still needs.
- The console MAY surface an "over-overridden rules" view for operators; it remains
  read-only, and proposing a revision/retirement is still a PR.

## Repository review and installation approval

Repository source review and installation approval are separate authority boundaries.
GitHub's protected-branch policy owns repository permissions, required reviews, stale-review
handling, and required exact-head CI. A pull request cannot select a different repository
policy by supplying an FDAI installation profile or omitting a verifier App id. This change
does not modify branch protection or grant a repository author runtime authority.

**Design and critique:** Requiring every source contributor to deploy an Entra verifier
conflated source review with installation approval. Simply skipping a missing App would
instead hide an unverifiable operational approval. The revised boundary uses protected
GitHub review for source and retains explicit, fail-closed installation verification.

CI classifies governed source changes with `--scope-only`; its output describes potential
installation review requirements, not approval evidence. Source checks do not load deployment
profiles, fetch Entra attestations, or issue operational approvals. The existing App-backed
CLI remains an optional integration for installations that select that trust path. Its
caller supplies the installation's active policy and authoritative GitHub review, commit,
and exact-head trusted Check Run facts. A successful result is review-only, not activation,
promotion, or execution permission. Missing App configuration or untrusted evidence in that
selected integration still blocks the installation review.

## Qualification evidence

An installation qualifies the governance rollout through one review-only record, built by
`fdai.core.governance_qualification` and `scripts/governance/build-governance-qualification.py`.
The record binds the installation, management scope, environment class, Rule generation digest,
ontology release digest, pinned provider revisions, and evidence cutoff before collection.

- **Sources.** Every required provider source is admitted only when it is available, observed no
  later than the cutoff, and fresh at the cutoff. Unavailable, stale, incomplete, revoked,
  conflicting, missing, post-cutoff, and conflicting-duplicate sources each become a named hold.
- **Frozen cohort.** False positives, false negatives, holds, and coverage are measured on a
  cohort frozen by digest. A changed case set fails closed. A held case is never counted as correct,
  a worst-case false-negative rate counts held violations as misses, a zero denominator is absent
  rather than zero, and every rate carries its Wilson 95% interval and the independent-group count.
- **Record.** The record is `ready_for_review` only when no source is held and the cohort is
  measured without holds; otherwise every blocker is named. It carries `authority: none`, never
  approves, promotes, or executes, and changes no mode. Its digest, the source digest, and the
  measurement digest are the evidence digests the implementation ledger MUST cite.

## RBAC (who can do what)

For installation governance, authoring, approving, assigning, and exempting are **separate permissions**.
The following table describes the default multi-operator profile, which excludes self-approval,
mirroring the approval≠execution rule in
[security-and-identity.md](../architecture/security-and-identity.md). These are **logical** governance roles;
they map to a small set of Entra security groups (Reader / Contributor / Approver / Owner +
Break-Glass) in [user-rbac-and-identity.md](../interfaces/user-rbac-and-identity.md). Several logical roles
collapse to the same Entra group - no-self-approval is enforced on verified authorship, not by
group separation, and high-risk approvals (`audit → deny / remediate`, exemption, override, or A1
channel routing) require a **quorum of two approvers** from `aw-approvers`.
An explicitly selected single-operator production profile instead lets its named operator
satisfy every change class with effective quorum one. Required capabilities and Owner-tier
checks remain, every approval needs fresh phishing-resistant authentication, and audit
records the original quorum, profile, named operator, and self-review. The installation's
active policy selects this profile; PR content cannot select it for the repository.

| Logical role | Entra group | May | May not |
|--------------|-------------|-----|---------|
| Rule author | `aw-contributors` | propose rules/rule-sets (draft PR) | approve or assign their own change |
| Approver | `aw-approvers` | review/approve governance PRs | author the change they approve |
| Assignment operator | `aw-contributors` | bind rules to scopes, set parameters/effect (via PR) | approve the enforce promotion alone |
| Enforce-promotion approver | `aw-approvers` (quorum-2) | approve `audit`→`deny`/`remediate` promotions | be the operator who proposed the promotion |
| Exemption approver | `aw-approvers` (quorum-2) | approve time-boxed exemptions | grant a permanent exemption, or approve their own request |
| Override approver | `aw-approvers` (quorum-2) | approve resource-group-scoped overrides (may be permanent) | approve an override outside the resource-group-equivalent scope, or approve their own request |
| A1 routing approver | `aw-approvers` (quorum-2) | approve changes to the decision-bearing primary or fallback route | approve a route they proposed, co-authored, or committed |
| Rule retirement approver | `aw-approvers` (quorum-2, Owner-tier) | approve moving a rule out of the enforce set globally | approve a retirement without an Owner-tier reviewer among the quorum, or approve their own request |

The deterministic decision core for that table is
`fdai.rule_catalog.schema.governance_review_authority`. It reads the shared role/capability
matrix, counts only approvals that name a non-blank operator object id, review the exact
pull-request head revision, follow that revision in time, carry the capability the change class
requires, and satisfy the phishing-resistant requirement of a high-risk class. Repeated approvals
from one operator count once, and an approval from the author, a recorded co-author, or the
committer blocks the change under the multi-operator profile even when other approvals already
reach the quorum. The selected single-operator profile permits its named human's self-review,
but never an executor's approval or an unnamed human's substitution. The decision is
review-only and grants no execution authority.

None of these governance roles hold the **executor's** identity; authoring/approving a rule never
grants the ability to run an action. Enforce promotions, exemptions, and overrides are the
highest-privilege governance acts and require MFA / phishing-resistant, action-bound approval
([security-and-identity.md](../architecture/security-and-identity.md)) enforced via Conditional Access on
`aw-approvers` and `aw-owners`
([user-rbac-and-identity.md#conditional-access](../interfaces/user-rbac-and-identity.md#43-conditional-access)).

The **risk-classification table** ([risk-classification.md](../decisioning/risk-classification.md)) is a
sibling governance artifact that decides how each match is routed (`auto` / `hil` / `deny`).
It is edited through the same PR flow as rules and assignments, with an elevated quorum
and Owner-tier reviewer for loosening changes.

### Notification routing scope

The A1 routing approver row covers decision-bearing routing only. The classifier treats a change
to `config/notifications-matrix.yaml` as A1 routing, the `override` installation-review class,
unless it can show that the change leaves A1 routing intact. The multi-operator requirement is
quorum two with trusted identity evidence; a selected single-operator profile changes only
the applicable quorum and self-review rule. The classifier
compares the matrix at the merge base with the matrix at the pull-request head, so later commits on
the base branch don't change the result. The change is A1 routing when any of these holds:

- either side is missing, isn't UTF-8, uses YAML anchors, aliases, merge keys, or duplicate keys,
  or fails the runtime matrix validation;
- anything outside `matrix.routes` changes, such as channel settings or the default route;
- a route is removed, because its category then resolves to the default route;
- the default route is modified;
- an added or modified route has the A1 trust tier before or after the change.

Adding or modifying any other route, such as an A2 alert or an A4 digest, is ordinary routing
configuration. It needs no identity attestation and follows normal pull-request review. Comment-only
edits don't change the parsed matrix. Source CI reports this scope without requiring
`FDAI_GOVERNANCE_IDENTITY_APP_ID`; GitHub branch protection remains authoritative for source
review in either case. For an installation using the App-backed CLI, missing trusted evidence
still fails closed. If the same diff changes the CI workflow, gate script, matrix validator,
router, trust-tier contract, or review-authority code, the classifier conservatively requires
installation identity review. `rule-catalog/override-parameter-bounds.yaml` always has the
override installation-review classification.

A new non-A1 route can't capture decision-bearing traffic. The router refuses to deliver an A1
message through a route whose tier isn't A1, and it escalates the message to the HIL sink with a
`trust_mismatch` audit outcome instead. Before this rule, an A1 message whose category had no route
reached the A1 default route, so adding a route for that category could have redirected it.

## Lifecycle and Versioning

- Rules, rule-sets, and assignments are versioned catalog-as-code. Exemptions carry a stable id,
  state, and creation/expiry timestamps but no artifact `version` in the current schema. Tracked
  file changes remain revertible through their PR history.
- Rule states: `draft → audit(shadow) ⇄ enforce(deny/remediate) → deprecated`, with `disabled`
  reachable from any active state and the `enforce → audit` demotion always available. Deprecation
  tombstones the rule (never a silent delete) so history stays reconstructable.
- Changing a rule's logic bumps its `version`; changing an assignment's parameters/effect/scope is
  itself an audited, versioned change. A rule set **pins the `version` of each member rule** so a
  rule change cannot silently alter a promoted set.
- **Rule revision upgrades (phases 1-9 implemented):** An activation generation pins each
  member's exact version and digest, and the ledger accepts only membership changes against an
  unchanged catalog, so changing an activated Rule's content makes an upgraded installation fail
  closed at startup. Until every phase below is operationally validated,
  `scripts/quality/architecture/check-rule-revision-lock.py` locks each shipped Rule's version,
  definition digest, and policy content digest in `rule-catalog/rule-revision-lock.json`, and a
  changed check ships as a new Rule id. Four earlier designs were rejected in critique; their
  findings are recorded in the
  [ledger](../../roadmap-implementation/rules-and-detection/rule-governance.md). The current
  design runs in this order, and each phase keeps startup fail-closed. The compatibility floor
  reads version 1 and 2 outer envelopes for every declared activation family, normalizes current
  typed payloads and nested command proposal/generation payloads to version 1, reads pre-version
  records as legacy version 1, and writes version 1 only. Manifest, prepare, and acknowledgement
  kinds are fixed at the envelope boundary; their semantic state machines remain owned by phases
  3 and 5. The retained `rule-revision-identities.json` registry now fixes each normalized Rule
  definition and complete policy artifact closure to its exact OPA builder stage and normalization
  implementation manifest. That manifest binds the normalizer, Rule/base/enum models, Python image,
  and Pydantic/PyYAML versions. A bounded lexer distinguishes strings, raw strings, escapes, and
  comments before dependency discovery. A static data prefix retains its complete package subtree,
  including child modules under the entrypoint's own package, while bare-root references that
  cannot produce a static closure fail closed.
  The registry uses explicit `(rule_id, rule_version)` fields rather than a concatenated key, and
  its checker appends a version bump while refusing to rewrite an existing revision. Signed
  manifests now bind non-direct sources to one release, target generation, profile, catalog,
  registry root, complete member set, deployment scope, bounded validity window, and nonce. A
  separate trust policy owns key rotation, revocation freshness, and validity. Verification
  compares every signed identity with an independently resolved local expectation, then reserves
  the nonce durably but cannot move the active pointer. A dormant v2 identity context now separates
  the full retained catalog manifest from the resolved active profile snapshot and generation
  digest. Catalog growth alone therefore changes proposal provenance without changing active
  identity. A dormant transition precondition retains every prior catalog revision, requires a
  strictly increasing semantic profile version for active member changes within the same profile,
  keeps cross-profile version namespaces independent, and preserves generation identity only
  when profile id, version, and members are all unchanged during catalog-only growth. Phases 1-6
  stay authority-neutral. Phase 7 is the only implemented cutover from the fenced version 1
  pointer to the authority-bearing version 2 pointer; startup can read that result but cannot
  originate it. Phase 8 moves one explicitly named revision and enforcing binding through one
  approved authority CAS. Phase 9 retains rollback closure, serializes every new reference against
  retirement, and runs rollback through the same cohort and authority CAS.
  1. **Dual-read codecs.** A compatibility release reads version 1 and 2 of every durable object
     and event (proposal and change union, approval, command, result, pointer, generation,
     idempotency row, manifest, and prepare and acknowledgement events) while still writing
     version 1. It becomes the minimum binary-rollback floor once any later phase runs.
  2. **Immutable revision identity.** One `(rule_id, rule_version)` maps permanently to one
     definition digest and one policy identity; a digest change without a version bump is
     rejected, never approved. The policy identity digests a canonical executable bundle: the
     referenced Rego, its transitive modules and data, and the OPA and normalization versions.
     Retained artifacts are stored by the full revision identity. This phase is implemented as a
     generated, append-only release registry, content-addressed retained definition and policy
     bytes, plus a fail-closed CI checker. The CI caller supplies its exact base revision, and a
     missing or unreadable baseline fails instead of disabling history checks. Merge-base
     comparison prevents removal or rewriting of an earlier retained revision. It remains
     authority-neutral: current activation generations still write version 1 and no registry
     entry selects membership or enforcement.
  3. **Signed registry and manifests.** Every non-direct startup source, including pull-request
     sources, carries a signed activation manifest binding the release or package id, target
     generation, profile, catalog manifest, full member identities, registry root, issuance time,
     and deployment scope, with defined trust roots, rotation, revocation, and anti-replay. The
     unsigned installation fallback is removed. Signing proves artifact integrity only and never
     replaces human approval. This phase is implemented as a versioned Ed25519 contract plus a
     fail-closed trust verifier, exact local identity expectation, and durable nonce reservation.
     No manifest is composed into
     activation until the later cohort and approved identity-upgrade phases.
  4. **Identity separation.** The active generation digest covers only the active member
     identities and the resolved profile snapshot. The full catalog manifest digest, which indexes
     every revision identity, becomes proposal provenance and a transition precondition. A profile
     version identifies a resolved member snapshot, so every revision change bumps it.
     This phase is implemented in an authority-neutral v2 contract. The signed-manifest
     expectation is derived from the validated catalog/profile/generation context, while current
     activation pointers and writes remain version 1. The transition identity joins source and
     target catalog, profile, and generation digests and rejects revision carry-forward under an
     unchanged or backward-moving version within the same profile.
  5. **Replica cohort protocol.** Activation follows a durable state machine: desired (approved,
     inert), prepared, active, and per-replica applied. Prepare freezes a cohort of authenticated
     replica ids, release ids, startup epochs, and serving leases. A keyed prepare announcement
     goes out on the event bus; each replica observes it from its own subscription and publishes an
     authenticated acknowledgement or refusal with its locally verified artifact digests, and a
     coordinator persists them idempotently. A refusal blocks activation; a replica leaves the
     cohort only with drain or lease-expiry evidence. Serving leases are fences bound to the
     applied generation: during prepare no replica is admitted or renewed unless it joins and
     prepares, and a replica rejects work once fenced or expired. One CAS then moves the
     authority-bearing active pointer, which prepare never touches, and that CAS binds the digest
     of the exact acknowledgement set. A replica records `applied` only after it
     replaces its complete T0 generation, and runtime evidence cites the replica's applied digest.
     This phase is implemented as a dormant v2 cohort ledger. It freezes exact replica,
     principal, release, startup epoch, and serving-lease identities; admits authenticated
     acknowledgements or refusals; binds the exact acknowledgement-set digest to a CAS-selected
     candidate-active record; fences expired or unacknowledged replicas; and retains applied
     readback. PostgreSQL rechecks lease expiry at database linearization and atomically guards
     candidate replacement plus applied insertion. Authentication binds the full frozen identity
     and exact receipt digest. Each successor prepare CAS-chains from the latest authenticated
     serving-inventory snapshot; replica removal or identity replacement requires independently
     verified drain or lease-expiry evidence. Candidate selection atomically guards that exact
     latest prepare. It never writes the version 1 active pointer.
  6. **Enforcement pins and dual-revision slots.** Every enforcing binding, including an explicit
     assignment, pins the revision it enforces. The runtime gains a prepared shadow slot keyed by
     full revision identity, so the old revision keeps enforcing while the new one evaluates in
     shadow, and every evaluation's evidence cites the revision identity it ran. Once every cohort
     replica reports the new revision applied, a separate approved CAS moves the binding. Combining revision and promotion
     in one approval requires the stronger promotion quorum and revision-keyed evidence.
     This phase is implemented as dormant contracts and an immutable Core ledger. Every binding
     pins one revision, the old slot stays enforce while the new slot is shadow, and evaluation
     evidence cites revision, binding, and slot digests. A move candidate requires the exact ACK
     set, every required replica applied to the slot's exact profile and revision, revision
     evidence, and separate promotion approval verified through an injected authority provider.
     Core derives the final approved enforce binding and move candidate from retained records.
     It remains inert and never changes current enforcement.
  7. **Approved identity upgrade.** Moving existing version 1 generations to version 2 is an
     explicit command approved by a distinct human. It binds the source generation digest, every
     target member identity, the target generation digest, and the signed release, and verifies
     policy identities against a reviewed baseline, not merely the installed bytes. It runs through
     the cohort protocol only after every serving binary is dual-read capable, and it is the
     cutover that makes version 2 authoritative. Startup may read back an approved upgrade but never
     originates one.
     This phase is implemented as a reviewed-baseline contract, authenticated replica-capability
     evidence bound into each cohort acknowledgement, a durable governance-attestation authority
     provider, and an atomic Core cutover. The baseline proves each legacy member's exact mapping
     to a revision whose digest covers the reviewed definition and policy identities. The cutover
     rechecks the signed manifest reservation, exact candidate-active cohort, all applied replicas,
     active approval profile, distinct approvers, and complete dual-read evidence. One transaction
     then fences the version 1 pointer and inserts the version 2 authority pointer; a later version
     1 writer is rejected, and an incomplete fence fails startup readback.
  8. **Revision changes.** A change names `rule_id`, the from and to revision identities, and the
     from and to catalog manifest and profile identities, all inside the approved proposal digest,
     and runs through the cohort protocol. Revisions never carry forward unattended.
     This phase is implemented as a single-Rule proposal and an authority-bearing binding pointer.
     The proposal contains the complete source/target identity transition, logical binding id,
     signed target release, registry root, cohort, slot, and approved move candidate. It rejects
     membership changes, multiple revision changes, and unrelated profile switches. Core rechecks
     the exact source authority pointer, source and target profile snapshots, authenticated v2-write
     acknowledgements, applied identities, manifest reservation, active approval profile, and
     database-time serving leases. One transaction CASes both the generation pointer and the
     binding pointer, so neither can become authoritative alone.
  9. **Retention and rollback.** A release or shared registry retains the full closure that
     supported rollback needs. A revision can't be retired while any active, desired, prepared,
     applied, or rollback-eligible generation, enforcement pin, or promotion record references
     it, and retirement is itself an approved, audited operation. Rollback is an approved
     transition through the same cohort protocol.
     This phase is implemented as a bounded reference snapshot, approved retirement tombstone,
     retained rollback eligibility, and rollback transition kind. Active, desired, latest
     prepared, current candidate/applied, rollback-eligible, enforcement-pin, and promotion
     references block retirement. Prepare, slot, move, desired, generation, binding, eligibility,
     and retirement writes all serialize through one retention epoch; database transactions reject
     a tombstoned target and prevent retirement from racing a new reference. Retirement verifies
     the exact content-addressed registry closure and never deletes historical bytes. A rollback
     must cite an unexpired eligibility record produced atomically by the transition it reverses,
     use a new monotonically increasing profile version, regain the old member and binding through
     a signed target manifest and fully applied v2-write cohort, and pass the same current
     governance approval and pair CAS as a forward revision change.

  Request identity derives from the release, the proposal digest, and the target generation, so
  concurrent replicas converge by reading back the same record.
- **Testability**: every assignment/exemption PR ships fixtures - the expected match set (which
  synthetic resources the scope selects) and, for enforce promotions, the shadow-eval sample the
  promotion gate scored - so governance changes are regression-tested like rule changes
  ([coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md)).

## YAML Shapes

### Rule Set (initiative)

```yaml
schema_version: 1.0.0
kind: rule-set
id: ruleset.security-baseline
version: 1.0.0
members:
  - { rule_id: object-storage.public-access.deny, version: 1.0.0, default_effect: deny }
  - { rule_id: sql-database.tde-required, version: 1.0.0, default_effect: audit }
  - { rule_id: postgresql-server.point-in-time-restore, version: 1.0.0, default_effect: audit }
provenance:
  created_at: 2026-07-03T00:00:00Z
  created_by: governance-team
```

### Assignment

```yaml
schema_version: 1.0.0
kind: assignment
id: assignment.security-baseline.prod
version: 1.0.0
rule_set: ruleset.security-baseline
scope:
  include:
    - scope://org/account-000/prod
  exclude:
    - scope://org/account-000/prod/sandbox
  selector:
    resource_types: [sql-database, postgresql-server, object-storage]
effect: audit
enforcement: do-not-enforce
effect_overrides:
  object-storage.public-access.deny: audit
parameter_overrides:
  postgresql-server.point-in-time-restore:
    min_retention_days: "14"
provenance:
  created_at: 2026-07-03T00:00:00Z
  created_by: assignment-operator
```

### Exemption

```yaml
schema_version: 1.0.0
id: exemption.legacy-store.public-access
rule_id: object-storage.public-access.deny
scope:
  subscription_id: 00000000-0000-0000-0000-000000000000
  resource_group: example-resource-group
justification: Documented migration remains in progress with a compensating control.
requested_by: <requester-entra-oid>
approved_by: <distinct-approver-entra-oid>
state: active
created_at: 2026-07-03T00:00:00Z
expires_at: 2026-09-30T00:00:00Z
```

`requested_by` and `approved_by` must be distinct UUIDs supplied by the deployment. Named
placeholders avoid placing real tenant identifiers in this repository example.

### Override

```yaml
schema_version: 1.0.0
id: override.pitr-relaxation.rg-analytics
version: 1.0.0
kind: override
target_rule: postgresql-server.point-in-time-restore
scope: scope://org/account-000/rg-analytics
mode: parameter-relaxation
parameter_overrides:
  min_retention_days: "3"
justification: Non-critical analytics workloads with 3-day retention accepted by the data owner.
requested_by: 00000000-0000-0000-0000-000000000004
approver: 00000000-0000-0000-0000-000000000005
provenance:
  created_at: 2026-07-03T00:00:00Z
  created_by: assignment-operator
```

> `rule-set`, `assignment`, `exemption`, and `override` all have strict schemas read by the
> governance catalog loader (`<root>/overrides/*.yaml` -> `Override`); `exemption` also retains
> focused validation and expiry CLIs. Each rule-set member pins a rule `version`. Typed validation
> of `parameter_overrides` remains follow-up work for assignments; the current assignment schema
> accepts string values, and an override's `parameter_overrides` uses the same string-value
> contract plus a separately reviewed key/bound allowlist
> (`rule-catalog/override-parameter-bounds.yaml`). Exemption `requested_by` must differ from
> `approved_by`; override `requested_by` must differ from `approver` (the same no-self-approval
> rule). The assignment above is intentionally held **fully in shadow** - the rule set's `deny`
> default for `object-storage.public-access.deny` is overridden to `audit` and `enforcement` is
> `do-not-enforce` until a separate promotion approval flips it.
## Open Decisions

- [x] Resolve `scope://...` through the event's normalized organization, account, resource-group,
      and resource hierarchy in the T0 runtime. Identifier matching is case-insensitive; tags and
      canonical resource types retain their declared semantics.
- [x] Keep override authoring catalog-as-code only. No Console authoring UI ships in P1 or P3;
      adding one requires a separate draft-only product design.
- [x] Keep override parameter values on the existing string wire contract. The separately reviewed
      policy supports finite numeric ranges or explicit string enums; unlisted, malformed,
      non-finite, or out-of-bound values fail the catalog load.
- [x] The configured **maximum exemption duration** and the ahead-of-expiry alert lead time:
      `AppConfig.rule_governance.exemption_max_duration_days` (default 180) and
      `exemption_alert_lead_days` (default 14), cross-validated so the lead time is always
      shorter than the maximum.
- [x] The exact check that enforces "override scope is resource-group-equivalent or
      narrower" against the Scope URI grammar: `Override.__post_init__` rejects any
      `ScopeRef.level < ScopeLevel.RESOURCE_GROUP` deterministically (organization/account
      addresses), proven by `test_organization_scope_is_rejected` /
      `test_account_scope_is_rejected` in `test_override.py`. Wiring an equivalent CI-only path
      filter (like the exemption directory check) is optional now that the load boundary itself
      is fail-closed on every invocation, including CI's `check-governance-transitions.py`.
- [x] The permitted `parameter-relaxation` bounds per rule: a **governance-level allowlist**
      (`rule-catalog/override-parameter-bounds.yaml`,
      `fdai.rule_catalog.schema.parameter_relaxation_policy`), not the rule's own schema (which
      still declares no relaxation range - that half of this decision remains open). An unlisted
      key or an out-of-bound value fails the catalog load closed; there is no runtime HIL
      fallback for a policy violation.
- [x] The initial "over-overridden" signal requires three distinct scopes, 14 observed days, and
      100 shadow hits. `OverrideDiscoverySignalSource` applies configurable positive thresholds to
      `governance.override_resolved` audit records and emits only inert
      `DiscoverySignalKind.OVERRIDE` evidence.

## Related docs

| To learn about | Read |
|----------------|------|
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/rules-and-detection/rule-governance.md) |
