---
title: Fork Example Vertical - New Business Object End-to-End
---

# Fork Example Vertical: New Business Object End-to-End

Concrete walkthrough for a fork that ships a **new business-object
vertical** on top of FDAI - a category of work the shipped
Resilience / Change Safety / Cost Governance verticals do not cover.
Typical examples: an architecture-review proposal flow, a
compliance-attestation record flow, an incident-postmortem workflow.

This document uses a generic **`GovernanceProposal`** example - a
proposal record that names one or more affected resources, is routed
to a Reviewer set based on which resources it touches, and produces
a published decision document once approved. The pattern generalises
to any non-Resource ObjectType lifecycle a fork needs.

**What this walkthrough is**: a stitched-together tour that references
every recipe you need from
[downstream-fork-seam-recipes.md](downstream-fork-seam-recipes.md).
It does not restate the recipe bodies; open both files side-by-side
if you are following along.

**What it is not**: a green-light for shipping a workflow tool.
Section 8 below covers the design decisions that a fork MUST make
before treating a proposal flow as production autonomy.

**Working reference in upstream**: this walkthrough is a full-lifecycle
pattern (a proposal flow with reviewers and a decision). The
**minimum working shipped example** is smaller and single-shot: an
on-demand `resource-group` **change summary** the operator asks for
by name. Its complete set of artifacts is already in the upstream
tree and is exercised by
[`tests/verticals/test_change_summary_example.py`](../../../tests/verticals/test_change_summary_example.py):

| Piece | Where it lives |
|-------|----------------|
| ObjectType | [`rule-catalog/vocabulary/object-types/ChangeSummary.yaml`](../../../rule-catalog/vocabulary/object-types/ChangeSummary.yaml) |
| LinkType | [`rule-catalog/vocabulary/link-types/summarizes.yaml`](../../../rule-catalog/vocabulary/link-types/summarizes.yaml) |
| ActionType | [`rule-catalog/action-types/ops.publish-change-summary.yaml`](../../../rule-catalog/action-types/ops.publish-change-summary.yaml) |
| Rule | [`rule-catalog/catalog/ops.change-summary.yaml`](../../../rule-catalog/catalog/ops.change-summary.yaml) |
| Rego | [`policies/change_summary/publish_change_summary.rego`](../../../policies/change_summary/publish_change_summary.rego) |
| Template | [`rule-catalog/remediation/change_summary/publish_change_summary.tftpl`](../../../rule-catalog/remediation/change_summary/publish_change_summary.tftpl) |

Copy that six-file scaffold, rename to your business object, and you
have a working starting point. The full walkthrough below shows what
grows on top when your workflow needs a lifecycle (reviewers,
approval quorum, decision publication) instead of a single-shot
report.

**Contents**

