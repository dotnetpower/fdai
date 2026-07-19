import { useEffect, useMemo, useReducer, useState } from "preact/hooks";
import { isOptionalReadApiUnavailable } from "../api";
import type { ReadApiClient } from "../api";
import { AgentOrgChart } from "../components/agent-org-chart";
import { AgentWorkspaceNav } from "../components/agent-workspace-nav";
import {
  AsyncBoundary,
  PageHeader,
  type AsyncState,
} from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, agentTerm, composeGlossary } from "../deck/glossary";
import { agentStreamDescriptor, useAgentStream, type AgentStreamStatus } from "../hooks/use-agent-stream";
import { observationSourceLabel, type ObservationSource } from "../hooks/observation-source";
import { t } from "../i18n";
import { currentRoute, navigate, routeHref } from "../router";
import {
  activeAgentCount,
  AGENT_ROLE,
  makeInitialState,
  PANTHEON,
  reducer,
  STATE_TASK,
  type AgentsState,
} from "./agents.model";
import { panelArray, panelBoolean, panelContractError, panelNullableString, panelNumber, panelRecord, panelString, panelStringArray } from "./panel-decode";

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

export function pantheonAgentHref(agent: string, correlation?: string | null): string {
  return routeHref("agents", {
    params: { view: "org", agent, correlation: correlation || null },
  });
}

export function PantheonRoute({ client }: Props) {
  const [state, setState] = useState<AsyncState<CombinedData>>({ status: "loading" });
  const [runtime, dispatch] = useReducer(reducer, undefined, makeInitialState);
  const stream = useMemo(agentStreamDescriptor, []);
  const { status: streamStatus, source: streamSource } = useAgentStream({
    url: stream.url,
    getAuthorizationHeader: client.authorizationHeader,
    onEvent: (message) => dispatch({ kind: "message", msg: message }),
  });

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
          if (isOptionalReadApiUnavailable(err)) {
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
    <div class="stack pantheon-route">
      <AgentWorkspaceNav />
      <PageHeader
        title={t("route.pantheon")}
        subtitle="The fixed 15-agent organization, enriched with each agent's current runtime state."
      />
      <AsyncBoundary state={state} resourceLabel="pantheon">
        {(data) => (
          <PantheonBody
            data={data}
            runtime={runtime}
            streamStatus={streamStatus}
            streamSource={streamSource}
          />
        )}
      </AsyncBoundary>
    </div>
  );
}

export function decodePantheonGraph(value: unknown): PantheonGraphResponse {
  const root = panelRecord(value, "pantheon graph");
  const agents = panelArray(root["agents"], "pantheon graph.agents").map((value, index) => {
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
    });
  const agentCount = panelNumber(root, "agent_count", "pantheon graph");
  const expectedNames = PANTHEON.map((agent) => agent.name);
  const actualNames = agents.map((agent) => agent.name);
  if (agentCount !== agents.length) {
    throw panelContractError("pantheon graph.agent_count MUST match agents.length");
  }
  if (
    actualNames.length !== expectedNames.length ||
    new Set(actualNames).size !== actualNames.length ||
    expectedNames.some((name) => !actualNames.includes(name))
  ) {
    throw panelContractError("pantheon graph.agents MUST contain the fixed 15-agent pantheon exactly once");
  }
  const parentByAgent = new Map(agents.map((agent) => [agent.name, agent.reports_to]));
  if (parentByAgent.get("Odin") !== null || agents.filter((agent) => agent.reports_to === null).length !== 1) {
    throw panelContractError("pantheon graph.agents MUST have Odin as its only reporting root");
  }
  for (const agent of agents) {
    const visited = new Set<string>();
    let current: string | null = agent.name;
    while (current !== null) {
      if (visited.has(current)) {
        throw panelContractError(`pantheon graph reporting chain for ${agent.name} MUST be acyclic`);
      }
      visited.add(current);
      if (!parentByAgent.has(current)) {
        throw panelContractError(`pantheon graph reporting chain for ${agent.name} MUST reference known agents`);
      }
      current = parentByAgent.get(current) ?? null;
    }
    if (!visited.has("Odin")) {
      throw panelContractError(`pantheon graph reporting chain for ${agent.name} MUST terminate at Odin`);
    }
  }
  return {
    agents,
    org_edges: panelArray(root["org_edges"], "pantheon graph.org_edges").map((value, index) => {
      const edge = panelRecord(value, `pantheon graph.org_edges[${index}]`);
      return {
        from: panelNullableString(edge, "from", "pantheon org edge"),
        to: panelString(edge, "to", "pantheon org edge"),
      };
    }),
    agent_count: agentCount,
    hard_dependency_agents: panelStringArray(root["hard_dependency_agents"], "pantheon graph.hard_dependency_agents"),
    hot_path_llm_agents: panelStringArray(root["hot_path_llm_agents"], "pantheon graph.hot_path_llm_agents"),
    mermaid: panelString(root, "mermaid", "pantheon graph"),
  };
}

