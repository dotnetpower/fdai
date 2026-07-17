import { useEffect, useState } from "preact/hooks";
import { CopyButton, UnavailableState } from "../components/ui";
import { currentRoute, navigate, routeHref } from "../router";
import type { ActionTypePaletteEntry, WorkflowCatalogEntry } from "../workflow/validate";
import { formatParams } from "./workflow-builder.helpers";
import {
  hasActionTypeRef,
  requestedActionType,
  type WorkflowGroup,
} from "./workflow-builder.model";

export function workflowStepHref(
  group: WorkflowGroup,
  workflow: string,
  step: string,
): string {
  return routeHref("workflow-builder", { params: { group, workflow, step } });
}

export function WorkflowDetail({
  workflow,
  palette,
  group,
}: {
  readonly workflow: WorkflowCatalogEntry;
  readonly palette: readonly ActionTypePaletteEntry[];
  readonly group: WorkflowGroup;
}) {
  const gate = workflow.promotion_gate;
  const requestedStep = currentRoute().search.get("step");
  const requestedAction = currentRoute().search.get("action");
  const matchedRequestedStep = requestedStep
    ? workflow.steps.find((step) => step.id === requestedStep) ?? null
    : null;
  const invalidRequestedStep = requestedStep !== null && matchedRequestedStep === null;
  const requestedActionStep = requestedAction !== null
    ? workflow.steps.find((step) => step.action_type_ref === requestedAction) ?? null
    : null;
  const requestedPaletteAction = requestedActionType(palette, requestedAction);
  const invalidRequestedAction = requestedAction !== null && requestedPaletteAction === null;
  const defaultStep = requestedStep !== null
    ? matchedRequestedStep
    : requestedAction !== null
      ? requestedActionStep
      : workflow.steps.find(hasActionTypeRef) ?? workflow.steps[0] ?? null;
  const [selectedStep, setSelectedStep] = useState<string | null>(defaultStep?.id ?? null);
  const selected = workflow.steps.find((step) => step.id === selectedStep) ?? defaultStep;
  useEffect(() => {
    if (selectedStep === selected?.id) return;
    setSelectedStep(selected?.id ?? null);
  }, [selected?.id, selectedStep]);
  useEffect(() => {
    const sync = () => {
      const route = currentRoute();
      const stepId = route.search.get("step");
      const actionName = route.search.get("action");
      const requested = stepId !== null
        ? workflow.steps.find((step) => step.id === stepId) ?? null
        : workflow.steps.find((step) => step.action_type_ref === actionName) ?? defaultStep;
      setSelectedStep(requested?.id ?? null);
    };
    window.addEventListener("popstate", sync);
    window.addEventListener("fdai:route-changed", sync);
    return () => {
      window.removeEventListener("popstate", sync);
      window.removeEventListener("fdai:route-changed", sync);
    };
  }, [defaultStep, workflow.steps]);
  const openStep = (stepId: string): void => {
    navigate(workflowStepHref(group, workflow.name, stepId));
  };
  const actionType = selected
    ? palette.find((entry) => entry.name === selected.action_type_ref) ?? null
    : requestedPaletteAction;
  return (
    <section class="workflow-catalog-workspace">
      <aside class="workflow-palette-panel">
        <h3>Palette <span>{palette.length} ActionTypes</span></h3>
        <p>Available on this deployment. Catalog view is read-only.</p>
        <ul>
          {palette.map((entry) => (
            <li key={entry.name} class={entry.name === actionType?.name ? "is-selected" : undefined}>
              <code>{entry.name}</code>
              <span class={`is-${entry.category ?? "other"}`}>{entry.category ?? "other"}</span>
            </li>
          ))}
        </ul>
      </aside>

      <section class="workflow-canvas-panel">
        <header>
          <div>
            <h3>{workflow.name}</h3>
            <p>{workflow.description ?? "Published workflow catalog entry"}</p>
          </div>
          <span class={workflow.default_mode === "enforce" ? "status-pill status-pill-enforce" : "status-pill status-pill-shadow"}>
            {workflow.default_mode}
          </span>
        </header>
        <div class="workflow-canvas-chain">
          <div class="workflow-canvas-node is-trigger">
            <span>when</span>
            <strong>{workflow.trigger.kind}</strong>
            <code>{workflow.trigger.kind === "signal" ? workflow.trigger.signal_type : workflow.trigger.schedule}</code>
          </div>
          {workflow.steps.map((step, index) => (
            <div class="workflow-canvas-step" key={step.id}>
              <i aria-hidden="true" />
              <button
                type="button"
                class={`workflow-canvas-node is-action ${selected?.id === step.id ? "is-selected" : ""}`}
                onClick={() => openStep(step.id)}
              >
                <span>{index === workflow.steps.length - 1 ? "then" : "do"}</span>
                <strong>{step.id}</strong>
                <code>{step.action_type_ref || step.guard_rule_ref || step.on_failure || "workflow stage"}</code>
              </button>
            </div>
          ))}
          <div class="workflow-canvas-step">
            <i aria-hidden="true" />
            <div class="workflow-canvas-node is-done"><span>done</span><strong>audit terminal state</strong></div>
          </div>
        </div>
      </section>

      <aside class="workflow-inspector-panel">
        <h3>Inspect <span>selected step</span></h3>
        {invalidRequestedStep ? (
          <UnavailableState message={`Step ${requestedStep} is not registered in ${workflow.name}.`} />
        ) : invalidRequestedAction ? (
          <UnavailableState message={`ActionType ${requestedAction} is not registered in this deployment.`} />
        ) : selected === null && actionType !== null ? (
          <>
            <code class="workflow-inspector-name">{actionType.name}</code>
            <dl>
              <div><dt>Category</dt><dd>{actionType.category ?? "not recorded"}</dd></div>
              <div><dt>Operation</dt><dd>{actionType.operation}</dd></div>
              <div><dt>Execution path</dt><dd>{actionType.execution_path ?? "not recorded"}</dd></div>
              <div><dt>Rollback</dt><dd>{actionType.rollback_contract}</dd></div>
              <div><dt>Default mode</dt><dd>{actionType.default_mode}</dd></div>
              <div><dt>Environment scope</dt><dd>{actionType.env_scope}</dd></div>
              <div><dt>HIL tiers</dt><dd>{actionType.hil_tiers.join(", ") || "none"}</dd></div>
              <div><dt>Description</dt><dd>{actionType.description ?? "not recorded"}</dd></div>
            </dl>
          </>
        ) : selected ? (
          <>
            <code class="workflow-inspector-name">{selected.action_type_ref || selected.id}</code>
            <dl>
              <div><dt>Step id</dt><dd>{selected.id}</dd></div>
              <div><dt>Category</dt><dd>{actionType?.category ?? "not recorded"}</dd></div>
              <div><dt>Execution path</dt><dd>{actionType?.execution_path ?? "not recorded"}</dd></div>
              <div><dt>Rollback</dt><dd>{actionType?.rollback_contract ?? "not recorded"}</dd></div>
              <div><dt>Default mode</dt><dd>{actionType?.default_mode ?? workflow.default_mode}</dd></div>
              <div><dt>Guard</dt><dd>{selected.guard_rule_ref ?? "none"}</dd></div>
              <div><dt>Compensated by</dt><dd>{selected.compensated_by ?? "none"}</dd></div>
              <div><dt>On failure</dt><dd>{selected.on_failure ?? "not recorded"}</dd></div>
              <div><dt>Parameters</dt><dd>{formatParams(selected.params)}</dd></div>
            </dl>
          </>
        ) : <p class="muted">This workflow has no steps.</p>}
        <div class="workflow-promotion-facts">
          <strong>Promotion gate</strong>
          <span>{gate.min_shadow_days}d shadow</span>
          <span>{gate.min_samples} samples</span>
          <span>accuracy &ge; {gate.min_accuracy}</span>
          <span>escapes &le; {gate.max_policy_escapes}</span>
        </div>
      </aside>

      <details class="workflow-yaml-panel">
        <summary>Published YAML and anti-scope</summary>
        {workflow.anti_scope ? <p><strong>Anti-scope:</strong> {workflow.anti_scope}</p> : null}
        <div class="code-actions"><CopyButton text={workflow.yaml} label="Copy YAML" /></div>
        <pre class="mono scroll code-block">{workflow.yaml}</pre>
      </details>
    </section>
  );
}
