import { useEffect, useState } from "preact/hooks";
import { isOptionalReadApiUnavailable } from "../api";
import type { ReadApiClient } from "../api";
import { AgentWorkspaceNav } from "../components/agent-workspace-nav";
import {
  AsyncBoundary,
  KpiCard,
  KpiGrid,
  PageHeader,
  type AsyncState,
} from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, agentTerm, composeGlossary } from "../deck/glossary";
import { t } from "../i18n";
import { routeHref } from "../router";
import { PANTHEON } from "./agents.model";
import { panelArray, panelBoolean, panelContractError, panelNullableString, panelNumber, panelRecord, panelString, panelStringArray } from "./panel-decode";

/**
 * Handover panel. Fetches ``GET /stewardship`` and renders the handover map
 * (maintainers + 15 agents + their stewards) plus the coverage report
 * (bus-factor / over-assignment / maintainer findings) as read-only tables.
 *
 * Opt-in on the API side (``ReadApiConfig.stewardship_map`` set). When not
 * wired, the panel surfaces a friendly "unavailable" state. Read-only: edits
 * are governance draft PRs, never a console mutation.
 */

type StewardKind = "user" | "group";
type StewardResponsibility = "accountable" | "informed";
type FindingSeverity = "warn" | "info";

interface StewardDto {
  readonly kind: StewardKind;
  readonly id: string;
  readonly responsibility: StewardResponsibility;
}

interface AgentStewardshipDto {
  readonly name: string;
  readonly autonomous: boolean;
  readonly accept_autonomous_reason: string | null;
  readonly bus_factor: number;
  readonly stewards: readonly StewardDto[];
}

interface MapDto {
  readonly version: number;
  readonly maintainers: readonly string[];
  readonly maintainer_count: number;
  readonly hop_timeout_seconds: number;
  readonly over_assigned_max: number;
  readonly agents: readonly AgentStewardshipDto[];
}

interface FindingDto {
  readonly code: string;
  readonly severity: FindingSeverity;
  readonly message: string;
  readonly agent: string | null;
}

interface CoverageDto {
  readonly is_clean: boolean;
  readonly total_agents: number;
  readonly autonomous_agents: number;
  readonly maintainer_count: number;
  readonly findings: readonly FindingDto[];
}

interface StewardshipResponse {
  readonly map: MapDto;
  readonly coverage: CoverageDto;
}

interface Props {
  readonly client: ReadApiClient;
}

