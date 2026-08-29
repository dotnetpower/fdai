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
| Ontology-grounded 15-agent review loop | in-progress | [Focused owner](../../roadmap/architecture/architecture-review/ontology-agent-loop.md); [delivery ledger](architecture-review/ontology-agent-loop.md) | Shared change, context, planning, impact, agent, and outcome foundations exist, but no complete ARB-specific loop is composed. |
| Evidence attestation and decision authority | in-progress | [Focused owner](../../roadmap/architecture/architecture-review/evidence-and-authority.md); [delivery ledger](architecture-review/evidence-and-authority.md); `core/architecture_review/{readiness,decision_receipt,projection}.py`; focused ARB tests | Provider-backed body attestation and a content-addressed no-execution-authority Decision receipt bind exact evidence and independently recorded approvals. Production readiness is not yet derived from the immutable receipt. |
| Production owner bindings, evidence, and approval | in-progress | `config/architecture-review.yaml` reports `production_approval_status: blocked`, empty binding maps, and open critical or high blockers | Repository tests prove the gate behavior, not a customer production approval or governed runtime result. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-29 | in-progress | Recorded the typed planned-change graph evidence receipt slice, hardened accepted blocker contracts, and aligned the dependency-ordered ARB ledgers. | `current change`; `services/core-control-plane/src/fdai/core/impact_analysis/change_assessment.py`, `services/core-control-plane/src/fdai/core/architecture_review/readiness.py`, focused ARB impact and readiness checks, and the focused ARB ledgers. | Finish exact context sourcing, provider-backed evidence attestation, immutable decision receipts, and the replayable observation-mode vertical slice. |
| 2026-08-29 | in-progress | Completed exact verified-snapshot graph evidence and the reusable provider-backed production evidence attestation boundary. Metadata, manifest status, or a syntactically valid URI cannot create production readiness. | `current change`; operational context and impact wiring from the preceding batch; `core/architecture_review/readiness.py`; focused ARB checks. | Implement immutable decision receipts and the replayable observation-mode agent loop, then bind governed production owners and evidence in a deployment. |
| 2026-08-29 | in-progress | Added the immutable ARB Decision receipt and additive Approval/Decision `1.1.0` ontology fields. Receipt-bound projection rejects tampered identity, unknown evidence, and unrecorded or mismatched approvers before writing. | `current change`; architecture-review receipt and projection modules, ontology declarations, and focused receipt, projection, and catalog checks. | Derive readiness from the receipt and complete the replayable observation-mode agent loop. |
| 2026-08-13 | in-progress | Adopted the implementation ledger, corrected the runtime exposure to the declarative workflow app, and separated reusable ARB implementation from production approval. | Current change: this document pair and the scope evidence above; the focused ARB readiness, projection, view, and report test command passed 19 tests. Earlier provenance was not reconstructed. | Bind production owners and governed evidence, resolve blockers, and record an approved runtime decision. |
| 2026-08-24 | in-progress | Split the canonical packet into a compact index and focused ontology-agent, evidence-authority, and delivery-plan owners without changing runtime authority. | `current change`; owner document set, paired translations, focused ledgers, code map, design route, and documentation checks. | Deliver the observation-mode vertical slice, provider-backed evidence attestation, and receipt-derived readiness tracked by the focused ledgers. |

### Remaining work

- [ ] Populate every required owner and evidence binding in a customer fork, resolve or formally accept every critical or high blocker, and record a passing `python3 scripts/governance/check-arb-readiness.py --require-production-ready` result against unexpired governed evidence.
- [ ] Record a staging `architecture-review` Process that passes the production gate, receives the required independent owner approvals, and persists the signed decision and audit receipt without deploying resources or promoting an ActionType.
- [ ] Complete the first observation-mode vertical slice in the [delivery plan](../../roadmap/architecture/architecture-review/delivery-plan.md#first-vertical-slice) and retain one replayable 15-agent ARB trace.
