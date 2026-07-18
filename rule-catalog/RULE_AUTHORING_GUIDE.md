# Rule Authoring Guide

How to author a new rule for the FDAI catalog. This guide is the
canonical procedure every rule PR MUST follow - hand-authored, generated,
or LLM-proposed. The T0 pipeline runs entirely **LLM-free**: rules produce
verdicts through OPA/Rego evaluation, so a well-authored rule turns a
class of misconfigurations into deterministic, auto-verifiable findings
that never need to reach T2.

For context on how rules fit into the trust router and control loop, see
[docs/roadmap/rules-and-detection/rule-catalog-collection.md](../docs/roadmap/rules-and-detection/rule-catalog-collection.md)
and [docs/roadmap/architecture/llm-strategy.md](../docs/roadmap/architecture/llm-strategy.md).

## What a rule ships

Every rule is a **tuple of four artifacts** on disk. All four MUST land
in the same PR - the loader cross-checks references at load time and
fail-closes if any is missing.

| # | Artifact | Path | Purpose |
|---|----------|------|---------|
| 1 | Rule YAML | `rule-catalog/catalog/<id>.yaml` | Normalized metadata (severity, category, provenance) + references to 2 and 3 |
| 2 | Rego policy | `policies/<dir>/<stem>.rego` | Deterministic predicate that returns `deny` when the resource violates the rule |
| 3 | IaC template | `rule-catalog/remediation/<dir>/<stem>.tftpl` | Terraform patch the executor renders into a shadow PR |
| 4 | (existing) ActionType | `rule-catalog/action-types/<name>.yaml` | Reused from the ontology; the rule's `remediates` field cross-references it |

