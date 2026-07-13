import { useEffect, useState } from "preact/hooks";
import { ReadApiError } from "../api";
import type { ReadApiClient } from "../api";
import {
  AsyncBoundary,
  KpiCard,
  KpiGrid,
  PageHeader,
  type AsyncState,
} from "../components/ui";
import { MermaidDiagram } from "../components/mermaid-diagram";
import { usePublishViewContext } from "../deck/context";
import { TERMS, agentTerm, composeGlossary } from "../deck/glossary";
import { t } from "../i18n";
import { panelArray, panelBoolean, panelNullableString, panelNumber, panelRecord, panelString, panelStringArray } from "./panel-decode";

/**
 * Pantheon panel. Fetches ``GET /pantheon/graph`` and
 * ``GET /pantheon/workflows`` and renders the 15 agents plus the 10
 * cross-agent workflows as read-only tables.
 *
 * Endpoints are opt-in on the API side
 * (``ReadApiConfig.expose_pantheon=True``). When they are not wired,
 * the panel surfaces a friendly "unavailable" state.
 */

interface AgentDto {
  readonly name: string;
  readonly layer: string;
  readonly reports_to: string | null;
  readonly owns: readonly string[];
  readonly executes: readonly string[];
  readonly subscribes: readonly string[];
  readonly publishes: readonly string[];
  readonly question_domains: readonly string[];
  readonly hot_path_llm: boolean;
  readonly off_path_llm: boolean;
  readonly hard_dependency: boolean;
}

interface PantheonGraphResponse {
  readonly agents: readonly AgentDto[];
  readonly org_edges: readonly { readonly from: string | null; readonly to: string }[];
  readonly agent_count: number;
  readonly hard_dependency_agents: readonly string[];
  readonly hot_path_llm_agents: readonly string[];
  readonly mermaid: string;
}

interface WorkflowDto {
  readonly id: string;
  readonly name: string;
  readonly primary_agent: string;
  readonly participating_agents: readonly string[];
  readonly trigger: string;
  readonly default_mode: string;
  readonly promotion_gate: string;
}

interface PantheonWorkflowsResponse {
  readonly workflows: readonly WorkflowDto[];
  readonly count: number;
}

interface CombinedData {
  readonly graph: PantheonGraphResponse;
  readonly workflows: PantheonWorkflowsResponse;
}

interface Props {
  readonly client: ReadApiClient;
}

