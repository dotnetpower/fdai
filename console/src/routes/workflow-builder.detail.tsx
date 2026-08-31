import { useEffect, useState } from "preact/hooks";
import { CopyButton, UnavailableState } from "../components/ui";
import { currentRoute, navigate, routeHref } from "../router";
import type {
  ActionTypePaletteEntry,
  WorkflowCatalogEntry,
  WorkflowCatalogStep,
} from "../workflow/validate";
import { formatParams } from "./workflow-builder.helpers";
import {
  hasActionTypeRef,
  requestedActionType,
  type WorkflowGroup,
} from "./workflow-builder.model";
import { formatNumber, statusLabel, t } from "./i18n/workflow";

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
        <h3>{t("workflow.detail.palette")} <span>{t("workflow.detail.actionTypeCount", { count: formatNumber(palette.length) })}</span></h3>
        <p>{t("workflow.detail.catalogReadOnly")}</p>
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
            <p>{workflow.description ?? t("workflow.detail.defaultDescription")}</p>
          </div>
          <span class={workflow.default_mode === "enforce" ? "status-pill status-pill-enforce" : "status-pill status-pill-shadow"}>
            {statusLabel(workflow.default_mode)}
          </span>
        </header>
        <div class="workflow-canvas-chain">
          <div class="workflow-canvas-node is-trigger">
            <span>{t("workflow.detail.when")}</span>
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
                <span>{t(index === workflow.steps.length - 1 ? "workflow.detail.then" : "workflow.detail.do")}</span>
                <strong>{step.id}</strong>
                <code>{stepPrimaryRef(step)}</code>
              </button>
            </div>
          ))}
          <div class="workflow-canvas-step">
            <i aria-hidden="true" />
            <div class="workflow-canvas-node is-done"><span>{t("workflow.detail.done")}</span><strong>{t("workflow.detail.auditTerminalState")}</strong></div>
          </div>
        </div>
      </section>

      <aside class="workflow-inspector-panel">
        <h3>{t("workflow.detail.inspect")} <span>{t("workflow.detail.selectedStep")}</span></h3>
        {invalidRequestedStep ? (
          <UnavailableState message={t("workflow.detail.stepNotFound", { step: requestedStep ?? "", workflow: workflow.name })} />
        ) : invalidRequestedAction ? (
          <UnavailableState message={t("workflow.detail.actionNotFound", { action: requestedAction ?? "" })} />
        ) : selected === null && actionType !== null ? (
          <>
            <code class="workflow-inspector-name">{actionType.name}</code>
            <dl>
              <div><dt>{t("workflow.detail.field.category")}</dt><dd>{actionType.category ?? t("workflow.detail.notRecorded")}</dd></div>
              <div><dt>{t("workflow.detail.field.operation")}</dt><dd>{actionType.operation}</dd></div>
              <div><dt>{t("workflow.detail.field.executionPath")}</dt><dd>{actionType.execution_path ?? t("workflow.detail.notRecorded")}</dd></div>
              <div><dt>{t("workflow.detail.field.rollback")}</dt><dd>{actionType.rollback_contract}</dd></div>
              <div><dt>{t("workflow.detail.field.defaultMode")}</dt><dd>{actionType.default_mode}</dd></div>
              <div><dt>{t("workflow.detail.field.environmentScope")}</dt><dd>{actionType.env_scope}</dd></div>
              <div><dt>{t("workflow.detail.field.hilTiers")}</dt><dd>{actionType.hil_tiers.join(", ") || t("workflow.detail.none")}</dd></div>
              <div><dt>{t("workflow.detail.field.description")}</dt><dd>{actionType.description ?? t("workflow.detail.notRecorded")}</dd></div>
            </dl>
          </>
        ) : selected ? (
          <>
            <code class="workflow-inspector-name">{selected.action_type_ref || selected.id}</code>
            <dl>
              <div><dt>{t("workflow.detail.field.stepId")}</dt><dd>{selected.id}</dd></div>
              <div><dt>{t("workflow.detail.field.stepKind")}</dt><dd>{t(`workflow.stepKind.${selected.kind ?? "action"}`)}</dd></div>
              {(selected.kind ?? "action") === "action" ? (
                <>
                  <div><dt>{t("workflow.detail.field.category")}</dt><dd>{actionType?.category ?? t("workflow.detail.notRecorded")}</dd></div>
                  <div><dt>{t("workflow.detail.field.executionPath")}</dt><dd>{actionType?.execution_path ?? t("workflow.detail.notRecorded")}</dd></div>
                  <div><dt>{t("workflow.detail.field.rollback")}</dt><dd>{actionType?.rollback_contract ?? t("workflow.detail.notRecorded")}</dd></div>
                  <div><dt>{t("workflow.detail.field.defaultMode")}</dt><dd>{actionType?.default_mode ?? workflow.default_mode}</dd></div>
                </>
              ) : null}
              {selected.kind === "wait" ? (
                <>
                  <div><dt>{t("workflow.detail.field.waitFor")}</dt><dd><code>{selected.wait_for ?? t("workflow.detail.notRecorded")}</code></dd></div>
                  <div><dt>{t("workflow.detail.field.timeoutSeconds")}</dt><dd>{selected.timeout_seconds ?? t("workflow.detail.notRecorded")}</dd></div>
                </>
              ) : null}
              {selected.kind === "approval" ? (
                <>
                  <div><dt>{t("workflow.detail.field.approvalRole")}</dt><dd>{selected.approval_role ?? t("workflow.detail.notRecorded")}</dd></div>
                  <div><dt>{t("workflow.detail.field.quorum")}</dt><dd>{selected.quorum ?? 1}</dd></div>
                  <div><dt>{t("workflow.detail.field.noSelfApproval")}</dt><dd>{selected.no_self_approval === false ? t("workflow.common.no") : t("workflow.common.yes")}</dd></div>
                  <div><dt>{t("workflow.detail.field.timeoutSeconds")}</dt><dd>{selected.timeout_seconds ?? t("workflow.detail.notRecorded")}</dd></div>
                </>
              ) : null}
              {selected.kind === "decision" ? (
                <div><dt>{t("workflow.detail.field.outcomes")}</dt><dd>{selected.outcomes?.join(", ") || t("workflow.detail.notRecorded")}</dd></div>
              ) : null}
              {selected.kind === "parallel" ? (
                <>
                  <div><dt>{t("workflow.detail.field.branches")}</dt><dd>{selected.branches?.join(", ") || t("workflow.detail.notRecorded")}</dd></div>
                  <div><dt>{t("workflow.detail.field.joinBehavior")}</dt><dd>{t("workflow.editor.joinAll")}</dd></div>
                </>
              ) : null}
              {selected.kind === "gate" ? (
                <div><dt>{t("workflow.detail.field.gateRef")}</dt><dd><code>{selected.gate_ref ?? t("workflow.detail.notRecorded")}</code></dd></div>
              ) : null}
              <div><dt>{t("workflow.detail.field.guard")}</dt><dd>{selected.guard_rule_ref ?? t("workflow.detail.none")}</dd></div>
              <div><dt>{t("workflow.detail.field.compensatedBy")}</dt><dd>{selected.compensated_by ?? t("workflow.detail.none")}</dd></div>
              <div><dt>{t("workflow.detail.field.onFailure")}</dt><dd>{selected.on_failure ?? t("workflow.detail.notRecorded")}</dd></div>
              <div><dt>{t("workflow.detail.field.parameters")}</dt><dd>{formatParams(selected.params)}</dd></div>
            </dl>
          </>
        ) : <p class="muted">{t("workflow.detail.emptySteps")}</p>}
        <div class="workflow-promotion-facts">
          <strong>{t("workflow.detail.promotionGate")}</strong>
          <span>{t("workflow.detail.shadowDays", { count: formatNumber(gate.min_shadow_days) })}</span>
          <span>{t("workflow.detail.samples", { count: formatNumber(gate.min_samples) })}</span>
          <span>{t("workflow.detail.accuracy", { value: gate.min_accuracy })}</span>
          <span>{t("workflow.detail.escapes", { value: gate.max_policy_escapes })}</span>
        </div>
      </aside>

      <details class="workflow-yaml-panel">
        <summary>{t("workflow.detail.yamlSummary")}</summary>
        {workflow.anti_scope ? <p><strong>{t("workflow.detail.antiScope")}</strong> {workflow.anti_scope}</p> : null}
        <div class="code-actions"><CopyButton text={workflow.yaml} label={t("workflow.detail.copyYaml")} /></div>
        <pre class="mono scroll code-block">{workflow.yaml}</pre>
      </details>
    </section>
  );
}

function stepPrimaryRef(step: WorkflowCatalogStep): string {
  if ((step.kind ?? "action") === "action") return step.action_type_ref ?? step.id;
  if (step.kind === "wait") return step.wait_for ?? step.id;
  if (step.kind === "approval") return step.approval_role ?? step.id;
  if (step.kind === "decision") return step.outcomes?.join(" | ") || step.id;
  if (step.kind === "parallel") return step.branches?.join(" + ") || step.id;
  return step.gate_ref ?? step.id;
}
