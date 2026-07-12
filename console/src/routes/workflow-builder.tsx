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
 * SRP: this file owns the route shell, the read-only catalog list, and the
 * per-workflow detail drawer. The conversational designer and its engine live
 * in the sibling `workflow-builder.chat*` modules; pure helpers, the intent
 * matcher, and the shared model live in `workflow-builder.{helpers,intent,model}`.
 */

import { useEffect, useState } from "preact/hooks";
import { ReadApiError } from "../api";
import type { ReadApiClient } from "../api";
import { AsyncBoundary, CopyButton, PageHeader, type AsyncState } from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { t } from "../i18n";
import type {
  ActionTypePaletteResponse,
  WorkflowCatalogEntry,
  WorkflowCatalogResponse,
} from "../workflow/validate";
import type { CombinedData } from "./workflow-builder.model";
import { formatParams } from "./workflow-builder.helpers";
import { WorkflowChat } from "./workflow-builder.chatpanel";

// Re-export the pure helpers the vitest suite pins so `./workflow-builder`
// stays a stable public import surface (workflow-builder.test.ts).
export { buildGithubNewFileUrl, humanizeName, suggestStepId } from "./workflow-builder.helpers";
export { suggestDraftFromText } from "./workflow-builder.intent";

interface Props {
  readonly client: ReadApiClient;
}

