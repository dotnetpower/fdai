import type { ComponentChildren } from "preact";
import { StatusBadge, type BadgeTone } from "./status-badge";
import "./agent-roster-table.css";

export type AgentRosterStateKind = "engaged" | "watching" | "idle" | "unobserved";

export interface AgentRosterTableRow {
  readonly name: string;
  readonly layerKey: string;
  readonly layerLabel: string;
  readonly roleTitle: string;
  readonly roleSummary?: string | null;
  readonly stateKind: AgentRosterStateKind;
  readonly stateLabel: string;
  readonly observed: boolean;
  readonly currentWork: string;
  readonly activeIncident: string;
  readonly stateSince: string;
  readonly reportsTo: string;
  readonly runtimeBinding: string;
  readonly authorityLabel: string;
  readonly recentEventsCount: number;
  readonly owns: readonly string[];
  readonly flags: readonly string[];
  readonly iconUrl: string;
  readonly activityHref: string;
  readonly openRoleLabel: string;
  readonly activityLabel: string;
  readonly askLabel: string;
}

export interface AgentRosterTableLabels {
  readonly agent: string;
  readonly layer: string;
  readonly state: string;
  readonly currentWork: string;
  readonly activeIncident: string;
  readonly stateSince: string;
  readonly actions: string;
  readonly details: string;
  readonly owns: string;
  readonly reportsTo: string;
  readonly runtimeBinding: string;
  readonly authority: string;
  readonly recentEvents: string;
}

export interface AgentRosterTableProps {
  readonly ariaLabel: string;
  readonly rows: readonly AgentRosterTableRow[];
  readonly labels: AgentRosterTableLabels;
  readonly onOpenRole: (agentName: string) => void;
  readonly onAskAgent: (agentName: string) => void;
  readonly empty?: ComponentChildren;
  readonly className?: string;
}

export function agentRosterTone(stateKind: AgentRosterStateKind, observed: boolean): BadgeTone {
  if (!observed || stateKind === "unobserved") return "neutral";
  if (stateKind === "engaged") return "live";
  if (stateKind === "watching") return "info";
  return "neutral";
}

export function AgentRosterTable({
  ariaLabel,
  rows,
  labels,
  onOpenRole,
  onAskAgent,
  empty,
  className,
}: AgentRosterTableProps) {
  if (rows.length === 0) {
    return <>{empty ?? null}</>;
  }

  return (
    <div
      class={className ? `cs-agent-roster-table-wrap ${className}` : "cs-agent-roster-table-wrap"}
      role="region"
      aria-label={ariaLabel}
    >
      <table class="cs-agent-roster-table">
        <thead>
          <tr>
            <th scope="col">{labels.agent}</th>
            <th scope="col">{labels.layer}</th>
            <th scope="col">{labels.state}</th>
            <th scope="col">{labels.currentWork}</th>
            <th scope="col">{labels.activeIncident}</th>
            <th scope="col">{labels.stateSince}</th>
            <th scope="col">{labels.actions}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const tone = agentRosterTone(row.stateKind, row.observed);
            return (
              <tr
                key={row.name}
                data-agent-name={row.name}
                data-agent-observed={row.observed ? "true" : "false"}
              >
                <td>
                  <div class="cs-agent-roster-identity">
                    <span class="cs-agent-roster-avatar" aria-hidden="true">
                      <span
                        class="agent-icon"
                        style={{ WebkitMaskImage: row.iconUrl, maskImage: row.iconUrl }}
                      />
                    </span>
                    <div class="cs-agent-roster-name">
                      <strong>{row.name}</strong>
                      <span class="cs-agent-roster-role">{row.roleTitle}</span>
                    </div>
                  </div>
                </td>
                <td>
                  <span class="cs-agent-roster-layer">{row.layerLabel}</span>
                </td>
                <td>
                  <StatusBadge tone={tone} label={row.stateLabel} />
                </td>
                <td>
                  <div class="cs-agent-roster-work">
                    <p class="cs-agent-roster-work-text">{row.currentWork}</p>
                    <details class="cs-agent-roster-details">
                      <summary>{labels.details}</summary>
                      <div class="cs-agent-roster-details-body">
                        {row.roleSummary ? (
                          <p class="cs-agent-roster-details-summary">{row.roleSummary}</p>
                        ) : null}
                        <dl class="cs-agent-roster-facts">
                          <div>
                            <dt>{labels.reportsTo}</dt>
                            <dd>{row.reportsTo}</dd>
                          </div>
                          <div>
                            <dt>{labels.runtimeBinding}</dt>
                            <dd>{row.runtimeBinding}</dd>
                          </div>
                          <div>
                            <dt>{labels.authority}</dt>
                            <dd>{row.authorityLabel}</dd>
                          </div>
                          <div>
                            <dt>{labels.recentEvents}</dt>
                            <dd>{row.observed ? String(row.recentEventsCount) : "-"}</dd>
                          </div>
                          <div>
                            <dt>{labels.owns}</dt>
                            <dd class="cs-agent-roster-owns">
                              {row.owns.length > 0
                                ? row.owns.map((item) => <code key={item}>{item}</code>)
                                : "-"}
                            </dd>
                          </div>
                        </dl>
                        {row.flags.length > 0 ? (
                          <div class="cs-agent-roster-flags">
                            {row.flags.map((flag) => (
                              <StatusBadge key={flag} tone="neutral" label={flag} noDot />
                            ))}
                          </div>
                        ) : null}
                      </div>
                    </details>
                  </div>
                </td>
                <td>
                  <span class="cs-agent-roster-meta">{row.activeIncident}</span>
                </td>
                <td>
                  <span class="cs-agent-roster-meta">{row.observed ? row.stateSince : "-"}</span>
                </td>
                <td>
                  <div class="cs-agent-roster-actions">
                    <button
                      type="button"
                      class="cs-control-button"
                      onClick={() => onOpenRole(row.name)}
                    >
                      {row.openRoleLabel}
                    </button>
                    <a class="cs-control-button" href={row.activityHref}>
                      {row.activityLabel}
                    </a>
                    <button
                      type="button"
                      class="cs-control-button is-primary"
                      onClick={() => onAskAgent(row.name)}
                    >
                      {row.askLabel}
                    </button>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
