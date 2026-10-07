import { useEffect, useState } from "preact/hooks";
import { isOptionalOperatorApiUnavailable, type OperatorApiClient } from "../api";
import {
  AsyncBoundary,
  CopyButton,
  StatusPill,
  UnavailableState,
  type AsyncState,
} from "../components/ui";
import { currentRoute, pushRouteState, routeHref, ROUTE_STATE_EVENT } from "../router";
import type {
  ActionTypePaletteEntry,
  WorkflowCatalogEntry,
  WorkflowCatalogStep,
} from "../workflow/validate";
import { formatParams, signalLabel } from "./workflow-builder.helpers";
import { describeSchedule, stepKindOf, triggerSummary } from "./workflow-builder.browse";
import {
  decodeProcessList,
  processHref,
  processTone,
  type ProcessListResponse,
} from "./processes.model";
import {
  hasActionTypeRef,
  requestedActionType,
  type WorkflowGroup,
} from "./workflow-builder.model";
import { formatDateTimeValue, formatNumber, statusLabel, t, triggerLabel } from "./i18n/workflow";

export function workflowStepHref(
  group: WorkflowGroup,
  workflow: string,
  step: string,
): string {
  return routeHref("workflow-builder", { params: { group, workflow, step } });
}

export function WorkflowDetail({
  client,
  workflow,
  workflows,
  palette,
  group,
  onSelectWorkflow,
  onClone,
}: {
  readonly client: OperatorApiClient;
  readonly workflow: WorkflowCatalogEntry;
  readonly workflows: readonly WorkflowCatalogEntry[];
  readonly palette: readonly ActionTypePaletteEntry[];
  readonly group: WorkflowGroup;
  readonly onSelectWorkflow: (workflow: WorkflowCatalogEntry) => void;
  readonly onClone: () => void;
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
    window.addEventListener(ROUTE_STATE_EVENT, sync);
    return () => {
      window.removeEventListener("popstate", sync);
      window.removeEventListener("fdai:route-changed", sync);
      window.removeEventListener(ROUTE_STATE_EVENT, sync);
    };
  }, [defaultStep, workflow.steps]);
  const openStep = (stepId: string): void => {
    pushRouteState(workflowStepHref(group, workflow.name, stepId));
  };
  const actionType = selected
    ? palette.find((entry) => entry.name === selected.action_type_ref) ?? null
    : requestedPaletteAction;
  const inspectorName = selected?.action_type_ref || selected?.id || actionType?.name || null;
  const inspectorDescription = actionType?.description
    ?? (selected ? t("workflow.detail.controlStepDescription") : null);
  const inspectorMode = actionType?.default_mode ?? workflow.default_mode;
  const showInspectorSummary = !invalidRequestedStep
    && !invalidRequestedAction
    && inspectorName !== null;
  const schedule = workflow.trigger.kind === "schedule" ? workflow.trigger.schedule ?? "" : null;
  const triggerTitle = schedule !== null
    ? describeSchedule(schedule) ?? schedule
    : signalLabel(workflow.trigger.signal_type ?? "") || triggerLabel(workflow.trigger.kind);
  const triggerRef = schedule !== null ? schedule : workflow.trigger.signal_type ?? "";
  return (
    <>
    <section class="workflow-catalog-workspace">
      <aside class="workflow-catalog-panel">
        <header>
          <div>
            <h3>{t("workflow.catalog.libraryHeading")}</h3>
            <p>{t("workflow.catalog.libraryDescription")}</p>
          </div>
          <span>{formatNumber(workflows.length)}</span>
        </header>
        <div class="workflow-catalog-list">
          {workflows.length === 0 ? <p>{t("workflow.catalog.filterEmpty")}</p> : null}
          {workflows.map((entry) => {
            const selectedWorkflow = entry.name === workflow.name;
            return (
              <button
                type="button"
                key={entry.name}
                class={selectedWorkflow ? "is-selected" : undefined}
                aria-pressed={selectedWorkflow}
                onClick={() => onSelectWorkflow(entry)}
              >
                <span>
                  <strong>{entry.name}</strong>
                  <small title={triggerSummary(entry.trigger)}>{triggerSummary(entry.trigger)}</small>
                </span>
                <span>{t("workflow.catalog.stepCount", { count: formatNumber(entry.step_count) })}</span>
              </button>
            );
          })}
        </div>
      </aside>

      <section class="workflow-canvas-panel">
        <header>
          <div>
            <h3>{workflow.name}</h3>
            <p>{workflow.description ?? t("workflow.detail.defaultDescription")}</p>
          </div>
          <div class="workflow-canvas-actions">
            <span class={workflow.default_mode === "enforce" ? "status-pill status-pill-enforce" : "status-pill status-pill-shadow"}>
              {statusLabel(workflow.default_mode)}
            </span>
            <button type="button" class="btn btn-small" onClick={onClone}>
              {t("workflow.detail.copyToDraft")}
            </button>
          </div>
        </header>
        <ol class="workflow-canvas-chain" aria-label={t("workflow.detail.chainAria")}>
          <li class="workflow-canvas-node is-trigger">
            <span>{t("workflow.detail.when")}</span>
            <strong>{triggerTitle}</strong>
            <code>{triggerRef}</code>
          </li>
          {workflow.steps.map((step) => (
            <li class="workflow-canvas-step" key={step.id}>
              <i aria-hidden="true" />
              <button
                type="button"
                class={`workflow-canvas-node is-action ${selected?.id === step.id ? "is-selected" : ""}`}
                aria-pressed={selected?.id === step.id}
                onClick={() => openStep(step.id)}
              >
                <span>{t(`workflow.stepKind.${stepKindOf(step)}`)}</span>
                <strong>{step.id}</strong>
                <code>{stepPrimaryRef(step)}</code>
                <StepPaths step={step} />
              </button>
            </li>
          ))}
          <li class="workflow-canvas-step">
            <i aria-hidden="true" />
            <div class="workflow-canvas-node is-done"><span>{t("workflow.detail.done")}</span><strong>{t("workflow.detail.auditTerminalState")}</strong></div>
          </li>
        </ol>
      </section>

      <aside class="workflow-inspector-panel">
        <h3>
          {t(actionType ? "workflow.detail.selectedActionType" : "workflow.detail.selectedStep")}
        </h3>
        {showInspectorSummary ? (
          <div class="workflow-inspector-summary">
            <div>
              <code class="workflow-inspector-name">{inspectorName}</code>
              <span class={inspectorMode === "enforce" ? "badge enforce" : "badge shadow"}>
                {statusLabel(inspectorMode)}
              </span>
            </div>
            {inspectorDescription ? <p>{inspectorDescription}</p> : null}
          </div>
        ) : null}
        {invalidRequestedStep ? (
          <UnavailableState message={t("workflow.detail.stepNotFound", { step: requestedStep ?? "", workflow: workflow.name })} />
        ) : invalidRequestedAction ? (
          <UnavailableState message={t("workflow.detail.actionNotFound", { action: requestedAction ?? "" })} />
        ) : selected === null && actionType !== null ? (
          <>
            <h4 class="workflow-inspector-section-title">{t("workflow.detail.safetyContract")}</h4>
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
            <h4 class="workflow-inspector-section-title">
              {t(actionType ? "workflow.detail.safetyContract" : "workflow.detail.contractDetails")}
            </h4>
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
            {actionType ? (
              <a
                class="workflow-inspector-link"
                href={routeHref("promotion-gates", { params: { q: actionType.name } })}
              >
                {t("workflow.detail.promotionStatus")}
              </a>
            ) : null}
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
    {group === "mine" ? null : <WorkflowRunHistory client={client} workflowName={workflow.name} />}
    </>
  );
}

/** Secondary control paths that a linear chain would otherwise hide. */
function StepPaths({ step }: { readonly step: WorkflowCatalogStep }) {
  const kind = stepKindOf(step);
  const items: string[] = [];
  if (kind === "parallel" && step.branches && step.branches.length > 0) {
    items.push(t("workflow.detail.paths.branches", { branches: step.branches.join(", ") }));
  }
  if (kind === "decision" && step.outcomes && step.outcomes.length > 0) {
    items.push(t("workflow.detail.paths.outcomes", { outcomes: step.outcomes.join(", ") }));
  }
  if (step.on_failure) items.push(t("workflow.detail.paths.onFailure", { step: step.on_failure }));
  if (step.compensated_by) {
    items.push(t("workflow.detail.paths.compensatedBy", { action: step.compensated_by }));
  }
  if (items.length === 0) return null;
  return (
    <span class="workflow-canvas-paths">
      {items.map((item) => <small key={item}>{item}</small>)}
    </span>
  );
}

const RUN_HISTORY_LIMIT = 5;

/** Principal-scoped Process history for the selected workflow. Read-only:
 * it links to the owning Process evidence and never starts a run. */
function WorkflowRunHistory({
  client,
  workflowName,
}: {
  readonly client: OperatorApiClient;
  readonly workflowName: string;
}) {
  const [state, setState] = useState<AsyncState<ProcessListResponse>>({ status: "loading" });
  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    const query = new URLSearchParams({ workflow_ref: workflowName });
    client.panel<unknown>(`/views/process?${query.toString()}`).then(
      (value) => {
        if (cancelled) return;
        try {
          setState({ status: "ready", data: decodeProcessList(value) });
        } catch (error) {
          setState({ status: "error", message: error instanceof Error ? error.message : String(error) });
        }
      },
      (error: unknown) => {
        if (cancelled) return;
        setState({
          status: isOptionalOperatorApiUnavailable(error) ? "unavailable" : "error",
          message: error instanceof Error ? error.message : String(error),
        });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [client, workflowName]);
  return (
    <section class="workflow-run-history" aria-labelledby="workflow-run-history-title">
      <header>
        <h3 id="workflow-run-history-title">{t("workflow.detail.runs.heading")}</h3>
        <p>{t("workflow.detail.runs.description")}</p>
      </header>
      <AsyncBoundary state={state} resourceLabel={t("workflow.detail.runs.resourceLabel")}>
        {(data) => {
          if (data.items.length === 0) {
            return <p class="workflow-run-history-empty">{t("workflow.detail.runs.empty")}</p>;
          }
          const counts = new Map<string, number>();
          for (const item of data.items) counts.set(item.status, (counts.get(item.status) ?? 0) + 1);
          const recent = [...data.items]
            .sort((left, right) => right.updated_at.localeCompare(left.updated_at))
            .slice(0, RUN_HISTORY_LIMIT);
          return (
            <>
              <p class="workflow-run-history-counts">
                {[...counts.entries()].map(([status, count]) => (
                  <span key={status}>
                    <StatusPill kind={processTone(status)} label={statusLabel(status)} />
                    {formatNumber(count)}
                  </span>
                ))}
              </p>
              <ul class="workflow-run-history-list">
                {recent.map((item) => (
                  <li key={item.id}>
                    <a href={processHref(item.id)}>{item.target_resource_id}</a>
                    <span>{item.current_step || t("workflow.chat.terminal")}</span>
                    <StatusPill kind={processTone(item.status)} label={statusLabel(item.status)} />
                    <time dateTime={item.updated_at}>{formatDateTimeValue(item.updated_at)}</time>
                  </li>
                ))}
              </ul>
              {data.items.length > RUN_HISTORY_LIMIT ? (
                <p class="workflow-run-history-more">
                  {t("workflow.detail.runs.more", {
                    shown: formatNumber(RUN_HISTORY_LIMIT),
                    total: formatNumber(data.items.length),
                  })}
                </p>
              ) : null}
            </>
          );
        }}
      </AsyncBoundary>
    </section>
  );
}

function stepPrimaryRef(step: WorkflowCatalogStep): string {
  if ((step.kind ?? "action") === "action") return step.action_type_ref ?? step.id;
  if (step.kind === "wait") return step.wait_for ?? step.id;
  if (step.kind === "approval") return step.approval_role ?? step.id;
  if (step.kind === "decision") {
    return t("workflow.detail.paths.outcomeCount", { count: formatNumber(step.outcomes?.length ?? 0) });
  }
  if (step.kind === "parallel") {
    return t("workflow.detail.paths.branchCount", { count: formatNumber(step.branches?.length ?? 0) });
  }
  return step.gate_ref ?? step.id;
}
