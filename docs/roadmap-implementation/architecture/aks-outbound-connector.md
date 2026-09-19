# AKS Outbound Connector Implementation

This ledger tracks the [owner design](../../roadmap/architecture/aks-outbound-connector.md).
Design acceptance does not prove runtime integration, deployment, or enforcement readiness.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| C1 metadata contracts | implemented | `cluster_connector.py`, generated schemas, and `test_cluster_connector.py`: 41 tests passed. | Registration, evidence references, and work references are typed; they grant no authority. Artifact schemas, authentication binding, and deployed version negotiation remain open. |
| C2 metadata checkpoint and sender | implemented | `kubernetes_connector.py`, `kubernetes_connector_transport.py`, and their focused regressions. | The metadata-only endpoint remains separate from complete snapshot admission. |
| C2 complete snapshot transport | implemented | `kubernetes_connector_artifact.py`, `kubernetes_connector_spool.py`, `kubernetes_connector_snapshot.py`, `kubernetes_connector_gateway.py`, and `kubernetes_connector_worker.py`; focused regressions and real loopback mTLS tests. | Validated normalized bytes, owner-only SQLite buffering, atomic Core snapshot/audit persistence, and replay before collection. This is snapshot collection, not Event history. |
| C2 runtime and inventory composition | implemented | `kubernetes_connector_runtime.py`, `kubernetes_connector_cli.py`, `inventory_job_config.py`, `inventory_sync_cli.py`; actual environment-to-enricher test and 264 passing focused/adjacent tests. | Explicit `observe-once` and `serve` entry points; mTLS-only ingress with current protected-file enrollment. One selected connector binding is exclusive with direct collection. |
| C2 local persistence verification | validated | `test_kubernetes_connector_postgres.py` passed against a disposable loopback PostgreSQL 16 instance. | Eight concurrent submissions produced one acceptance; restart readback, audit chain, and forced audit-failure transaction rollback passed. Temporary schema/container removed. This does not validate production migrations or roles. |
| C2 Event history and broader fleet integration | not-started | Owner design | Event cursor/gap transfer, automatic stale-spool recovery, mixed direct/outbound fleet routing, and Entra-authenticated ingress remain open. |
| C3 governed operations | not-started | Existing isolated Executor is a reuse candidate, not connector evidence. | Preserve existing approval, audit, lock, recovery, and effect verification. |
| C4 bounded policy configuration analysis | implemented | `kubernetes_connector_policy.py`; 24 focused tests passed; strict mypy passed. | Pod selectors, namespace selectors, expressions, numeric ports, and additive policy unions are analyzed. Named ports, ipBlock/NAT, host networking, incomplete or stale input remain unknown. This is not CNI enforcement evidence. |
| C4 operational policy context | not-started | Owner design | Authenticated full-policy collection, flow binding, label governance, existing-owner detection, and operator integration remain open. |
| C5 restricted enforcement | not-started | Owner design | Separate ActionType, shadow promotion, and independent probes required. |
| C6 operational readiness | not-started | Owner design | No deployment or live private-cluster receipt exists for this connector. |
| C6 private detection and proposal checkpoint | implemented | `aks_subscription_discovery.py`, `kubernetes_connector_planning.py`, `kubernetes_connector_proposals.py`, `kubernetes_connector_proposal_cli.py`; 9 discovery, 25 selector/schema and 14 proposal/CLI cases passed. | Explicit private facts survive unavailable credential reads. The Inventory Job creates atomic audited proposals; missing constraints remain unknown. |
| C6 proposal persistence mechanics | validated | Extended `test_kubernetes_connector_postgres.py` passed against disposable PostgreSQL 16. | Eight concurrent proposal attempts create one record, replayable readback succeeds, and forced audit failure rolls back updates. This is not deployed database-role evidence. |
| C6 constraint sources and operator presentation | not-started | Owner design | A reader Protocol and server-owned context format exist, but authenticated constraint collectors, reviewed writer, Console/ChatOps delivery, installed-observer suppression and governed installation are not implemented. |
| Critique and hardening campaign | not-started | User-requested acceptance criteria in owner design | At least ten rounds after implementation and another ten if direct verification finds a defect. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-19 | implemented | Added explicit private-AKS discovery, evidence-bound deployment selection, audited deduplicated proposal storage, replayable current reads and no-authority Core CLI commands. Hardened digest serialization, closed candidate states, source ordering, owner retention, I/O expiry and changed-evidence readback. | `current change`; 48 focused discovery/selector/proposal cases passed and the extended real PostgreSQL atomicity check passed. | Bind authenticated constraint collectors/writer and Operator projection, implement installation and the remaining C2-C6 scope, then perform the full requested critique and direct-validation campaign. |
| 2026-09-19 | not-started | Recorded the revised outbound connector design and explicit separation from network segmentation. | `current change`; English/Korean owner design and this ledger. | Implement C1-C6, record at least ten critique rounds, and retain direct verification evidence. |
| 2026-09-19 | implemented | Added the foundation's typed metadata schemas, audited stream checkpoint, bounded HTTPS sender, and read-only policy configuration analyzer. Hardened identity syntax, durable integer bounds, acknowledgment types, identity-error redaction, policy analysis budgets, order-stable policy digests, and race replay validation. | `current change`; the four focused test files listed above passed 102 cases in total. No live network, Azure, deployment, or effect evidence is claimed. | Complete the runtime integrations, deployment packaging and current-identity bindings; then perform the requested full-scope critique and direct verification campaign. |
| 2026-09-19 | implemented | Connected complete content-safe snapshots through persistent local buffering, verified TLS client identity, atomic Core persistence, and the existing Inventory Job relationship verifier. Added role-separated executable composition without a new distribution or execution authority. | `current change`; 264 focused and adjacent tests passed; Ruff and strict mypy passed for 12 source files. Real loopback mTLS and disposable PostgreSQL checks passed. | Complete Event history, governed work, policy context/enforcement and deployment packaging; obtain the selected target before private-cluster validation. |

