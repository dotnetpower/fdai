# Phase 3 — Integrated Control Loop (Resilience · Change Safety · Cost Governance)

**Goal**: unify the three initial verticals under one control loop and deliver the
autonomous-operations MVP — the first release that runs Resilience, Change Safety, and Cost
Governance end to end through a single risk-gated loop — including scheduled DR/chaos testing
and cost auto-actions. This phase adds no new tier; it composes the T0/T1/T2 router, quality
gate, and risk gate delivered in P2 (see
[phase-2-quality-and-t1.md](phase-2-quality-and-t1.md)) into one loop, and enforces the safety
invariants and control-loop wiring defined in
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md).

All RPO/RTO, savings, and lead-time figures here are **measured values reported against stated
objectives on a fixed scenario set and measurement window** — never estimates or unbaselined
multipliers (see [goals-and-metrics.md](../goals-and-metrics.md)).

## Deliverables

Each deliverable maps to a section below.

- **Unified control loop** across Resilience, Change Safety, and Cost Governance — one
  `trust-router` → `risk-gate` → `executor` → `audit` path, with per-resource ordering/locking
  and cross-vertical conflict handling ([Unified Control Loop](#unified-control-loop)).
- **DR/Chaos scheduler** with window-based test failover / game days, deep DB-DR handling, and
  measured RPO/RTO reporting ([#dr--chaos--scheduled-periodic-testing](#dr--chaos--scheduled-periodic-testing)).
- **FinOps auto-actions** with risk-gated autonomy delivered as remediation PRs
  ([FinOps](#finops)).
- **Integrated Change Safety** — low-risk auto-merge/reconcile, high-risk to HIL
  ([Change Safety](#change-safety-integrated)).

## Unified Control Loop

- **Single path**: every domain event is normalized at `event-ingest`, routed by the shared
  `trust-router`, and passes the same `risk-gate` before the `executor` acts. Domains differ in
  rules and identity, not in loop structure.
- **Per-vertical identity**: Resilience, Change Safety, and Cost Governance each execute under
  a **separate user-assigned Managed Identity** scoped to its own action whitelist, so blast
  radius is bounded by vertical and no vertical can assume another's identity
  ([security-and-identity.md](../security-and-identity.md)).
- **Ordering and locking**: actions that mutate the same resource are serialized on a
  per-resource key; the `executor` holds the per-resource lock for the whole action window.
  Concurrent mutations on one resource are mutually excluded across domains.
- **Cross-vertical conflict handling**: when two verticals target the same resource in the
  same window (e.g. a cost idle-shutdown vs a DR failover rehearsal, or a change reconcile vs
  a rightsizing PR), the loop resolves by precedence **Resilience safety hold > Change Safety
  > Cost Governance**; the lower-precedence action is deferred and re-evaluated, or escalated
  to HIL if it cannot be safely deferred. Conflicts never resolve by racing.
- **Idempotency**: all P3 actions key off the stable idempotency key; re-delivered events and
  retried actions are no-ops on already-applied state.
- **Audit**: every terminal outcome — auto-apply, HIL approve/reject/timeout, defer, abstain,
  and every scheduled DR run and FinOps action — writes an append-only audit entry with event
  id, domain, tier, decision, identity, mode (shadow/enforce), and rollback reference.
- **Shadow first**: each new P3 action (DR experiment type, FinOps action, cross-domain rule)
  ships in **shadow mode** (judge-and-log, no mutation) and is promoted to enforce
  per-action only after measured validation with zero policy-violation escapes.

## DR / Chaos — Scheduled Periodic Testing

- **Window-based scheduler**: run DR failover and Chaos experiments only inside approved
  maintenance windows (test failover / game days). The scheduler honors **freeze/quiet
  periods** and per-resource **opt-out tags**, caps **concurrent experiments** (a
  blast-radius limit), and notifies operators before and after each run.
- **RPO/RTO reporting**: for each run, report **measured RPO** (data loss at failover) and
  **measured RTO** (wall-clock to restored service) against their stated objectives, as
  median and p90 over runs, on the fixed measurement window
  ([goals-and-metrics.md](../goals-and-metrics.md)). A run whose RPO/RTO breaches objective
  is flagged, not silently averaged away.

### DR Safety Invariants (every experiment)

Each experiment path MUST satisfy all four invariants, or it does not ship
([architecture.instructions.md](../../../.github/instructions/architecture.instructions.md)):

- **Stop-condition**: explicit abort triggers (health-probe failure, error-rate/latency
  threshold, exceeding the run's time box) that auto-halt the experiment.
- **Blast-radius limit**: scope, batch size, and concurrency caps; experiments target a bounded
  resource set, never a whole environment at once.
- **Rollback**: a tested, automatic rollback that restores prior state on stop or on failure;
  rollback is exercised in shadow before enforce.
- **Isolation**: production is never the chaos target — experiments run against non-prod or an
  isolated restored environment (see Deep DB-DR). Chaos on a production resource is denied by
  default and, where unavoidable, requires HIL approval plus explicit isolation.

### Deep DB-DR (stateful — dedicated design)

Stateful services cannot be "killed and revived" like stateless ones, so DB-DR runs on an
isolated copy and never on the live production DB.

- **Replication/backup**: point-in-time restore (PITR / continuous restore), geo-replication
  (active geo-replication / read replica), and periodic backup-restore rehearsal.
- **Test method** (all steps required, in order):
  1. **Restore into an isolated environment** — restore a replica/snapshot into a
     network-isolated environment with no write path back to production; tear the environment
     down after the test.
  2. **Verify integrity deterministically** — a verifier checks row/record counts, cryptographic
     content checksums, and referential/constraint consistency against the source snapshot;
     any mismatch fails the run.
  3. **App-level smoke tests** — run representative read and write operations against the
     restored copy to confirm application-level recoverability.
- **RPO methodology**: continuously measure replication lag (report p50/p95/max) and, in
  forced-failover rehearsals, measure the **actual data loss** at the failover point; compare
  both against the RPO objective on the same window.
- **RTO methodology**: measure **wall-clock from failover trigger to verified restored service**
  (restore + failover + integrity pass + smoke pass); report median and p90 and compare against
  the RTO objective. Large-DB restore RTO is measured, not assumed.
- **Promotion gate**: DB-DR stays in shadow until integrity verification and smoke tests pass on
  the scenario set with zero integrity mismatches.

## FinOps

- **Trigger**: cost events / anomalies (native anomaly detection surfaces candidates into the
  loop).
- **Routing and autonomy**: candidate actions (idle shutdown, rightsizing, spot/autoscale) are
  routed by the shared `trust-router` and gated by the `risk-gate` — **non-prod, low-risk
  actions auto-execute; any production-impacting action goes to HIL**.
- **Delivery**: actions are delivered as **remediation PRs** (GitOps), so audit, review, and
  rollback come from git — not out-of-band API mutations.
- **Guardrails** (required on every FinOps action):
  - respect **exclusion/opt-out tags** and **protect production** resources from automatic
    scale-down or shutdown;
  - honor **minimum-capacity floors** and **dependency checks** so a shutdown cannot strand a
    dependent workload;
  - be **idempotent** and **reversible** (a shut-down resource can be restarted; a rightsizing
    PR can be reverted);
  - carry a **stop-condition** (abort on unexpected impact) and an **audit entry**.
- **Outcome**: unit-cost visibility plus an automated savings loop for low-risk actions;
  reported savings are **measured**, not projected.

## Change Safety (integrated)

- Low-risk changes **auto-merge/reconcile**; high-risk changes go to **HIL**, where the human
  approves, rejects, or lets the request time out (reject and timeout are no-ops that still
  audit). Approval and execution remain distinct principals
  ([security-and-identity.md](../security-and-identity.md)).
- **Change lead time** is reported as a **measured** reduction against the P0 reference agent on
  the same scenario set (median and p90), per [goals-and-metrics.md](../goals-and-metrics.md)
  — no unbaselined "weeks to hours" claim.

## Testability

- Unit-test the `risk-gate` routing for each domain and the cross-domain precedence/deferral
  logic; property-test the invariants "high-risk never auto-executes", "shadow mode never
  mutates", "re-applying an action is a no-op", and "concurrent actions on one resource are
  serialized".
- Every P3 action path has a **shadow-mode test** (judges and logs without mutating) and a
  **rollback test** (rollback restores prior state); DB-DR adds an **integrity-verification
  regression test** on fixture snapshots.
- Fixtures for DR schedules, FinOps candidates, and rule entries are English and secret-free,
  following the normalized rule schema
  ([coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md)).

## Exit Criteria

Each criterion is measurable on the fixed scenario set and measurement window
([goals-and-metrics.md](../goals-and-metrics.md)):

- Autonomous MVP operates across all three verticals with all four safety invariants enforced and
  **zero policy-violation escapes**.
- DR/Chaos runs on schedule within approved windows, reporting measured RPO/RTO (median and p90)
  against objectives, with automatic rollback verified.
- Deep DB-DR completes restore-into-isolated-env with **zero integrity mismatches** and passing
  app-level smoke tests; production DB is never a chaos target.
- FinOps closes an automated savings loop for low-risk actions with measured savings, guardrails
  enforced, and no production resource auto-modified.
- Cross-domain conflicts on shared resources are resolved by precedence/locking with no double
  mutation, and **guard metrics do not regress** vs the P0 baseline.

## Open Questions (each needs an owner)

- Safe failover window and large-DB restore RTO targets — owner: DR/Chaos lead.
- Initial risk-classification policy (auto vs HIL) and cross-domain precedence tuning —
  owner: risk-gate/policy owner.
- Freeze/quiet-period calendar and game-day opt-out governance — owner: operations owner.

## Dependencies

- **P2 must be validated** ([phase-2-quality-and-t1.md](phase-2-quality-and-t1.md)): the LLM
  quality gate (guarding T2), the T1 lightweight tier, and the continuous rule-update pipeline
  must be running and measured in shadow. P3 composes these into one loop and cannot start until
  they are trustworthy.
- P0 baseline exists so P3 RPO/RTO, savings, and lead-time figures compare against a reference.
- Feeds **P4** ([phase-4-scale.md](phase-4-scale.md)): the integrated autonomous MVP is P4's
  starting point for continuous measurement, pattern-library growth, and model tracking on
  the Azure baseline. **Multi-cloud expansion is TBD** (see
  [Implementation Focus](../../../.github/copilot-instructions.md#implementation-focus-must)).
