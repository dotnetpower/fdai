---
title: Rule Governance
---
# Rule Governance

How an administrator **controls** rules - authoring, parameterizing, scoping, enabling, and
exempting them - the way Azure Policy lets an operator manage definitions, assignments, and
exemptions. This is the human-facing control surface over the rule catalog.

It builds on the collected/normalized rules in
[rule-catalog-collection.md](rule-catalog-collection.md) and the deterministic evaluation in
[phase-1-rule-catalog-t0.md](../phases/phase-1-rule-catalog-t0.md). It obeys the app-shape rule
that the **console is read-only and actions flow through PRs**, never UI buttons
([app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md)), and the
shadow-before-enforce and safety invariants in
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md).

> Customer-agnostic: all identifiers, scopes, and values below are synthetic placeholders per
> [generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md).

> **Implementation status**: Effect/scope/assignment/rule-set domain models, strict YAML loaders,
> the directory catalog loader, effect/enforcement transition CI, and T0 runtime assignment
> consumption are implemented. Startup loads one immutable governance catalog, and T0 applies
> resolved scope, exclusions, selectors, effect, enforcement, parameters, and precedence before
> ordinary authorization and safety checks. The catalog now loads strict Azure-shaped exemptions
> and binds them to the safety check, enforces a configured maximum exemption duration, and
> schedules ahead-of-expiry alerts with lifecycle audit evidence via an injectable notifier and
> the standard append-only audit boundary. The catalog also loads strict overrides bound to a
> resource-group-or-narrower `scope://` address, resolves the narrowest covering override on top
> of an assignment's effect, and applies `disabled` / `severity-downgrade` / `parameter-relaxation`
> at T0 - a parameter-relaxation override's keys and bounds are checked against a separately
> reviewed policy file at the catalog-load boundary, failing closed otherwise. Pull-request
> identity checks are implemented; trusted-verifier deployment remains external work.

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

> **Implementation status**: the effect foundation ships in
> [`rule_catalog/schema/effect.py`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/effect.py) - the
> `Effect` (`disabled` / `audit` / `deny` / `remediate`) and `Enforcement`
> (`enforce` / `do-not-enforce`) enums, the strictest-effect precedence
> (`deny` > `remediate` > `audit` > `disabled`) used to resolve conflicting assignments, and
> `validate_effect_transition` enforcing the transition table above (a raise to an enforce effect
> requires the separate promotion approval). The scope selection layer ships alongside in
> [`rule_catalog/schema/scope.py`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/scope.py) - the
> `ScopeLevel` hierarchy, `ScopeSelector` (resource-type / tag / resource-id, AND-of-declared),
> exclusions, `Scope.covers`, and the `most_specific` precedence helper. The `Assignment` artifact
> and the `resolve_assignments` conflict resolver (strictest effect wins; the most-specific scope
> supplies parameters; a specificity tie flags HIL; losers recorded for audit) ship in
> [`rule_catalog/schema/assignment.py`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/assignment.py). The
> `RuleSet` (initiative) grouping - version-pinned members with per-rule `default_effect` and
> `assignment_from_rule_set` - ships in
> [`rule_catalog/schema/rule_set.py`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/rule_set.py). The
> governance model layer (effect / scope / assignment / rule-set) is complete in-memory. The
> assignment catalog-as-code loader also ships:
> [`assignment.schema.json`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/assignment.schema.json) +
> `load_assignment_from_mapping`
> ([`governance_loader.py`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/governance_loader.py)), which
> validates a YAML assignment and builds the domain object, failing at the boundary with every
> schema issue. The rule-set loader (`rule_set.schema.json` + `load_rule_set_from_mapping`) ships
> in the same module. A directory loader
> ([`governance_catalog.py`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/governance_catalog.py),
> `load_governance_catalog`) reads the whole catalog-as-code tree (`assignments/` + `rule-sets/`),
> aggregating every file's issues. An assignment binds either an explicit `target_rule_ids` list or
> a `rule_set` (by id): the loader resolves a rule-set reference against the loaded rule-sets and
> expands it via `assignment_from_rule_set` (carrying the set's per-rule `default_effect` as
> overrides), so "rule-set applied to a scope" works end-to-end; an unresolved reference fails at the
> load boundary. The CI transition gate core also ships:
> `validate_catalog_transition`
> ([`governance_transitions.py`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/governance_transitions.py))
> compares a previous and current `GovernanceCatalog` and rejects any per-rule effective-effect
> transition outside the allowed table - a new assignment/rule is validated from the mandated
> `audit` default, and raising to an enforce effect (`deny` / `remediate`) needs the assignment id
> in `promotions_approved`. The **enforcement** `do-not-enforce` -> `enforce` activation - the go-live
> flip that takes an enforce-tier effect out of shadow - needs the same approval, so a two-step
> `deny(shadow)` then `deny(enforce)` cannot reach production unreviewed. A thin `git`-diff CI script
> ([`check-governance-transitions.py`](../../../scripts/governance/check-governance-transitions.py)) wraps the
> validator: it materializes the catalog at the base ref and the working tree and fails the build on
> a rejected transition. The gate governs **effect + enforcement** transitions; it does not flag a
> scope / blast-radius **widening** (a lower-specificity scope can be offset by a tighter `selector`, so a
> sound widening check needs coverage analysis, not a specificity heuristic) - that is a separate
> future check. Runtime startup now loads this catalog once, and T0 resolves each finding against
> the immutable assignment tuple. Audit/disabled and non-enforcing decisions remain
> observation-only; parameter ties require human review; remediate+enforce still passes through
> execution authorization and the unified safety check.
>
> The shipped catalog-as-code schema now matches the "YAML Shapes" section below: a shared
> `Provenance` value object ([`provenance.py`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/provenance.py)),
> the `kind` ([`governance_kind.py`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/governance_kind.py))
> discriminator plus an artifact `version`, the canonical `scope://`
> [`ScopeRef`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/scope.py) address and the include/exclude
> [`ScopeBinding`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/scope.py) form (unified behind the
> `ScopeMatcher` protocol), and per-rule `parameter_overrides` all ship. A rule-set is bound through
> `rule_set` (or an explicit `target_rule_ids` list) and scope narrowing uses the richer `selector`
> (`resource_types` / `tags` / `resource_ids`).

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

