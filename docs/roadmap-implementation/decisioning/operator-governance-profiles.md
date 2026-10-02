# Operator Governance Profiles implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Single-operator production profile selection and audit fields | not-started | Design only: `docs/roadmap/decisioning/operator-governance-profiles.md` Single-operator production profile section | Records the original quorum and an effective quorum of one |
| Single-operator standing authorization | not-started | Design only: Single-operator production profile section and `docs/roadmap/decisioning/escalation-and-standing-authority.md` | The shipped schema still requires two approvals |
| Attributed operator override promotion | not-started | Design only: Attributed operator override promotion section | Adds `promotion_kind` to the promotion registry |
| Policy-administration add-on and Operator API routes | not-started | Design only: Policy administration in FDAI Console section | Requires the `read-only-console` and `enterprise-identity-governance` add-ons |
| Policy revision validation, signing, and activation | not-started | Design only: Validation and activation section | Mimir is the single writer. Core applies hard constraints after operator policy, so no revision raises an outcome past them. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-10-02 | not-started | Adopted the ledger with the accepted ADR-0003 design. No implementation exists. | `current change`; `docs/roadmap/decisioning/operator-governance-profiles.md`, `docs/roadmap/architecture/decisions/0003-hub-managed-lifecycle-and-operator-governance.md`; constitution, design-route, roadmap-tracking, translation, punctuation, and link checks | Every item below |

### Remaining work

- [ ] Add the approval profile to approval policy, and record tests in which the named operator
  satisfies a quorum of two with an effective quorum of one, an unnamed principal is refused, and
  Var and Thor stay distinct.
- [ ] Allow one approval in the standing-authorization schema only under the single-operator
  production profile, and record tests that keep two approvals mandatory in the multi-operator
  profile.
- [ ] Add `promotion_kind` to the promotion registry, and record tests in which an override is
  marked, regression demotion and capability recall take precedence, and a recalled capability
  can't be promoted again.
- [ ] Add the `policy-administration` add-on, the Operator API request route, and Mimir activation,
  and record tests for role, fresh authentication, schema validation, restricted Rego compilation,
  and rejection of a revision that exceeds a Release maximum.
- [ ] Record a never-raising test in which an operator revision that allows a hard-constraint
  violation still ends in denial, because Core applies the constraint after operator policy.
- [ ] Record activation tests in which a new revision applies only to later decisions, an in-flight
  decision keeps its pinned digest, and a relaxing revision waits for quorum in the multi-operator
  profile.
- [ ] Retain one governed receipt in which a single-operator installation approves, executes, and
  independently verifies a promoted action with the reduced quorum visible in the audit.