Optional if you introduce a new ActionType or resource-type: add the
matching declaration files (see [Extending the ontology](#extending-the-ontology)).

## Step-by-step

The steps are ordered so each one produces a validating artifact - a
half-finished rule always fails a specific test, never leaks into runtime.

### 1. Pick an ActionType

- Browse [`rule-catalog/action-types/`](action-types/). Reuse an existing
  ActionType whenever the operation matches (`enable`, `disable`, `tag`,
  `rotate`, `right-size`, `delete-orphan`, `set-tls-policy`, etc.).
- Add a new ActionType only when no existing verb+contract fits. New
  ActionTypes require rollback contract, promotion gate, preconditions,
  stop conditions, and blast radius (see [Extending the ontology](#extending-the-ontology)).

### 2. Pick a resource type

- The `resource_type` field MUST resolve to an id in
  [`rule-catalog/vocabulary/resource-types.yaml`](vocabulary/resource-types.yaml).
- Add a new entry when the target has no CSP-neutral counterpart yet; keep
  the identifier kebab-case, provide `category` and `azure_arm_type`.

### 3. Write the Rego policy

- Package name convention: `fdai.<snake_dir>.<file_stem>` so the
  package path uniquely maps to the file.
- Use `default deny := false` and one or more `deny if { ... }` rules.
- Read observed props from `input.resource.props.<field>`; the T0 engine
  passes the snapshot the inventory adapter returned.
- Read tunables from `input.parameters.<name>` and fall back to a default
  with the `X := v if { v := input.parameters.x } else := <default>` idiom.
- Emit a `deny_reason` string so audit entries and shadow reports can cite
  a machine-readable reason.
- Fail closed: if a property is missing, prefer `deny` over "pass by
  default"; unknown state SHOULD trigger a finding.

Minimum shape:

```rego
# METADATA
# title: <one-line summary>
# description: |
#   <why this rule exists>
# custom:
#   rule_id: <matches the YAML id>
#   severity: high
#   category: security
package fdai.<snake_dir>.<file_stem>

import rego.v1

default deny := false

deny if {
    input.resource.type == "<resource-type>"
    input.resource.props.<flag> != true
}

deny_reason := "<machine_readable_reason>" if deny
```

### 4. Write the IaC (Terraform) template

- `.tftpl` is a Terraform template file, rendered by
  `TemplateRenderer` with the executor's `Action.params` and a stable
  `resource_id`. Anything you interpolate becomes a placeholder like
  `${resource_id}` or `${retention_days}`.
- Render the **target state**, not a mutation - the shadow PR shows the
  desired Terraform stanza the operator merges.
- Do NOT include destructive fallbacks or `terraform destroy`. Removing a
  resource is expressed as a comment stanza saying the PR removes the
  block; the ActionType's `rollback_contract` records how to recover.
- Keep the template CSP-neutral in intent even though the resource type
  is Azure-specific today; a future provider adapter renders the same
  target state in its own IaC.

### 5. Write the rule YAML

- File name MUST equal `<id>.yaml`. Test
  `test_shipped_catalog_rule_ids_match_filenames` enforces this.
- The `id` is globally unique and dot-separated (`<resource-type>.<axis>.<verb>`).
- `remediates` MUST point at an ActionType present in
  [`rule-catalog/action-types/`](action-types/).
- `check_logic.reference` MUST equal the on-disk path of the Rego file,
  starting with `policies/`.
- `remediation.template_ref` MUST equal the on-disk path of the tftpl
  file, starting with `remediation/`.
- `provenance` cites the normative source. For seed rules we use the
  upstream Microsoft Learn / CIS URL; when redistribution is restricted
  set `license: LicenseRef-reference-only` and `redistribution: reference-only`.

Template:

```yaml
schema_version: "1.0.0"
id: <resource-type>.<axis>.<verb>
version: "1.0.0"
source: mcsb            # or waf | aks_baseline | azure_policy | azure_advisor | cis | custom
severity: high          # critical | high | medium | low
category: security      # security | reliability | cost | config_drift | compliance
resource_type: <one of vocabulary/resource-types.yaml>
check_logic:
  kind: rego
  reference: policies/<dir>/<stem>.rego
remediation:
  template_ref: remediation/<dir>/<stem>.tftpl
  cost_impact_monthly_usd: 0.0
remediates: <one of action-types/*.yaml>
parameters:              # optional, threaded into Rego as input.parameters
  min_retention_days: 7
provenance:
  source_url: https://learn.microsoft.com/security/benchmark/azure/...
  resolved_ref: "0000000000000000000000000000000000000000"
  content_hash: "sha256:0000000000000000000000000000000000000000000000000000000000000000"
  license: LicenseRef-reference-only
  redistribution: reference-only
  retrieved_at: "2026-07-06T00:00:00Z"
```

### 6. Validate locally

Run these in order - each catches a different class of drift:

```bash
uv run pytest tests/rule_catalog -q      # schema + cross-reference load
uv run pytest tests/pipeline -q          # end-to-end control loop with OPA
uv run pytest tests/core/tiers -q        # T0 evaluator round-trip
scripts/quality/localization/check-translations.sh            # docs pair invariant (if you touched user docs)
```

A pytest failure with `test_shipped_catalog_loads_and_covers_every_action_type`
usually means an ActionType has no rule pointing at it - either the rule
YAML has a typo in `remediates`, or the ActionType is unused (add ≥1 rule).

## Extending the ontology

### New ActionType

Add `rule-catalog/action-types/<name>.yaml`:

```yaml
schema_version: "1.0.0"
name: remediate.<verb>-<object>
version: "1.0.0"
operation: enable        # from Operation enum
interfaces:
  - ControlPlane
  - IdempotentByKey
  - RequiresInventoryFresh
rollback_contract: state_forward_only   # pr_revert | scripted | pitr | snapshot_restore | state_forward_only
irreversible: false
default_mode: shadow                     # MUST be shadow at introduction
promotion_gate:
  min_shadow_days: 14
  min_samples: 30
  min_accuracy: 0.98
  max_policy_escapes: 0
preconditions:
  - kind: graph_fresh_within_seconds
    value: 300
  - kind: no_conflicting_open_action_on_resource
stop_conditions:
  - kind: provider_api_error_streak
    count: 3
  - kind: time_box_exceeded_seconds
    seconds: 600
blast_radius:
  computation: static_enum
  static_bucket: resource
description: >-
  One paragraph: what the action does, why the contract is what it is,
  and how it reverses.
```

Rules - the loader enforces every ActionType has ≥1 rule pointing at it,
so ship the ActionType and its first rule in the same PR.

### New resource_type

Add a new entry to
[`rule-catalog/vocabulary/resource-types.yaml`](vocabulary/resource-types.yaml)
under the appropriate category, including `azure_arm_type` and
`typical_parents`.

## Ontology & LLM handoff

The rule catalog is **the ontology surface an LLM can consult** when
reasoning about a case that fell through T0. The pieces the LLM reads:

- `rule-catalog/vocabulary/resource-types.yaml` - resource-type ids and
  ARM mappings.
- `rule-catalog/action-types/*.yaml` - operation verbs, rollback contracts,
  preconditions, blast-radius semantics.
- `rule-catalog/catalog/*.yaml` - every rule's metadata (severity,
  category, remediates target, provenance).
- The Rego files themselves - the deterministic ground truth. A rule
  proposal that contradicts an existing rego is a proposal to change the
  rego, not to bypass it.

Guidance for an LLM proposing new rules from a fresh source:

1. **Cite provenance.** Every proposal MUST include a working URL and a
   short excerpt of the normative text; no provenance = the loader rejects
   the rule at load, before any evaluation.
2. **Map to existing vocabulary.** If a new source talks about, say,
   `Microsoft.Storage/storageAccounts`, map it to `object-storage`, not a
   new name.
3. **Prefer an existing ActionType.** New ActionTypes are HIL-reviewed
   because rollback contracts and preconditions are load-bearing safety
   surfaces.
4. **Compose the artifact tuple in one commit.** Half-a-rule (YAML but no
   Rego) fails the loader and blocks CI.
5. **Default to shadow.** The rule's ActionType stays `default_mode:
   shadow` until the promotion gate is measured on the frozen scenario
   set.
6. **Abstain on doubt.** If the source is ambiguous (e.g. severity depends
   on context the source doesn't state), leave the field at its
   conservative default and flag it in the PR - an author reviews it.

## Seed batch reference

The initial 50-rule seed was produced by a one-shot manifest + generator:

- Manifest: [`tools/seed_p1_manifest.yaml`](../tools/seed_p1_manifest.yaml)
- Generator: [`tools/seed_p1_rules.py`](../tools/seed_p1_rules.py)

The generator is not part of the runtime pipeline; it's kept as a
worked example of the artifact shape and as a repeatable regeneration
path if the seeds ever drift. **New rules go through the manual flow
above**, not through the generator - the manifest was a bootstrap
convenience, not the authoring interface.

## Anti-patterns

- **Rule without Rego.** The YAML alone means nothing at runtime.
- **Rego without a rule YAML.** Never dispatched by the T0 engine.
- **Reusing a template across resource types.** Templates are per-rule;
  duplication is acceptable, cross-contamination is not.
- **Bypassing the ActionType.** The dispatch is `rule.remediates -> ActionType`.
  If the operation doesn't fit any existing ActionType, add one - do not
  invent an inline action shape in the rule.
- **Adding a rule in enforce mode.** New ActionTypes MUST ship as
  `default_mode: shadow`; promotion is a separate governance step.
- **Skipping provenance.** A rule without cited provenance is rejected at
  load. The `example.com` placeholder is only for local scratch rules,
  never for shipped catalog entries.

## Governance and update pipeline

Rules are versioned and can be revised or retired through the same
authoring flow - bump `version`, keep the `id`. The continuous update
pipeline (see
[docs/roadmap/rules-and-detection/rule-catalog-collection.md](../docs/roadmap/rules-and-detection/rule-catalog-collection.md))
watches upstream sources, opens shadow PRs, and enforces regressions
before a rule can promote to enforce.
