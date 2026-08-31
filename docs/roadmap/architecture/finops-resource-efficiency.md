---
title: FinOps Resource Efficiency and SKU Decisions
---

# FinOps Resource Efficiency and SKU Decisions

This document defines how FDAI analyzes a subscription-wide resource estate, decides whether each
resource is correctly sized, and verifies the outcome of an approved change. It refines the broader
FinOps control loop without creating a second ontology, agent organization, or execution path.

> **Scope:** This design owns subscription analysis, resource-efficiency evidence, service-family
> sizing profiles, resource-level decision cases, savings attribution, and the FDAI Console
> workspace. The complete FinOps agent loop belongs to
> [FinOps Autonomous Operations](finops-autonomous-operations.md). Package distribution and
> activation belong to [Ontology-Grounded FinOps Package Architecture](finops-package-architecture.md).
>
> **Authority boundary:** A provider recommendation, utilization score, ontology relationship, or
> estimated saving can only support or lower a decision. Forseti judges, Var records human approval,
> Thor executes, Heimdall verifies effects, Vidar recovers, and Saga closes the audit record.
>
> **Current state:** Generic cost guards, a right-size `ActionType`, initial cost rules, Njord cost
> advice, and Freyr capacity advice exist. The subscription analysis projection, complete
> service-family profiles, resource-efficiency decision frame, multi-effect settlement, and Console
> workspace described here are not implemented.

## Design at a glance

FDAI analyzes the subscription as one bounded evidence scope, then creates a separate immutable
`DecisionCase` for each resource or explicitly coupled target set. The subscription is never a bulk
execution target. Each case compares no change with safe alternatives, removes options that violate
higher-order objectives, and closes only when authoritative cost and operational observations settle
the expected effects.

```text
subscription evidence scope
  -> resource and relationship coverage
  -> resource or coupled-set DecisionCase
  -> safe ActionOption comparison
  -> judgment, approval when required, and execution
  -> independent operational and cost settlement
  -> subscription-level read-only projection
```

## Analysis scope and action granularity

### Subscription-wide analysis

A subscription analysis snapshot should pin:

- **Identity:** Subscription, resource, resource type, SKU, region, resource group, and provider
  revision.
- **Coverage:** Included resource types, omitted types, permissions, pagination, collection windows,
  and explicit truncation.
- **Relationships:** Service, workload, ownership, containment, dependency, and runtime-call paths
  supported by reviewed links.
- **Objectives:** Effective cost, service, recovery, architecture, environment, and change-window
  constraints at one evidence cutoff.
- **Evidence health:** Source authority, event time, recorded time, freshness, completeness,
  conflicts, and synthetic status.

The aggregate view can report cost, utilization, and opportunity coverage. It does not grant
permission to change every resource in the scope.

### Resource-level decisions

FDAI should create one decision case for one exact resource by default. A coupled target set is
allowed only when changing one member independently would make the result invalid, such as a
scale-set SKU and its instance count.

Every coupled set should record:

- an ordered list of exact resource identities and revisions;
- a content digest for the complete affected set;
- a completeness and truncation receipt;
- a configured member and impact-scope ceiling;
- one causal ordering and locking contract;
- one safe-to-retry idempotency identity; and
- a tested rollback contract that covers every member.

A coupled set that reaches subscription scope, lacks complete membership, or cannot roll back as one
bounded unit is not action-eligible.

## Ontology profile

The capability reuses the shared operational spine:

```text
BusinessService -> Workload -> Resource -> ResourceType
DecisionCase -> ActionOption -> ExpectedEffect -> ActionRun -> ObservedOutcome
```

The FinOps package should add reviewed semantic profiles and property semantics, not a parallel cost
graph. The minimum property families are:

| Family | Required meaning |
|--------|------------------|
| Cost basis | billed, amortized, effective, and list-price cost; currency; pricing unit; commitment coverage |
| Resource configuration | current SKU, capacity, replica count, autoscale bounds, region, and capability flags |
| Utilization | metric identity, unit, P50, P95, P99, maximum, observation window, sample count, and seasonality |
| Service health | latency, error rate, throttling, saturation, headroom, SLO state, and error-budget state |
| Recommendation evidence | provider recommendation id, algorithm or rule revision, lookback, proposed configuration, and confidence |
| Expected economics | projected cost delta, uncertainty range, cost-basis revision, and invalidation conditions |

