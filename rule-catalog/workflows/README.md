# Workflow catalog

Catalog-as-code business processes. Each YAML here is one `Workflow`: an
ordered list of steps, every step referencing one ontology `ActionType`,
plus a trigger, a promotion gate, and a default mode.

- **Schema:** [`services/core-control-plane/src/fdai/shared/contracts/workflow/schema.json`](../../services/core-control-plane/src/fdai/shared/contracts/workflow/schema.json)
- **Loader:** [`services/core-control-plane/src/fdai/rule_catalog/schema/workflow.py`](../../services/core-control-plane/src/fdai/rule_catalog/schema/workflow.py)
- **Design:** [`docs/roadmap/decisioning/process-automation.md`](../../docs/roadmap/decisioning/process-automation.md)
- **Reference workflows (prose + sequence diagrams):** [`docs/roadmap/agents/agent-workflows.md`](../../docs/roadmap/agents/agent-workflows.md)

## Rules

- Every `action_type_ref` and `compensated_by` MUST resolve to an
  `ActionType` name under [`../action-types/`](../action-types/). A typo
  fails at load, not at first dispatch.
- Every upstream Workflow MUST set `default_mode: shadow`. Promotion to
  enforce is a separate gated governance PR.
- A Workflow never declares a new mutation primitive. A missing capability
  is an upstream `ActionType` PR, not an inline step body.
- Steps are dispatched one at a time through the same control loop
  (`ActionType` -> risk-gate -> executor -> audit); there is no side
  channel and no direct executor call.
- `gate_ref: change-window.active` reads the target's reviewed `ChangeWindow`
  at the Process evaluation time. Missing, frozen, quiet, malformed, or
  truncated evidence blocks the gate.
