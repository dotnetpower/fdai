---
title: Ontology Value Realization
---
# Ontology Value Realization

This document defines how FDAI turns ontology-grounded inference into measured operational value. It records a sober assessment of where the ontology and workflow system stand, the decisions that bound the work, and the phases that close the gap between governed safety and demonstrated outcomes. It adds no agent, no authority, and no second decision pipeline.

> **Scope:** Value here means measured operational units: duration, cost with a declared currency, and counts. Revenue attribution, CRM, and customer analytics stay out of scope, matching the [Outcome Assurance](outcome-assurance.md#non-goals) non-goals. Converting units to a business figure is a deployment decision.
>
> **Authority boundary:** Every artifact here is a read model or a gate input. An ontology reading can keep a gate shut and can never grant execution authority. A value claim never approves, promotes, or executes anything.

## Design at a glance

FDAI already grounds entities, relationships, time, and evidence in a typed ontology and governs every action with approval, audit, and effect verification. The remaining gap is demonstrating value: workflows rarely consume ontology reasoning, most inference engines run only in tests, evidence is mostly fixture-based, and no ledger settles a claimed improvement against a baseline. The phases below close that gap in order, and each phase has an observable exit condition.

## Assessment

The assessment compares the repository with the public pattern of ontology-centered operating platforms: objects and links, functions, governed actions with writeback, decision applications, what-if scenarios, and a measured feedback loop. It is a static review of source, catalogs, and ledgers. It ran no live validation.

| Area | Observed state | Assessment |
|------|----------------|------------|
| Ontology structure | 89 ObjectTypes, 127 LinkTypes, 7 interface types, effective-time and provenance on every fact. | Strong |
| Functions | One catalog-declared FunctionType plus about 40 source-derived read FunctionTypes registered by `operational_function_types`. All are read-only evidence queries. No function computes a decision, score, or forecast for a workflow. | Evidence reads are broad; decision functions are absent |
| Causal inference | The catalog declares one causal mechanism. A separate 55-scenario causal, forecast, and impact engine exists, but only its own tests reference it, so no runtime path consumes it. | Capability exists, unwired |
| Business layer | `BusinessService` carries identity, criticality, and ownership. Objectives link to services. | Impact is ordinal, not measured |
| Workflows | 14 catalog workflows, all `shadow`. Triggers are schedule or signal. Step parameters accept only `${event.*}` tokens. A gate can read the `ChangeWindow` and nothing else from the ontology. | The workflow layer does not consume ontology reasoning |
| Action reach | Of 58 ActionTypes, about 10 have a direct executor binding, 23 are PR-native shadow, and 9 have no binding. | Mostly proposals |
| Evidence realism | Competency receipts are `deterministic_fixture`, retrieval evaluation is synthetic, typed selection runs in shadow, and the external benchmark harness is dormant. | No live accuracy claim is supported |
| Value measurement | Cost effect settlement, MTTR, DORA, and cohort claims exist as parts. No workflow-level ledger settles a claimed improvement. | Parts without a closed loop |
| Data reach | Azure Resource Manager and Kubernetes. Customer-system adapters are open work. | Bounds achievable value |

The strength is governance. The weakness is demonstrated inference and value. FDAI should not claim business value until Phase 3 settles a claim from independent observations.

## Decisions

These decisions fix the scope so the phases can proceed without further agreement.

1. **Three value loops.** Resilience (MTTR on the reusable AKS commerce scenario), Cost Governance (realized savings through the existing settlement), and Change Safety (lead time, change failure rate, rollback rate against baseline).
2. **Units, not revenue.** A value claim records seconds, a cost amount with one currency, or a count. The upstream repository holds no monetary conversion rate.
3. **Baseline-relative and conservative.** Baseline and treatment share one scenario-set version, the treatment is observed after the window ends, and the reported value is the conservative bound of the 95% interval.
4. **Independence.** Executor output never counts as evidence. A policy escape blocks any claimed value.
5. **Fixtures stay test-only.** A fixture can prove a contract and never a measured outcome. Measured claims use retained, sanitized replay or live cohorts held in deployment storage.
6. **Bounded adoption.** Promote one measured process at a time, and keep the shadow default until gate evidence exists.

## Phases

### VR0 - Value claim ledger

- Define the typed value claim, cohort, and settlement contract.
- Settle a claim only from complete, independent, scope-matched cohorts above the sample floor.
- Record the claim with the workflow, version, objective, and evidence references.

### VR1 - Ontology-aware workflows

- Add a gate that reads an ontology function reading, using the `ontology-function:<function>` gate reference, and opens only for a complete, fresh, receipted, exact-function result.
- Add decision functions for blast radius, change risk, and cost of delay, each deterministic, read-only, and replayable.
- Grow the catalog of causal mechanisms with refutation reads, and wire the existing engine behind the same evidence rules.
- Bind at least three catalog workflows to ontology function gates in shadow.

### VR2 - Real-data evidence

- Retain sanitized incident cohorts with reviewed labels and a separate holdout.
- Report top-1 and top-3 root-cause accuracy, correct abstention, wrong-action rate, and time to evidence.
- Compare against the Azure SRE Agent through the parity procedure.
- Run a live model only on explicit request.

### VR3 - Close the loop

- Promote one workflow per value loop through the normal gates, with real executor bindings, staging parity, and independent effect verification.
- Settle one value claim per loop from independent observation.
- Feed the gap between expected and observed effect back to operational learning.

### VR4 - Consumption and reach

- Add an operator decision queue that shows recommended action, evidence, uncertainty, expected effect, and the approval control.
- Add deployment, service-catalog, ITSM, and billing adapters behind provider contracts after explicit approval of each non-Azure adapter.
- Publish an onboarding playbook: connect data, state a value claim, baseline, shadow, promote.

## Success measures

| Measure | Starting point | Target at VR3 exit |
|---------|----------------|--------------------|
| Workflows that consume ontology function results | 0 | 3 or more |
| Source-derived decision functions | 0 | 3 or more |
| Wired causal mechanisms | 1 | 8 or more |
| Root-cause accuracy on a retained holdout | none | reported with interval |
| Promoted workflows | 0 | 3 |
| Independently settled value claims | 0 | 1 per loop |
| Policy escapes | 0 | 0 |

## Non-goals

- Revenue, customer, or product analytics.
- A composite value or maturity score.
- Authority from an ontology reading or a value claim.
- Customer data, tenant values, or monetary rates in the upstream repository.

## Related docs

| To learn about | Read |
|----------------|------|
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/architecture/ontology-value-realization.md) |
| Outcome projection and non-goals | [outcome-assurance.md](outcome-assurance.md) |
| Ontology layers and authority | [operating-ontology.md](operating-ontology.md) |
| Workflow delivery waves | [customer-workflow-automation-plan.md](../decisioning/customer-workflow-automation-plan.md) |
| Workflow and control loop | [workflow-control-loop-integration.md](../decisioning/workflow-control-loop-integration.md) |
| Business scenario | [aks-commerce-business-scenario.md](../operations/aks-commerce-business-scenario.md) |