### Remaining work

- [x] Generate no-authority proposal schemas and prove explicit private detection, deterministic selection, atomic persistence and bounded Core CLI readback with focused tests.
- [ ] Connect authenticated constraint producers and a reviewed writer; demonstrate eligible and denied recommendations from real retained preflight receipts rather than hand-supplied facts.
- [ ] Publish purpose/role-scoped current proposals through the existing Operator boundary, suppress already-satisfied observer setup, and test expiration, revocation, acknowledgement and notification deduplication.
- [x] Pass the 41 metadata contract tests, including scope, freshness, strict types, and semantic schema dispatch.
- [ ] Validate content-safe artifact bodies, independently authenticated registration, and exact observed target revisions before any inventory promotion.
- [x] Prove complete snapshot transfer through certificate-authenticated ingress, persistent replay, and the existing inventory enricher using local synthetic evidence.
- [ ] Bind and validate Event lifecycle history, coverage gaps and operator-controlled expired-stream recovery; retain private-cluster generation readback through the protected deployment path.
- [ ] Prove guarded task delivery, current authorization, duplicate suppression, and unknown-outcome recovery.
- [ ] Prove policy analysis handles effective allow unions, label drift, ownership conflicts, and incomplete input.
- [ ] Register shadow-only segmentation with tested recovery and independent positive and negative probes.
- [ ] Validate install, upgrade, revocation, removal, and a selected private-cluster readback through the approved deployment path.
- [ ] Record at least ten actual critique rounds with no unresolved Medium-or-higher finding.
- [ ] Run direct verification; repeat at least ten rounds after any discovered defect before repeating verification.

## Evidence limitations and next boundary

