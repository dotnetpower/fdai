# Phase 1 - Rule Catalog and T0 Deterministic Engine implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Migrated implementation notes

> **Implementation status**: Authored rule, Rego, and remediation seeds; the ActionType catalog;
> T0 engine; OPA evaluator; control-loop orchestration; GitOps draft-PR adapter; Azure inventory
> snapshot/delta primitives; and frozen-scenario replay are implemented. This document's
> "shadow only" language is the phase boundary when P1 first lands, not the current mode of the
> whole runtime. The repository now also contains later-phase promotion, risk/HIL, and
> enforce-capable adapters. Production inventory and GitOps delivery require deployment-specific
> provider and credential bindings.
> Rego evaluation now pins the exact `data.<package>.deny` decision path, OPA version, source and
> normalized AST semantic digests, canonical input digest, and result digest. T0 retains receipts
> for both allow and deny outcomes in the audit hint; denied findings carry the same receipt.

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Migrated legacy status | in-progress | Legacy status detail below | The prior owner did not use the structured ledger shape. |

#### Migrated legacy status detail


### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-24 | in-progress | Migrated the legacy status into the delegated ledger without reconstructing earlier provenance. | current change; preserved owner status from `docs/roadmap/phases/phase-1-rule-catalog-t0.md`. | Replace the legacy summary with bounded evidence-backed scope rows and observable exits. |

### Remaining work

- [ ] Replace the migrated legacy summary with bounded evidence-backed scope rows and observable remaining-work exits.