export function decodePantheonWorkflows(value: unknown): PantheonWorkflowsResponse {
  const root = panelRecord(value, "pantheon workflows");
  const workflows = panelArray(root["workflows"], "pantheon workflows.workflows").map((value, index) => {
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
    });
  const count = panelNumber(root, "count", "pantheon workflows");
  const knownAgents = new Set(PANTHEON.map((agent) => agent.name));
  if (count !== workflows.length) {
    throw panelContractError("pantheon workflows.count MUST match workflows.length");
  }
  if (new Set(workflows.map((workflow) => workflow.id)).size !== workflows.length) {
    throw panelContractError("pantheon workflows.id MUST be unique");
  }
  for (const workflow of workflows) {
    if (!knownAgents.has(workflow.primary_agent)) {
      throw panelContractError(`pantheon workflow ${workflow.id} primary_agent MUST be a fixed agent`);
    }
    if (
      workflow.participating_agents.some((agent) => !knownAgents.has(agent)) ||
      !workflow.participating_agents.includes(workflow.primary_agent)
    ) {
      throw panelContractError(`pantheon workflow ${workflow.id} participants MUST be fixed agents and include primary_agent`);
    }
  }
  return { workflows, count };
}

const LAYER_ORDER = ["governance", "pipeline", "domain"] as const;
const LAYER_COPY: Readonly<Record<string, string>> = {
  governance: "Direction, memory, learning, and audit",
  pipeline: "Sense, judge, approve, execute, and recover",
  domain: "Advisory specialists that never execute",
};

type PantheonView = "directory" | "org";

export function pantheonViewFromSearch(search: URLSearchParams): PantheonView {
  return search.get("view") === "org" ? "org" : "directory";
}

function pantheonViewFromRoute(): PantheonView {
  return pantheonViewFromSearch(currentRoute().search);
}