Azure Advisor recommendations enter a derived evidence lane. They are not a `Verdict`,
`ActionOption`, approval, or provider truth about the current resource. Freyr's sizing advice and
Njord's cost advice also remain advisory inputs. Forseti alone turns complete evidence into an
eligible option and final decision.

For the first release, avoid a second durable `SizingRecommendation` object when `Forecast`,
`Observation`, `Signal`, and `ActionOption` can preserve the required lineage. A future
`CostAllocation` relationship object is appropriate only when allocation percentage, method,
effective interval, and policy revision need their own lifecycle.

## Evidence and authority

| Source | Evidence role | Does not prove |
|--------|---------------|----------------|
| Cost Management export or FOCUS dataset | Rated usage, cost, pricing quantity, and billing-period facts | Resource performance or action authority |
| Azure Resource Graph and bounded ARM reads | Current resource identity, configuration, SKU, location, tags, and provider relationships | Utilization, service health, or successful change |
| Azure Monitor and service metrics | Capacity, performance, throttling, availability, and post-change operational effects | Final billed savings |
| Azure Advisor | Provider-derived optimization advice and corroborating rationale | FDAI judgment, approval, or safe execution |
| Pricing and commitment data | Effective rate, Reservation or Savings Plan coverage, and scenario pricing | Required capacity or business value |
| FDAI ontology context | Service, workload, owner, dependency, objective, and decision lineage | External state or permission |
| Audit and outcome records | Decision, execution, recovery, and verification lineage | Facts not independently observed |

Ordinary analysis reads the current operational graph first. A bounded live read is appropriate only
when required evidence is stale, incomplete, conflicting, unavailable, or explicitly requested.

## Eligibility and agent choreography

The decision order is fixed so a lower cost cannot compensate for a failed operational constraint:

1. Resolve the exact target identity and revision.
2. Prove resource and relationship coverage for the requested scope.
3. Resolve service, workload, environment, owner, and applicable objectives.
4. Validate the `ActionType`, rollback, change window, permissions, and impact limit.
5. Ask Njord for cost-basis and expected-cost advice.
6. Ask Freyr for capacity, saturation, headroom, and sizing advice.
7. Let Forseti remove every option that violates a hard constraint and issue the final decision.
8. Ask Odin to rank only the remaining eligible options when objectives still conflict.
9. Route approved work through Thor, then let Heimdall and Saga close each expected effect.

Detection can continue for an unclassified or unmapped resource, but the result remains
analysis-only. No change option becomes eligible until the service and workload mapping,
environment, applicable objectives, and required relationship coverage are current and complete.
Missing ownership does not make the resource safe to change.

## Evidence recovery and targeted human clarification

FDAI should ask a person only after bounded recovery cannot obtain one decision-critical fact from
the operational graph, an authoritative provider, governed configuration, approved documents, or
the audit history. It should ask one narrow question instead of presenting the complete Cost
Optimization questionnaire.

Each question should identify the missing fact, exact target and revision, why the fact blocks a
decision, eligible respondent role, allowed response shape, effective scope, expiry, and the result
FDAI will reevaluate. The response receipt should preserve the actor, role, conversation and turn,
recorded time, effective interval, and correlation identity.

A human response is an attestation. It can establish organizational intent, ownership, workload
priority, or an approved operating window only inside the respondent's authority and declared
scope. It cannot assert current Azure state, replace an authoritative observation, approve an
action, or raise autonomy. Conflicting observations and attestations remain an explicit evidence
conflict.

Forseti owns the held decision and the fact that clarification is required. Bragi renders the
question and translates the response through the conversational port without judging it. The
operator response reenters the typed pipeline under the operator's identity, and Forseti reevaluates
the same pinned case or creates a new revision when the cutoff changes. If execution later requires
human approval, Var runs that separate approval step. No response, an expired response, an
ineligible respondent, or a conflict leaves the case held without mutation. FDAI never requests a
secret or credential as clarification.

## Deterministic service-family profiles

