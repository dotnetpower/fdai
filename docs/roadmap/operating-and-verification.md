# Operating and Verification

How to know AIOpsPilot is **alive, correct, and behaving** — from a freshly provisioned
deployment onward. This document is **self-observability**: how the system reports on
itself. It is distinct from
[observability-and-detection.md](observability-and-detection.md), which is what the system
**detects about the environment it watches**. Presentation / dashboard layout is out of scope
for this document.

Complements [deploy-and-onboard.md](deploy-and-onboard.md) (provisioning) and
[startup-and-lifecycle.md](startup-and-lifecycle.md) (bootstrap). Azure focus: non-Azure
providers are TBD (see
[Implementation Focus](../../.github/copilot-instructions.md#implementation-focus-must)).

## Self-Health Signals

Signals a healthy deployment MUST emit continuously. Every signal maps 1:1 to an alert rule
(see [Alert Routing](#alert-routing)).

| Signal | Purpose | Failure mode caught |
|--------|---------|---------------------|
| **Liveness probe** (per container) | container process alive | crash loop |
| **Readiness probe** (per container) | dependencies reachable | boot without Kafka broker / Key Vault reference / DB |
| **Adapter healthcheck** (per provider adapter) | Kafka broker reachable (Event Hubs `:9093`), Key Vault reference resolvable, Diagnostic-Settings forwarders healthy, catalog loaded in OPA, T2 model endpoints reachable | silent dependency drop |
| **Event lag** (ingest to first tier decision) | per-tier latency | ingress backpressure |
| **DLQ depth** (per queue / topic) | dead-letter accumulation | poison message, consumer failure |
| **Cold-start rate + duration** | scale-to-zero warm-up cost | deadline misses (routes to HIL) |
| **Verifier failure rate** | T2 verifier abstain / fail rate | drift in verifier accuracy |
| **Mixed-model disagreement rate** | cross-check disagreement | model degradation |
| **Rollback rate** | actions later reverted | miscalibrated rules or actions |
| **Override rate** | override create / modify per rule | poor-fit rules (feeds the discovery loop) |
| **Discovery loop pass rate** | candidate → quality gate pass % | loop drift |
| **Kill-switch state** | on / off | contained emergency posture |
| **Canary result** | synthetic loop round-trip | silent ingress death |
| **Time since last successful canary** | staleness | monitor of the monitor |

Signals emit via OpenTelemetry to the configured backend
([deployment.md#observability-slos-and-alerting](deployment.md#observability-slos-and-alerting)).

## Synthetic Canary Event

A scale-to-zero, event-driven system has a specific silent failure mode: **no events arrive →
looks healthy**. Mitigation: a periodic canary.

- A **synthetic event** with a known payload is emitted on a fixed cadence from a canary
  service into the same event bus a real event uses.
- The canary event carries a marker so the **risk gate always short-circuits it to a no-op
  audit entry** — it never mutates any resource.
- The **full loop** — `ingest → correlation → tier decision → audit entry` — MUST complete
  within a bounded budget; a failure to complete raises an SLO-burn alert on the
  [operational lane](#alert-routing).
- The canary is **versioned**, **rate-capped**, and its idempotency key is distinguishable
  from a real event's so canary samples cannot corrupt regression measurement or the
  autonomous discovery loop's observe stage.
- The canary MUST be exercised in **kill-switch on** and **kill-switch off** states so the
  kill-switch itself stays proven.

**TBD**: canary cadence, exact payload shape, and round-trip budget.

## Post-Deploy Smoke Tests

Automated tests run against the live deployment after every promotion. A failing smoke test
**aborts the promotion and rolls traffic back**
([deployment.md#release-and-rollback](deployment.md#release-and-rollback)).

1. **Adapter reachability** — Kafka round-trip (Event Hubs `:9093` produce + consume on a
   probe topic), Key Vault reference resolution, DB write + delete on a probe table, T2 model
   endpoint low-cost ping (per model, including cross-check target).
2. **Config load** — the deployed image reports its version, catalog ref, and config hash;
   values match the expected release manifest.
3. **Canary round-trip** — fire one synthetic event, verify the audit entry lands within
   budget.
4. **Shadow decision correctness** — a fixture set of representative events is fed in shadow
   mode; verdicts match golden expectations (regression suite).
5. **Kill-switch check** — toggle kill-switch **on**, verify all actions abstain during the
   window (probing with the canary); toggle **off**, verify normal decisions resume. Both
   states leave audit entries.
6. **HIL dry-run** — a synthetic high-risk finding is routed to the HIL channel, an approver
   approves (in a dry-run harness that does not execute), the audit trail records both hops.

**TBD**: fixture composition, per-step budgets, and the promotion-gate wiring.

## Alert Routing

Two independent lanes, each with an owner and a channel. Concrete channel names / ownership
matrix is fork responsibility. Channel selection, trust tiering, and fallback rules are
defined in [channels-and-notifications.md](channels-and-notifications.md); this section is
the alert-side view of that model.

| Lane | Signal source | Route |
|------|---------------|-------|
| **Operational** | SLO burn, DLQ depth, verifier failure rate, cold-start deadline miss, adapter unhealthy, canary miss, IaC drift, secret near expiry | on-call rotation (paging channel) |
| **HIL** | high-risk finding, enforce-promotion request, override request, exemption-expiry warning, break-glass request | Teams HIL channel |

Rules that apply to every alert:

- Alerts MUST be **actionable**: each alert links to (a) its dashboard panel, (b) its
  runbook, (c) the correlated audit id if applicable.
- **De-duplication**: correlated alerts collapse per the correlation rules in
  [observability-and-detection.md](observability-and-detection.md); an alert storm from one
  root cause is one page, not many.
- **Fallback channel**: if the primary channel (Teams / paging) is unreachable, HIL items
  queue in the state store and alert via a secondary channel; nothing auto-executes on the
  fallback path.

**TBD**: the concrete channel-ownership matrix and the fallback channel selection.

## Audit Investigation Flow

Given a correlation id or audit id, the operator walks a fixed path. Each hop is a **stored
link captured at write time**, not a search — the walk is O(1) lookups.

```mermaid
flowchart LR
    A[Audit id or correlation id] --> B[Event lookup]
    B --> C[Tier decision plus confidence]
    C --> D[Cited rules and their versions]
    D --> E[Risk-gate decision auto or HIL]
    E --> F[Approver identity when HIL]
    F --> G[Action outcome plus idempotency key]
    G --> H[Rollback reference when applicable]
```

The audit record is append-only and hash-chained per
[security-and-identity.md](security-and-identity.md); the same walk works for shadow and
enforce events (mode is recorded on every entry).

## Runbook Set

Every automated action has an operator-facing runbook. Runbooks live in a **fork-local**
`runbooks/` folder (not committed upstream, per
[generic-scope.instructions.md](../../.github/instructions/generic-scope.instructions.md)).
Upstream ships the **runbook template + required sections**; the concrete text is authored
per fork.

| Runbook | Purpose | Trigger |
|---------|---------|---------|
| **Kill-switch drill** | halt all auto-execution, verify all paths abstain | operational incident, scheduled drill |
| **DLQ drain** | inspect, replay, or discard dead-lettered events (with idempotency-key guards) | DLQ depth alert |
| **Drift reconciliation** | reconcile IaC drift via a PR (never silent apply) | scheduled drift alert |
| **Application rollback** | shift traffic back to the previous container revision | SLO burn, error spike, smoke-test fail |
| **Action rollback** | revert a per-action change (git revert, snapshot restore, replica-promotion undo) | rollback request, auto-demotion |
| **DR failover** | fail the control plane to an alternate region from state + backups | region outage |
| **Override withdrawal** | remove an active override, re-enable the underlying rule on that scope | rule revised, risk changed |
| **Catalog rollback** | revert to the previous rule-catalog version | bad rule set promoted |
| **Break-glass** | grant scoped emergency access under audit + auto-expiry | verified emergency |

Every runbook MUST state:

- **Preconditions** (permissions, prerequisite alerts).
- **Exact commands** (or the exact console navigation), copy-pasteable.
- **Verification** (what to check that proves it worked).
- **Rollback of the runbook itself** (undo of the operator step).
- The **audit trail** the runbook leaves.

**TBD**: the runbook template and its required-sections schema.

## Version and Configuration Exposure

The system MUST expose, at any time, machine- and human-readable, without special access:

- Deployed image **digest** and semantic version tag.
- Rule catalog **version tag + content hash**.
- **Config hash** (a stable sum over live runtime configuration; secrets excluded).
- Per-rule **effect + enforcement flag** — "what is currently enforced" for each rule /
  scope.
- Per-scope **override count** (linked to a list view).
- **Autonomous discovery loop state** (enabled / disabled, last cycle timestamp, last cycle
  pass rate).
- **Time since last successful canary** round-trip.
- **Kill-switch state** and **break-glass usage** in the current window.

Content only; presentation / dashboard layout is defined separately.

## Open Decisions

- [ ] Synthetic canary cadence, payload shape, and round-trip budget.
- [ ] Smoke-test suite composition (fixture set, per-step budgets, promotion-gate wiring).
- [ ] Alert channel ownership matrix (fork vs upstream) and the fallback channel selection.
- [ ] Runbook template — required sections, format, and CI check that a runbook is present
      for every automated action.
- [ ] Retention window and query model for the audit investigation flow.
- [ ] Cold-start deadline value (shared with
      [startup-and-lifecycle.md](startup-and-lifecycle.md#cold-start-scale-to-zero-specifics)).
