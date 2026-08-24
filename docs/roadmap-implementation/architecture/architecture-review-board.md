# Architecture Review Board Packet implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

The reusable ARB contract, fail-closed production gate, workflow, ontology projection, and
read-only workflow app are implemented. Production readiness remains blocked because the upstream
manifest intentionally has no customer owner or evidence bindings and all critical or high
blockers remain open.

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Machine-readable review contract and readiness checker | implemented | `config/architecture-review.yaml`; `core/architecture_review/readiness.py`; `scripts/governance/check-arb-readiness.py`; focused readiness tests | Structural health and production readiness are evaluated separately, and malformed, incomplete, unknown, or expired evidence fails closed. |
| Review workflow, production gate, and ontology projection | implemented | `rule-catalog/workflows/architecture-review.yaml`; `core/architecture_review/projection.py`; `runtime/control_loop.py`; focused projection tests | The control-only workflow records checks, approvals, and decisions without deploying resources or enabling an ActionType. |
| Declarative operator review surface | implemented | `rule-catalog/operator-console/architecture-review.yaml`, `views/architecture-review.yaml`, and `reports/architecture-review-process.yaml`; focused view and report tests | The published read-only workflow app and Process view expose projected review state through catalog-validated routes. |
| Production owner bindings, evidence, and approval | in-progress | `config/architecture-review.yaml` reports `production_approval_status: blocked`, empty binding maps, and open critical or high blockers | Repository tests prove the gate behavior, not a customer production approval or governed runtime result. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-13 | in-progress | Adopted the implementation ledger, corrected the runtime exposure to the declarative workflow app, and separated reusable ARB implementation from production approval. | Current change: this document pair and the scope evidence above; the focused ARB readiness, projection, view, and report test command passed 19 tests. Earlier provenance was not reconstructed. | Bind production owners and governed evidence, resolve blockers, and record an approved runtime decision. |

### Remaining work

- [ ] Populate every required owner and evidence binding in a customer fork, resolve or formally accept every critical or high blocker, and record a passing `python3 scripts/governance/check-arb-readiness.py --require-production-ready` result against unexpired governed evidence.
- [ ] Record a staging `architecture-review` Process that passes the production gate, receives the required independent owner approvals, and persists the signed decision and audit receipt without deploying resources or promoting an ActionType.