One utilization percentage is not a portable sizing rule. Each profile is a versioned declarative
asset selected from reviewed resource-type and service bindings and recorded by exact id, version,
and digest in the decision frame. Mimir governs promotion through the existing regression and
observation-mode process.

| Service family | Minimum evidence before a sizing decision |
|----------------|-------------------------------------------|
| VM and VM Scale Sets | CPU, memory, network, disk throughput and IOPS, burst credits, instance count, and SKU capability compatibility |
| Azure SQL and PostgreSQL | CPU, memory, data and log IO, connections, storage growth, throttling, HA, zone, and backup requirements |
| AKS node pools | Requested and used CPU and memory, pending pods, node pressure, disruption budgets, topology, and autoscale bounds |
| App Service and Container Apps | Request concurrency, replica utilization, latency, error rate, cold starts, scale events, and minimum replicas |
| Storage | Capacity, transaction mix, access frequency, redundancy, retrieval, replication, and egress rather than compute utilization |

Profiles should define lookback, aggregation, percentile, minimum samples, seasonal exclusions,
headroom targets, incompatibility checks, and falsifiers. Deployment policy supplies thresholds
inside reviewed semantic bounds.

## Decision classes

The operator-facing projection should classify each admitted resource as exactly one of:

- **Downsize:** A cheaper bounded option satisfies every higher-order objective.
- **Keep:** The current configuration is the best eligible option at the current cutoff.
- **Upsize:** Capacity or service objectives require more capacity or a different SKU.
- **Scale or schedule:** Autoscale, instance count, or operating schedule is a better control than a
  fixed SKU change.
- **Stop or retire:** Complete evidence proves the resource is unused and safe removal is separately
  governed by an appropriate `ActionType`.
- **Review required:** Evidence is incomplete, stale, conflicting, or outside deterministic policy.

These are display classifications. Canonical machine records continue to use their existing object,
decision, and action values.

## Savings attribution and effect settlement

Savings should remain separated by evidence strength:

| Stage | Meaning | Claim boundary |
|-------|---------|----------------|
| Projected saving | Estimated difference between the no-change baseline and one option | Scenario only; not realized |
| Verified run-rate saving | Post-change usage and performance normalized to a comparable demand window | Resource or workload when attribution is supported |
| Amortized commitment-aware run rate | Verified run rate after Reservation, Savings Plan, Hybrid Benefit, and effective-price treatment | Scope covered by the pricing receipt |
| Invoice-allocated settlement | Cost difference confirmed in finalized billing data and allocated by a reviewed rule | Account-period or cohort unless an explicit resource allocation receipt exists |

Every option should declare separate expected effects for cost, headroom, latency or errors, SLO,
dependent workloads, and recoverability. Heimdall closes each effect as `verified`, `failed`,
`censored`, or `unscorable`. A provider API success, lower list price, or observed cost decrease
without comparable demand is not realized savings.

Usage optimization and rate optimization should not double count the same baseline. A commitment
purchase should use the capacity remaining after accepted resource-efficiency decisions.

## Console information architecture

The Console keeps its five stable navigation domains. FinOps appears as the Cost Governance
workspace under Overview, using stable machine id `cost-governance` and the existing
`/verticals/cost-governance` route family. It does not add an agent-specific menu or a sixth Activity
Bar domain.

The navigation entry remains discoverable when the package is disabled or unavailable. Settings >
Runtime policies shows the package state and gives Owners an audited enablement control. Data access
remains a separate purpose- and scope-bound grant. An enabled workspace with no retained
authoritative observations shows an empty evidence state instead of sample cost values.
An explicit authenticated-review policy can provide aggregate-only access for a development
deployment. It preserves browser Entra identity and does not grant package activation or action
authority.

The local authoritative analytics collector combines bounded Azure Consumption Usage Details,
subscription budgets, Azure Advisor Cost recommendations, and supported Azure Monitor metrics into
one immutable snapshot. It stores only pseudonymous resource and recommendation references, exact
source timestamps, completeness, and typed limitations. Advisor records remain provider candidates;
they do not become `DecisionCase`, approval, execution, or verified savings records.

