---
title: Agent Pantheon Implementation Plan
---

# Agent Pantheon Implementation Plan

This document coordinates the implementation of the fixed 15-agent pantheon. It keeps the
append-only delivery ledger, the W0-W8 dependency order, and the runtime composition contract in
one place. Agent roles and invariants live in [Agent Pantheon](agent-pantheon.md), while each
cross-agent workflow has an independent rollout record in
[Agent Workflow Shadow Rollout](agent-workflow-rollout.md).

> **Scope:** The plan is customer-agnostic and Azure-first. Forks configure provider and delivery
> bindings through the supported dependency-injection seams. They don't rename agents, change
> role bindings, or bypass shadow promotion.

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
| Live operational KPI validation and actual enforce promotion | in-progress | [Operational Learning Ontology](../rules-and-detection/operational-learning-ontology.md), [Goals and Metrics](../architecture/goals-and-metrics.md) | Measurement and observation consumers exist, but no complete retained live-shadow cohort, operational promotion receipt, independent review, or actual pantheon enforce promotion is evidenced by this plan. |

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
  [Operational Learning Ontology](../rules-and-detection/operational-learning-ontology.md).
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

## Design at a glance

The waves describe dependency order, not separate sources of authority. Completed implementation
detail belongs to the current agent, workflow, ontology, and runtime owners. This document retains
only the coordination summary and the composition rules that connect those owners in a live
process.

| Wave | Bounded outcome | Current owner |
|------|-----------------|---------------|
| **W0** | Documentation and ontology foundations | [Agent Pantheon](agent-pantheon.md), [Agent Workflows](agent-workflows.md) |
| **W1** | Agent framework, fixed registry, topics, and two-port skeleton | [`agents/_framework/`](../../../services/core-control-plane/src/fdai/agents/_framework/) |
| **W2** | Saga, Mimir, Muninn, and Norns governance mechanics | [Agent Pantheon](agent-pantheon.md) |
| **W3** | Sensing, judgment, risk, rollback, and shadow execution chain | [Agent Pantheon](agent-pantheon.md) |
| **W4** | Deterministic-first conversation and arbitration | [Conversational Deliberation](conversational-deliberation.md) |
| **W5** | Cost, capacity, and resilience specialists | [Agent Pantheon](agent-pantheon.md) |
| **W6** | Audited handoff and security escalation | [Agent Pantheon](agent-pantheon.md) |
| **W7** | Independently promoted cross-agent workflows | [Agent Workflow Shadow Rollout](agent-workflow-rollout.md) |
| **W8** | KPI, promotion, and degradation evidence | [Agent Pantheon KPI and degradation policy](agent-pantheon.md#42-per-agent-kpi-success-and-degradation-signals) |

## 11. Wave 7 - Cross-agent workflows in shadow

The rollout order, per-workflow shadow gate, dependency, and anti-scope are owned by
[Agent Workflow Shadow Rollout](agent-workflow-rollout.md). Each workflow remains an independent
review, and no workflow reaches enforcement during this wave.

## Runtime composition contract

`PantheonRuntime` is the composition boundary for the fixed agent set. The implementation lives in
`services/core-control-plane/src/fdai/agents/_framework/runtime.py` and is assembled by
`services/core-control-plane/src/fdai/runtime/bootstrap.py`.

### Assembly and lifecycle

- `PantheonRuntime.build(provider, raw_event_topic)` instantiates the enabled agents, binds one
  `EventBusBridge`, and registers each declared subscription under an agent-specific consumer group.
- Raw ingress uses a distinct pantheon consumer group and enters through Huginn. It runs beside the
  primary control loop without stealing records or becoming its dependency.
- `run()` isolates consumer failures, restarts bounded transient failures, and keeps healthy sibling
  consumers running. Shutdown remains bounded.
- The runtime is enabled and shadow by default. `FDAI_START_PANTHEON=0` disables it, and missing
  consumer composition causes an explicit skip rather than an in-memory substitute.
- Thor remains `enforce=False` unless a separately reviewed promotion enables enforcement. Enforce
  composition requires a durable Saga audit binding and durable in-flight ActionRun storage.
- During cross-vertical arbitration, constitutional hard constraints remove ineligible options
  before Odin ranks the remaining soft objectives.

### Configurable and observable seams

| Seam | Contract |
|------|----------|
| `consumer_group_prefix` | Isolates consumer groups by environment. |
| `disabled_agents` | Removes optional agents from binding and subscription; Saga and Vidar cannot be disabled. |
| `saga` | Supplies append-only durable audit for enforce operation. |
| `thor_state_store` | Rehydrates non-terminal ActionRuns and preserves resource locks after restart. |
| `payload_validator` | Rejects malformed publications at the provider boundary. |
| Consumer restart bounds | Apply exponential backoff and a finite restart cap without cancelling siblings. |
| `health()` | Reports bridge metrics, agent and consumer state, unavailable agents, continuity, and effective enforcement. |
| Shadow observer | Measures would-be decisions without consuming records from authoritative subscribers. |
| `ShadowDivergenceLedger` | Joins shadow and authoritative decisions by correlation id for promotion evidence. |
| `heimdall_action_observation_hook` | Restores exact terminal ActionRun artifacts and records only independently verified effect observations. |
| Heartbeat | Emits the bounded health snapshot at the configured cadence. |

### Event-bus invariants

- Topic ownership and partition keys come from the shared topic registry. Mutation topics require a
  non-empty resource key, and an invalid key fails closed before publication.
- Published envelopes carry producer, schema, correlation, and idempotency metadata. Consumer-side
  ownership checks dead-letter an impostor publisher before handler delivery.
- Handler retries and timeouts are bounded. Ordered mutation streams can halt on poison records so a
  later effect cannot overtake a failed earlier effect.
- DLQ redrive is an explicit operator action. DLQ write failure is counted and isolated from healthy
  consumers.
- `InMemoryBus` follows the same envelope, partition, timeout, and failure-isolation contract as the
  production bridge.
- Agent publication uses the `PantheonBus` protocol, so runtime composition can replace delivery
  adapters without changing role or authority contracts.

## Governance and rollback

The authoritative cross-wave rules are maintained in the repository instructions:

- Documentation and bilingual updates: [Coding Conventions](../../../.github/instructions/coding-conventions.instructions.md) and [Language Policy](../../../.github/instructions/language.instructions.md).
- Fixed agent roles and permissions: [Agent Pantheon Instructions](../../../.github/instructions/agent-pantheon.instructions.md).
- Fork customization: [Customer-Agnostic Scope](../../../.github/instructions/generic-scope.instructions.md).

Each bounded wave remains independently reversible. A newly composed stage starts in shadow, and a
rollback restores the prior binding without granting authority or rewriting historical evidence.

## Related docs

| To learn about | Read |
|----------------|------|
| Fixed roles, topics, actions, and degradation | [Agent Pantheon](agent-pantheon.md) |
| Cross-agent workflow definitions | [Agent Workflows](agent-workflows.md) |
| Per-workflow rollout order and evidence | [Agent Workflow Shadow Rollout](agent-workflow-rollout.md) |
| Runtime source ownership | [Project Structure](../architecture/project-structure.md) |
| KPI measurement and promotion evidence | [Goals and Metrics](../architecture/goals-and-metrics.md) |
| Supported downstream bindings | [Downstream Fork Guide](../fork-and-sequencing/downstream-fork-guide.md) |
