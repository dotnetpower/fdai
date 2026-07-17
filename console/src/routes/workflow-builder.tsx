/**
 * Workflow builder route - browse the built-in workflow catalog read-only,
 * or design a new workflow by chatting with a deterministic assistant.
 *
 * Authoring is conversational, not a form: the operator describes what they
 * want in plain words and the designer (workflow-builder.chat.ts / .tsx)
 * asks follow-up questions, proposes options, shows the generated YAML, and
 * lets them dry-test it. Read-only by construction - `POST /workflows/validate`
 * is a pure check and nothing here mutates control-plane state. The output is
 * canonical YAML the operator copies into a `rule-catalog/workflows/<name>.yaml`
 * remediation PR through the git-native path, never a console button
 * (app-shape.instructions.md § Operator console). New workflows are locked to
 * `shadow` mode - promotion to enforce is a separate governance PR
 * (process-automation.md § 6).
 *
 * SRP: this file owns route loading and top-level mode selection. Catalog,
 * detail, automation, chat, and Python-task surfaces live in sibling modules.
 */

import { useEffect, useState } from "preact/hooks";
import { isOptionalReadApiUnavailable } from "../api";
import type { ReadApiClient } from "../api";
import { AsyncBoundary, PageHeader, type AsyncState } from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { t } from "../i18n";
import type {
  ActionTypePaletteResponse,
  WorkflowCatalogResponse,
  WorkflowDefinitionCatalogResponse,
} from "../workflow/validate";
import type { CombinedData } from "./workflow-builder.model";
import { BuiltInList } from "./workflow-builder.catalog";
import { WorkflowChat } from "./workflow-builder.chatpanel";
import { PythonTaskWorkbench } from "./workflow-builder.python-task";

// Re-export the pure helpers the vitest suite pins so `./workflow-builder`
// stays a stable public import surface (workflow-builder.test.ts).
export { buildGithubNewFileUrl, humanizeName, suggestStepId } from "./workflow-builder.helpers";
export { suggestDraftFromText } from "./workflow-builder.intent";
export { hasEquivalentWorkflowBinding } from "./workflow-builder.automations";
export { workflowStepHref } from "./workflow-builder.detail";
export { hasActionTypeRef, requestedActionType, workflowSelection } from "./workflow-builder.model";

interface Props {
  readonly client: ReadApiClient;
}

const EMPTY_WORKFLOW_DEFINITIONS: WorkflowDefinitionCatalogResponse = {
  groups: { built_in: [], shared: [], mine: [] },
  bindings: [],
  counts: { built_in: 0, shared: 0, mine: 0 },
};

export async function loadWorkflowDefinitions(
  client: Pick<ReadApiClient, "panel">,
): Promise<WorkflowDefinitionCatalogResponse> {
  try {
    return await client.panel<WorkflowDefinitionCatalogResponse>("/workflows/definitions");
  } catch (error) {
    if (isOptionalReadApiUnavailable(error)) return EMPTY_WORKFLOW_DEFINITIONS;
    throw error;
  }
}

export function WorkflowBuilderRoute({ client }: Props) {
  const [state, setState] = useState<AsyncState<CombinedData>>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    (async () => {
      try {
        const [palette, catalog, definitions] = await Promise.all([
          client.panel<ActionTypePaletteResponse>("/workflows/action-types"),
          client.panel<WorkflowCatalogResponse>("/workflows/catalog"),
          loadWorkflowDefinitions(client),
        ]);
        if (!cancelled) {
          setState({
            status: "ready",
            data: {
              palette: palette.action_types,
              workflows: catalog.workflows,
              definitions,
            },
          });
        }
      } catch (err) {
        if (!cancelled) {
          const message = err instanceof Error ? err.message : String(err);
          if (isOptionalReadApiUnavailable(err)) {
            setState({
              status: "unavailable",
              message:
                "The workflow authoring routes are not wired on this deployment. " +
                "Set ReadApiConfig.workflow_authoring in the composition root to enable them.",
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
      <PageHeader title={t("route.workflowBuilder")} subtitle={t("workflowBuilder.subtitle")} />
      <AsyncBoundary state={state} resourceLabel="workflow builder">
        {(data) => <WorkflowShell data={data} />}
      </AsyncBoundary>
    </div>
  );
}
/** Top-level view switch: the read-only built-in list, or the conversational
 * designer. Authoring is deliberately gated behind an explicit "design a new
 * workflow" action so the default surface is safe inspection. */
function WorkflowShell({ data }: { readonly data: CombinedData }) {
  const [mode, setMode] = useState<"list" | "new" | "python">("list");

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
              step_actions: w.steps.map((s) => s.action_type_ref).join(" -> "),
              mode: w.default_mode,
            })),
          };
      return {
        routeId: "workflow-builder",
        routeLabel: "Workflow builder",
        purpose:
          "Inspect the built-in workflows (a trigger plus an ordered chain of " +
          "ActionType steps) and design a new one by chatting with the builder. " +
          "New workflows are locked to shadow mode; promotion to enforce is a " +
          "separate reviewed PR. Read-only by construction.",
        glossary: composeGlossary([TERMS.actionType, TERMS.shadowMode, TERMS.mode]),
        headline: isNew
          ? `Conversational workflow designer open - ${data.palette.length} ActionTypes available`
          : `${data.workflows.length} built-in workflows - ${data.palette.length} ActionTypes`,
        capturedAt: new Date().toISOString(),
        facts: [
          { key: "built_in_count", value: data.workflows.length, group: "workflow" },
          { key: "palette_size", value: data.palette.length, group: "workflow" },
          { key: "mode", value: isNew ? "new (chat designer)" : "list", group: "workflow" },
          ...(isNew
            ? [
                {
                  key: "default_mode",
                  value: "shadow (locked; promotion is a separate PR)",
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
    return <WorkflowChat palette={data.palette} onBack={() => setMode("list")} />;
  }
  if (mode === "python") {
    return <PythonTaskWorkbench onBack={() => setMode("list")} />;
  }
  return (
    <BuiltInList
      workflows={data.workflows}
      definitions={data.definitions}
      palette={data.palette}
      onNew={() => setMode("new")}
      onPython={() => setMode("python")}
    />
  );
}
