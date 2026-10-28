import { useEffect, useMemo, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import { Tooltip } from "../components/tooltip";
import { currentRoute, pushRouteState, routeHref, ROUTE_STATE_EVENT } from "../router";
import type {
  ActionTypePaletteEntry,
  WorkflowBindingEntry,
  WorkflowCatalogEntry,
  WorkflowDefinitionCatalogResponse,
} from "../workflow/validate";
import type { PythonTaskCapabilityReport } from "../workflow/python-task";
import { WorkflowAutomations } from "./workflow-builder.automations";
import { WorkflowDetail } from "./workflow-builder.detail";
import {
  EMPTY_BROWSE_FILTER,
  filterWorkflows,
  triggerSummary,
  workflowApprovalFacts,
  workflowCategories,
  workflowStepKinds,
  type WorkflowBrowseFilter,
} from "./workflow-builder.browse";
import {
  workflowFromDefinition,
  workflowGroup,
  workflowSelection,
  type WorkflowGroup,
} from "./workflow-builder.model";
import { formatNumber, statusLabel, t, triggerLabel } from "./i18n/workflow";
import "./workflow-builder.workspace.css";

function groupLabel(group: WorkflowGroup): string {
  if (group === "built_in") return t("workflow.catalog.group.builtIn");
  if (group === "shared") return t("workflow.catalog.group.shared");
  return t("workflow.catalog.group.mine");
}

const PYTHON_UNAVAILABLE_REASON_KEYS: Readonly<Record<string, string>> = {
  python_task_validator_not_bound: "workflow.catalog.pythonUnavailableReason.validator",
  python_task_vm_runner_not_bound: "workflow.catalog.pythonUnavailableReason.vmTaskRunner",
};

/** Explain why Python task authoring is off. A missing capability route and a
 * server-reported unavailable state are distinct; unknown reasons stay generic. */
export function pythonTaskUnavailableMessage(
  report: PythonTaskCapabilityReport | null,
): string | null {
  if (report === null) return t("workflow.catalog.pythonUnavailable");
  if (report.available) return null;
  const details = report.reasons
    .map((reason) => PYTHON_UNAVAILABLE_REASON_KEYS[reason])
    .filter((key): key is string => key !== undefined)
    .map((key) => t(key));
  return [t("workflow.catalog.pythonUnavailableReported"), ...details].join(" ");
}

export function BuiltInList({
  client,
  workflows,
  definitions,
  palette,
  pythonTasks,
  onNew,
  onClone,
  onPython,
  onCatalogRevision,
}: {
  readonly client: OperatorApiClient;
  readonly workflows: readonly WorkflowCatalogEntry[];
  readonly definitions: WorkflowDefinitionCatalogResponse;
  readonly palette: readonly ActionTypePaletteEntry[];
  readonly pythonTasks: PythonTaskCapabilityReport | null;
  readonly onNew: () => void;
  readonly onClone: (workflowName: string) => void;
  readonly onPython: () => void;
  readonly onCatalogRevision: (revision: string | null) => void;
}) {
  const initialGroup = workflowGroup(currentRoute().search.get("group"));
  const [group, setGroup] = useState<WorkflowGroup>(initialGroup);
  const pythonUnavailable = pythonTaskUnavailableMessage(pythonTasks);
  const groupedWorkflows = useMemo(() => group === "built_in"
    ? workflows
    : definitions.groups[group].map(workflowFromDefinition), [definitions.groups, group, workflows]);
  const requestedWorkflow = currentRoute().search.get("workflow");
  const requestedAction = currentRoute().search.get("action");
  const [selected, setSelected] = useState<string | null>(() => workflowSelection(
    groupedWorkflows,
    requestedWorkflow,
    requestedAction,
  ));
  const [filter, setFilter] = useState<WorkflowBrowseFilter>(EMPTY_BROWSE_FILTER);
  const [bindings, setBindings] = useState<readonly WorkflowBindingEntry[]>(definitions.bindings);
  const current = groupedWorkflows.find((workflow) => workflow.name === selected) ?? null;
  const currentDefinition = current
    ? definitions.groups[group].find((definition) => definition.workflow_name === current.name) ?? null
    : null;
  useEffect(() => {
    onCatalogRevision(current ? `${current.name}@${current.version}` : null);
  }, [current?.name, current?.version, onCatalogRevision]);
  useEffect(() => () => onCatalogRevision(null), [onCatalogRevision]);
  useEffect(() => {
    const sync = () => {
      const route = currentRoute();
      const workflowName = route.search.get("workflow");
      const actionName = route.search.get("action");
      const nextGroup = workflowGroup(route.search.get("group"));
      setGroup(nextGroup);
      const available = nextGroup === "built_in"
        ? workflows
        : definitions.groups[nextGroup].map(workflowFromDefinition);
      setSelected(workflowSelection(available, workflowName, actionName));
    };
    window.addEventListener("popstate", sync);
    window.addEventListener("fdai:route-changed", sync);
    window.addEventListener(ROUTE_STATE_EVENT, sync);
    return () => {
      window.removeEventListener("popstate", sync);
      window.removeEventListener("fdai:route-changed", sync);
      window.removeEventListener(ROUTE_STATE_EVENT, sync);
    };
  }, [definitions.groups, workflows]);
  const invalidRequestedWorkflow = requestedWorkflow !== null && current === null;
  const invalidRequestedAction = requestedWorkflow === null
    && requestedAction !== null
    && current === null;
  // Selection updates history in place so active filters and loaded data
  // persist; Back and deep links still restore the same selection.
  const openWorkflow = (workflow: WorkflowCatalogEntry | null): void => {
    pushRouteState(routeHref("workflow-builder", {
      params: { group, workflow: workflow?.name, step: null, action: null },
    }));
  };

  const categories = useMemo(() => workflowCategories(groupedWorkflows, palette), [groupedWorkflows, palette]);
  const stepKinds = useMemo(() => workflowStepKinds(groupedWorkflows), [groupedWorkflows]);
  const shown = useMemo(
    () => filterWorkflows(groupedWorkflows, filter, palette),
    [filter, groupedWorkflows, palette],
  );
  const filtered = filter.text.trim() !== "" || filter.category !== "" || filter.stepKind !== "";
  const shadowCount = groupedWorkflows.filter((workflow) => workflow.default_mode !== "enforce").length;
  const enforceCount = groupedWorkflows.length - shadowCount;
  const approval = current ? workflowApprovalFacts(current, palette) : null;

  return (
    <div class="stack workflow-browser">
      <p class="workflow-source-note">
        <strong>{t("workflow.catalog.liveSourceTitle")}</strong>
        <span>{t("workflow.catalog.sourceNote")}</span>
      </p>

      {current && approval ? (
        <section class="workflow-summary-grid" aria-label={t("workflow.catalog.summaryAria")}>
          <div>
            <span>{t("workflow.catalog.summary.steps")}</span>
            <strong>{formatNumber(current.step_count)}</strong>
            <small>{t("workflow.catalog.summary.stepsHint")}</small>
          </div>
          <div>
            <span>{t("workflow.catalog.summary.approvalSteps")}</span>
            <strong>{formatNumber(approval.approvalSteps)}</strong>
            <small>{t("workflow.catalog.summary.hilActions", { count: formatNumber(approval.hilGatedActions) })}</small>
          </div>
          <div>
            <span>{t("workflow.catalog.summary.defaultMode")}</span>
            <strong>{statusLabel(current.default_mode)}</strong>
            <small>{t("workflow.catalog.summary.modeHint")}</small>
          </div>
          <div>
            <span>{t("workflow.catalog.summary.catalogState")}</span>
            <strong>
              {currentDefinition === null
                ? t("workflow.catalog.summary.reviewed")
                : statusLabel(currentDefinition.lifecycle)}
            </strong>
            <small>
              {currentDefinition === null
                ? t("workflow.catalog.summary.reviewedHint", { version: current.version })
                : t("workflow.catalog.summary.definitionHint", {
                    version: current.version,
                    origin: currentDefinition.origin,
                  })}
            </small>
          </div>
        </section>
      ) : null}

      <section class="workflow-review-controls" aria-label={t("workflow.catalog.reviewControls")}>
        <nav class="workflow-origin-tabs" aria-label={t("workflow.catalog.ownership")}>
          {(["built_in", "shared", "mine"] as const).map((value) => (
            <a
              key={value}
              href={routeHref("workflow-builder", { params: { group: value } })}
              class={group === value ? "is-active" : undefined}
              aria-current={group === value ? "page" : undefined}
            >
              <span>{groupLabel(value)}</span>
              <strong>{formatNumber(value === "built_in" ? workflows.length : definitions.groups[value].length)}</strong>
            </a>
          ))}
        </nav>
        <label class="workflow-filter-field">
          <span>{t("workflow.catalog.filterLabel")}</span>
          <input
            class="form-input"
            type="search"
            value={filter.text}
            placeholder={t("workflow.catalog.filterPlaceholder")}
            aria-label={t("workflow.catalog.filterAria")}
            onInput={(event) => setFilter({ ...filter, text: (event.target as HTMLInputElement).value })}
          />
        </label>
        <label class="workflow-filter-field">
          <span>{t("workflow.catalog.categoryFilter")}</span>
          <select
            class="form-input"
            value={filter.category}
            onChange={(event) => setFilter({ ...filter, category: (event.target as HTMLSelectElement).value })}
          >
            <option value="">{t("workflow.catalog.allCategories")}</option>
            {categories.map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </label>
        <label class="workflow-filter-field">
          <span>{t("workflow.catalog.stepKindFilter")}</span>
          <select
            class="form-input"
            value={filter.stepKind}
            onChange={(event) => setFilter({ ...filter, stepKind: (event.target as HTMLSelectElement).value })}
          >
            <option value="">{t("workflow.catalog.allStepKinds")}</option>
            {stepKinds.map((value) => (
              <option key={value} value={value}>{t(`workflow.stepKind.${value}`)}</option>
            ))}
          </select>
        </label>
        <div class="workflow-filter-summary">
          <span role="status">
            {t("workflow.catalog.filterSummary", {
              shown: formatNumber(shown.length),
              total: formatNumber(groupedWorkflows.length),
              shadow: formatNumber(shadowCount),
              enforce: formatNumber(enforceCount),
            })}
          </span>
          {filtered ? (
            <button type="button" class="btn btn-small secondary" onClick={() => setFilter(EMPTY_BROWSE_FILTER)}>
              {t("workflow.catalog.clearFilters")}
            </button>
          ) : null}
        </div>
        <div class="workflow-command-bar">
          <button type="button" class="btn" onClick={onNew}>
            + {t("workflow.catalog.designNew")}
          </button>
          {pythonTasks !== null && pythonTasks.available ? (
            <button type="button" class="btn" onClick={onPython}>
              {t("workflow.catalog.authorPython")}
            </button>
          ) : null}
          {pythonUnavailable !== null ? (
            <Tooltip content={pythonUnavailable}>
              <span
                class="workflow-command-note"
                tabIndex={0}
                aria-describedby="python-task-unavailable"
              >
                {t("workflow.catalog.pythonUnavailableShort")}
              </span>
            </Tooltip>
          ) : null}
          {pythonUnavailable !== null ? (
            <span id="python-task-unavailable" class="sr-only" role="status">
              {pythonUnavailable}
            </span>
          ) : null}
        </div>
      </section>

      {invalidRequestedWorkflow ? (
        <div class="state-block state-unavailable" role="alert">
          {t("workflow.catalog.workflowNotFound", { workflow: requestedWorkflow ?? "" })}
        </div>
      ) : invalidRequestedAction ? (
        <div class="state-block state-unavailable" role="alert">
          {t("workflow.catalog.actionNotConnected", { action: requestedAction ?? "" })}
        </div>
      ) : null}

      {groupedWorkflows.length === 0 ? (
        <div class="state-block state-empty">
          <p>{t(group === "mine" ? "workflow.catalog.emptyMine" : "workflow.catalog.empty")}</p>
          {group === "mine" ? (
            <button type="button" class="btn btn-small" onClick={onNew}>
              + {t("workflow.catalog.designNew")}
            </button>
          ) : null}
        </div>
      ) : current ? (
        <WorkflowDetail
          key={`${group}:${current.name}`}
          client={client}
          workflow={current}
          workflows={shown}
          palette={palette}
          group={group}
          onSelectWorkflow={openWorkflow}
          onClone={() => onClone(current.name)}
        />
      ) : (
        <section class="workflow-selection-recovery">
          <h3>{t("workflow.catalog.libraryHeading")}</h3>
          <p>{t("workflow.catalog.selectionRequired")}</p>
          <div class="workflow-catalog-list">
            {shown.map((workflow) => (
              <button type="button" key={workflow.name} onClick={() => openWorkflow(workflow)}>
                <strong>{workflow.name}</strong>
                <span>{triggerLabel(workflow.trigger.kind)} - {triggerSummary(workflow.trigger)}</span>
              </button>
            ))}
          </div>
        </section>
      )}

      <WorkflowAutomations
        bindings={bindings}
        definitions={definitions}
        selectedDefinition={currentDefinition}
        onCreated={(binding) => setBindings((items) => [...items, binding])}
        onDeleted={(bindingId) => setBindings((items) =>
          items.filter((binding) => binding.binding_id !== bindingId),
        )}
      />
    </div>
  );
}