export function WorkflowBuilderRoute({ client }: Props) {
  const [state, setState] = useState<AsyncState<CombinedData>>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    (async () => {
      try {
        const [palette, catalog] = await Promise.all([
          client.panel<ActionTypePaletteResponse>("/workflows/action-types"),
          client.panel<WorkflowCatalogResponse>("/workflows/catalog"),
        ]);
        if (!cancelled) {
          setState({
            status: "ready",
            data: { palette: palette.action_types, workflows: catalog.workflows },
          });
        }
      } catch (err) {
        if (!cancelled) {
          const message = err instanceof Error ? err.message : String(err);
          if (err instanceof ReadApiError && err.status === 404) {
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
    <div class="stack">
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
  const [mode, setMode] = useState<"list" | "new">("list");

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
  return <BuiltInList workflows={data.workflows} onNew={() => setMode("new")} />;
}

/** Read-only list of shipped workflows + a details drawer per row, fronted by
 * a single call-to-action that opens the conversational designer. */
function BuiltInList({
  workflows,
  onNew,
}: {
  readonly workflows: readonly WorkflowCatalogEntry[];
  readonly onNew: () => void;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const current = workflows.find((w) => w.name === selected) ?? null;

  const needle = filter.trim().toLowerCase();
  const shown = needle
    ? workflows.filter((w) => {
        const trig =
          w.trigger.kind === "signal" ? w.trigger.signal_type ?? "" : w.trigger.schedule ?? "";
        return (
          w.name.toLowerCase().includes(needle) ||
          w.trigger.kind.includes(needle) ||
          trig.toLowerCase().includes(needle) ||
          w.default_mode.includes(needle)
        );
      })
    : workflows;
  const shadowCount = workflows.filter((w) => w.default_mode !== "enforce").length;
  const enforceCount = workflows.length - shadowCount;

  return (
    <div class="stack">
      <div class="callout">
        <strong>Design a workflow by chatting.</strong> A workflow is a business process - a
        trigger plus an ordered chain of actions the control plane runs for you, each with a
        built-in safety net (stop-condition, rollback, blast-radius cap, audit). Describe what you
        want in plain words; the designer asks a few questions, shows you the exact YAML and a
        visual of how it runs, and lets you test it. Nothing is created until you open a PR.
      </div>

      <div class="section-header">
        <button type="button" class="btn" onClick={onNew}>
          + Design a new workflow
        </button>
      </div>

      <section class="stack-section">
        <div class="section-header">
          <h3 class="section-title">Browse the full catalog ({workflows.length})</h3>
        </div>
        <p class="muted small">
          The shipped workflows, for reference: open a row to see every step and the raw YAML.
        </p>
        {workflows.length === 0 ? (
          <p class="muted small">No built-in workflows are served on this deployment.</p>
        ) : (
          <>
            <div class="list-toolbar">
              <input
                class="form-input"
                type="search"
                value={filter}
                placeholder="Filter by name, trigger, or mode..."
                aria-label="Filter workflows"
                onInput={(e) => setFilter((e.target as HTMLInputElement).value)}
              />
              <span class="muted small">
                Showing {shown.length} of {workflows.length} - {shadowCount} shadow,{" "}
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
                  {shown.map((w) => {
                    const isOpen = w.name === selected;
                    const toggle = () => setSelected(isOpen ? null : w.name);
                    return (
                      <tr
                        key={w.name}
                        class={isOpen ? "row-active" : ""}
                        onClick={toggle}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            toggle();
                          }
                        }}
                        tabIndex={0}
                        role="button"
                        aria-expanded={isOpen}
                        style="cursor: pointer"
                      >
                        <td class="mono">{w.name}</td>
                        <td class="mono muted">
                          <span class="badge tag">{w.trigger.kind}</span>{" "}
                          {w.trigger.kind === "signal" ? w.trigger.signal_type : w.trigger.schedule}
                        </td>
                        <td>{w.step_count}</td>
                        <td>
                          <span
                            class={w.default_mode === "enforce" ? "badge enforce" : "badge shadow"}
                          >
                            {w.default_mode}
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

      {current ? <WorkflowDetail workflow={current} /> : null}
    </div>
  );
}

/** Read-only detail: property table + steps + raw catalog YAML. */
function WorkflowDetail({ workflow }: { readonly workflow: WorkflowCatalogEntry }) {
  const gate = workflow.promotion_gate;
  return (
    <section class="stack-section">
      <div class="section-header">
        <h3 class="section-title mono">{workflow.name}</h3>
      </div>
      {workflow.description ? <p class="muted">{workflow.description}</p> : null}
      <div class="prop-grid">
        <div class="prop">
          <span class="prop-label">Version</span>
          <span class="mono">{workflow.version}</span>
        </div>
        <div class="prop">
          <span class="prop-label">Trigger</span>
          <span class="mono">
            {workflow.trigger.kind}:{" "}
            {workflow.trigger.kind === "signal"
              ? workflow.trigger.signal_type
              : workflow.trigger.schedule}
          </span>
        </div>
        <div class="prop">
          <span class="prop-label">Default mode</span>
          <span class={workflow.default_mode === "enforce" ? "badge enforce" : "badge shadow"}>
            {workflow.default_mode}
          </span>
        </div>
        <div class="prop">
          <span class="prop-label">Promotion gate</span>
          <span class="mono small">
            {gate.min_shadow_days}d, {gate.min_samples} samples, acc &ge; {gate.min_accuracy},
            escapes &le; {gate.max_policy_escapes}
          </span>
        </div>
      </div>

      <h4 class="section-subtitle">Steps ({workflow.steps.length})</h4>
      <div class="scroll">
        <table class="data-table">
          <thead>
            <tr>
              <th>#</th>
              <th>Step id</th>
              <th>ActionType</th>
              <th>Guard</th>
              <th>Compensated by</th>
              <th>On failure</th>
              <th>Params</th>
            </tr>
          </thead>
          <tbody>
            {workflow.steps.map((s, i) => (
              <tr key={s.id}>
                <td>{i + 1}</td>
                <td class="mono">{s.id}</td>
                <td class="mono">{s.action_type_ref}</td>
                <td class="mono muted">{s.guard_rule_ref ?? "-"}</td>
                <td class="mono muted">{s.compensated_by ?? "-"}</td>
                <td class="mono muted">{s.on_failure ?? "-"}</td>
                <td class="mono muted">{formatParams(s.params)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {workflow.anti_scope ? (
        <p class="muted small">
          <strong>Anti-scope:</strong> {workflow.anti_scope}
        </p>
      ) : null}

      <div class="code-actions">
        <CopyButton text={workflow.yaml} label="Copy YAML" />
      </div>
      <pre class="mono scroll code-block">{workflow.yaml}</pre>
    </section>
  );
}