export function HandoverRoute({ client }: Props) {
  const [state, setState] = useState<AsyncState<StewardshipResponse>>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    (async () => {
      try {
        const data = decodeStewardship(await client.panel<unknown>("/stewardship"));
        if (!cancelled) {
          setState({ status: "ready", data });
        }
      } catch (err) {
        if (!cancelled) {
          const message = err instanceof Error ? err.message : String(err);
          if (isOptionalReadApiUnavailable(err)) {
            setState({
              status: "unavailable",
              message:
                "The stewardship endpoint is not wired on this deployment. " +
                "Set ReadApiConfig.stewardship_map in the composition root to enable it.",
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
      <AgentWorkspaceNav />
      <PageHeader
        title={t("route.handover")}
        subtitle="Who owns each of the 15 agents now that FDAI runs the control plane - stewards, maintainers, and handover coverage. Read-only."
      />
      <AsyncBoundary state={state} resourceLabel="handover">
        {(data) => <HandoverBody data={data} />}
      </AsyncBoundary>
    </div>
  );
}

export function decodeStewardship(value: unknown): StewardshipResponse {
  const root = panelRecord(value, "stewardship");
  const map = panelRecord(root["map"], "stewardship.map");
  const coverage = panelRecord(root["coverage"], "stewardship.coverage");
  const decoded: StewardshipResponse = {
    map: {
      version: panelNumber(map, "version", "stewardship.map"),
      maintainers: panelStringArray(map["maintainers"], "stewardship.map.maintainers"),
      maintainer_count: panelNumber(map, "maintainer_count", "stewardship.map"),
      hop_timeout_seconds: panelNumber(map, "hop_timeout_seconds", "stewardship.map"),
      over_assigned_max: panelNumber(map, "over_assigned_max", "stewardship.map"),
      agents: panelArray(map["agents"], "stewardship.map.agents").map((value, index) => {
        const agent = panelRecord(value, `stewardship.map.agents[${index}]`);
        return {
          name: panelString(agent, "name", "stewardship agent"),
          autonomous: panelBoolean(agent, "autonomous", "stewardship agent"),
          accept_autonomous_reason: panelNullableString(agent, "accept_autonomous_reason", "stewardship agent"),
          bus_factor: panelNumber(agent, "bus_factor", "stewardship agent"),
          stewards: panelArray(agent["stewards"], "stewardship agent.stewards").map((value, stewardIndex) => {
            const steward = panelRecord(value, `stewardship agent.stewards[${stewardIndex}]`);
            return {
              kind: stewardshipEnum(steward, "kind", ["user", "group"]),
              id: panelString(steward, "id", "steward"),
              responsibility: stewardshipEnum(
                steward,
                "responsibility",
                ["accountable", "informed"],
              ),
            };
          }),
        };
      }),
    },
    coverage: {
      is_clean: panelBoolean(coverage, "is_clean", "stewardship.coverage"),
      total_agents: panelNumber(coverage, "total_agents", "stewardship.coverage"),
      autonomous_agents: panelNumber(coverage, "autonomous_agents", "stewardship.coverage"),
      maintainer_count: panelNumber(coverage, "maintainer_count", "stewardship.coverage"),
      findings: panelArray(coverage["findings"], "stewardship.coverage.findings").map((value, index) => {
        const finding = panelRecord(value, `stewardship.coverage.findings[${index}]`);
        return {
          code: panelString(finding, "code", "stewardship finding"),
          severity: stewardshipEnum(finding, "severity", ["warn", "info"]),
          message: panelString(finding, "message", "stewardship finding"),
          agent: panelNullableString(finding, "agent", "stewardship finding"),
        };
      }),
    },
  };
  const expectedNames = PANTHEON.map((agent) => agent.name);
  const actualNames = decoded.map.agents.map((agent) => agent.name);
  if (
    actualNames.length !== expectedNames.length ||
    new Set(actualNames).size !== actualNames.length ||
    expectedNames.some((name) => !actualNames.includes(name))
  ) {
    throw panelContractError("stewardship.map.agents MUST contain the fixed 15-agent pantheon exactly once");
  }
  if (decoded.map.maintainer_count !== decoded.map.maintainers.length) {
    throw panelContractError("stewardship.map.maintainer_count MUST match maintainers.length");
  }
  if (
    decoded.coverage.total_agents !== decoded.map.agents.length ||
    decoded.coverage.maintainer_count !== decoded.map.maintainer_count ||
    decoded.coverage.autonomous_agents !== decoded.map.agents.filter((agent) => agent.autonomous).length
  ) {
    throw panelContractError("stewardship.coverage counts MUST match the handover map");
  }
  return decoded;
}

function stewardshipEnum<const T extends string>(
  value: Readonly<Record<string, unknown>>,
  key: string,
  allowed: readonly T[],
): T {
  const decoded = panelString(value, key, "stewardship");
  if (!allowed.includes(decoded as T)) {
    throw panelContractError(`stewardship.${key} MUST be one of ${allowed.join(", ")}`);
  }
  return decoded as T;
}

function HandoverBody({ data }: { readonly data: StewardshipResponse }) {
  const { map, coverage } = data;
  usePublishViewContext(
    () => ({
      routeId: "handover",
      routeLabel: "Handover",
      purpose:
        "Human <-> agent handover map. Which people are accountable for each of " +
        "the 15 agents (escalation + review), plus the FDAI maintainers. " +
        "Read-only; edits are governance draft PRs.",
      glossary: composeGlossary([agentTerm(), TERMS.hil]),
      headline: `${map.agents.length} agents - ${map.maintainer_count} maintainers`,
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "agent_count", value: map.agents.length, group: "handover" },
        { key: "maintainer_count", value: map.maintainer_count, group: "handover" },
        { key: "autonomous_agents", value: coverage.autonomous_agents, group: "handover" },
        { key: "coverage_clean", value: coverage.is_clean ? "yes" : "no", group: "handover" },
      ],
      records: {
        agents: map.agents.map((a) => ({
          name: a.name,
          stewards: a.stewards.map((s) => `${s.kind}:${s.responsibility}`).join(", ") || "-",
          bus_factor: a.bus_factor,
          autonomous: a.autonomous ? "yes" : "no",
        })),
        findings: coverage.findings.map((f) => ({
          code: f.code,
          severity: f.severity,
          agent: f.agent ?? "",
          message: f.message,
        })),
      },
    }),
    [map, coverage],
  );

  const maintainerBanner =
    map.maintainer_count < 1
      ? { level: "fail", text: "No maintainer configured - at least 1 is required." }
      : map.maintainer_count === 1
        ? { level: "warn", text: "Only 1 maintainer - 2 are recommended for succession safety." }
        : null;

  return (
    <div class="stack">
      <KpiGrid>
        <KpiCard label="Agents" value={map.agents.length} />
        <KpiCard label="Maintainers" value={map.maintainer_count} />
        <KpiCard label="Autonomous" value={coverage.autonomous_agents} />
        <KpiCard label="Coverage" value={coverage.is_clean ? "clean" : "review"} />
      </KpiGrid>

      {maintainerBanner ? (
        <div class={`callout callout--${maintainerBanner.level === "fail" ? "danger" : "warn"}`}>
          {maintainerBanner.text}
        </div>
      ) : null}

      <div class="callout">
        <strong>Propose a change</strong> - editing the handover map is a governance draft
        PR (Owner-gated). Edit <code>config/agent-stewardship.yaml</code> and open a PR; the
        console never writes it directly. On merge, the affected agents' stewards and the
        maintainer are notified and the change is recorded in the audit log.
      </div>

      <section class="stack">
        <h3>Handover map</h3>
        <div class="data-table-wrap">
          <table class="cs-table">
          <thead>
            <tr>
              <th>Agent</th>
              <th>Stewards</th>
              <th>Bus-factor</th>
              <th>Mode</th>
            </tr>
          </thead>
          <tbody>
            {map.agents.map((a) => (
              <tr key={a.name}>
                <td><a href={routeHref("agents", { params: { agent: a.name } })}>{a.name}</a></td>
                <td>
                  {a.autonomous
                    ? `autonomous (${a.accept_autonomous_reason ?? "no reason"})`
                    : a.stewards
                        .map((s) => `${s.kind} / ${s.responsibility}`)
                        .join(", ") || "-"}
                </td>
                <td>{a.autonomous ? "-" : a.bus_factor}</td>
                <td>{a.autonomous ? "autonomous" : "mapped"}</td>
              </tr>
            ))}
          </tbody>
          </table>
        </div>
      </section>

      {coverage.findings.length > 0 ? (
        <section class="stack">
          <h3>Coverage findings</h3>
          <div class="data-table-wrap">
            <table class="cs-table">
            <thead>
              <tr>
                <th>Severity</th>
                <th>Code</th>
                <th>Agent</th>
                <th>Message</th>
              </tr>
            </thead>
            <tbody>
              {coverage.findings.map((f, i) => (
                <tr key={`${f.code}-${i}`}>
                  <td>{f.severity}</td>
                  <td>{f.code}</td>
                  <td>{f.agent ? <a href={routeHref("agents", { params: { agent: f.agent } })}>{f.agent}</a> : "-"}</td>
                  <td>{f.message}</td>
                </tr>
              ))}
            </tbody>
            </table>
          </div>
        </section>
      ) : null}
    </div>
  );
}
