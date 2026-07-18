---
title: Exemption Workflow
owner: aw-owners (Owner-tier)
sla: "Approval decision within 1 business day of PR open"
---

# Exemption Workflow

Time-boxed, audited, owner-approved waiver path for a specific rule
assignment against a specific scope. Backed by the schema in
[`rule-catalog/schema/exemption.json`](../../src/fdai/rule_catalog/schema/exemption.schema.json)
and a CI validator that runs on every PR that touches
`rule-catalog/exemptions/`.

## When to use an exemption

An exemption suppresses **enforce** for a specific rule against a specific
scope. It is the right tool when *all* of the following hold:

- The rule is correct in general but wrong for **this** scope.
- The scope is narrowed to a resource group (or narrower).
- There is a **plan** to remove the exemption - an exemption is a stall,
  not a fix.
- The blast radius of leaving the rule off is understood and bounded.

If the rule is wrong in general, retire the rule via the rule-catalog
pipeline instead. If the wrong dimension is auto-vs-HIL, tune
`risk-classification`, not the rule.

## Roles

- **Requester** - any member of the `aw-contributors` Entra group (or
  above) MAY open an exemption PR.
- **Approver** - MUST be an `aw-owners` member. **Approver ≠ Requester**
  - branch protection enforces "author ≠ reviewer", and the exemption
  artifact carries `requested_by` and `approved_by` fields the CI check
  inspects for distinct values.
- **Auditor** - every state transition (active / expired / revoked)
  writes an audit-log entry with the actor principal.

## Procedure

1. **Open a PR** using the `Exemption Request` template.
2. **Fill the artifact** at `rule-catalog/exemptions/<id>.json` according
   to the [schema](../../src/fdai/rule_catalog/schema/exemption.schema.json).
3. **CI runs**:
   - Schema validation (`exemption-check` job).
   - Author-≠-reviewer branch-protection rule (repo settings).
   - `requested_by` ≠ `approved_by` model invariant.
   - `expires_at > created_at` model invariant.
4. **Owner-tier review + merge**. The merge has no side effect on the
   live Azure resources today; enforcement suppression takes effect once
   the catalog pipeline (Phase 2) picks the exemption up.
5. **Auto-expiry**. A scheduled job (`scripts/governance/exemption-expire.py`, moved
   to a Container Apps Job after W4.1) flips each artifact to
   `state=expired` the moment `expires_at` passes, and re-applies the
   underlying rule assignment. The event is audit-logged.

## Time-boxing

- `expires_at` MUST be strictly after `created_at`.
- No hard maximum window is codified here; longer windows MUST be
  justified in the PR body.
- A lookahead notification fires on the default A1 channel 14 days before
  `expires_at` via the `exemption_expiry_lookahead_weekly` route (W5.4 -
  depends on the channels adapter; tracked separately).

## Revocation

An owner MAY revoke an active exemption by:

1. Editing the artifact to `state=revoked`, setting `revoked_at` and
   `revoked_by`.
2. Merging the revocation PR - Owner-tier review, no self-approval.

Revocation flips enforce back on immediately (the moment the catalog
pipeline observes the state change).

## Escalation

- If CI is flapping on a request that plainly satisfies the schema, page
  `aw-owners` on the default A1 channel with the CI log attached.
- If an exemption is denied but the environment is materially at risk,
  escalate to `aw-break-glass` - under Conditional Access, this is a
  short-lived, audited grant, not a bypass.

## References

| Artifact | Path |
|----------|------|
| Design: Human Override | [../../.github/instructions/architecture.instructions.md#human-override](../../.github/instructions/architecture.instructions.md#human-override) |
| Exemption schema | [../../src/fdai/rule_catalog/schema/exemption.schema.json](../../src/fdai/rule_catalog/schema/exemption.schema.json) |
| CI check (`exemption-check` job) | [../../.github/workflows/ci.yml](../../.github/workflows/ci.yml) |
| Expiry CLI | [../../scripts/governance/exemption-expire.py](../../scripts/governance/exemption-expire.py) |
| PR template | [../../.github/PULL_REQUEST_TEMPLATE/exemption.md](../../.github/PULL_REQUEST_TEMPLATE/exemption.md) |
