import { useEffect, useState } from "preact/hooks";
import { currentRoute, navigate, routeHref } from "../router";
import type {
  ActionTypePaletteEntry,
  WorkflowBindingEntry,
  WorkflowCatalogEntry,
  WorkflowDefinitionCatalogResponse,
} from "../workflow/validate";
import { WorkflowAutomations } from "./workflow-builder.automations";
import { WorkflowDetail } from "./workflow-builder.detail";
import {
  workflowFromDefinition,
  workflowGroup,
  workflowGroupLabel,
  workflowSelection,
  type WorkflowGroup,
} from "./workflow-builder.model";

export function BuiltInList({
  workflows,
  definitions,
  palette,
  onNew,
  onPython,
}: {
  readonly workflows: readonly WorkflowCatalogEntry[];
  readonly definitions: WorkflowDefinitionCatalogResponse;
  readonly palette: readonly ActionTypePaletteEntry[];
  readonly onNew: () => void;
  readonly onPython: () => void;
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

  return (
    <div class="stack">
      <div class="governance-readonly-banner">
        <strong>Catalog workflows are read-only here.</strong> A workflow is a business process - a
        trigger plus an ordered chain of actions the control plane runs for you, each with a
        built-in safety net (stop-condition, rollback, blast-radius cap, audit). Describe what you
        want in plain words; the designer asks a few questions, shows you the exact YAML and a
        visual of how it runs, and lets you test it. YAML changes land through a PR. The Python
        task workbench uses its own validated artifact and typed proposal path.
      </div>

      <div class="section-header workflow-builder-actions">
        <button type="button" class="btn" onClick={onNew}>
          + Design a new workflow
        </button>
        <button type="button" class="btn" onClick={onPython}>
          Author Python VM task
        </button>
      </div>

      <section class="stack-section">
        <nav class="workflow-origin-tabs" aria-label="Workflow ownership">
          {(["built_in", "shared", "mine"] as const).map((value) => (
            <a
              key={value}
              href={routeHref("workflow-builder", { params: { group: value } })}
              class={group === value ? "is-active" : undefined}
              aria-current={group === value ? "page" : undefined}
            >
              <span>{workflowGroupLabel(value)}</span>
              <strong>{value === "built_in" ? workflows.length : definitions.groups[value].length}</strong>
            </a>
          ))}
        </nav>
        <div class="section-header">
          <h3 class="section-title">
            {workflowGroupLabel(group)} workflows ({groupedWorkflows.length})
          </h3>
        </div>
        <p class="muted small">
          The shipped workflows, for reference: open a row to see every step and the raw YAML.
        </p>
        {groupedWorkflows.length === 0 ? (
          <p class="muted small">No workflows are available in this group.</p>
        ) : (
          <>
            <div class="list-toolbar">
              <input
                class="form-input"
                type="search"
                value={filter}
                placeholder="Filter by name, trigger, or mode..."
                aria-label="Filter workflows"
                onInput={(event) => setFilter((event.target as HTMLInputElement).value)}
              />
              <span class="muted small">
                Showing {shown.length} of {groupedWorkflows.length} - {shadowCount} shadow, {" "}
                {enforceCount} enforce
              </span>
            </div>
            <div class="scroll">
              <table class="data-table data-table-clickable">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Trigger</th>
                    <th>Steps</th>
                    <th>Mode</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((workflow) => {
                    const isOpen = workflow.name === selected;
                    const toggle = () => openWorkflow(isOpen ? null : workflow);
                    return (
                      <tr
                        key={workflow.name}
                        class={isOpen ? "row-active" : ""}
                        onClick={toggle}
                        onKeyDown={(event) => {
                          if (event.key === "Enter" || event.key === " ") {
                            event.preventDefault();
                            toggle();
                          }
                        }}
                        tabIndex={0}
                        role="button"
                        aria-expanded={isOpen}
                        style="cursor: pointer"
                      >
                        <td class="mono">{workflow.name}</td>
                        <td class="mono muted">
                          <span class="badge tag">{workflow.trigger.kind}</span>{" "}
                          {workflow.trigger.kind === "signal" ? workflow.trigger.signal_type : workflow.trigger.schedule}
                        </td>
                        <td>{workflow.step_count}</td>
                        <td>
                          <span class={workflow.default_mode === "enforce" ? "badge enforce" : "badge shadow"}>
                            {workflow.default_mode}
                          </span>
                        </td>
                        <td class="chevron-col">
                          <span class="row-chevron">{isOpen ? "▾" : "▸"}</span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>

      {invalidRequestedWorkflow ? (
        <div class="state-block state-unavailable" role="alert">
          Workflow <code>{requestedWorkflow}</code> is not registered in this group. Choose a workflow from the table.
        </div>
      ) : invalidRequestedAction ? (
        <div class="state-block state-unavailable" role="alert">
          ActionType <code>{requestedAction}</code> is not connected to a workflow in this group.
        </div>
      ) : null}

      <WorkflowAutomations
        bindings={bindings}
        definitions={definitions}
        selectedDefinition={currentDefinition}
        onCreated={(binding) => setBindings((items) => [...items, binding])}
        onDeleted={(bindingId) => setBindings((items) =>
          items.filter((binding) => binding.binding_id !== bindingId),
        )}
      />

      {current ? <WorkflowDetail workflow={current} palette={palette} group={group} /> : null}
    </div>
  );
}
