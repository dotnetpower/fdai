import { useLayoutEffect, useRef, useState } from "preact/hooks";
import { t } from "../i18n";
import { currentRoute, routeHref } from "../router";
import {
  ORG_CHART,
  isEngaged,
  type AgentNode,
  type AgentsState,
  type Incident,
} from "../routes/agents.model";
import {
  agentRoleTitle,
  agentStateLabel,
  stateTaskLabel,
} from "../routes/agents.view-model";

interface Point {
  readonly x: number;
  readonly y: number;
}

interface Geometry {
  readonly centers: Record<string, Point>;
  readonly width: number;
  readonly height: number;
}

const EMPTY_GEOMETRY: Geometry = { centers: {}, width: 0, height: 0 };

function agentIconUrl(name: string): string {
  return `url("${import.meta.env.BASE_URL}agent-icons/${name.toLowerCase()}.svg")`;
}

export function AgentOrgChart({ state }: { readonly state: AgentsState }) {
  const stageRef = useRef<HTMLElement | null>(null);
  const nodeRefs = useRef(new Map<string, HTMLElement>());
  const [geometry, setGeometry] = useState<Geometry>(EMPTY_GEOMETRY);
  const [focusedAgent, setFocusedAgent] = useState<string | null>(null);

  useLayoutEffect(() => {
    const stage = stageRef.current;
    if (!stage || typeof ResizeObserver === "undefined") return undefined;
    const measure = (): void => {
      const stageBox = stage.getBoundingClientRect();
      const centers: Record<string, Point> = {};
      for (const [name, element] of nodeRefs.current) {
        const ring = element.querySelector<HTMLElement>(".agent-ring") ?? element;
        const box = ring.getBoundingClientRect();
        centers[name] = {
          x: box.left - stageBox.left + box.width / 2,
          y: box.top - stageBox.top + box.height / 2,
        };
      }
      setGeometry({ centers, width: stageBox.width, height: stageBox.height });
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(stage);
    return () => observer.disconnect();
  }, [state.agents]);

  const renderNode = (name: string) => {
    const node = state.agents[name];
    if (!node) return null;
    const roleTitle = agentRoleTitle(name) ?? node.layer;
    const incident = node.correlationId ? (state.incidents[node.correlationId] ?? null) : null;
    const iconUrl = agentIconUrl(name);
    const focused = focusedAgent === name;
    return (
      <a
        key={name}
        ref={(element) => {
          if (element) nodeRefs.current.set(name, element);
          else nodeRefs.current.delete(name);
        }}
        href={routeHref("agents", {
          params: {
            view: "org",
            agent: name,
            data: currentRoute().search.get("data") === "sample" ? "sample" : null,
          },
        })}
        class={`agent-node layer-${node.layer} state-${node.state}${
          isEngaged(node) ? " is-engaged" : ""
        }${focused ? " is-hovered" : ""}`}
        aria-label={t("pantheon.openAgent", { name, role: roleTitle })}
        onMouseEnter={() => setFocusedAgent(name)}
        onMouseLeave={() => setFocusedAgent((current) => current === name ? null : current)}
        onFocus={() => setFocusedAgent(name)}
        onBlur={() => setFocusedAgent((current) => current === name ? null : current)}
      >
        <span class="agent-ring" aria-hidden="true">
          <span
            class="agent-icon"
            style={{ WebkitMaskImage: iconUrl, maskImage: iconUrl }}
          />
        </span>
        <span class="agent-name">{name}</span>
        <span class="agent-state">{roleTitle}</span>
        <AgentOrgTooltip node={node} incident={incident} />
      </a>
    );
  };

  return (
    <section
      ref={stageRef}
      class="agents-stage pantheon-org-stage layout-org"
      aria-label={t("pantheon.organizationChartLabel")}
    >
      <OrgReportingLines geometry={geometry} />
      <div class="agents-org">
        <div class="org-tier org-root">{renderNode(ORG_CHART.root)}</div>
        <div class="org-tier org-branches">
          {ORG_CHART.lines.map((line) => (
            <div class="org-branch" key={line.manager}>
              <div class="org-manager">{renderNode(line.manager)}</div>
              <div class="org-reports">{line.reports.map(renderNode)}</div>
            </div>
          ))}
          <div class="org-branch org-staff-branch">
            <div class="org-staff-label">{t("agents.layout.staffToOdin")}</div>
            <div class="org-reports">{ORG_CHART.staff.map(renderNode)}</div>
          </div>
        </div>
      </div>
    </section>
  );
}

function AgentOrgTooltip({
  node,
  incident,
}: {
  readonly node: AgentNode;
  readonly incident: Incident | null;
}) {
  return (
    <span class="agent-tooltip" role="tooltip">
      <span class="agent-tooltip-head">
        <strong>{node.name}</strong>
        <span class={`agent-tooltip-state state-${node.state}`}>{agentStateLabel(node)}</span>
      </span>
      <span class="agent-tooltip-task">{stateTaskLabel(node.state)}</span>
      {node.detail ? <span class="agent-tooltip-detail">{node.detail}</span> : null}
      {incident ? (
        <span class="agent-tooltip-incident">
          <span class="agent-tooltip-ticket">{incident.ticketId || t("agents.common.incident")}</span>
          <span class="agent-tooltip-title">{incident.title}</span>
        </span>
      ) : (
        <span class="agent-tooltip-idle">{t("agents.common.notEngaged")}</span>
      )}
    </span>
  );
}

function OrgReportingLines({ geometry }: { readonly geometry: Geometry }) {
  if (geometry.width === 0) return null;
  const edges: { readonly from: string; readonly to: string; readonly staff: boolean }[] = [];
  for (const line of ORG_CHART.lines) {
    edges.push({ from: line.manager, to: ORG_CHART.root, staff: false });
    for (const report of line.reports) {
      edges.push({ from: report, to: line.manager, staff: false });
    }
  }
  for (const staff of ORG_CHART.staff) {
    edges.push({ from: staff, to: ORG_CHART.root, staff: true });
  }
  return (
    <svg
      class="agents-org-lines"
      width={geometry.width}
      height={geometry.height}
      viewBox={`0 0 ${geometry.width} ${geometry.height}`}
      aria-hidden="true"
    >
      {edges.map(({ from, to, staff }) => {
        const source = geometry.centers[from];
        const target = geometry.centers[to];
        if (!source || !target) return null;
        return (
          <line
            key={`${from}-${to}`}
            class={`org-edge${staff ? " is-staff" : ""}`}
            x1={source.x}
            y1={source.y}
            x2={target.x}
            y2={target.y}
          />
        );
      })}
    </svg>
  );
}
