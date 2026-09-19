# AKS Outbound Connector Implementation

This ledger tracks the [owner design](../../roadmap/architecture/aks-outbound-connector.md).
Design acceptance does not prove runtime integration, deployment, or enforcement readiness.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| C1 metadata contracts | implemented | `cluster_connector.py`, generated schemas, and `test_cluster_connector.py`: 41 tests passed. | Registration, evidence references, and work references are typed; they grant no authority. Artifact schemas, authentication binding, and deployed version negotiation remain open. |
| C2 metadata checkpoint and sender | implemented | `kubernetes_connector.py`: 11 tests passed; `kubernetes_connector_transport.py`: 26 tests passed. | Existing audited StateStore operations are reused. Transport tests use a mock HTTP transport; no production authentication, HTTP ingress, spool, or inventory integration is claimed. |
| C2 outbound observation integration | not-started | Owner design | Requires authenticated ingress, content-safe artifacts, durable buffering, and single-writer promotion. |
| C3 governed operations | not-started | Existing isolated Executor is a reuse candidate, not connector evidence. | Preserve existing approval, audit, lock, recovery, and effect verification. |
| C4 bounded policy configuration analysis | implemented | `kubernetes_connector_policy.py`; 24 focused tests passed; strict mypy passed. | Pod selectors, namespace selectors, expressions, numeric ports, and additive policy unions are analyzed. Named ports, ipBlock/NAT, host networking, incomplete or stale input remain unknown. This is not CNI enforcement evidence. |
| C4 operational policy context | not-started | Owner design | Authenticated full-policy collection, flow binding, label governance, existing-owner detection, and operator integration remain open. |
| C5 restricted enforcement | not-started | Owner design | Separate ActionType, shadow promotion, and independent probes required. |
| C6 operational readiness | not-started | Owner design | No deployment or live private-cluster receipt exists for this connector. |
| Critique and hardening campaign | not-started | User-requested acceptance criteria in owner design | At least ten rounds after implementation and another ten if direct verification finds a defect. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-19 | not-started | Recorded the revised outbound connector design and explicit separation from network segmentation. | `current change`; English/Korean owner design and this ledger. | Implement C1-C6, record at least ten critique rounds, and retain direct verification evidence. |
| 2026-09-19 | implemented | Added the foundation's typed metadata schemas, audited stream checkpoint, bounded HTTPS sender, and read-only policy configuration analyzer. Hardened identity syntax, durable integer bounds, acknowledgment types, identity-error redaction, policy analysis budgets, order-stable policy digests, and race replay validation. | `current change`; the four focused test files listed above passed 102 cases in total. No live network, Azure, deployment, or effect evidence is claimed. | Complete the runtime integrations, deployment packaging and current-identity bindings; then perform the requested full-scope critique and direct verification campaign. |

### Remaining work

- [x] Pass the 41 metadata contract tests, including scope, freshness, strict types, and semantic schema dispatch.
- [ ] Validate content-safe artifact bodies, independently authenticated registration, and exact observed target revisions before any inventory promotion.
- [ ] Prove durable outbound observation through authenticated ingress and the existing inventory writer.
- [ ] Prove guarded task delivery, current authorization, duplicate suppression, and unknown-outcome recovery.
- [ ] Prove policy analysis handles effective allow unions, label drift, ownership conflicts, and incomplete input.
- [ ] Register shadow-only segmentation with tested recovery and independent positive and negative probes.
- [ ] Validate install, upgrade, revocation, removal, and a selected private-cluster readback through the approved deployment path.
- [ ] Record at least ten actual critique rounds with no unresolved Medium-or-higher finding.
- [ ] Run direct verification; repeat at least ten rounds after any discovered defect before repeating verification.

## Evidence limitations and next boundary

The current source changes are a foundation checkpoint, not completion of the requested project.
No runtime composition binds these modules, no HTTP ingress authenticates a workload, no worker
collects and persists an artifact for this transport, and no connector task reaches the existing
Executor. The policy analyzer is callable local code only. Network policy enforcement remains absent.
The design's ten critique entries are design review, not ten post-implementation hardening rounds.

The operator has not selected an AKS subscription, cluster, test namespace, existing policy owner,
or a live change envelope for this work. Those values are needed before live deployment or state
changes. They do not block the remaining local implementation, which is still open above. No old
session's resource identity is implicitly reused as authorization.
