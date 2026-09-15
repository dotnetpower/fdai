import type { VNode } from "preact";
import { createPortal } from "preact/compat";
import { useEffect, useLayoutEffect, useRef, useState } from "preact/hooks";
import { t } from "../i18n";
import { routeHref } from "../router";
import {
  AGENT_CONTRACT,
  AGENT_ROLE,
  ORG_CHART,
  isEngaged,
  type AgentNode,
} from "./agents.model";
import { OrgReportingLines } from "./agents.constellation";
import {
  EMPTY_GEOMETRY,
  agentIconUrl,
  agentRoleSummary,
  agentRoleTitle,
  agentRuntimeBindingLabel,
  agentStateLabel,
  rosterLayerOf,
  type Geometry,
  type Point,
} from "./agents.view-model";

interface WorkspaceProps {
  readonly agents: Readonly<Record<string, AgentNode>>;
  readonly selectedAgent: string | null;
  readonly runtimeCurrent: boolean;
  readonly onSelectAgent: (agent: string | null) => void;
}

export function AgentOrganizationWorkspace({
  agents,
  selectedAgent,
  runtimeCurrent,
  onSelectAgent,
}: WorkspaceProps) {
  const containerRef = useRef<HTMLElement | null>(null);
  const nodeRefs = useRef(new Map<string, HTMLElement>());
  const [geometry, setGeometry] = useState<Geometry>(EMPTY_GEOMETRY);
  const selectedNode = selectedAgent ? agents[selectedAgent] : undefined;

  useLayoutEffect(() => {
    const container = containerRef.current;
    if (container === null || typeof ResizeObserver === "undefined") return undefined;
    const measure = (): void => {
      const box = container.getBoundingClientRect();
      const centers: Record<string, Point> = {};
      for (const [name, element] of nodeRefs.current) {
        const ring = element.querySelector<HTMLElement>(".agent-ring") ?? element;
        const bounds = ring.getBoundingClientRect();
        centers[name] = {
          x: bounds.left - box.left + bounds.width / 2,
          y: bounds.top - box.top + bounds.height / 2,
        };
      }
      setGeometry({ centers, w: box.width, h: box.height });
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(container);
    return () => observer.disconnect();
  }, [agents]);

  const renderNode = (name: string): VNode | null => {
    const node = agents[name];
    if (node === undefined) return null;
    const roleTitle = agentRoleTitle(name) ?? name;
    const engaged = runtimeCurrent && isEngaged(node);
    const selected = selectedAgent === name;
    const iconUrl = agentIconUrl(name);
    return (
      <button
        key={name}
        type="button"
        ref={(element) => {
          if (element) nodeRefs.current.set(name, element as HTMLElement);
          else nodeRefs.current.delete(name);
        }}
        class={`agent-node layer-${node.layer} state-${node.state}${
          engaged ? " is-engaged" : ""
        }${selected ? " is-agent-selected" : ""}`}
        aria-pressed={selected}
        aria-label={t("pantheon.openAgent", { name, role: roleTitle })}
        onClick={() => onSelectAgent(selected ? null : name)}
      >
        <span class="agent-ring" aria-hidden="true">
          <span
            class="agent-icon"
            style={{ WebkitMaskImage: iconUrl, maskImage: iconUrl }}
          />
        </span>
        <span class="agent-name">{name}</span>
        <span class="agent-state">{roleTitle}</span>
        <span class="agent-role-tooltip" role="tooltip">
          <span>
            <strong>{name}</strong>
            <small>{roleTitle}</small>
          </span>
          <span>{agentStateLabel(node)}</span>
        </span>
      </button>
    );
  };

  const onTreeKeyDown = (event: KeyboardEvent): void => {
    if (!["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
      return;
    }
    const buttons = [...(containerRef.current?.querySelectorAll<HTMLButtonElement>(".agent-node") ?? [])];
    const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
    if (index < 0) return;
    event.preventDefault();
    const next = event.key === "Home"
      ? 0
      : event.key === "End"
        ? buttons.length - 1
        : (index + (event.key === "ArrowUp" || event.key === "ArrowLeft" ? -1 : 1) +
          buttons.length) % buttons.length;
    buttons[next]?.focus();
  };

  return (
    <div class="agent-organization-workspace">
      <section
        ref={containerRef}
        class="agents-stage agent-organization-stage"
        aria-label={t("agents.org.chartLabel")}
        onKeyDown={onTreeKeyDown}
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
      <AgentRoleDetail node={selectedNode} />
    </div>
  );
}

function AgentRoleDetail({ node }: { readonly node: AgentNode | undefined }) {
  if (node === undefined) {
    return (
      <aside class="agent-role-detail is-empty" aria-live="polite">
        <span class="agent-role-detail-kicker">{t("agents.org.eyebrow")}</span>
        <h3>{t("pantheon.reportingTree")}</h3>
        <p>{t("pantheon.organizationHint")}</p>
        <p class="agent-role-boundary">{t("agents.organization.boundary")}</p>
      </aside>
    );
  }
  const role = AGENT_ROLE[node.name];
  const contract = AGENT_CONTRACT[node.name];
  const layer = rosterLayerOf(node.name);
  return (
    <aside
      class={`agent-role-detail layer-${node.layer}`}
      role="region"
      aria-label={node.name}
      aria-live="polite"
    >
      <header>
        <span class="agent-role-detail-kicker">{t("agents.org.eyebrow")}</span>
        <h3>{node.name}</h3>
        <p>{agentRoleTitle(node.name)}</p>
      </header>
      <p class="agent-role-summary">{agentRoleSummary(node.name)}</p>
      <dl>
        <div>
          <dt>{t("agents.card.reportsTo")}</dt>
          <dd>{role?.reportsTo ?? t("pantheon.root")}{role?.staff ? ` (${t("agents.common.staff")})` : ""}</dd>
        </div>
        <div>
          <dt>{t("agents.filter.layer")}</dt>
          <dd>{t(`agentActivity.filter.${layer}`)}</dd>
        </div>
        <div>
          <dt>{t("agents.card.runtimeBinding")}</dt>
          <dd>{agentRuntimeBindingLabel(node.name)}</dd>
        </div>
        <div>
          <dt>{t("agents.filter.state")}</dt>
          <dd>{agentStateLabel(node)}</dd>
        </div>
      </dl>
      <section class="agent-role-owns" aria-labelledby={`agent-role-owns-${node.name}`}>
        <h4 id={`agent-role-owns-${node.name}`}>{t("agents.card.owns")}</h4>
        <ul>
          {(contract?.owns ?? []).map((objectType) => <li key={objectType}>{objectType}</li>)}
        </ul>
      </section>
      <p class="agent-role-boundary">{t("agents.organization.boundary")}</p>
      <a
        class="agent-role-activity-link"
        href={routeHref("agent-activity", {
          params: { view: "waterfall", agent: node.name },
        })}
      >
        {t("agents.workspace.activity")}
      </a>
    </aside>
  );
}

interface DialogProps extends WorkspaceProps {
  readonly onClose: () => void;
}

export function AgentOrganizationDialog({
  agents,
  selectedAgent,
  runtimeCurrent,
  onSelectAgent,
  onClose,
}: DialogProps) {
  const dialogRef = useRef<HTMLElement | null>(null);
  const closeRef = useRef<HTMLButtonElement | null>(null);
  const portalHostRef = useRef<HTMLDivElement | null>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  if (portalHostRef.current === null && typeof document !== "undefined") {
    portalHostRef.current = document.createElement("div");
    portalHostRef.current.dataset.agentOrganizationPortal = "";
  }

  useLayoutEffect(() => {
    const portalHost = portalHostRef.current;
    if (portalHost === null) return undefined;
    document.body.append(portalHost);
    return () => portalHost.remove();
  }, []);

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const portalHost = portalHostRef.current;
    const siblings = [...document.body.children].filter(
      (element): element is HTMLElement => element !== portalHost && element instanceof HTMLElement,
    );
    const priorInert = siblings.map((element) => element.inert);
    siblings.forEach((element) => { element.inert = true; });
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
      }
    };
    document.body.classList.add("agent-organization-dialog-open");
    document.addEventListener("keydown", closeOnEscape);
    closeRef.current?.focus();
    return () => {
      document.body.classList.remove("agent-organization-dialog-open");
      document.removeEventListener("keydown", closeOnEscape);
      siblings.forEach((element, index) => { element.inert = priorInert[index] ?? false; });
      previous?.focus();
    };
  }, []);

  const onKeyDown = (event: KeyboardEvent): void => {
    if (event.key === "Escape") return;
    if (event.key !== "Tab" || dialogRef.current === null) return;
    const focusable = [...dialogRef.current.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])',
    )].filter((element) => element.offsetParent !== null || element === document.activeElement);
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (!first || !last) return;
    if (event.shiftKey && (
      document.activeElement === first || document.activeElement === dialogRef.current
    )) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  if (portalHostRef.current === null) return null;
  return createPortal(
    <div class="agent-organization-scrim" onClick={onClose}>
      <section
        ref={dialogRef}
        class="agent-organization-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="agent-organization-dialog-title"
        tabIndex={-1}
        onClick={(event) => event.stopPropagation()}
        onKeyDown={onKeyDown}
      >
        <header class="agent-organization-dialog-header">
          <div>
            <span>{t("agents.org.eyebrow")}</span>
            <h2 id="agent-organization-dialog-title">{t("agents.org.title")}</h2>
            <p>{t("agents.org.description")}</p>
          </div>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            aria-label={t("agents.organization.close")}
          >
            {"\u00d7"}
          </button>
        </header>
        <div class="agent-organization-dialog-body">
          <AgentOrganizationWorkspace
            agents={agents}
            selectedAgent={selectedAgent}
            runtimeCurrent={runtimeCurrent}
            onSelectAgent={onSelectAgent}
          />
        </div>
      </section>
    </div>,
    portalHostRef.current,
  );
}
