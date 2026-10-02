# Hub-Managed Lifecycle implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Lifecycle Hub service and Hub PostgreSQL | not-started | Design only: `docs/roadmap/deployment/hub-managed-lifecycle.md` Architecture and Hub data model | One implementation serves central Hub cells and Target Hubs |
| Installation enrollment | not-started | Design only: Enrollment and migration section | Entities start unmanaged and become managed after review |
| Lifecycle agent inside the cluster | not-started | Design only: Architecture section | Installed first, independent of Core, Kubernetes rights in FDAI namespaces only |
| Infrastructure agent on the execution host | not-started | Design only: Architecture section | Reuses the existing exact-plan claim, apply, and verification-only recovery stages |
| Lifecycle Plans, constraints, and envelope checks | not-started | Design only: Lifecycle Plans and Constraints sections | Installation agents derive the maximum envelope locally, and a Plan can only narrow it |
| Plan authentication, replay rejection, and key lifecycle | not-started | Design only: Trust boundaries and Lifecycle Plans sections | Audience, key epoch, source-state digest, sequence, and fencing generation |
| Local lifecycle authorization receipt and phase fencing | not-started | Design only: Lifecycle Plans section | The receipt stands in for the operator's invocation in the exact-plan stages |
| Dual-slot self-upgrade | not-started | Design only: Lifecycle Plans section | Covers both installation agents and Target Hubs |
| Reported state, drift, and reconciliation | not-started | Design only: Entities and reported state, and Failure, drift, and reconciliation sections | Agents report sub-state of the Core Entity |
| Commands with expiry | not-started | Design only: Commands and overrides section | No command raises authority |
| Operations-loop exclusion of FDAI-owned resources | not-started | Design only: Separation from the operations loop section | Ownership is proven by signed Foundation receipts and Terraform state identity, not by the `fdai:managed=true` tag |
| Workload rendering outside Terraform | not-started | Design only: Enrollment and migration section | Needs its own migration design |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-10-02 | not-started | Adopted the ledger with the accepted ADR-0003 design. No implementation exists. | `current change`; `docs/roadmap/deployment/hub-managed-lifecycle.md`, `docs/roadmap/architecture/decisions/0003-hub-managed-lifecycle-and-operator-governance.md`; design-route, roadmap-tracking, constitution, translation, punctuation, and link checks | Every item below |

### Remaining work

- [ ] Add a Hub service with its PostgreSQL schema, and record a passing focused test that computes a
  Lifecycle Plan from a channel subscription, version range, configuration revision, and
  constraints with no Azure credential in its environment.
- [ ] Add installation enrollment, and record a test in which an unapproved registration receives
  no Plan and an approved one starts with unmanaged Entities only.
- [ ] Add the lifecycle agent, and record tests that prove it applies only signed Release images,
  refuses a change outside the Plan envelope, and holds Kubernetes rights in FDAI namespaces only.
- [ ] Add the infrastructure agent, and record a test in which the deletion or replacement of an
  existing Azure resource is held for confirmation while an in-envelope change applies through the
  existing exact-plan coordinator.
- [ ] Record constraint tests for maintenance and suppression windows, version ranges, schema
  ranges, artifact availability, override coverage, data residency, and recall.
- [ ] Record Plan tests that reject a stale sequence, a wrong audience, a revoked Hub key, and an
  envelope wider than the locally derived maximum.
- [ ] Record a test in which an automatic apply runs only under a local lifecycle authorization
  receipt bound to the exact plan digest, and a later phase waits for the earlier phase receipt.
- [ ] Record dual-slot self-upgrade tests for both agents and a Target Hub, including rollback to
  the old slot after a failed health check.
- [ ] Record a drift test in which a manual Deployment change produces a reconciliation Plan in the
  next matching window.
- [ ] Record a command test in which a break-glass change is reconciled to the approved revision at
  expiry and an authority-raising command is rejected.
- [ ] Record a risk-gate test that denies an operations-loop action targeting a resource with a
  signed Foundation ownership receipt, and a test in which a manually tagged customer resource
  doesn't become an FDAI-owned Entity.
- [ ] Publish a migration design that moves workload rendering from the Terraform application stage
  to the lifecycle agent, with rollback, before any Hub-managed installation exists.
- [ ] Retain one governed connected-installation receipt and one offline Target Hub receipt that
  show an automatic upgrade, independent readback, and a second zero-change plan.