## Administrator Control Flow (GitOps, not buttons)

Administrators control rules exactly like changing Azure Policy - author, parameterize, assign,
exempt - but the change is delivered as a **reviewed PR to catalog-as-code**, so audit, rollback,
and approval come from git for free:

![Administrator Control Flow (GitOps, not buttons). The main stages are administrator, draft change: rule / assignment / exemption, catalog-as-code PR, CI: schema + policy-as-code + shadow eval, review + approval, blocked, separate enforce-promotion approval, merge → catalog, T0 loads at runtime.](../../diagrams/generated/fdai-roadmap-rules-and-detection-rule-governance-01.en.svg)

- The console MAY offer an **authoring UI**, but it only **produces a draft PR** - it never
  executes or mutates the live catalog directly (keeps the console read-only).
- Every governance change (create/modify rule, assignment, exemption, effect change) is a PR with
  an author, reviewer, and audit trail. Raising an effect toward enforce requires the extra
  promotion approval.
- A draft PR is validated **against the current merged catalog**, not the authoring UI's local
  view; a stale draft must rebase, so the live catalog stays the single source of truth and
  concurrent edits cannot silently clobber each other. Approvals happen in git (or ChatOps), never
  as a console button - the console only renders state and emits draft PRs.

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
- The current schema doesn't store an assignment reference or waiver/mitigated category. That
  metadata is follow-up contract work.
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
  the shipped default only logs - no network) and the standard append-only audit boundary, using
  the state store's atomic claim-and-audit primitive so an alert fires **at most once** per
  exemption across replays or replicas. `scripts/governance/exemption-expire.py` runs both passes
  offline (`--alert-lead-days`, `--no-alerts`) for the standalone/no-cloud-dependency workflow.
  Wiring the coordinator into a live scheduled trigger (Container Apps Job / CronJob) and a
  production notifier (ChatOps/email) remain deployment-configured operational work, same as the
  standalone expiry script's real deployment shape.
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

## RBAC (who can do what)