1. [Overview and design constraints](#1-overview-and-design-constraints)
2. [Ontology (ObjectType + LinkType)](#2-ontology-objecttype--linktype)
3. [Signal source](#3-signal-source)
4. [ActionType catalog](#4-actiontype-catalog)
5. [Rule catalog](#5-rule-catalog)
6. [Delivery adapter (decision publisher)](#6-delivery-adapter-decision-publisher)
7. [Read panel](#7-read-panel)
8. [Wiring in `entry.py`](#8-wiring-in-entrypy)
9. [Shadow-first promotion path](#9-shadow-first-promotion-path)
10. [Anti-patterns](#10-anti-patterns)

## 1. Overview and design constraints

**Goal**: turn "a proposal was opened" into "the right reviewers were
assigned, the decision was recorded, the outcome document was
published" - autonomously where safe, with HIL where not.

**Fit within FDAI's model**:

| FDAI concept | Governance proposal example |
|---|---|
| ObjectType | `GovernanceProposal`, `Reviewer`, `ApprovalDecision` |
| Signal | `governance.proposal.opened`, `governance.review.received` |
| Rule | "assign reviewers based on affected components" |
| ActionType | `governance.assign-reviewers`, `governance.publish-decision` |
| Delivery adapter | Confluence page publisher (or Word / Markdown PR) |
| HIL channel | reviewers cast their decision via Teams Adaptive Card |
| Read panel | recent decisions dashboard |

**Design constraints (fork MUST honour)**:

- **Deterministic-first**: reviewer routing is a T0 rule, not an LLM
  call. Component-to-owner mapping is a lookup table in the fork's
  rule catalog.
- **Shadow-first**: every new ActionType ships `default_mode: shadow`.
  Section 9 covers promotion.
- **Read-only console**: dashboards project state; approvals never
  come from console buttons.
- **One workflow ObjectType per lifecycle**: put the state field
  (`draft` -> `under_review` -> `approved` / `rejected` -> `published`)
  on `GovernanceProposal` itself. Do NOT put it on the shipped
  `Finding` type - the audit log stays append-only and non-mutable.
- **Approver identity is not execution identity**: the reviewer
  approves via Teams; the executor applies the decision. Distinct
  principals, per
  [security-and-identity.md](../architecture/security-and-identity.md).

## 2. Ontology (ObjectType + LinkType)

Recipe reference:
[seam-recipes 5.8a](downstream-fork-seam-recipes.md#58a-ontology-object-type--link-type-additions).

**New ObjectTypes** under `fork/vocabulary/object-types/`:

- `GovernanceProposal` - the workflow object. Carries `state`,
  `affected_components`, `submitted_at`, `decision_ref` (nullable).
  `key: id`.
- `Reviewer` - identity that MAY vote. `key: id`. Populated by the
  fork's IdP sync (Entra group -> Reviewer instance).
- `ApprovalDecision` - immutable record of one reviewer's vote.
  `key: id`. Multiple `ApprovalDecision` instances aggregate into a
  proposal's outcome; the aggregation is a T0 rule, not a mutable
  field on `GovernanceProposal`.

**New LinkTypes** under `fork/vocabulary/link-types/`:

- `affects: GovernanceProposal -> Resource` (M:M). Populated by the
  proposal payload; drives reviewer routing.
- `assigned_reviewer: GovernanceProposal -> Reviewer` (M:M).
  Populated by the assign-reviewers ActionType.
- `decides_on: ApprovalDecision -> GovernanceProposal` (M:1,
  temporal_order: true). Each vote timestamps the moment of decision.

**Anti-pattern**: adding a `state` LinkType (`state_of` etc). State
is a property of `GovernanceProposal`, not an edge. LinkTypes model
relationships between object identities.

## 3. Signal source

A signal is the primitive that enters `event-ingest`. For the
proposal flow, the fork emits two signal types:

- `governance.proposal.opened` - a proposal was submitted (GitHub PR
  labelled `proposal`, a form POST, a Slack workflow). Payload MUST
  include the proposal id, submitter id, and the list of affected
  resource ids.
- `governance.review.received` - a reviewer voted (Teams Adaptive
  Card callback). Payload MUST include the proposal id, reviewer id,
  decision (`approve` / `reject`), and free-text justification.

**How signals reach the control loop**: publish them to your fork's
Kafka topic on the shipped `EventBus` seam. Upstream's
`event-ingest` module normalises the payload against the shipped
`event/1.0.0` schema, so no custom ingest code is needed - the
fork's producer just posts JSON that matches the schema.

**Idempotency**: each signal MUST carry a stable id
(`gov.proposal.<uuid>` / `gov.review.<uuid>`). Shipped deduplication prevents a redelivery from
applying the same side effect twice; it never pretends a failed attempt succeeded.

**Schema note**: the shipped `event/1.0.0` schema is generic (payload
is an open object). No fork edit is required. A fork MAY register
its own JSON Schema fragments for the payload shape inside its
adapter tests, but core does not validate them.

## 4. ActionType catalog

Recipe reference:
[seam-recipes 5.12](downstream-fork-seam-recipes.md#512-actiontype-catalog-additions).

Two ActionTypes cover the workflow. Ship them under
`fork/action-types/`.

### 4.1 `governance.assign-reviewers`

```yaml
# fork/action-types/governance.assign-reviewers.yaml
schema_version: "1.0.0"
name: governance.assign-reviewers
version: "1.0.0"
operation: update
interfaces: [ControlPlane, IdempotentByKey, RequiresInventoryFresh]
rollback_contract: state_forward_only
irreversible: false
default_mode: shadow
promotion_gate:
  min_shadow_days: 14
  min_samples: 30
  min_accuracy: 0.98
  max_policy_escapes: 0
preconditions:
  - kind: graph_fresh_within_seconds
    value: 300
  - kind: link_exists
    link_type: affects
  - kind: no_conflicting_open_action_on_resource
stop_conditions:
  - kind: provider_api_error_streak
    count: 3
  - kind: time_box_exceeded_seconds
    seconds: 300
blast_radius:
  computation: static_enum
  static_bucket: resource
description: Assign the deterministic reviewer set for one governance proposal.
category: governance
trigger_kind:
  kind: rule_violation
execution_path: pr_native
ceiling_by_tier:
  t0: { max_autonomy: enforce_hil, min_role: approver }
  t1: { max_autonomy: shadow_only, min_role: approver }
  t2: { max_autonomy: shadow_only, min_role: approver }
prod_downgrade:
  mode: enforce_hil
  detection_ref: risk-classification/env-detector
```

Rollback is `state_forward_only` because assigning reviewers is non-destructive: a wrong
assignment is corrected by a superseding assignment record. `IdempotentByKey` plus
`no_conflicting_open_action_on_resource` bounds reprocessing of the same proposal.

### 4.2 `governance.publish-decision`

```yaml
# fork/action-types/governance.publish-decision.yaml
schema_version: "1.0.0"
name: governance.publish-decision
version: "1.0.0"
operation: create
interfaces: [ControlPlane, DataPlaneMutating, IdempotentByKey, RequiresInventoryFresh]
rollback_contract: pr_revert  # publisher issues a retraction page
irreversible: false
default_mode: shadow
promotion_gate:
  min_shadow_days: 21
  min_samples: 20
  min_accuracy: 0.99
  max_policy_escapes: 0
preconditions:
  - kind: graph_fresh_within_seconds
    value: 300
  - kind: resource_property_equals
    property: state
    value: approved
  - kind: no_conflicting_open_action_on_resource
stop_conditions:
  - kind: provider_api_error_streak
    count: 3
  - kind: time_box_exceeded_seconds
    seconds: 300
blast_radius:
  computation: static_enum
  static_bucket: resource
description: Publish the approved decision artifact for one governance proposal.
category: governance
trigger_kind:
  kind: rule_violation
execution_path: pr_native
ceiling_by_tier:
  t0: { max_autonomy: enforce_hil, min_role: approver }
  t1: { max_autonomy: shadow_only, min_role: approver }
  t2: { max_autonomy: shadow_only, min_role: approver }
prod_downgrade:
  mode: enforce_hil
  detection_ref: risk-classification/env-detector
```

`rollback_contract: pr_revert` maps to the Confluence publisher's
retract-page path (section 6). A fork that publishes to an
append-only store (Word docs in a locked SharePoint library) uses
`state_forward_only` instead and adds a `stop_conditions` entry that
blocks re-publishing over a superseding decision.

## 5. Rule catalog

Recipe reference:
[seam-recipes 5.8](downstream-fork-seam-recipes.md#58-rule-catalog-additions).

Two rules drive the workflow.

### 5.1 Reviewer routing (T0)

```yaml
# fork/rules/governance.assign-reviewers.yaml
schema_version: "1.0.0"
id: fork-x.governance.assign-reviewers
version: "1.0.0"
source: custom
severity: medium
category: compliance
resource_type: governance.proposal   # see the caveat below
check_logic:
  kind: rego
  reference: policies/fork-x/governance/assign_reviewers.rego
remediation:
  template_ref: remediation/fork-x/governance/assign_reviewers.yaml
  cost_impact_monthly_usd: 0
remediates: governance.assign-reviewers
provenance:
  source_url: https://example.com/governance-baseline
  resolved_ref: "0000000000000000000000000000000000000000"
  content_hash: "sha256:0000000000000000000000000000000000000000000000000000000000000000"
  license: LicenseRef-reference-only
  redistribution: reference-only
  retrieved_at: "2026-07-08T00:00:00Z"
```

**The `resource_type` caveat**: the shipped rule loader validates
`resource_type` against the ResourceType registry (a subtype registry
of the built-in `Resource` ObjectType). Until the upstream loader is
generalised to accept any registered ObjectType, a fork has two
options:

1. **Model proposal subtypes as ResourceType entries** in the fork's
   own vocabulary extension (`fork/vocabulary/resource-types-fork.yaml`
   loaded via a separate `load_resource_type_registry_from_mapping`
   call and concatenated with upstream). The name is misleading -
   these are not cloud resources - but the mechanism works.
2. **Open an upstream issue** to add a `Rule.target_object_type` field.
   Do not fork-patch the rule loader; the cross-reference is the load-
   time typo guard.

Option 1 is what a first pass ships with; option 2 is the cleaner
long-term direction and blocks on an upstream design pass.

### 5.2 Decision publication (T0)

```yaml
# fork/rules/governance.publish-decision.yaml
schema_version: "1.0.0"
id: fork-x.governance.publish-decision
version: "1.0.0"
source: custom
severity: medium
category: compliance
resource_type: governance.proposal
check_logic:
  kind: rego
  reference: policies/fork-x/governance/publish_decision.rego
remediation:
  template_ref: remediation/fork-x/governance/publish_decision.yaml
  cost_impact_monthly_usd: 0
remediates: governance.publish-decision
provenance:
  source_url: https://example.com/governance-baseline
  resolved_ref: "0000000000000000000000000000000000000000"
  content_hash: "sha256:0000000000000000000000000000000000000000000000000000000000000000"
  license: LicenseRef-reference-only
  redistribution: reference-only
  retrieved_at: "2026-07-08T00:00:00Z"
```

Both rules ship policies under `policies/fork-x/governance/`. The
Rego evaluates whether the proposal is in the right state
(`under_review` for reviewer assignment; `approved` with quorum met
for publication) and returns a deterministic verdict. **No LLM call
touches this decision path** - it is pure state-machine logic.

## 6. Delivery adapter (decision publisher)

Recipe reference:
[seam-recipes 5.13](downstream-fork-seam-recipes.md#513-delivery-adapter-custom-publisher).

The `governance.publish-decision` ActionType hands a rendered
decision payload to the fork's publisher. A minimal Confluence page
publisher lives under `fork/adapters/confluence_publisher.py` (see
recipe 5.13 for the code).

**What the payload carries** for a decision publication:

- `title` - `"Governance Decision: <proposal-id>"`
- `body` - templated Markdown / storage-format XML. Fields come from
  the ontology: proposal summary, affected components list, reviewer
  votes, final outcome, justification. **Every field is deterministic
  ontology data** - no LLM narrative in the shipped template.
- `diff` - unused for a document publisher; upstream tolerates
  an empty diff on the `RemediationPr` payload.
- `labels` - `("governance", "decision", proposal.state)`.

**Narrative fields (optional)**: if the fork wants an LLM-generated
executive summary, it MUST route the generation through the shipped
quality gate (5.7) and abstain-on-ungrounded rule. A summary that
cannot cite the ontology fields it is summarising is dropped, and
the page publishes without a summary. Do NOT let the LLM write a
verdict; the verdict is deterministic.

## 7. Read panel

Recipe reference:
[seam-recipes 5.14](downstream-fork-seam-recipes.md#514-console-readpanel-additions).

A `GovernanceDecisionsPanel` at `/panels/governance/decisions` lists
the last N proposals with:

- proposal id + submitted-at
- reviewer set (from `assigned_reviewer` links)
- decisions (from `decides_on` links, ordered by timestamp)
- current state + link to the published decision page (from
  `decision_ref`)

The panel reads from a **projection store** the fork maintains from
the audit log; it does not read from a live Confluence API or from
the running control loop. See recipe 5.14 for the mount + registry
edit.

## 8. Wiring in `entry.py`

Recipe reference:
[seam-recipes 5.15](downstream-fork-seam-recipes.md#515-fork-entry-point-entrypy).

The fork's `entry.py` composes:

1. `default_container_from_env()` for the base seams.
2. Ontology concatenation (ObjectType + LinkType) - recipe 5.8a.
3. ActionType concatenation (upstream + `fork/action-types/`) -
   recipe 5.12.
4. Rule concatenation (upstream + `fork/rules/`) - recipe 5.8.
5. `wire_azure_container` via `_finalize_llm_bindings` - recipe 5.1.
6. Fork publisher (`ConfluencePagePublisher`) - recipe 5.13.
7. Fork HIL channel (`TeamsHilChannel`) - recipe 5.5.
8. Fork read panels (`GovernanceDecisionsPanel`) - recipe 5.14.
9. `_consume` from upstream to run the Kafka event loop.

The entry-point recipe (5.15) provides the skeleton; the fork wires
the seven items above into that skeleton in order.

**Composition-root order matters**: ObjectType MUST load before
LinkType (LinkType cross-references ObjectType), and ActionType
MUST load before Rule (Rule cross-references ActionType via
`remediates`). Recipe 5.15's skeleton respects this order.

## 9. Shadow-first promotion path

Both fork ActionTypes ship `default_mode: shadow`. Promotion to
enforce is a **separate PR** that flips one field, gated on the
`promotion_gate` block being green.

**Concrete gate for `governance.assign-reviewers`**:

- 14 shadow days observed.
- At least 30 proposals routed through the rule.
- Reviewer set produced by the rule matches an operator-selected
  reviewer set in >= 98% of cases.
- Zero policy-violation escapes (a proposal where the shadow rule
  would have assigned reviewers who lack the required scope).

**How to measure**: the shipped audit log records every shadow-mode
verdict alongside its would-be action. A fork's measurement job
(cron, Container App Jobs, or a manual notebook the first few times)
runs a comparison query at the end of each shadow window. Green
across all four criteria -> a separate PR flips `default_mode: enforce`
and is reviewed against the shadow evidence.

**Regression demote**: after enforcement, if the fork's KPI dashboard
shows the rule's precision dropping below the promotion floor, the
demote path is a same-shape PR that flips the mode back to `shadow`.
There is no auto-demote today; the fork's on-call reads the
regression alert and files the PR.

## 10. Anti-patterns

- **Skipping recipe 5.8a and shoving the ObjectType into a rule
  parameter dict**. Rules would still fire but the assurance twin,
  the operator console, and any custom delivery adapter cannot
  dispatch on the object. Ontology-first is the whole point.
- **Making `GovernanceProposal.state` an audit-log field**. The
  audit log is append-only; state transitions live on the object,
  and transitions are themselves emitted as signals that produce
  their own audit rows.
- **Reviewer routing via T2 (LLM)**. Any T2 call here is a red flag -
  component-to-owner mapping is deterministic table lookup, not
  reasoning. If the reviewer set is genuinely ambiguous, the correct
  outcome is HIL (`escalate`), not an LLM guess.
- **Bundling everything in one giant fork PR**. Ship the fork in the
  order of section 8: ontology first, ActionTypes second, rules third,
  delivery fourth, panels fifth, entry point last. Each PR carries a
  passing test slice from recipe 5.11.
- **Renaming the fork's script entry to something other than `fdai`**
  and forgetting to update the container CMD. Recipe 5.15 covers this;
  the failure mode is silent: the container image runs upstream's
  `__main__` and none of the fork wiring runs.
- **Auto-promoting an ActionType without measured evidence**. Every
  promotion PR references the shadow-window report; a promotion PR
  without evidence is a policy bypass that the reviewer MUST reject.