export function PantheonRoute({ client }: Props) {
  const [state, setState] = useState<AsyncState<CombinedData>>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    (async () => {
      try {
        const [graph, workflows] = await Promise.all([
          client.panel<unknown>("/pantheon/graph").then(decodePantheonGraph),
          client.panel<unknown>("/pantheon/workflows").then(decodePantheonWorkflows),
        ]);
        if (!cancelled) {
          setState({ status: "ready", data: { graph, workflows } });
        }
      } catch (err) {
        if (!cancelled) {
          const message = err instanceof Error ? err.message : String(err);
          if (err instanceof ReadApiError && err.status === 404) {
            setState({
              status: "unavailable",
              message:
                "The pantheon endpoints are not wired on this deployment. " +
                "Set ReadApiConfig.expose_pantheon=True in the composition root to enable them.",
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
      <PageHeader
        title={t("route.pantheon")}
        subtitle="15 named agents that own the runtime control plane + 10 cross-agent workflows they compose."
      />
      <AsyncBoundary state={state} resourceLabel="pantheon">
        {(data) => <PantheonBody data={data} />}
      </AsyncBoundary>
    </div>
  );
}

function decodePantheonGraph(value: unknown): PantheonGraphResponse {
  const root = panelRecord(value, "pantheon graph");
  return {
    agents: panelArray(root["agents"], "pantheon graph.agents").map((value, index) => {
      const agent = panelRecord(value, `pantheon graph.agents[${index}]`);
      return {
        name: panelString(agent, "name", "pantheon agent"),
        layer: panelString(agent, "layer", "pantheon agent"),
        reports_to: panelNullableString(agent, "reports_to", "pantheon agent"),
        owns: panelStringArray(agent["owns"], "pantheon agent.owns"),
        executes: panelStringArray(agent["executes"], "pantheon agent.executes"),
        subscribes: panelStringArray(agent["subscribes"], "pantheon agent.subscribes"),
        publishes: panelStringArray(agent["publishes"], "pantheon agent.publishes"),
        question_domains: panelStringArray(agent["question_domains"], "pantheon agent.question_domains"),
        hot_path_llm: panelBoolean(agent, "hot_path_llm", "pantheon agent"),
        off_path_llm: panelBoolean(agent, "off_path_llm", "pantheon agent"),
        hard_dependency: panelBoolean(agent, "hard_dependency", "pantheon agent"),
      };
    }),
    org_edges: panelArray(root["org_edges"], "pantheon graph.org_edges").map((value, index) => {
      const edge = panelRecord(value, `pantheon graph.org_edges[${index}]`);
      return {
        from: panelNullableString(edge, "from", "pantheon org edge"),
        to: panelString(edge, "to", "pantheon org edge"),
      };
    }),
    agent_count: panelNumber(root, "agent_count", "pantheon graph"),
    hard_dependency_agents: panelStringArray(root["hard_dependency_agents"], "pantheon graph.hard_dependency_agents"),
    hot_path_llm_agents: panelStringArray(root["hot_path_llm_agents"], "pantheon graph.hot_path_llm_agents"),
    mermaid: panelString(root, "mermaid", "pantheon graph"),
  };
}

function decodePantheonWorkflows(value: unknown): PantheonWorkflowsResponse {
  const root = panelRecord(value, "pantheon workflows");
  return {
    workflows: panelArray(root["workflows"], "pantheon workflows.workflows").map((value, index) => {
      const workflow = panelRecord(value, `pantheon workflows.workflows[${index}]`);
      return {
        id: panelString(workflow, "id", "pantheon workflow"),
        name: panelString(workflow, "name", "pantheon workflow"),
        primary_agent: panelString(workflow, "primary_agent", "pantheon workflow"),
        participating_agents: panelStringArray(workflow["participating_agents"], "pantheon workflow.participating_agents"),
        trigger: panelString(workflow, "trigger", "pantheon workflow"),
        default_mode: panelString(workflow, "default_mode", "pantheon workflow"),
        promotion_gate: panelString(workflow, "promotion_gate", "pantheon workflow"),
      };
    }),
    count: panelNumber(root, "count", "pantheon workflows"),
  };
}

function PantheonBody({ data }: { readonly data: CombinedData }) {
  const { graph, workflows } = data;
  usePublishViewContext(
    () => ({
      routeId: "pantheon",
      routeLabel: "Pantheon",
      purpose:
        "The 15 fixed pantheon agents and how they hand work off - who senses, " +
        "judges, executes, approves, and audits. Shows reporting lines, owned " +
        "action kinds, and which agents sit on the hot path. Read-only.",
      glossary: composeGlossary([agentTerm(), TERMS.hil, TERMS.actionType]),
      headline: `${graph.agent_count} agents - ${workflows.count} workflows`,
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "agent_count", value: graph.agent_count, group: "pantheon" },
        { key: "workflow_count", value: workflows.count, group: "pantheon" },
        {
          key: "hard_dependency_count",
          value: graph.hard_dependency_agents.length,
          group: "pantheon",
        },
        {
          key: "hot_path_llm_count",
          value: graph.hot_path_llm_agents.length,
          group: "pantheon",
        },
      ],
      records: {
        agents: graph.agents.map((a) => ({
          name: a.name,
          layer: a.layer,
          reports_to: a.reports_to ?? "",
          owns: a.owns.join(", ") || "-",
          executes: a.executes.join(", ") || "-",
          question_domains: a.question_domains.join(", ") || "-",
          hard_dependency: a.hard_dependency ? "yes" : "no",
          hot_path_llm: a.hot_path_llm ? "yes" : "no",
        })),
        workflows: workflows.workflows.map((w) => ({
          id: w.id,
          name: w.name,
          primary_agent: w.primary_agent,
          participating_agents: w.participating_agents.join(", ") || "-",
          trigger: w.trigger,
          default_mode: w.default_mode,
        })),
      },
    }),
    [graph, workflows],
  );

  return (
    <div class="stack">
      <KpiGrid>
        <KpiCard label="Agents" value={graph.agent_count} />
        <KpiCard label="Workflows" value={workflows.count} />
        <KpiCard label="Hard dependencies" value={graph.hard_dependency_agents.length} />
        <KpiCard label="Hot-path LLM" value={graph.hot_path_llm_agents.length} />
      </KpiGrid>

      <section class="stack-section">
        <div class="section-header">
          <h3 class="section-title">Org chart</h3>
        </div>
        <MermaidDiagram source={graph.mermaid} ariaLabel="Agent org chart" />
        <details class="mermaid-source-toggle">
          <summary class="details-summary">Show Mermaid source</summary>
          <pre class="mono scroll code-block">{graph.mermaid}</pre>
        </details>
      </section>

      <section class="stack-section">
        <h3 class="section-title">Agents ({graph.agents.length})</h3>
        <div class="scroll">
          <table class="data-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Layer</th>
                <th>Reports to</th>
                <th>Owns</th>
                <th>Flags</th>
              </tr>
            </thead>
            <tbody>
              {graph.agents.map((a) => (
                <tr key={a.name}>
                  <td class="mono">{a.name}</td>
                  <td>{a.layer}</td>
                  <td class="mono muted">{a.reports_to ?? "-"}</td>
                  <td>
                    <ChipList items={a.owns} />
                  </td>
                  <td>
                    {a.hard_dependency ? <span class="badge hil">hard-dep</span> : null}
                    {a.hot_path_llm ? <span class="badge shadow">hot-LLM</span> : null}
                    {a.off_path_llm ? <span class="badge shadow">batch-LLM</span> : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section class="stack-section">
        <h3 class="section-title">Workflows ({workflows.workflows.length})</h3>
        <div class="scroll">
          <table class="data-table">
            <thead>
              <tr>
                <th>Id</th>
                <th>Name</th>
                <th>Primary</th>
                <th>Participants</th>
                <th>Mode</th>
              </tr>
            </thead>
            <tbody>
              {workflows.workflows.map((w) => (
                <tr key={w.id}>
                  <td class="mono">{w.id}</td>
                  <td>{w.name}</td>
                  <td class="mono">{w.primary_agent}</td>
                  <td>
                    <ChipList items={w.participating_agents} />
                  </td>
                  <td>
                    <span
                      class={
                        w.default_mode === "enforce"
                          ? "badge enforce"
                          : "badge shadow"
                      }
                    >
                      {w.default_mode}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function ChipList({ items }: { readonly items: readonly string[] }) {
  if (items.length === 0) {
    return <span class="muted">-</span>;
  }
  return (
    <ul class="type-chip-list">
      {items.map((name) => (
        <li key={name} class="type-chip mono">{name}</li>
      ))}
    </ul>
  );
}
