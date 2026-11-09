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

The assessment compares the repository with the public pattern of ontology-centered operating platforms: objects and links, functions, governed actions with writeback, decision applications, what-if scenarios, and a measured feedback loop. It is a static review of source, catalogs, and ledgers. It ran no live validation. The table records the state before VR1, and the [implementation ledger](../../roadmap-implementation/architecture/ontology-value-realization.md) records what changed since.

| Area | Observed state | Assessment |
|------|----------------|------------|
| Ontology structure | 89 ObjectTypes, 127 LinkTypes, 7 interface types, effective-time and provenance on every fact. | Strong |
| Functions | One catalog-declared FunctionType plus about 40 source-derived read FunctionTypes registered by `operational_function_types`. All are read-only evidence queries. No function computes a decision, score, or forecast for a workflow. | Evidence reads are broad; decision functions are absent |
| Causal inference | The catalog declares 12 causal mechanisms (`causal-mechanisms.yaml`). A separate 55-scenario causal, forecast, and impact engine is bridged through `CatalogCausalGradeBridge`. | Bridged with refutation reads |
| Business layer | `BusinessService` carries identity, criticality, and ownership. Objectives link to services. | Impact is ordinal, not measured |
| Workflows | 16 catalog workflows, all `shadow`. Two workflows (`blast-radius-gated-service-restart`, `change-risk-gated-scale-in`) bind `ontology-function:` gates in addition to `ChangeWindow`. | Initial ontology function gates wired |
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
- Add decision functions for blast radius, change risk, and cost of delay, each deterministic, read-only, and replayable. Cost of delay is a ranking signal with no gate, because a cost threshold is a business decision that FinOps will own.
- Grow the catalog of causal mechanisms with refutation reads, and wire the existing engine behind the same evidence rules.
- Bind at least two catalog workflows to ontology function gates in shadow.
- Bind the decision functions to the runtime ontology graph, the provider-observed change feed, and observed cost through read-only evidence readers. A truncated, stale, synthetic, conflicted, or unobserved source closes the gate, and a reviewed configuration selects thresholds and never evidence.
- Provide ontology-native workflow primitives (`core/workflow/ontology_native.py`: `ObjectSetWorkflowInput`, `ForEachObjectSetRunner`, receipt-bound `${step.<id>.output.<field>}` substitution, `evaluate_ontology_decision_branch`, `OntologyConditionTriggerEvaluator`, and `OntologyOwnershipApprovalResolver`), advanced decision functions and Merkle DAG composition (`core/ontology_platform/advanced_decision_functions.py`: `decision.slo_exhaustion_eta`, `decision.change_collision`, `decision.recovery_feasibility`, `decision.spof_exposure`, `OntologyFunctionDagRunner`), FinOps value modeling (`core/ontology_platform/finops_value_modeling.py`: `CostObservationOntologyProjector`, `decision.budget_burn_risk`, `score_business_service_criticality`, `filter_safe_sizing_recommendations`, `evaluate_unit_economics`), and scenario-branch digital twin simulation (`core/ontology_platform/digital_twin_simulation.py`: `simulate_workflow_on_scenario_branch`, `compare_counterfactual_options`, `build_workflow_topology_preview`, `validate_chaos_spof_recovery_readiness`).
- Connect T2 reasoning to allowlisted decision tools, shadow workflow compilation, live RCA hypothesis filtering, abstention recovery planning, and approver briefings (`core/ontology_platform/aip_agent_integration.py`).

### VR2 - Real-data evidence

- Retain sanitized incident cohorts with reviewed labels and a separate holdout.
- Report top-1 and top-3 root-cause accuracy, correct abstention, wrong-action rate, and time to evidence.
- Compare against the Azure SRE Agent through the parity procedure.
- Run a live model only on explicit request.

### VR3 - Close the loop

- Promote one workflow per value loop through the normal gates, with real executor bindings, staging parity (`verify_action_staging_parity`), Wave 5 scale controls (`WorkflowScaleSafetyController`), and independent effect verification.
- Settle one value claim per loop from independent observation (`PostWindowValueClaimAutoSettler`), and benchmark parity (`evaluate_sre_agent_parity_cohort`).
- Feed the gap between expected and observed effect back to operational learning (`recalibrate_option_utility_from_settlement`).

### VR4 - Consumption and reach

- Add an operator decision queue (`core/decision_case/decision_queue.py`, `core/ontology_platform/enterprise_governance_bridges.py`) that shows recommended action, evidence, uncertainty, expected effect, and the approval control, ordered by the ungated `decision.cost_of_delay` ranking signal, together with Console Decision Inbox (`build_decision_inbox_view_model`) and per-workflow `ValueClaim` drill-down views (`build_workflow_value_claim_drilldowns`).
- Add provider-neutral deployment, service-catalog (`DeploymentAndServiceCatalogBridge`), ITSM change-window, on-call shift, and ticket audit correlation bridges (`EnterpriseGovernanceOntologyBridge`); vendor-specific non-Azure adapters still require explicit per-adapter approval.
- Bind read-only semantic catalog, rule/control, workflow/business-scenario, governance-lineage, and reviewed cloud-reference query functions (`catalog.search_workflows`, `catalog.search_business_scenarios`, `catalog.search_rules_and_controls`, `catalog.resolve_governance_chain`, `catalog.search_cloud_reference` in `core/ontology_platform/catalog_knowledge_queries.py` over `config/cloud-reference-corpus.yaml`) into `build_semantic_query_runtime` so natural-language questions over workflows, atomic rules, WAF/CAF/WARA/MCSB controls, best practices, baselines, probes, and cloud domain concepts (such as AKS network policies) return citation-backed `QueryTable` rows with zero execution authority.
- Publish an onboarding playbook: connect data, state a value claim, baseline, shadow, promote.

## Use-case onboarding playbook

1. **Connect data.** Bind the active inventory snapshot (`Resource`), service catalog (`BusinessService`, `Workload`, `implemented_by`), provider change feed, and `RecoveryPlan` records into the runtime ontology instance graph.
2. **State a value claim.** Declare a `ValueClaimDeclaration` with the workflow reference, objective reference, metric name, unit (`duration_seconds`, `cost_amount` with currency, or `count`), direction, scenario-set version, window bounds, and minimum sample floor.
3. **Establish the baseline.** Collect a complete `CohortRole.BASELINE` cohort on `ObservationLane.INDEPENDENT_OBSERVATION` for the frozen scenario-set version before enabling treatment.
4. **Exercise in shadow.** Run the workflow in `shadow` mode behind the `config/workflow-ontology-gates.yaml` gates (`decision.blast_radius`, `decision.change_risk`), verify causal hypotheses through `CatalogCausalGradeBridge` and `evaluate_disjoint_causal_holdout`, and review prioritized candidates in `DecisionQueueProjection` using the `decision.cost_of_delay` ranking signal.
5. **Promote and settle.** Promote one workflow per loop after the promotion gates pass with zero policy escapes, collect the post-window `CohortRole.TREATMENT` cohort from independent observation, and run `settle_and_publish_value_claims` to record the conservative 95% bound in `StateStoreValueClaimLedger` and Outcome Assurance.

## Success measures

| Measure | Starting point | Target at VR3 exit |
|---------|----------------|--------------------|
| Workflows that consume ontology function results | 0 | 2 or more |
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