| Workspace page | Primary projection |
|----------------|--------------------|
| Overview | Total cost, analysis coverage, projected opportunity, verified savings, objective risk, and unavailable evidence |
| Resource efficiency | Resource inventory, current SKU, utilization, decision class, evidence health, and proposed option |
| Optimization cases | Read-only correlation of `DecisionCase`, options, final decision, approval, action, and recovery records |
| Outcomes | Expected effects, observed outcomes, verified savings, regressions, rollbacks, and unresolved settlement |

The Optimization cases page never mutates `DecisionCase`. Its live status comes from owned
projections over Saga audit, Thor action, Var approval, Vidar rollback, and Heimdall outcome records.
Every aggregate links to the narrowest filtered evidence route. Missing evidence renders
unavailable with its reason instead of being inferred in the browser.

## Delivery and promotion gates

Deliver the capability in bounded stages:

| Stage | Behavior | Exit evidence |
|-------|----------|---------------|
| A0 analysis | Read-only subscription and resource projection | Exact identity, source coverage, freshness, and negative-case fixtures |
| Observation mode | Generate decision cases and compare options without mutation | F1-F8 competency, service-profile replay, zero policy escapes, and measured recommendation accuracy |
| Non-production human approval | Execute reversible, resource-scoped changes after approval | Seven safeguards, rollback drill, complete terminal audit, and independent settlement |
| Bounded enforcement | Consider only promoted low-risk actions inside standing policy | Live cohort, zero objective regressions, complete settlement, and independently reviewed promotion |

Production rightsizing remains human-approved until a separately reviewed action profile and live
cohort prove a narrower posture. Package availability or enablement never promotes an action.

## External design inputs

This design uses external guidance as reviewed evidence, not as an authority shortcut:

| Source | Design input |
|--------|--------------|
| [FinOps Usage Optimization](https://www.finops.org/framework/capabilities/usage-optimization/) | Separate waste, scheduling, scaling, rightsizing, and workload changes while preserving business requirements. |
| [FinOps Rate Optimization](https://www.finops.org/framework/capabilities/rate-optimization/) | Keep resource-efficiency and commitment savings distinct and avoid double counting. |
| [Azure Advisor VM and VMSS optimization](https://learn.microsoft.com/en-us/azure/advisor/advisor-cost-recommendations) | Use percentile-based CPU, memory, and network evidence, configurable lookback, capability compatibility, and workload posture. |
| [Azure Cost Optimization workbook](https://learn.microsoft.com/en-us/azure/advisor/advisor-workbook-cost-optimization) | Separate overview, usage optimization, and rate optimization while keeping filters and evidence drill-down. |
| [FOCUS specification](https://focus.finops.org/) | Normalize cost and usage data without replacing provider observations or allocation policy. |

Provider thresholds and recommendation algorithms are versioned evidence inputs. They are not
universal ontology bounds, FDAI policy, approval, or execution authority.

## Non-goals

- Purchasing Reservations or Savings Plans, negotiating rates, or managing commitment portfolios.
- Budget enforcement, chargeback, shared-cost allocation, or organization-wide financial policy.
- Creating a FinOps super-agent, private workflow bus, mutable case store, or second ontology graph.
- Treating a subscription as one mutation target.
- Claiming savings from list-price arithmetic, provider acceptance, or incomplete billing data.
- Applying one generic utilization threshold to every Azure service.

## Related docs

| To learn about | Read |
|----------------|------|
| Complete FinOps agent loop and recovery order | [FinOps Autonomous Operations](finops-autonomous-operations.md) |
| Package, provider, and activation boundaries | [Ontology-Grounded FinOps Package Architecture](finops-package-architecture.md) |
| Delivery sequence | [FinOps Package Delivery Plan](../fork-and-sequencing/finops-package-delivery-plan.md) |
| Implementation state for this design | [FinOps Resource Efficiency implementation ledger](../../roadmap-implementation/architecture/finops-resource-efficiency.md) |
| Shared semantic and authority model | [FDAI Operating Ontology](operating-ontology.md) |
| Action safety contracts | [Action Ontology](../decisioning/action-ontology.md) |
| Console shell and read boundary | [Operator Console](../interfaces/operator-console.md) |
