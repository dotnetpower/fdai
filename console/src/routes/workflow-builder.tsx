/**
 * Workflow builder route - browse the built-in workflow catalog read-only,
 * or design a new workflow by chatting with a deterministic assistant.
 *
 * Authoring is conversational, not a form: the designer
 * (workflow-builder.chat.ts / .tsx) asks follow-up questions, offers explicit
 * ActionType and trigger choices, shows the generated YAML, and validates it.
 * An operator can also start from a copy of a visible workflow. `POST
 * /workflows/validate` is a pure check; the only write is an explicit private
 * draft save. Catalog publication stays a git-native remediation PR, never a
 * console button (app-shape.instructions.md § Operator console). New workflows
 * are locked to `shadow` mode - promotion to enforce is a separate governance
 * PR (process-automation.md § 6).
 *
 * SRP: this file owns route loading and URL-backed mode selection (`mode=new`,
 * `mode=python`, and the one-shot `from=<workflow>` copy seed). Catalog,
 * detail, automation, chat, and Python-task surfaces live in sibling modules.
 */

import { useCallback, useEffect, useMemo, useState } from "preact/hooks";
import { isOptionalOperatorApiUnavailable, OperatorApiError } from "../api";
import type { OperatorApiClient } from "../api";
import { AsyncBoundary, PageHeader, type AsyncState } from "../components/ui";
import {
  currentRoute,
  pushRouteState,
  replaceRouteState,
  routeHref,
  ROUTE_STATE_EVENT,
} from "../router";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import type {
  ActionTypePaletteResponse,
  WorkflowCatalogResponse,
  WorkflowDefinitionCatalogResponse,
} from "../workflow/validate";
import {
  decodePythonTaskAvailability,
  type PythonTaskCapabilityReport,
} from "../workflow/python-task";
import {
  workflowFromDefinition,
  workflowGroup,
  type CombinedData,
} from "./workflow-builder.model";
import { BuiltInList, pythonTaskUnavailableMessage } from "./workflow-builder.catalog";
import { WorkflowChat, type WorkflowChatSeed } from "./workflow-builder.chatpanel";
import { catalogToForm } from "./workflow-builder.helpers";
import { PythonTaskWorkbench } from "./workflow-builder.python-task";
import { formatNumber, t } from "./i18n/workflow";
import { workflowGateRefs } from "./workflow-builder.structure";

// Re-export the pure helpers the vitest suite pins so `./workflow-builder`
// stays a stable public import surface (workflow-builder.test.ts).
export { buildGithubNewFileUrl, humanizeName, suggestStepId } from "./workflow-builder.helpers";
export { suggestDraftFromJudgment, suggestDraftFromText } from "./workflow-builder.intent";
export { hasEquivalentWorkflowBinding } from "./workflow-builder.automations";
export { workflowStepHref } from "./workflow-builder.detail";
export { hasActionTypeRef, requestedActionType, workflowSelection } from "./workflow-builder.model";

interface Props {
  readonly client: OperatorApiClient;
}

const EMPTY_WORKFLOW_DEFINITIONS: WorkflowDefinitionCatalogResponse = {
  groups: { built_in: [], shared: [], mine: [] },
  bindings: [],
  counts: { built_in: 0, shared: 0, mine: 0 },
};

function isOptionalWorkflowCapabilityUnavailable(error: unknown): boolean {
  return isOptionalOperatorApiUnavailable(error)
    || (error instanceof OperatorApiError && error.status === 503);
}

export async function loadWorkflowDefinitions(
  client: Pick<OperatorApiClient, "panel">,
): Promise<WorkflowDefinitionCatalogResponse> {
  try {
    return await client.panel<WorkflowDefinitionCatalogResponse>("/workflows/definitions");
  } catch (error) {
    if (isOptionalWorkflowCapabilityUnavailable(error)) return EMPTY_WORKFLOW_DEFINITIONS;
    throw error;
  }
}

export async function loadPythonTaskAvailability(
  client: Pick<OperatorApiClient, "panel">,
): Promise<PythonTaskCapabilityReport | null> {
  try {
    const payload = await client.panel<unknown>("/python-tasks/capabilities");
    return decodePythonTaskAvailability(payload);
  } catch (error) {
    if (isOptionalWorkflowCapabilityUnavailable(error)) return null;
    throw error;
  }
}

