# FDAI

**Forward Deployed AI for Cloud Ops.** FDAI is an autonomous control plane
that lives inside your cloud - it watches Azure events, resolves the
repeatable ones with rules and policies, and reserves LLM reasoning for the small
ambiguous residual, so most operations run without a human in the loop.

What makes it different: deterministic-first with a 3-tier trust router
(T0 rules -> T1 similarity reuse -> T2 grounded LLM), every autonomous action ships
in shadow mode first, and the rule catalog continuously updates itself. Actions are
delivered as remediation PRs, so audit and rollback come for free.

## What can you achieve?

FDAI ships three initial verticals under one event-driven core. Other AIOps
domains (posture management, SRE/SLO) fit the same architecture and are future scope.

### Change Safety

Rule-catalog-driven policy gates on every proposed change. Each candidate is
dry-run against policy-as-code (policies expressed as machine-readable rules),
blast-radius scoped (the scope a change can affect), and either auto-merged
(low risk) or routed to human-in-the-loop review (HIL, high risk).

Example: an IaC PR introduces a public-egress NSG rule -> risk gate flags
high-risk -> HIL approval card in Teams -> approver clicks approve -> executor
merges the remediation pull request (remediation PR) and writes the audit
entry.

### Resilience

Scheduled disaster-recovery drills, database DR exercises, and blast-radius
bounded chaos experiments. The scheduler owns cadence; the risk gate owns
scope; the audit log owns proof.

Example: a nightly job finds a PITR gap on a critical database -> agent
schedules a paired restore drill in the exercise window -> restore succeeds
against the target RPO/RTO -> audit entry recorded for compliance.

### Cost Governance

Anomaly detection on spend, right-sizing recommendations, and auto-execution
of the low-risk subset (idle disk cleanup, unused public IP release, orphan
NIC removal).

Example: cost-anomaly detector fires on cache-tier over-provisioning ->
T0 rule matches -> two-week shadow (observe and log without acting) proves
accuracy -> promotion to enforce -> right-size remediation PR ships with a
rollback path.

### Rule Catalog That Grows Itself

The catalog stays current on its own. A discovery loop (the pipeline that
proposes new or revised rules) watches upstream sources (WAF, MCSB, CIS,
Advisor, OPA/Gatekeeper, Checkov, tfsec, KICS, Trivy, kube-bench) and
operational signals (HIL patterns, shadow drift, overrides) and proposes new,
revised, or retired rules through the same quality gate (a set of checks the
model output must pass).

Example: three shadow entries in a row show a rule triggering on legitimate
traffic -> discovery loop flags the drift -> a revision PR lands with the
tightened threshold and a fresh regression suite.

## Works across your stack

- **Azure resources**: any resource accessible through Azure Resource Manager
  and its adapters (Container Apps, PostgreSQL Flexible, Event Hubs on the
  Kafka wire protocol, Key Vault via native secret binding).
- **GitOps delivery**: every autonomous action is a remediation PR (GitHub App
  or Azure DevOps). Audit and rollback come from git.
- **ChatOps**: Teams Adaptive Cards for HIL approvals. Slack, email, webhook,
  pager, and SMS are pluggable channels for send-only categories.
- **Event bus**: Kafka wire protocol on Event Hubs Standard. Native Azure
  signals (Activity Log, Resource events) are forwarded into Kafka topics so
  the core sees Kafka only.
- **CSP-neutral by design**: cloud access sits behind provider adapters
  (OPA for policy-as-code, Terraform for infrastructure-as-code).
  Cloud-provider-neutral (CSP-neutral) is a design principle; Azure is the
  implemented target, and non-Azure providers are TBD, tracked as a preserved
  seam rather than a delivery commitment.

## How it works

1. **Ingest**: events land on the bus. `event-ingest` normalizes and
   deduplicates them and correlates related events into one incident.
2. **Route**: the trust router (picks the tier that decides the event) picks
   the lowest sufficient tier. T0 deterministic (rule verdict) -> T1
   lightweight reuse (similarity to resolved incidents) -> T2 reasoning
   (frontier LLM + verifier + mixed-model cross-check + policy grounding).
   T2 output must clear the quality gate before it becomes eligible to
   execute.
3. **Gate and act**: the risk gate decides auto, HIL (hold for a human),
   abstain (no autonomous action), or deny. Auto and approved-HIL actions
   become remediation PRs. Every terminal path (including reject, timeout,
   and abstain) writes an audit entry.

```text
event -> event-ingest -> trust-router -> T0 | T1 | (T2 -> quality-gate)
      -> risk-gate    -> auto | HIL | abstain -> executor -> delivery -> audit
```

## Grows with your environment

- **Day 1**: T0 rules run in shadow mode on your events. Every finding writes
  an audit entry so you can see what it would have done.
- **Week 1**: shadow metrics show which actions clear their promotion gate.
  T1 starts reusing patterns from resolved incidents; T2 stays a small share.
- **Month 1**: promoted actions run autonomously with rollback paths. The
  discovery loop begins proposing catalog updates from your own operating
  signals (HIL approvals, shadow accuracy drift, overrides).

The longer it runs, the smaller the T2 share and the higher the auto-resolution
rate. All targets require a measured baseline before they can be claimed
([goals-and-metrics.md](docs/roadmap/goals-and-metrics.md)).

## Get started

- **User guide**: [docs/user-guide/get-started.md](docs/user-guide/get-started.md)
- **Detailed roadmap**: [docs/roadmap/README.md](docs/roadmap/README.md)
- **Contributor rules**: [.github/copilot-instructions.md](.github/copilot-instructions.md)

This repository is generic and customer-agnostic. Per-customer customization
lives in a separate fork, wired through the composition root
([generic-scope.instructions.md](.github/instructions/generic-scope.instructions.md)).

## Next steps

| To learn about | Read |
|----------------|------|
| The control loop and 3-tier routing | [architecture.instructions.md](.github/instructions/architecture.instructions.md) |
| Deployment topology (headless core + PR delivery + thin console + ChatOps) | [app-shape.instructions.md](.github/instructions/app-shape.instructions.md) |
| Safety rules on every autonomous action | [coding-conventions.instructions.md](.github/instructions/coding-conventions.instructions.md) |
| The phased delivery plan (P0 -> P4) | [docs/roadmap/README.md](docs/roadmap/README.md) |
| Risk classification (auto vs HIL vs deny) | [docs/roadmap/risk-classification.md](docs/roadmap/risk-classification.md) |
| Shadow-then-enforce promotion | [docs/user-guide/concepts/shadow-then-enforce.md](docs/user-guide/concepts/shadow-then-enforce.md) |
