# Fork Example Vertical: New Business Object End-to-End implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Shipped `ChangeSummary` reference scaffold | implemented | Six catalog, policy, and indexing artifacts linked by the owner; `services/core-control-plane/tests/verticals/test_change_summary_example.py`; focused checks (`6 passed`) | The upstream reference loads its ObjectType, LinkType, ActionType, rule, Rego policy, and remediation template; retains shadow and rollback invariants; indexes under `resource-group`; fires only for the explicit synthetic request marker. |
| Generic ObjectType rule targeting | not-started | Owner section 5.1 `resource_type` caveat | The upstream rule loader cannot target an arbitrary registered ObjectType. The documented first-pass ResourceType workaround remains available, but the cleaner `Rule.target_object_type` contract requires an upstream design and implementation. |
| `GovernanceProposal` downstream lifecycle walkthrough | not-applicable | `docs/roadmap/fork-and-sequencing/downstream-fork-example-vertical.md` | Apart from the separately tracked generic ObjectType targeting gap, the proposal, reviewer, publication, and read-panel flow is a procedural downstream design example, not an upstream executable capability or authority grant. |
| Downstream adapter, promotion, and operational evidence | not-applicable | `.github/instructions/generic-scope.instructions.md`; owner section 9 | A downstream distribution owns its business-object implementation, principals, deployment bindings, shadow evidence, promotion, rollback drill, and operational receipts. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-24 | not-started | Adopted the delegated ledger; earlier provenance was not reconstructed. | current change; `docs/roadmap/fork-and-sequencing/downstream-fork-example-vertical.md`. | Assess bounded source and test evidence before raising any scope state. |
| 2026-09-12 | in-progress | Replaced the unassessed placeholder with the verified shipped `ChangeSummary` scaffold, retained the upstream generic ObjectType targeting gap, and separated the remaining design-only walkthrough plus downstream-owned operational evidence. | `current change`; focused change-summary example tests (`6 passed`); owner section 5.1 caveat; generic-scope boundary. | Design and implement generic ObjectType rule targeting upstream; downstream distributions retain their own lifecycle implementation and promotion evidence. |

### Remaining work

- [x] Verify the shipped six-artifact `ChangeSummary` scaffold with its focused catalog, policy,
  and indexing checks (`6 passed`), while leaving downstream implementation and promotion outside
  upstream scope.
- [ ] Complete the upstream design for `Rule.target_object_type`, implement loader cross-reference
  validation for arbitrary registered ObjectTypes, and record passing schema and rule-loader tests
  before removing the documented ResourceType workaround.