Authoring, approving, assigning, and exempting are **separate permissions** - no self-approval,
mirroring the approval≠execution rule in
[security-and-identity.md](../architecture/security-and-identity.md). These are **logical** governance roles;
they map to a small set of Entra security groups (Reader / Contributor / Approver / Owner +
Break-Glass) in [user-rbac-and-identity.md](../interfaces/user-rbac-and-identity.md). Several logical roles
collapse to the same Entra group - no-self-approval is enforced by CI on PR authorship, not by
group separation, and high-risk approvals (`audit → deny / remediate`, exemption, override)
require a **quorum of two approvers** from `aw-approvers`.

| Logical role | Entra group | May | May not |
|--------------|-------------|-----|---------|
| Rule author | `aw-contributors` | propose rules/rule-sets (draft PR) | approve or assign their own change |
| Approver | `aw-approvers` | review/approve governance PRs | author the change they approve |
| Assignment operator | `aw-contributors` | bind rules to scopes, set parameters/effect (via PR) | approve the enforce promotion alone |
| Enforce-promotion approver | `aw-approvers` (quorum-2) | approve `audit`→`deny`/`remediate` promotions | be the operator who proposed the promotion |
| Exemption approver | `aw-approvers` (quorum-2) | approve time-boxed exemptions | grant a permanent exemption, or approve their own request |
| Override approver | `aw-approvers` (quorum-2) | approve resource-group-scoped overrides (may be permanent) | approve an override outside the resource-group-equivalent scope, or approve their own request |