export type WorkflowBuilderMode = "list" | "new" | "python";

/** Decode the URL-owned builder mode; unknown values fall back to the list. */
export function workflowBuilderMode(value: string | null): WorkflowBuilderMode {
  return value === "new" || value === "python" ? value : "list";
}

/** Builder href that keeps the current selection and applies overrides. */
export function workflowBuilderHref(
  search: URLSearchParams,
  overrides: Readonly<Record<string, string | null>>,
): string {
  const params: Record<string, string | null> = {};
  search.forEach((value, key) => {
    params[key] = value;
  });
  return routeHref("workflow-builder", { params: { ...params, ...overrides } });
}

export function WorkflowBuilderRoute({ client }: Props) {
  const [state, setState] = useState<AsyncState<CombinedData>>({ status: "loading" });
  const [catalogRevision, setCatalogRevision] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    (async () => {
      try {
        const [palette, catalog, definitions, pythonTasks] = await Promise.all([
          client.panel<ActionTypePaletteResponse>("/workflows/action-types"),
          client.panel<WorkflowCatalogResponse>("/workflows/catalog"),
          loadWorkflowDefinitions(client),
          loadPythonTaskAvailability(client),
        ]);
        if (!cancelled) {
          setState({
            status: "ready",
            data: {
              palette: palette.action_types,
              workflows: catalog.workflows,
              definitions,
              pythonTasks,
            },
          });
        }
      } catch (err) {
        if (!cancelled) {
          const message = err instanceof Error ? err.message : String(err);
          if (isOptionalOperatorApiUnavailable(err)) {
            setState({
              status: "unavailable",
              message: t("workflow.builder.unavailable"),
            });
          } else {
            setState({ status: "error", message });
          }
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [client]);

  return (
    <div class="stack governance-route workflow-builder-route">
      <PageHeader
        title={t("route.workflowBuilder")}
        subtitle={t("workflowBuilder.subtitle")}
        actions={catalogRevision ? (
          <div class="workflow-header-meta">
            <span>{t("workflow.catalog.selectedRevision")}</span>
            <strong>{catalogRevision}</strong>
          </div>
        ) : null}
      />
      <AsyncBoundary state={state} resourceLabel={t("workflow.builder.resourceLabel")}>
        {(data) => (
          <WorkflowShell
            client={client}
            data={data}
            onCatalogRevision={setCatalogRevision}
          />
        )}
      </AsyncBoundary>
    </div>
  );
}
/** Top-level view switch: the read-only built-in list, or the conversational
 * designer. Authoring is deliberately gated behind an explicit "design a new
 * workflow" action so the default surface is safe inspection. */
function WorkflowShell({
  client,
  data,
  onCatalogRevision,
}: {
  readonly client: OperatorApiClient;
  readonly data: CombinedData;
  readonly onCatalogRevision: (revision: string | null) => void;
}) {
  const [mode, setMode] = useState<WorkflowBuilderMode>(
    () => workflowBuilderMode(currentRoute().search.get("mode")),
  );
  const [seedName, setSeedName] = useState<string | null>(
    () => currentRoute().search.get("from"),
  );
  useEffect(() => {
    const sync = () => {
      const search = currentRoute().search;
      setMode(workflowBuilderMode(search.get("mode")));
      setSeedName(search.get("from"));
    };
    window.addEventListener("popstate", sync);
    window.addEventListener("fdai:route-changed", sync);
    window.addEventListener(ROUTE_STATE_EVENT, sync);
    return () => {
      window.removeEventListener("popstate", sync);
      window.removeEventListener("fdai:route-changed", sync);
      window.removeEventListener(ROUTE_STATE_EVENT, sync);
    };
  }, []);
  // Mode changes update history without remounting the panel, so loaded
  // catalogs, filters, and an in-progress draft survive the switch.
  const openMode = useCallback((next: WorkflowBuilderMode, from: string | null = null): void => {
    pushRouteState(workflowBuilderHref(currentRoute().search, {
      mode: next === "list" ? null : next,
      from,
    }));
  }, []);
  const seed = useMemo<WorkflowChatSeed | null>(() => {
    if (mode !== "new" || seedName === null) return null;
    const group = workflowGroup(currentRoute().search.get("group"));
    const source = group === "built_in"
      ? data.workflows.find((workflow) => workflow.name === seedName)
      : data.definitions.groups[group]
        .map(workflowFromDefinition)
        .find((workflow) => workflow.name === seedName);
    return source ? { form: catalogToForm(source), source: source.name } : null;
  }, [data.definitions.groups, data.workflows, mode, seedName]);
  const gateRefs = useMemo(() => workflowGateRefs([
    ...data.workflows,
    ...Object.values(data.definitions.groups).flatMap((group) =>
      group.map((definition) => definition.workflow_document)
    ),
  ]), [data.definitions.groups, data.workflows]);

  usePublishViewContext(
    () => {
      const isNew = mode === "new";
      // In the designer, ground the deck in the ActionType palette so "what
      // can this do / what does <action> mean?" is answerable. In the list
      // view, ground it in the shipped workflows instead.
      const records: Record<string, readonly Record<string, unknown>[]> = isNew
        ? {
            action_types: data.palette.map((p) => ({
              name: p.name,
              category: p.category ?? "-",
              rollback: p.rollback_contract,
              hil_tiers: p.hil_tiers.length > 0 ? p.hil_tiers.join(",") : "none",
              summary: p.description ?? "-",
            })),
          }
        : {
            workflows: data.workflows.map((w) => ({
              name: w.name,
              description: w.description ?? "-",
              trigger:
                w.trigger.kind === "signal" ? w.trigger.signal_type : w.trigger.schedule,
              steps: w.step_count,
              step_actions: w.steps.map((s) =>
                s.action_type_ref
                ?? s.wait_for
                ?? s.approval_role
                ?? s.gate_ref
                ?? s.kind
                ?? s.id
              ).join(" -> "),
              mode: w.default_mode,
            })),
          };
      return {
        routeId: "workflow-builder",
        routeLabel: t("workflow.builder.routeLabel"),
        purpose: t("workflow.builder.purpose"),
        glossary: composeGlossary([TERMS.actionType, TERMS.shadowMode, TERMS.mode]),
        headline: isNew
          ? t("workflow.builder.headlineNew", { count: formatNumber(data.palette.length) })
          : t("workflow.builder.headlineList", {
              workflows: formatNumber(data.workflows.length),
              actions: formatNumber(data.palette.length),
            }),
        capturedAt: new Date().toISOString(),
        facts: [
          { key: "built_in_count", value: data.workflows.length, group: "workflow" },
          { key: "palette_size", value: data.palette.length, group: "workflow" },
          {
            key: "mode",
            value: t(isNew ? "workflow.builder.modeNew" : "workflow.builder.modeList"),
            group: "workflow",
          },
          ...(isNew
            ? [
                {
                  key: "default_mode",
                  value: t("workflow.builder.defaultMode"),
                  group: "workflow",
                },
              ]
            : []),
        ],
        records,
      };
    },
    [data.workflows, data.palette, mode],
  );

  if (mode === "new") {
    return (
      <WorkflowChat
        client={client}
        palette={data.palette}
        gateRefs={gateRefs}
        onBack={() => openMode("list")}
        seed={seed}
        onSeedConsumed={() => replaceRouteState(
          workflowBuilderHref(currentRoute().search, { from: null }),
        )}
      />
    );
  }
  if (mode === "python") {
    return data.pythonTasks !== null && data.pythonTasks.available
      ? <PythonTaskWorkbench availability={data.pythonTasks} onBack={() => openMode("list")} />
      : (
        <div class="stack">
          <div class="state-block state-unavailable" role="status">
            {pythonTaskUnavailableMessage(data.pythonTasks)}
          </div>
          <div>
            <button type="button" class="btn btn-small" onClick={() => openMode("list")}>
              &larr; {t("workflow.pythonTask.back")}
            </button>
          </div>
        </div>
      );
  }
  return (
    <BuiltInList
      client={client}
      workflows={data.workflows}
      definitions={data.definitions}
      palette={data.palette}
      pythonTasks={data.pythonTasks}
      onNew={() => openMode("new")}
      onClone={(workflow) => openMode("new", workflow)}
      onPython={() => openMode("python")}
      onCatalogRevision={onCatalogRevision}
    />
  );
}
