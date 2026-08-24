# Agent Pantheon Implementation Plan implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| W0-W1 documentation, ontology, and framework scaffolding | implemented | [`test_framework_layout.py`](../../../services/core-control-plane/tests/agents/test_framework_layout.py), [`test_pantheon_doc_parity.py`](../../../services/core-control-plane/tests/agents/test_pantheon_doc_parity.py), [`test_topics.py`](../../../services/core-control-plane/tests/agents/test_topics.py) | The fixed registry, package boundary, documentation parity, and typed-topic foundation are executable and checked. |
| W2-W6 governance, pipeline, interface, specialist, handoff, and security mechanics | implemented | [`test_runtime_chain.py`](../../../services/core-control-plane/tests/agents/test_runtime_chain.py), [`test_thor_durable.py`](../../../services/core-control-plane/tests/agents/test_thor_durable.py), [`test_conversational_port.py`](../../../services/core-control-plane/tests/agents/test_conversational_port.py), [`test_prompt_deliberation.py`](../../../services/core-control-plane/tests/agents/test_prompt_deliberation.py) | Focused synthetic tests exercise the bounded mechanics, including T1 answer evaluation before optional T2 synthesis. They do not establish live operational validation. |
| W7 cross-agent shadow workflow mechanics | implemented | [`test_wave7_workflows.py`](../../../services/core-control-plane/tests/agents/test_wave7_workflows.py) | Workflows have executable synthetic shadow traces and no evidence here of a default enforce workflow. |
| W8 KPI, promotion, and degradation machinery | implemented | [`test_wave8_kpi_degradation.py`](../../../services/core-control-plane/tests/agents/test_wave8_kpi_degradation.py) | KPI reports distinguish measured values from unavailable evidence, promotion fails closed on missing evidence, and injected degradation drills cover the fixed pantheon. |
| W3 trace-continuity evidence handoff | implemented | `huginn.py`; `heimdall.py`; `test_trace_continuity_chain.py` | The sensing path preserves only bounded allowlisted continuity evidence and carries an observed reason into one Incident candidate without changing roles, topics, or action authority. |
| Terminal ActionRun effect-observation path | implemented | [`executed_action_observation.py`](../../../services/core-control-plane/src/fdai/delivery/executed_action_observation.py), [`wire_azure_operational_evidence.py`](../../../services/core-control-plane/src/fdai/composition/wire_azure_operational_evidence.py), [`test_executed_action_observation.py`](../../../services/core-control-plane/tests/delivery/test_executed_action_observation.py) | Heimdall consumes Thor's terminal ActionRun, restores exact pre-dispatch artifacts, and stores only verifier-accepted independent observations. Deployment-owned signed context and live closure evidence remain open. |
| O7 operational-promotion evidence measurement | implemented | [`operational_promotion.py`](../../../services/core-control-plane/src/fdai/core/measurement/operational_promotion.py), [`operational_promotion_evidence.py`](../../../services/core-control-plane/src/fdai/delivery/measurement/operational_promotion_evidence.py), [`test_operational_promotion_evidence.py`](../../../services/core-control-plane/tests/delivery/test_operational_promotion_evidence.py) | The runner consumes manifest-bound immutable batches and fails closed on missing causal, unit, recurrence, or policy-escape evidence. No runtime producer currently materializes the complete live batches. |
| Live operational KPI validation and actual enforce promotion | in-progress | [Operational Learning Ontology](../../roadmap/rules-and-detection/operational-learning-ontology.md), [Goals and Metrics](../../roadmap/architecture/goals-and-metrics.md) | Measurement and observation consumers exist, but no complete retained live-shadow cohort, operational promotion receipt, independent review, or actual pantheon enforce promotion is evidenced by this plan. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-13 | in-progress | Replaced the broad W0-W8 completion claim with independently evidenced implementation areas. | current change | Gather live evidence and complete separately reviewed promotion before claiming validation or enforce operation. |
| 2026-08-14 | implemented | Made optional conversational T2 synthesis conditional on deterministic conflict evaluation over bounded T1 answer signals. | `current change`; 36 focused deliberation tests and framework-layout checks. | Retain governed runtime evidence for the no-escalation and conflict-escalation branches. |
| 2026-08-17 | implemented | Added a bounded Huginn-to-Heimdall continuity evidence handoff and retained the recognized observed reason on the Incident candidate. | `current change`; focused trace-to-Incident chain passed with forged action-like input excluded. | Retain the governed live scenario evidence tracked by issue #142. |
| 2026-08-23 | implemented | Added Heimdall's typed terminal ActionRun observation path with exact artifact restoration and independently verified Azure effect collection. | `current change`; executed-action observation, Azure collector, composition, runtime topic, and Pantheon parity checks. | Bind the deployment-owned signed-context issuer and retain a governed live closure receipt. |
| 2026-08-23 | implemented | Added the O7 immutable evidence consumer, manifest-bound causal and measurement-unit verifiers, durable receipt sink, and opt-in measurement job. | `current change`; operational-promotion source, runner, persistence, CLI, and Terraform checks. | Implement the governed live-batch producer and accumulate action-specific evidence before promotion review. |
| 2026-08-24 | implemented | Preserved every selected expected effect and its independent outcome in the operational hypothesis lineage without changing any agent role, topic, or authority. Singular-only stored records retain one-effect read compatibility, and ambiguous dual-field records fail closed. | `current change`; `hypothesis_lineage.py`; `ActionOption.yaml`; focused lineage and competency checks passed 15 cases. | Complete the remaining lineage producer, signed-context, and live-batch prerequisites. |

### Remaining work

- [x] Reconcile one-to-many `expects` links with runtime expected-effect lineage and preserve one
  independent outcome per selected effect, as recorded in
  [Operational Learning Ontology](../../roadmap/rules-and-detection/operational-learning-ontology.md).
- [ ] Complete the remaining prerequisites: bind the deployment-owned signed-context issuer,
  preserve the remaining Forseti-owned causal lineage properties, construct the real runtime
  producer, and implement the governed live-batch producer.
- [ ] Demonstrate declared degradation behavior against operating dependencies, without widening
  any agent's role, topic ownership, model policy, or action authority.
- [ ] Run the declared KPI collectors against a retained live-shadow cohort on one pinned runtime,
  catalog, ActionType, workflow, and scenario-set revision.
- [ ] Retain authoritative outcome, recurrence, rollback, and zero-escape evidence with sample counts
  and confidence intervals for each promotion candidate.
- [ ] Complete an independent promotion review and record the authoritative promoted-set receipt
  before enabling or reporting pantheon enforce operation.