The deterministic decision core for that table is
`fdai.rule_catalog.schema.governance_review_authority`. It reads the shared role/capability
matrix, counts only approvals that name a non-blank operator object id, review the exact
pull-request head revision, follow that revision in time, carry the capability the change class
requires, and satisfy the phishing-resistant requirement of a high-risk class. Repeated approvals
from one operator count once, and an approval from the author, a recorded co-author, or the
committer blocks the change even when other approvals already reach the quorum. The decision is
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

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Effect, scope, assignment, and rule-set contracts | implemented | `services/core-control-plane/src/fdai/rule_catalog/schema/effect.py`; `scope.py`; `assignment.py`; `rule_set.py`; focused schema tests | Strict models reject invalid scopes, references, effects, and rule-set expansion. |
| Governance catalog and transition CI | implemented | `services/core-control-plane/src/fdai/rule_catalog/schema/governance_catalog.py`; `governance_transitions.py`; `scripts/governance/check-governance-transitions.py`; `.github/workflows/ci.yml` | Directory loading and reviewed effect/enforcement transition checks are wired. |
| Exemptions and expiry | implemented | `services/core-control-plane/src/fdai/rule_catalog/schema/exemption.py`; `exemption_lifecycle.py`; `governance_catalog.py`; `shared/config/models.py` (`RuleGovernanceConfig`); `delivery/catalog_exemption.py`; `delivery/exemption_lifecycle.py`; `shared/providers/exemption_lifecycle.py`; `runtime/control_loop.py`; `scripts/governance/exemption-expire.py`; focused loader, config, lifecycle, coordinator, safety-check, and runtime tests | Startup enforces the configured maximum duration and binds exemptions to the safety check. Scheduled expiry mechanics and ahead-of-expiry alerting are a pure decision core plus an idempotent, audited coordinator; live scheduling and a production notifier remain deployment work. |
| Override artifact and resolution | implemented | `services/core-control-plane/src/fdai/rule_catalog/schema/override.py`; `override.schema.json`; `parameter_relaxation_policy.py`; `governance_loader.py`; `governance_catalog.py`; `rule-catalog/overrides/`; `rule-catalog/override-parameter-bounds.yaml`; `core/control_loop/_execution.py`, `_helpers.py`, `_process.py`, `_audit_helpers.py`, `_boundary.py`, `orchestrator.py`; focused schema, loader, catalog, and pipeline tests | Directory loader, resource-group-or-narrower scope enforcement, no-stacking, distinct-approver, and the reviewed parameter-relaxation-bounds policy all fail closed at catalog load. `resolve_override` + T0 consumption apply `disabled` / `severity-downgrade` / `parameter-relaxation` on top of assignment resolution and audit every resolution. |
| T0 assignment consumption | implemented | `services/core-control-plane/src/fdai/runtime/control_loop.py`; `services/core-control-plane/src/fdai/core/control_loop/_execution.py`; `services/core-control-plane/src/fdai/core/control_loop/_process.py`; focused governance and pipeline tests | One immutable startup catalog supplies scope, exclusions, selectors, effect, enforcement, parameters, and precedence. Enforcing remediation still passes through execution authorization and the unified safety check. |
| Governance pull-request identity checks | implemented | `services/core-control-plane/src/fdai/rule_catalog/schema/governance_review_authority.py`; `services/core-control-plane/src/fdai/delivery/gitops_pr/governance_review.py`; `scripts/governance/check-governance-review-authority.py`; `.github/workflows/ci.yml`; focused authority, metadata, CLI, and workflow tests | CI fetches exact-head GitHub commit, review, and Check Run facts and accepts identity evidence only from the configured trusted verifier App. Missing configuration or attestation blocks governed changes. Deploying that external Entra verifier and retaining blocked-then-cleared evidence remain operational work. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-19 | implemented | Closed the stale detection-and-routing threshold residual against Constitution Article 4. Production T1, quality-gate, and self-consistency values already come from the versioned `config/1.0.0` schema; Heimdall repeat policy comes from bounded Runtime Settings. The remaining three Heimdall security-correlation literals now use bounded startup settings with unchanged defaults. An AST-derived test fixes the exact seven numeric LLM consumers and five Heimdall setting consumers, so a new unbound production threshold fails the gate. | [Issue #219](https://github.com/dotnetpower/fdai/issues/219); focused setting, runtime, framework-layout, ingress, and threshold checks pass 134 cases. | None for production-composed routing and detection threshold bounds. Pure detector constructor defaults remain injectable algorithm defaults, not active composition policy. |
| 2026-08-19 | implemented | Declared the last two unbound adaptive thresholds. `promotion_gate` in the shipped `ontology/action-type` contract now also declares `min_fidelity` and `max_recurrence_rate` as optional ratio bounds, documented as bound declarations that the ActionType promotion evaluator does not read, and `GraphModelPromotionPolicy` derives its accepted range from them instead of the literal `0.0 <= value <= 1.0` it restated. `UNBOUND_ADAPTIVE_THRESHOLDS` is now empty and the focused test asserts that every discovered numeric threshold is bound. Also corrected the frozen scenario count in `test_shadow_eval.py`, which `544e80a72` broke by adding three `sre.*` scenarios without updating it. | `current change`; `tests/core/operational_learning/test_threshold_bounds.py`, `tests/core/assurance_twin`, `tests/contracts`, `tests/rule_catalog`, and `tests/core/measurement` passed 1640 focused cases; task-scoped Ruff, format, and mypy passed; `check-core-imports` and `check-property-semantic-coverage` passed. | Extend the registry beyond the promotion gate to detection and routing thresholds; those are still literals at their use sites. |
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance. | `current change`; current source, CI wiring, and focused tests listed in the scope table. | Wire T0 consumption, complete exemption operations, and implement governed overrides and PR identity checks. |
| 2026-08-17 | in-progress | Added the pure governance pull-request review-authority decision: operator object identity, the capability each change class requires, distinct-approver quorum, phishing-resistant high-risk approvals, revision-bound freshness, and author/co-author/committer self-approval prevention. | `current change`; `services/core-control-plane/src/fdai/rule_catalog/schema/governance_review_authority.py`; `PYTHONPATH="$PWD/services/core-control-plane/src:$PWD/packages/service-contracts/src" .venv/bin/python -m pytest -q --no-cov services/core-control-plane/tests/rule_catalog/schema/test_governance_review_authority.py` passed 16 tests. | Bind the decision to real pull-request review metadata in the governance CI gate and retain one blocked-then-cleared evidence record. |
| 2026-08-17 | in-progress | Hardened the review-authority decision so a head commit time that is not absolute fails closed: freshness is never compared against an ambiguous instant and no approval counts toward the quorum. | `current change`; `PYTHONPATH="$PWD/services/core-control-plane/src:$PWD/packages/service-contracts/src" .venv/bin/python -m pytest -q --no-cov services/core-control-plane/tests/rule_catalog/schema/test_governance_review_authority.py` passed 17 tests. | Bind the decision to real pull-request review metadata in the governance CI gate and retain one blocked-then-cleared evidence record. |
| 2026-08-18 | in-progress | Added `shared/ontology/threshold_bounds.py`, which reads the numeric promotion-gate bounds from the shipped `ontology/action-type` contract and offers one checker. `ShadowDwellThresholds` now derives its floors and its accuracy ceiling from that declaration instead of restating them, and one focused sweep proves every registered adaptive threshold stays inside its declared bound while the pydantic `PromotionGate` model and the JSON contract cannot drift apart. Two `GraphModelPromotionPolicy` rate thresholds have no ontology declaration and are named as an explicit gap rather than left silent. | `current change`; `tests/core/operational_learning` passed 88 focused cases; `tests/core/risk_gate`, `tests/core/measurement`, `tests/core/assurance_twin`, and `tests/rule_catalog` passed 1716 cases; task-scoped Ruff, format, and strict mypy passed. | Declare ontology bounds for `min_fidelity` and `max_recurrence_rate`, then move them out of the unbound set; extend the registry beyond the promotion gate to detection and routing thresholds. |
| 2026-08-23 | in-progress | Added a strict delivery boundary that joins GitHub review state, exact commit, and timestamp to deployment-verified Entra OID, FDAI roles, and phishing-resistant assurance. Latest decisive review state wins, stale revisions remain visible to the pure authority decision, and missing or early attestations fail closed. | `current change`; `delivery/gitops_pr/governance_review.py`; focused metadata and authority tests passed 23 cases. | Bind a deployment-owned identity/assurance provider and real pull-request metadata collector into CI, then retain a blocked-and-cleared evidence record. |
| 2026-08-23 | implemented | Connected the authority decision to GitHub's exact-head PR, commit, review, and Check Run metadata. A configured verifier App must publish the bounded Entra principal bundle in its successful exact-head Check Run; an absent App id, missing or failed check, stale revision, unverified role, weak assurance, self-approval, or insufficient quorum blocks CI. Assignment changes use the stricter enforce-promotion class until transition intent is independently proven. | `current change`; `scripts/governance/check-governance-review-authority.py`; `.github/workflows/ci.yml`; focused governance CLI, bridge, authority, and workflow tests passed 69 cases. | Deploy the trusted Entra verifier GitHub App and retain one blocked-then-cleared governed PR evidence record. |
| 2026-08-23 | in-progress | Completed immutable T0 assignment consumption and integrated strict exemption artifacts into the startup governance catalog and safety check. Hardened duplicate JSON detection, UTC and terminal-state validation, unknown-rule and duplicate-active-scope rejection, exact resource identity, canonical ARM scope parsing, subscription isolation, deterministic fallback, and terminal revocation across both registries. | `current change`; focused governance loader, exemption model/CLI, catalog and fallback registry, runtime composition, safety-check, and T0 pipeline checks passed. Twelve adversarial hardening rounds leave no Medium-or-higher implementation finding in this slice. | Configure maximum exemption duration and alert lead time, then wire scheduled expiry, notifications, and lifecycle audit delivery. Override delivery and trusted-verifier deployment remain separate. |
| 2026-08-29 | implemented | Configured the maximum exemption duration and ahead-of-expiry alert lead time as bounded, cross-validated `AppConfig.rule_governance` settings; the governance catalog loader now fails closed on an over-duration exemption. Added the pure `plan_exemption_lifecycle` decision core, an injectable `ExemptionLifecycleNotifier` contract (safe log-only default), and `ExemptionLifecycleCoordinator`, which delivers an ahead-of-expiry alert at most once per exemption via the state store's atomic claim-and-audit primitive and appends lifecycle audit evidence for both alert and already-due-expiry decisions; `exemption-expire.py` runs the alert pass offline. Implemented the full override artifact end to end: `Override` model + `override.schema.json` + `load_override_from_mapping` + the `<root>/overrides/` directory loader, enforcing resource-group-or-narrower scope, distinct approver, per-mode field invariants, and no-stacking at the catalog-load boundary; a separately reviewed `override-parameter-bounds.yaml` allowlist gates `parameter-relaxation`, failing the catalog load closed on an unlisted key or out-of-bound value (no runtime HIL fallback for that violation). Wired `resolve_override` and `apply_governance_override_to_rule` into T0 so an override applies on top of assignment resolution (`disabled` routes to `governance_observe` even under an enforced `deny`; `severity-downgrade` and `parameter-relaxation` merge into the dispatched rule) and appends a `governance.override_resolved` audit entry shaped for the existing `DiscoverySignalKind.OVERRIDE` discovery-loop input. Fixed a governance-runtime-contracts CI path regex that expected a non-existent `rule-catalog/governance/...` nesting instead of the actual flat `rule-catalog/{assignments,exemptions,overrides}/` convention, which would have silently skipped the review-authority gate on this change's own new `overrides/` content. | `current change`; `services/core-control-plane/tests/config/test_rule_governance_config.py`; `tests/exemption/test_exemption_max_duration.py`; `tests/rule_catalog/schema/test_exemption_lifecycle.py`, `test_override.py`, `test_override_loader.py`, `test_parameter_relaxation_policy.py`, `test_override_parameter_bounds_file.py`, `test_governance_catalog.py`; `tests/providers/test_exemption_lifecycle_notifier.py`; `tests/delivery/test_exemption_lifecycle.py`; `tests/core/test_control_loop_governance_override.py`; `tests/pipeline/test_control_loop_e2e.py` (`test_override_disabled_suppresses_an_enforced_deny_assignment`, `test_override_outside_its_scope_does_not_apply`); `tests/runtime/test_control_loop_parameter_relaxation_policies.py`, `test_thor_execution_port.py`; `tests/integration/scripts/test_exemption_expire.py` all passed; task-scoped Ruff and mypy passed. | Deploy the trusted Entra verifier GitHub App (unrelated, pre-existing external item; see below). Wire the exemption-lifecycle coordinator into a live scheduled trigger and a production notifier, and bind a concrete `DiscoverySignalSource` for `DiscoverySignalKind.OVERRIDE`, remain deployment/composition-root work outside this change's scope. |

### Remaining work

- [x] Load one immutable governance catalog at startup and prove T0 applies resolved effect, enforcement, scope, exclusions, and precedence without bypassing the safety check. Focused pipeline coverage proves remediate+enforce still obeys the unified safety decision.
- [x] Configure and enforce the maximum exemption duration and alert lead time, then schedule expiry and deliver ahead-of-expiry notifications with lifecycle audit evidence. Proven by `plan_exemption_lifecycle` + `ExemptionLifecycleCoordinator` focused tests; wiring the coordinator into a live scheduled trigger (Container Apps Job / CronJob) and a production ChatOps/email notifier is deployment-configured operational work, not a design gap.
- [x] Implement the bounded override schema, loader, precedence resolver, and runtime consumption with resource-group-or-narrower scope checks. Proven by `services/core-control-plane/tests/rule_catalog/schema/test_override.py`, `test_override_loader.py`, `test_governance_catalog.py`, and the `tests/pipeline/test_control_loop_e2e.py` override precedence e2e cases.
- [x] The deterministic pull-request review-authority decision enforces operator identity, the required capability per change class, a distinct-approver quorum, phishing-resistant high-risk approvals, revision-bound approval freshness, and author/co-author/committer self-approval prevention, proven by `services/core-control-plane/tests/rule_catalog/schema/test_governance_review_authority.py`.
- [x] Bind the decision to exact-head pull-request, commit, review, and trusted verifier Check Run metadata in CI. Missing trusted attestation fails closed; focused CLI and workflow tests cover accepted, sub-quorum, self-approval, and untrusted-App cases.
- [ ] Deploy the trusted Entra verifier GitHub App, configure `FDAI_GOVERNANCE_IDENTITY_APP_ID`, and retain one evidence record showing a self-approval or sub-quorum change blocked and the corrected change cleared.

## Open Decisions

- [ ] Adapter that resolves the implemented `scope://...` syntax against the Azure resource
  hierarchy (non-Azure resolution is TBD; see
  [Always-On Rules](../../../.github/copilot-instructions.md#always-on-rules-must)).
- [ ] Whether the authoring UI ships in the console (draft-PR only) in P1 or P3.
- [ ] The concrete parameter **type vocabulary** (int/string/enum/bool/array + range/pattern
      constraints) that CI validates `parameter_overrides` against.
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
- [ ] The signal thresholds the discovery loop uses to flag "over-overridden" rules (number
      of distinct scopes with an active override, dwell time, and shadow-hit rate) before
      proposing a revision/retirement. The evidence source exists
      (`governance.override_resolved` audit entries), but no concrete `DiscoverySignalSource`
      binds them into `DiscoverySignalKind.OVERRIDE` yet - the same composition-root gap every
      discovery signal kind currently has.
