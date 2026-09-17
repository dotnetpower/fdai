import { useEffect, useState } from "preact/hooks";
import { Tooltip } from "../components/tooltip";
import { currentRoute, navigate, routeHref } from "../router";
import type {
  ActionTypePaletteEntry,
  WorkflowBindingEntry,
  WorkflowCatalogEntry,
  WorkflowDefinitionCatalogResponse,
} from "../workflow/validate";
import type { PythonTaskAvailability } from "../workflow/python-task";
import { WorkflowAutomations } from "./workflow-builder.automations";
import { WorkflowDetail } from "./workflow-builder.detail";
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

export function workflowAuthorityGateCount(
  workflow: WorkflowCatalogEntry,
  palette: readonly ActionTypePaletteEntry[],
): number {
  const gatedActions = new Set(
    palette.filter((entry) => entry.hil_tiers.length > 0).map((entry) => entry.name),
  );
  return workflow.steps.filter((step) =>
    step.kind === "approval"
    || (
      typeof step.action_type_ref === "string"
      && gatedActions.has(step.action_type_ref)
    )
  ).length;
}

export function BuiltInList({
  workflows,
  definitions,
  palette,
  pythonTasks,
  onNew,
  onPython,
  onCatalogRevision,
}: {
  readonly workflows: readonly WorkflowCatalogEntry[];
  readonly definitions: WorkflowDefinitionCatalogResponse;
  readonly palette: readonly ActionTypePaletteEntry[];
  readonly pythonTasks: PythonTaskAvailability | null;
  readonly onNew: () => void;
  readonly onPython: () => void;
  readonly onCatalogRevision: (revision: string | null) => void;
}) {
  const initialGroup = workflowGroup(currentRoute().search.get("group"));
  const [group, setGroup] = useState<WorkflowGroup>(initialGroup);
  const groupedWorkflows = group === "built_in"
    ? workflows
    : definitions.groups[group].map(workflowFromDefinition);
  const requestedWorkflow = currentRoute().search.get("workflow");
  const requestedAction = currentRoute().search.get("action");
  const [selected, setSelected] = useState<string | null>(() => workflowSelection(
    groupedWorkflows,
    requestedWorkflow,
    requestedAction,
  ));
  const [filter, setFilter] = useState("");
  const [bindings, setBindings] = useState<readonly WorkflowBindingEntry[]>(definitions.bindings);
  const current = groupedWorkflows.find((workflow) => workflow.name === selected) ?? null;
  const currentDefinition = current
    ? definitions.groups[group].find((definition) => definition.workflow_name === current.name) ?? null
    : null;
  useEffect(() => {
    onCatalogRevision(current ? `${current.name}@${current.version}` : null);
  }, [current?.name, current?.version, onCatalogRevision]);
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
    return () => {
      window.removeEventListener("popstate", sync);
      window.removeEventListener("fdai:route-changed", sync);
    };
  }, [definitions.groups, workflows]);
  const invalidRequestedWorkflow = requestedWorkflow !== null && current === null;
  const invalidRequestedAction = requestedWorkflow === null
    && requestedAction !== null
    && current === null;
  const openWorkflow = (workflow: WorkflowCatalogEntry | null): void => {
    navigate(routeHref("workflow-builder", {
      params: { group, workflow: workflow?.name, step: null, action: null },
    }));
  };

  const needle = filter.trim().toLowerCase();
  const shown = needle
    ? groupedWorkflows.filter((workflow) => {
        const trigger = workflow.trigger.kind === "signal"
          ? workflow.trigger.signal_type ?? ""
          : workflow.trigger.schedule ?? "";
        return (
          workflow.name.toLowerCase().includes(needle) ||
          workflow.trigger.kind.includes(needle) ||
          trigger.toLowerCase().includes(needle) ||
          workflow.default_mode.includes(needle)
        );
      })
    : groupedWorkflows;
  const shadowCount = groupedWorkflows.filter((workflow) => workflow.default_mode !== "enforce").length;
  const enforceCount = groupedWorkflows.length - shadowCount;
  const authorityGates = current ? workflowAuthorityGateCount(current, palette) : 0;

  return (
    <div class="stack workflow-browser">
      <p class="workflow-source-note">
        <strong>{t("workflow.catalog.liveSourceTitle")}</strong>
        <span>{t("workflow.catalog.liveSourceBody")}</span>
      </p>

      <div class="governance-readonly-banner">
        <strong>{t("workflow.catalog.readOnlyTitle")}</strong>{" "}
        {t("workflow.catalog.readOnlyBody")}
      </div>

      {current ? (
        <section class="workflow-summary-grid" aria-label={t("workflow.catalog.summaryAria")}>
          <div>
            <span>{t("workflow.catalog.summary.steps")}</span>
            <strong>{formatNumber(current.step_count)}</strong>
            <small>{t("workflow.catalog.summary.stepsHint")}</small>
          </div>
          <div>
            <span>{t("workflow.catalog.summary.authorityGates")}</span>
            <strong>{formatNumber(authorityGates)}</strong>
            <small>{t("workflow.catalog.summary.authorityHint")}</small>
          </div>
          <div>
            <span>{t("workflow.catalog.summary.defaultMode")}</span>
            <strong>{statusLabel(current.default_mode)}</strong>
            <small>{t("workflow.catalog.summary.modeHint")}</small>
          </div>
          <div>
            <span>{t("workflow.catalog.summary.validation")}</span>
            <strong>{t("workflow.catalog.summary.validationPassed")}</strong>
            <small>{t("workflow.catalog.summary.revision", { version: current.version })}</small>
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
            value={filter}
            placeholder={t("workflow.catalog.filterPlaceholder")}
            aria-label={t("workflow.catalog.filterAria")}
            onInput={(event) => setFilter((event.target as HTMLInputElement).value)}
          />
        </label>
        <span class="workflow-filter-summary">
          {t("workflow.catalog.filterSummary", {
            shown: formatNumber(shown.length),
            total: formatNumber(groupedWorkflows.length),
            shadow: formatNumber(shadowCount),
            enforce: formatNumber(enforceCount),
          })}
        </span>
        <div class="workflow-command-bar">
          <button type="button" class="btn" onClick={onNew}>
            + {t("workflow.catalog.designNew")}
          </button>
          {pythonTasks ? (
            <Tooltip>
            <button
              type="button"
              class="btn"
              onClick={onPython}
            >
              {t("workflow.catalog.authorPython")}
            </button>
            </Tooltip>
          ) : null}
          {pythonTasks === null ? (
            <span id="python-task-unavailable" class="sr-only" role="status">
              {t("workflow.catalog.pythonUnavailable")}
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
        <div class="state-block state-empty">{t("workflow.catalog.empty")}</div>
      ) : current ? (
        <WorkflowDetail
          workflow={current}
          workflows={shown}
          palette={palette}
          group={group}
          onSelectWorkflow={openWorkflow}
        />
      ) : (
        <section class="workflow-selection-recovery">
          <h3>{t("workflow.catalog.libraryHeading")}</h3>
          <p>{t("workflow.catalog.selectionRequired")}</p>
          <div class="workflow-catalog-list">
            {shown.map((workflow) => (
              <button type="button" key={workflow.name} onClick={() => openWorkflow(workflow)}>
                <strong>{workflow.name}</strong>
                <span>{triggerLabel(workflow.trigger.kind)} / {t("workflow.catalog.stepCount", { count: formatNumber(workflow.step_count) })}</span>
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