The complete snapshot path is executable and explicitly selectable, but the requested project is
not complete. Snapshot ingress authenticates the actual mTLS certificate and rechecks a protected
server-owned registration; the worker collects and persists content-safe snapshots. The existing
Inventory Job selects the stored-source adapter only through explicit mutually exclusive settings.
No connector task reaches the Executor. Event history and network policy enforcement remain absent.
The policy analyzer is still callable local code only. No private AKS deployment or operational
readback was performed. The ten design critiques and the observation-slice reviews below do not
complete the requested post-implementation campaign across C1-C6.

The operator has not selected an AKS subscription, cluster, test namespace, existing policy owner,
or a live change envelope for this work. Those values are needed before live deployment or state
changes. They do not block the remaining local implementation, which is still open above. No old
session's resource identity is implicitly reused as authorization.

## Observation-slice review

These are bounded reviews of the connected snapshot path. Each names its inspected boundary and
executable evidence; they are not a substitute for the final full-scope campaign after C3-C6 exist.

| Review | Boundary and finding | Disposition and evidence |
|--------|----------------------|--------------------------|
| O1 | Producer/consumer diagnostic parity. Medium: initial decoder did not match boolean readiness, container field names, and normalized workload counters. | Fixed from actual producer code; real collector roundtrip retains typed diagnostics and excludes command/environment content. |
| O2 | Nested diagnostic validation. Medium: generic scalar acceptance admitted integers as names and booleans as counters. | Fixed required fields, exact counter types, timestamp and enum checks; six malformed nested-record cases reject. |
| O3 | Source identity and namespace isolation. No new confirmed defect. | Artifact tests reject foreign cluster/namespace/UID/kind; exact namespace coverage and UID uniqueness are required. |
| O4 | Transport authentication. No new confirmed defect. | Real TLS tests accept only registered certificate fingerprints; cleartext, forged headers, unknown enrollment and revoked enrollment are denied. |
| O5 | Transfer parsing and bounds. No new confirmed defect. | Duplicate outer JSON and compressed payloads are denied; artifact digest/length mismatch and unsupported fields reject before storage. |
| O6 | Restart and ambiguous acknowledgment. No new confirmed defect. | Real SQLite restart and worker lost-ACK tests replay the same packet without new collection or duplicate audit. |
| O7 | Queue deletion. Medium: a boolean acknowledgment sequence could compare equal to sequence one. | Fixed strict positive-integer validation; regression proves pending data is retained. |
| O8 | Cancellation and capacity. No new confirmed defect. | Cancellation retains the pending packet; count/byte limits reject new data without eviction or sequence advancement. |
| O9 | Current enrollment and local venue. Medium: the new gateway lacked an explicit local-DB venue guard. | Added loopback-only checks including `hostaddr` and service indirection; enrollment reload tests observe revocation and reject duplicate bindings. |
| O10 | Single writer and atomic persistence. No new confirmed source defect. | Actual Inventory Job composition reaches the existing verified-relationship enricher. Real PostgreSQL concurrency and injected audit failure prove one acceptance and transaction rollback. |

Direct validation first found a test-certificate defect: strict OpenSSL required an Authority Key
Identifier. The synthetic chain was corrected without weakening certificate verification, and the
same real-TLS check passed. The initial PostgreSQL attempt used the ordinary local service role,
which correctly refused `CREATE SCHEMA`; validation moved to a disposable isolated database rather
than changing that role. These environment/test findings are not evidence of AKS readiness.

## Proposal-slice review

These checks concern the new read-only recommendation slice, not the final C1-C6 campaign.
Wire serialization initially produced unequal UTC digest encodings; using the same typed serializer
fixed the failing selector tests. Contract review then found contradictory candidate states and
unbounded validity; closed reason sets, full combination coverage and semantic dispatch now reject them.
Persistence review found old source observations could overwrite newer discoveries and expired
contexts could forget ownership. Source-time ordering and retained owner pins now have regressions.
Stored context is replayed before readback; four corruption cases reject. Constraint drift and
expiry during I/O reject rather than displaying a stale recommendation. In-memory contention and
real PostgreSQL contention/audit rollback passed. No installation authority, live source collection,
Console delivery or final full-scope review completion is claimed by these checks.
