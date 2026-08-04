import { useEffect, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import type { AuthContext } from "../auth";
import { AsyncBoundary, KpiCard, KpiGrid, LoadingState, type AsyncState } from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, agentTerm, composeGlossary } from "../deck/glossary";
import { t } from "../i18n";
import { currentRoute, navigate, routeHref } from "../router";
import { HandoverProposalEditor } from "./handover-editor";
import type { StewardshipResponse } from "./handover";
import { SettingsIamAssignments } from "./settings-iam-assignments";
import type { IamOverview } from "./settings-iam.model";

export type AgentOversightView =
  | "overview"
  | "human-dependencies"
  | "knowledge-handover"
  | "approval-routes"
  | "mapping-reviews";

const VIEWS: readonly AgentOversightView[] = [
  "overview",
  "human-dependencies",
  "knowledge-handover",
  "approval-routes",
  "mapping-reviews",
];

export function oversightViewFromSegment(segment: string | undefined): AgentOversightView | null {
  if (segment === undefined || segment === "") return "overview";
  return VIEWS.includes(segment as AgentOversightView) ? segment as AgentOversightView : null;
}

export function viewRequiresStewardship(view: AgentOversightView): boolean {
  return view === "overview" || view === "human-dependencies";
}

export function AgentOversightBody({ stewardshipState, client, auth }: {
  readonly stewardshipState: AsyncState<StewardshipResponse>;
  readonly client: OperatorApiClient;
  readonly auth: AuthContext;
}) {
  const requestedView = oversightViewFromSegment(currentRoute().segments[0]);
  const [view, setView] = useState<AgentOversightView>(requestedView ?? "overview");

  const selectView = (next: AgentOversightView) => {
    setView(next);
    navigate(routeHref("handover", { segments: next === "overview" ? [] : [next] }));
  };

  return (
    <div class="stack agent-oversight-workspace">
      {stewardshipState.status === "ready" ? <StewardshipViewContext data={stewardshipState.data} /> : null}
      <div class="settings-tabs" role="tablist" aria-label={t("handover.viewsLabel")}>
        {VIEWS.map((item) => (
          <button
            key={item}
            id={`agent-oversight-tab-${item}`}
            type="button"
            role="tab"
            class={requestedView !== null && view === item ? "is-active" : undefined}
            aria-selected={requestedView !== null && view === item}
            aria-controls={`agent-oversight-panel-${item}`}
            tabIndex={view === item ? 0 : -1}
            onClick={() => selectView(item)}
          >
            {t(`handover.view.${item}`)}
          </button>
        ))}
      </div>
      {requestedView === null ? (
        <div class="state-block state-unavailable" role="alert">{t("handover.invalidView")}</div>
      ) : (
        <div
          id={`agent-oversight-panel-${view}`}
          role="tabpanel"
          aria-labelledby={`agent-oversight-tab-${view}`}
        >
          {renderView(view, stewardshipState, client, auth)}
        </div>
      )}
    </div>
  );
}

function renderView(
  view: AgentOversightView,
  stewardshipState: AsyncState<StewardshipResponse>,
  client: OperatorApiClient,
  auth: AuthContext,
) {
  if (viewRequiresStewardship(view)) {
    return (
      <AsyncBoundary state={stewardshipState} resourceLabel={t("route.handover")}>
        {(data) => view === "overview" ? <Overview data={data} /> : <HumanDependencies data={data} />}
      </AsyncBoundary>
    );
  }
  switch (view) {
    case "knowledge-handover":
      return <HandoverProposalEditor client={client} auth={auth} />;
    case "approval-routes":
      return <UnavailableView title={t("handover.view.approval-routes")} message={t("handover.approvalRoutesUnavailable")} />;
    case "mapping-reviews":
      return <MappingReviews client={client} auth={auth} />;
  }
}

function StewardshipViewContext({ data }: { readonly data: StewardshipResponse }) {
  const { map, coverage } = data;
  usePublishViewContext(
    () => ({
      routeId: "handover",
      routeLabel: t("route.handover"),
      purpose: t("handover.subtitle"),
      glossary: composeGlossary([agentTerm(), TERMS.hil]),
      headline: `${map.agents.length} ${t("handover.agents")} - ${map.maintainer_count} ${t("handover.maintainers")}`,
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "agent_count", value: map.agents.length, group: "handover" },
        { key: "maintainer_count", value: map.maintainer_count, group: "handover" },
        { key: "autonomous_agents", value: coverage.autonomous_agents, group: "handover" },
        { key: "coverage_clean", value: coverage.is_clean ? "yes" : "no", group: "handover" },
      ],
      records: {
        agents: map.agents.map((agent) => ({
          name: agent.name,
          stewards: agent.stewards
            .map((steward) => `${steward.kind}:${steward.responsibility}${steward.duty ? `:${steward.duty}` : ""}`)
            .join(", ") || "-",
          bus_factor: agent.bus_factor,
          autonomous: agent.autonomous ? "yes" : "no",
        })),
        findings: coverage.findings.map((finding) => ({
          code: finding.code,
          severity: finding.severity,
          agent: finding.agent ?? "",
          message: finding.message,
        })),
      },
    }),
    [map, coverage],
  );
  return null;
}

