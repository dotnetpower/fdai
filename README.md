# FDAI

**Forward Deployed Agents for Cloud Ops.** FDAI is an autonomous control plane
that lives inside your cloud - it watches Azure events, resolves the
repeatable ones with rules and policies, and reserves LLM reasoning for the small
ambiguous residual, so most operations run without a human in the loop.

What makes it different: deterministic-first with a 3-tier trust router
(T0 rules -> T1 similarity reuse -> T2 grounded LLM), every autonomous action ships
in observation mode first, and the rule catalog continuously updates itself. Actions are
delivered as fix PRs, so audit and rollback come for free.

## What can you achieve?

FDAI ships three initial verticals under one event-driven core. Other AIOps
domains (posture management, SRE/SLO) fit the same architecture and are future scope.

### Change Safety

Rule-catalog-driven policy gates on every proposed change. Each candidate is
dry-run against policy-as-code (policies expressed as machine-readable rules),
limited to an explicit impact scope, and either auto-merged (low risk) or routed
to human approval (high risk).

Example: an IaC PR introduces a public-egress NSG rule -> safety check flags
high-risk -> human approval card in Teams -> approver clicks approve -> executor
merges the fix pull request and writes the audit entry.

### Resilience

Scheduled disaster-recovery drills, database DR exercises, and impact-scoped
chaos experiments. The scheduler owns cadence; the safety check owns
scope; the audit log owns proof.

Example: a nightly job finds a PITR gap on a critical database -> agent
schedules a paired restore drill in the exercise window -> restore succeeds
against the target RPO/RTO -> audit entry recorded for compliance.

### Cost Governance

Anomaly detection on spend, right-sizing recommendations, and auto-execution
of the low-risk subset (idle disk cleanup, unused public IP release, orphan
NIC removal).

Example: cost-anomaly detector fires on cache-tier over-provisioning ->
T0 rule matches -> two weeks in observation mode prove accuracy -> enforcement
mode is enabled -> a right-size fix pull request ships with a rollback path.

### Rule Catalog That Grows Itself

The catalog stays current on its own. A discovery loop (the pipeline that
proposes new or revised rules) watches upstream sources (WAF, MCSB, CIS,
Advisor, OPA/Gatekeeper, Checkov, tfsec, KICS, Trivy, kube-bench) and
operational signals (approval patterns, observation drift, overrides) and proposes new,
revised, or retired rules through the same quality gate (a set of checks the
model output must pass).

Example: three observation-mode entries in a row show a rule triggering on legitimate
traffic -> discovery loop flags the drift -> a revision PR lands with the
tightened threshold and a fresh regression suite.

## Works across your stack

- **Azure resources**: any resource accessible through Azure Resource Manager
  and its adapters (Container Apps, PostgreSQL Flexible, Event Hubs on the
  Kafka wire protocol, Key Vault via native secret binding).
- **GitOps delivery**: every autonomous action is a fix pull request (GitHub App
  or Azure DevOps). Audit and rollback come from git.
- **ChatOps**: Teams Adaptive Cards for approval requests. Slack, email, webhook,
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
  the lowest sufficient tier. T0 deterministic (rule decision) -> T1
   lightweight reuse (similarity to resolved incidents) -> T2 reasoning
   (frontier LLM + verifier + mixed-model cross-check + policy evidence check).
   T2 output must clear the quality gate before it becomes eligible to
   execute.
3. **Gate and act**: the safety check decides automatic execution (`auto`),
   human approval (`hil`), hold for review (`abstain`), or denial (`deny`).
   Automatically eligible and approved actions become fix pull requests. Every
   terminal path, including rejection, timeout, and review holds, writes an audit entry.

```text
event -> event-ingest -> trust-router -> T0 | T1 | (T2 -> quality-gate)
      -> risk-gate    -> auto | HIL | abstain -> executor -> delivery -> audit
```

## Grows with your environment

- **Day 1**: T0 rules run in observation mode on your events. Every detected issue writes
  an audit entry so you can see what it would have done.
- **Week 1**: observation metrics show which actions clear their promotion gate.
  T1 starts reusing patterns from resolved incidents; T2 stays a small share.
- **Month 1**: promoted actions run autonomously with rollback paths. The
  discovery loop begins proposing catalog updates from your own operating
  signals (approval patterns, observation accuracy drift, overrides).

The longer it runs, the smaller the T2 share and the higher the auto-resolution
rate. All targets require a measured baseline before they can be claimed
([goals-and-metrics.md](docs/roadmap/architecture/goals-and-metrics.md)).

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
| Risk classification (auto vs human approval vs deny) | [docs/roadmap/decisioning/risk-classification.md](docs/roadmap/decisioning/risk-classification.md) |
| Shadow-then-enforce promotion | [docs/user-guide/concepts/shadow-then-enforce.md](docs/user-guide/concepts/shadow-then-enforce.md) |

## License

Licensed under the Business Source License 1.1 (BSL 1.1). Commercial use requires
a separate license - contact the FDAI maintainers. See [LICENSE](LICENSE).