function PantheonBody({
  data,
  runtime,
  streamStatus,
  streamSource,
}: {
  readonly data: CombinedData;
  readonly runtime: AgentsState;
  readonly streamStatus: AgentStreamStatus;
  readonly streamSource: ObservationSource;
}) {
  const { graph, workflows } = data;
  const active = activeAgentCount(runtime);
  const [view, setView] = useState<PantheonView>(pantheonViewFromRoute);

  const openView = (next: PantheonView): void => {
    setView(next);
    navigate(routeHref("pantheon", { params: { view: next === "directory" ? null : next } }));
  };
  usePublishViewContext(
    () => ({
      routeId: "pantheon",
      routeLabel: "Pantheon",
      purpose:
        "The 15 fixed pantheon agents and how they hand work off - who senses, " +
        "judges, executes, approves, and audits. Shows reporting lines, owned " +
        "action kinds, and which agents sit on the hot path. Read-only.",
      glossary: composeGlossary([agentTerm(), TERMS.hil, TERMS.actionType]),
      headline: `${graph.agent_count} agents - ${workflows.count} workflows - ${view} view`,
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
        { key: "engaged_agents", value: active, group: "runtime" },
        { key: "stream_status", value: streamStatus, group: "runtime" },
        { key: "stream_source", value: observationSourceLabel(streamSource), group: "runtime" },
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
    [graph, workflows, active, streamStatus, streamSource, view],
  );

  return (
    <div class="stack pantheon-directory">
      <section class="pantheon-source-banner" aria-label="Pantheon data source">
        <div>
          <strong>Read-only organization</strong>
          <span>
            Cards come from the fork-locked pantheon registry. Runtime state comes from
            <code> GET /agents/stream</code> and never grants execution authority.
          </span>
        </div>
        <div class="pantheon-source-state">
          <span class={`agents-conn conn-${streamStatus}`}>{streamStatus}</span>
          <span class="status-pill status-pill-neutral">
            {observationSourceLabel(streamSource)}
          </span>
          <span><strong>{active}</strong> engaged</span>
        </div>
      </section>

      <div class="pantheon-view-bar">
        <div>
          <strong>{view === "directory" ? "Agent directory" : "Reporting organization"}</strong>
          <span>
            {view === "directory"
              ? "Compare ownership, dependencies, and runtime work by layer."
              : "Follow reporting lines, inspect live state, and open an agent for detail."}
          </span>
        </div>
        <div class="agents-layout-toggle" role="group" aria-label="Pantheon view">
          <button
            type="button"
            class={view === "directory" ? "is-active" : ""}
            aria-pressed={view === "directory"}
            onClick={() => openView("directory")}
          >
            Directory
          </button>
          <button
            type="button"
            class={view === "org" ? "is-active" : ""}
            aria-pressed={view === "org"}
            onClick={() => openView("org")}
          >
            Org chart
          </button>
        </div>
      </div>

      <div class="pantheon-legend" aria-label="Pantheon flags">
        <span class="pt-badge is-hotllm">hot-path LLM</span>
        <span class="pt-badge is-offllm">off-path LLM</span>
        <span class="pt-badge is-hard">hard dependency</span>
      </div>

      {view === "org" ? <AgentOrgChart state={runtime} /> : LAYER_ORDER.map((layer) => {
        const agents = graph.agents.filter((agent) => agent.layer === layer);
        return (
          <section class="pt-layer" key={layer}>
            <header class="pt-layer-head">
              <div>
                <h3>{titleCase(layer)} layer</h3>
                <p>{LAYER_COPY[layer]}</p>
              </div>
              <span>{agents.length} agents</span>
            </header>
            <div class="pt-grid">
              {agents.map((agent) => (
                <PantheonAgentCard
                  key={agent.name}
                  agent={agent}
                  runtime={runtime.agents[agent.name]}
                />
              ))}
            </div>
          </section>
        );
      })}

      {view === "directory" ? <section class="pantheon-tree-section">
        <header class="pt-layer-head">
          <div>
            <h3>Reporting tree</h3>
            <p>Every reporting line is projected from the registry.</p>
          </div>
        </header>
        <ReportingTree agents={graph.agents} />
      </section> : null}

      <details class="pantheon-workflows">
        <summary>
          <strong>Cross-agent workflows</strong>
          <span>{workflows.workflows.length} registered</span>
        </summary>
        <div class="data-table-wrap">
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
                  <td class="mono">
                    <a href={pantheonAgentHref(w.primary_agent, runtime.agents[w.primary_agent]?.correlationId)}>
                      {w.primary_agent}
                    </a>
                  </td>
                  <td>
                    <ChipList items={w.participating_agents} runtime={runtime} />
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
      </details>
    </div>
  );
}

function PantheonAgentCard({
  agent,
  runtime,
}: {
  readonly agent: AgentDto;
  readonly runtime: AgentsState["agents"][string] | undefined;
}) {
  const role = AGENT_ROLE[agent.name];
  const state = runtime?.observed ? runtime.state : "unobserved";
  return (
    <article class={`pt-card is-${agent.layer}`}>
      <header class="pt-card-head">
        <span class={`pt-avatar is-${agent.layer}`}>{agent.name.slice(0, 2)}</span>
        <div>
          <h4><a href={pantheonAgentHref(agent.name, runtime?.correlationId)}>{agent.name}</a></h4>
          <p>{role?.title ?? titleCase(agent.layer)}</p>
        </div>
        <span class={`pt-runtime state-${state}`}>
          <i aria-hidden="true" />
          {state}
        </span>
      </header>
      {role ? <p class="pt-summary">{role.summary}</p> : null}
      <p class="pt-owns">
        <strong>Owns</strong>{" "}
        {agent.owns.length > 0 ? agent.owns.map((item) => <code key={item}>{item}</code>) : "-"}
      </p>
      <p class="pt-reports"><strong>Reports to</strong> {agent.reports_to ?? "- (root)"}</p>
      <div class="pt-badges">
        {agent.hot_path_llm ? <span class="pt-badge is-hotllm">hot-path LLM</span> : null}
        {agent.off_path_llm ? <span class="pt-badge is-offllm">off-path LLM</span> : null}
        {agent.hard_dependency ? <span class="pt-badge is-hard">hard dependency</span> : null}
      </div>
      <div class="pt-live-detail">
        <span>{runtime?.observed ? runtime.detail ?? STATE_TASK[runtime.state] : "No runtime signal observed"}</span>
        {runtime?.correlationId ? <code>{runtime.correlationId}</code> : null}
      </div>
    </article>
  );
}

function ReportingTree({ agents }: { readonly agents: readonly AgentDto[] }) {
  const byParent = new Map<string | null, AgentDto[]>();
  for (const agent of agents) {
    const siblings = byParent.get(agent.reports_to) ?? [];
    siblings.push(agent);
    byParent.set(agent.reports_to, siblings);
  }
  const branch = (agent: AgentDto) => (
    <li key={agent.name}>
      <a class="pt-tree-name" href={pantheonAgentHref(agent.name)}>{agent.name}</a>{" "}
      <span class="pt-tree-role">- {AGENT_ROLE[agent.name]?.title ?? titleCase(agent.layer)}</span>
      {(byParent.get(agent.name)?.length ?? 0) > 0 ? (
        <ul>{byParent.get(agent.name)!.map(branch)}</ul>
      ) : null}
    </li>
  );
  return <div class="pt-tree"><ul>{(byParent.get(null) ?? []).map(branch)}</ul></div>;
}

function titleCase(value: string): string {
  return value ? `${value[0]!.toUpperCase()}${value.slice(1)}` : value;
}

function ChipList({
  items,
  runtime,
}: {
  readonly items: readonly string[];
  readonly runtime?: AgentsState;
}) {
  if (items.length === 0) {
    return <span class="muted">-</span>;
  }
  return (
    <ul class="type-chip-list">
      {items.map((name) => (
        <li key={name} class="type-chip mono">
          <a href={pantheonAgentHref(name, runtime?.agents[name]?.correlationId)}>{name}</a>
        </li>
      ))}
    </ul>
  );
}