function Overview({ data }: { readonly data: StewardshipResponse }) {
  const { map, coverage } = data;
  const maintainerBanner = map.maintainer_count < 1
    ? { level: "danger", text: t("handover.noMaintainer") }
    : map.maintainer_count === 1
      ? { level: "warn", text: t("handover.oneMaintainer") }
      : null;
  return (
    <div class="stack">
      <KpiGrid>
        <KpiCard href={routeHref("agents")} label={t("handover.agents")} value={map.agents.length} />
        <KpiCard href={routeHref("handover", { segments: ["human-dependencies"] })} label={t("handover.maintainers")} value={map.maintainer_count} />
        <KpiCard href={routeHref("handover", { segments: ["human-dependencies"] })} label={t("handover.autonomous")} value={coverage.autonomous_agents} />
        <KpiCard href={routeHref("handover", { segments: ["human-dependencies"] })} label={t("handover.coverage")} value={t(coverage.is_clean ? "handover.clean" : "handover.review")} />
      </KpiGrid>
      {maintainerBanner ? <div class={`callout callout--${maintainerBanner.level}`}>{maintainerBanner.text}</div> : null}
      {coverage.findings.length > 0 ? <CoverageFindings data={data} /> : (
        <div class="state-block state-empty">{t("handover.noFindings")}</div>
      )}
    </div>
  );
}

function HumanDependencies({ data }: { readonly data: StewardshipResponse }) {
  return (
    <section class="stack" aria-labelledby="agent-oversight-dependencies-title">
      <h3 id="agent-oversight-dependencies-title">{t("handover.mapTitle")}</h3>
      <div class="data-table-wrap">
        <table class="cs-table">
          <thead><tr><th>{t("handover.agent")}</th><th>{t("handover.owners")}</th><th>{t("handover.backupCoverage")}</th><th>{t("handover.mode")}</th></tr></thead>
          <tbody>{data.map.agents.map((agent) => (
            <tr key={agent.name}>
              <td><a href={routeHref("agents", { params: { agent: agent.name } })}>{agent.name}</a></td>
              <td>{agent.autonomous
                ? `${t("handover.autonomous")} (${agent.accept_autonomous_reason ?? t("handover.noReason")})`
                : agent.stewards.map((steward) => `${steward.kind} / ${steward.responsibility}${steward.duty ? ` / ${steward.duty}` : ""}`).join(", ") || "-"}</td>
              <td>{agent.autonomous ? "-" : agent.bus_factor}</td>
              <td>{t(agent.autonomous ? "handover.autonomous" : "handover.mapped")}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
    </section>
  );
}

function CoverageFindings({ data }: { readonly data: StewardshipResponse }) {
  return (
    <section class="stack" aria-labelledby="agent-oversight-findings-title">
      <h3 id="agent-oversight-findings-title">{t("handover.findingsTitle")}</h3>
      <div class="data-table-wrap"><table class="cs-table">
        <thead><tr><th>{t("handover.severity")}</th><th>{t("handover.code")}</th><th>{t("handover.agent")}</th><th>{t("handover.message")}</th></tr></thead>
        <tbody>{data.coverage.findings.map((finding, index) => (
          <tr key={`${finding.code}-${index}`}><td>{finding.severity}</td><td>{finding.code}</td><td>{finding.agent ? <a href={routeHref("agents", { params: { agent: finding.agent } })}>{finding.agent}</a> : "-"}</td><td>{finding.message}</td></tr>
        ))}</tbody>
      </table></div>
    </section>
  );
}

function MappingReviews({ client, auth }: { readonly client: OperatorApiClient; readonly auth: AuthContext }) {
  const [state, setState] = useState<{ readonly status: "loading" } | { readonly status: "error"; readonly message: string } | { readonly status: "ready"; readonly overview: IamOverview }>({ status: "loading" });
  useEffect(() => {
    let cancelled = false;
    client.iamOverview().then(
      (overview) => { if (!cancelled) setState({ status: "ready", overview }); },
      (reason) => { if (!cancelled) setState({ status: "error", message: reason instanceof Error ? reason.message : String(reason) }); },
    );
    return () => { cancelled = true; };
  }, [client]);
  if (state.status === "loading") return <LoadingState label={t("handover.mappingReviewsLoading")} />;
  if (state.status === "error") return <UnavailableView title={t("handover.view.mapping-reviews")} message={state.message} />;
  return <SettingsIamAssignments client={client} auth={auth} canManage={state.overview.principal.capabilities.includes("manage-group-membership")} principalOid={state.overview.principal.oid} />;
}

function UnavailableView({ title, message }: { readonly title: string; readonly message: string }) {
  return <section class="state-block state-unavailable" role="status"><strong>{title}</strong><p>{message}</p></section>;
}
