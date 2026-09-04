import { useEffect, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import type { AuthContext } from "../auth";
import {
  AsyncBoundary,
  KpiCard,
  KpiGrid,
  LoadingState,
  StatusPill,
  type AsyncState,
} from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, agentTerm, composeGlossary } from "../deck/glossary";
import { t } from "../i18n";
import { currentRoute, navigate, routeHref } from "../router";
import { PANTHEON } from "./agents.model";
import { HandoverProposalEditor } from "./handover-editor";
import { ownershipText } from "./ownership-copy";
import type {
  CurrentOwnershipAgentDto,
  FindingDto,
  IdentityHealthStatus,
  OwnershipAgentStatus,
  OwnershipReadiness,
  OwnershipSubjectDto,
  StewardDto,
  StewardshipResponse,
} from "./handover";
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
  "mapping-reviews",
  "knowledge-handover",
  "approval-routes",
];
const ASSIGNMENT_PROPOSAL_STATES = new Set([
  "draft",
  "pending_review",
  "approved",
  "ownership_pr_open",
  "ownership_merged",
  "iam_applying",
  "active",
  "rejected",
  "degraded",
  "superseded",
]);

export function oversightViewFromSegment(segment: string | undefined): AgentOversightView | null {
  if (segment === undefined || segment === "") return "overview";
  return VIEWS.includes(segment as AgentOversightView) ? segment as AgentOversightView : null;
}

export function viewRequiresStewardship(view: AgentOversightView): boolean {
  return view === "overview" || view === "human-dependencies";
}

export function adjacentOversightView(
  view: AgentOversightView,
  direction: "next" | "previous" | "first" | "last",
): AgentOversightView {
  if (direction === "first") return VIEWS[0]!;
  if (direction === "last") return VIEWS[VIEWS.length - 1]!;
  const offset = direction === "next" ? 1 : -1;
  return VIEWS[(VIEWS.indexOf(view) + offset + VIEWS.length) % VIEWS.length]!;
}

export function AgentOversightBody({ stewardshipState, client, auth }: {
  readonly stewardshipState: AsyncState<StewardshipResponse>;
  readonly client: OperatorApiClient;
  readonly auth: AuthContext;
}) {
  const requestedView = oversightViewFromSegment(currentRoute().segments[0]);
  const view = requestedView ?? "overview";

  const selectView = (next: AgentOversightView) => {
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
            onKeyDown={(event) => {
              const direction = event.key === "ArrowRight"
                ? "next"
                : event.key === "ArrowLeft"
                  ? "previous"
                  : event.key === "Home"
                    ? "first"
                    : event.key === "End"
                      ? "last"
                      : null;
              if (direction === null) return;
              event.preventDefault();
              const next = adjacentOversightView(item, direction);
              selectView(next);
              queueMicrotask(() => document.getElementById(`agent-oversight-tab-${next}`)?.focus());
            }}
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
      <section class="settings-iam-panel" aria-labelledby="agent-oversight-source-title">
        <header class="settings-iam-panel-head">
          <div>
            <h3 id="agent-oversight-source-title">{t("handover.sourceHealth")}</h3>
            <p>{t("handover.sourceHealthHint")}</p>
          </div>
          <StatusPill
            kind={identityHealthPillKind(data.identity_health.status)}
            label={t(`handover.identityHealthStatus.${data.identity_health.status}`)}
          />
        </header>
        <dl class="agent-oversight-source-grid">
          <dt>{t("handover.identityHealth")}</dt>
          <dd>{t(`handover.identityHealthStatus.${data.identity_health.status}`)}</dd>
          <dt>{t("handover.checkedAt")}</dt>
          <dd>{data.identity_health.checked_at ?? t("handover.notObserved")}</dd>
        </dl>
      </section>
      {maintainerBanner ? <div class={`callout callout--${maintainerBanner.level}`}>{maintainerBanner.text}</div> : null}
      {coverage.findings.length > 0 ? <CoverageFindings data={data} /> : (
        <div class="state-block state-empty">{t("handover.noFindings")}</div>
      )}
    </div>
  );
}

function HumanDependencies({ data }: { readonly data: StewardshipResponse }) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<"all" | "ready" | "attention" | "autonomous" | "proposal">("all");
  const ownership = data.current_ownership;
  if (ownership === null) {
    return (
      <div class="stack">
        <UnavailableView
          title={ownershipText("currentOwnershipUnavailableTitle")}
          message={ownershipText("currentOwnershipUnavailable")}
        />
        <LegacyOwnershipTable data={data} />
      </div>
    );
  }
  const normalizedQuery = query.trim().toLowerCase();
  const agents = ownership.agents.filter((agent) => {
    const searchText = [
      agent.name,
      ...agent.subjects.flatMap((subject) => [
        subject.display_name,
        subject.username,
        subject.subject_id,
      ]),
      ...agent.proposals.flatMap((proposal) => [
        proposal.subject.display_name,
        proposal.subject.username,
        proposal.scope_ref,
      ]),
    ].filter((value): value is string => value !== null).join(" ").toLowerCase();
    const matchesStatus = status === "all"
      || (status === "ready" && agent.coverage.status === "ready")
      || (status === "attention" && !["ready", "autonomous"].includes(agent.coverage.status))
      || (status === "autonomous" && agent.autonomous)
      || (status === "proposal" && agent.proposals.length > 0);
    return matchesStatus && (!normalizedQuery || searchText.includes(normalizedQuery));
  });
  return (
    <div class="stack current-ownership-workspace">
      <section
        class={`ownership-readiness ownership-readiness--${ownership.deployment_readiness}`}
        aria-labelledby="ownership-readiness-title"
      >
        <div>
          <span>{ownershipText("deploymentReadiness")}</span>
          <h3 id="ownership-readiness-title">
            {ownershipText(`readiness.${ownership.deployment_readiness}`)}
          </h3>
          <p>{ownershipText(`readinessHint.${ownership.deployment_readiness}`)}</p>
        </div>
        <dl>
          <dt>{ownershipText("directorySource")}</dt>
          <dd>{ownershipText(`directoryAvailability.${ownership.directory.availability}`)}</dd>
          <dt>{ownershipText("observedAt")}</dt>
          <dd>{ownership.directory.observed_at ?? t("handover.notObserved")}</dd>
          <dt>{ownershipText("assignmentSource")}</dt>
          <dd>{ownershipText(ownership.assignment_projection.truncated
            ? "assignmentAvailability.truncated"
            : `assignmentAvailability.${ownership.assignment_projection.availability}`)}</dd>
          <dt>{ownershipText("sourceRevision")}</dt>
          <dd>{ownership.source_revision ? (
            <details class="ownership-source-revision">
              <summary>{ownershipText("viewSourceRevision")}</summary>
              <code>{ownership.source_revision}</code>
            </details>
          ) : t("handover.notObserved")}</dd>
        </dl>
      </section>
      <KpiGrid>
        <KpiCard
          href={routeHref("handover", { segments: ["human-dependencies"] })}
          label={ownershipText("readyAgents")}
          value={ownership.summary.ready_agents}
          tone={ownership.summary.ready_agents === ownership.summary.agent_count ? "positive" : "default"}
        />
        <KpiCard
          href={routeHref("handover", { segments: ["human-dependencies"] })}
          label={ownershipText("coverageGapAgents")}
          value={ownership.summary.coverage_gap_agents}
          tone={ownership.summary.coverage_gap_agents > 0 ? "warning" : "positive"}
        />
        <KpiCard
          href={routeHref("handover", { segments: ["human-dependencies"] })}
          label={t("handover.autonomous")}
          value={ownership.summary.autonomous_agents}
        />
        <KpiCard
          href={routeHref("handover", { segments: ["mapping-reviews"] })}
          label={ownershipText("pendingProposals")}
          value={ownership.summary.pending_proposals}
          tone={ownership.summary.pending_proposals > 0 ? "warning" : "default"}
        />
      </KpiGrid>
      <section class="agent-oversight-maintainers" aria-labelledby="agent-oversight-maintainers-title">
        <div>
          <h3 id="agent-oversight-maintainers-title">{t("handover.maintainersTitle")}</h3>
          <p>{t("handover.maintainersHint")}</p>
        </div>
        <ul>
          {ownership.maintainers.map((maintainer, index) => (
            <li key={`${maintainer.subject_id}:${index}`}>
              <OwnershipIdentity subject={maintainer} compact />
            </li>
          ))}
        </ul>
      </section>
      <section class="stack" aria-labelledby="agent-oversight-dependencies-title">
        <header class="agent-oversight-section-head">
          <div>
            <h3 id="agent-oversight-dependencies-title">{t("handover.mapTitle")}</h3>
            <p>{t("handover.mapHint")}</p>
          </div>
          <StatusPill
            kind={readinessPillKind(ownership.deployment_readiness)}
            label={ownershipText(`readiness.${ownership.deployment_readiness}`)}
          />
        </header>
        <div class="ownership-filters" role="group" aria-label={ownershipText("filtersLabel")}>
          <input
            type="search"
            value={query}
            aria-label={ownershipText("searchOwners")}
            placeholder={ownershipText("searchOwners")}
            onInput={(event) => setQuery(event.currentTarget.value)}
          />
          <select
            value={status}
            aria-label={ownershipText("statusFilter")}
            onChange={(event) => setStatus(event.currentTarget.value as typeof status)}
          >
            <option value="all">{ownershipText("statusFilterValue.all")}</option>
            <option value="ready">{ownershipText("statusFilterValue.ready")}</option>
            <option value="attention">{ownershipText("statusFilterValue.attention")}</option>
            <option value="autonomous">{ownershipText("statusFilterValue.autonomous")}</option>
            <option value="proposal">{ownershipText("statusFilterValue.proposal")}</option>
          </select>
          <span>{ownershipText("filteredAgents", { count: agents.length })}</span>
        </div>
        {agents.length === 0 ? (
          <div class="state-block state-empty">{ownershipText("noOwnersMatch")}</div>
        ) : (
        <div class="data-table-wrap agent-oversight-ownership-table">
          <table class="cs-table">
            <thead><tr><th>{t("handover.agent")}</th><th>{ownershipText("primaryOwner")}</th><th>{ownershipText("backupOwners")}</th><th>{ownershipText("scopeAndChanges")}</th><th>{t("handover.mode")}</th></tr></thead>
            <tbody>{agents.map((agent) => <CurrentOwnershipRow agent={agent} key={agent.name} />)}</tbody>
          </table>
        </div>
        )}
      </section>
    </div>
  );
}

function LegacyOwnershipTable({ data }: { readonly data: StewardshipResponse }) {
  return (
    <section class="stack" aria-labelledby="legacy-ownership-title">
      <h3 id="legacy-ownership-title">{ownershipText("legacyOwnershipTitle")}</h3>
      <div class="data-table-wrap agent-oversight-ownership-table">
        <table class="cs-table">
          <thead><tr><th>{t("handover.agent")}</th><th>{t("handover.owners")}</th><th>{t("handover.accountableSubjects")}</th><th>{t("handover.mode")}</th></tr></thead>
          <tbody>{data.map.agents.map((agent) => {
            const mode = ownershipMode(agent.autonomous, data.identity_health.status);
            return (
              <tr key={agent.name}>
                <td><a href={routeHref("agents", { params: { agent: agent.name } })}>{agent.name}</a></td>
                <td>{agent.autonomous
                  ? <span class="ownership-autonomous-reason">{agent.accept_autonomous_reason ?? t("handover.noReason")}</span>
                  : <StewardSubjects stewards={agent.stewards} />}</td>
                <td>{agent.autonomous ? "-" : agent.bus_factor}</td>
                <td><StatusPill kind={mode.kind} label={t(mode.key)} /></td>
              </tr>
            );
          })}</tbody>
        </table>
      </div>
    </section>
  );
}

function CurrentOwnershipRow({ agent }: { readonly agent: CurrentOwnershipAgentDto }) {
  const primary = agent.subjects.filter(
    (subject) => subject.responsibility === "accountable" && subject.duty === "primary",
  );
  const backup = agent.subjects.filter(
    (subject) => subject.responsibility === "accountable"
      && (subject.duty === "backup" || subject.duty === "escalation"),
  );
  return (
    <tr>
      <td data-label={t("handover.agent")}>
        <a href={routeHref("agents", { params: { agent: agent.name } })}>{agent.name}</a>
        <small class="ownership-agent-layer">
          {ownershipText(`agentLayer.${PANTHEON.find((item) => item.name === agent.name)?.layer ?? "domain"}`)}
        </small>
      </td>
      <td data-label={ownershipText("primaryOwner")}>{agent.autonomous
        ? <span class="ownership-autonomous-reason">{agent.accept_autonomous_reason ?? t("handover.noReason")}</span>
        : primary.length > 0
          ? <span class="ownership-subject-list">{primary.map((subject) => <OwnershipIdentity subject={subject} key={`${subject.kind}:${subject.subject_id}:primary`} />)}</span>
          : <span class="ownership-gap">{ownershipText("primaryMissing")}</span>}</td>
      <td data-label={ownershipText("backupOwners")}>{agent.autonomous
        ? "-"
        : backup.length > 0
          ? <span class="ownership-subject-list">{backup.map((subject) => <OwnershipIdentity subject={subject} key={`${subject.kind}:${subject.subject_id}:${subject.duty}`} />)}</span>
          : <span class="ownership-gap">{ownershipText("backupMissing")}</span>}</td>
      <td data-label={ownershipText("scopeAndChanges")}>
        <div class="ownership-scope">
          <span>{agent.scope.scope_ref ?? ownershipText("agentDomainScope")}</span>
          <small>{ownershipText("effectiveDatesNotRecorded")}</small>
        </div>
        {agent.proposals.length > 0 ? (
          <details class="ownership-proposals">
            <summary>{ownershipText("proposedChanges", { count: agent.proposals.length })}</summary>
            <ul>{agent.proposals.map((proposal) => (
              <li key={`${proposal.case_id}:${proposal.duty}:${proposal.scope_ref}`}>
                <OwnershipIdentity subject={proposal.subject} compact />
                <span>{t(`handover.duty.${proposal.duty}`)} - <code>{proposal.scope_ref}</code></span>
                <small>{ownershipText("proposalState", {
                  state: assignmentProposalStateLabel(proposal.state),
                  revision: proposal.revision,
                })}</small>
              </li>
            ))}</ul>
          </details>
        ) : null}
      </td>
      <td data-label={t("handover.mode")}>
        <StatusPill
          kind={agentStatusPillKind(agent.coverage.status)}
          label={ownershipText(`agentStatus.${agent.coverage.status}`)}
        />
        <small class="ownership-coverage-count">
          {ownershipText("coverageCounts", {
            primary: agent.coverage.primary_count,
            backup: agent.coverage.backup_or_escalation_count,
          })}
        </small>
      </td>
    </tr>
  );
}

function OwnershipIdentity({
  subject,
  compact = false,
}: {
  readonly subject: OwnershipSubjectDto;
  readonly compact?: boolean;
}) {
  return (
    <span class={`ownership-identity ${compact ? "ownership-identity--compact" : ""}`}>
      <strong>{subject.display_name ?? ownershipText(`subjectResolution.${subject.resolution}`)}</strong>
      {subject.username ? <span>{subject.username}</span> : null}
      <small>
        {[
          t(`handover.subjectKind.${subject.kind}`),
          subject.duty ? t(`handover.duty.${subject.duty}`) : null,
          subject.roles.length > 0 ? subject.roles.join(", ") : null,
        ].filter(Boolean).join(" / ")}
      </small>
      <details>
        <summary>{ownershipText("technicalIdentity")}</summary>
        <code>{subject.subject_id}</code>
      </details>
    </span>
  );
}

function assignmentProposalStateLabel(state: string): string {
  return ASSIGNMENT_PROPOSAL_STATES.has(state)
    ? t(`settings.iam.assignmentState.${state}`)
    : t("settings.iam.notObserved");
}

function CoverageFindings({ data }: { readonly data: StewardshipResponse }) {
  const groups = groupCoverageFindings(data.coverage.findings);
  return (
    <section class="stack" aria-labelledby="agent-oversight-findings-title">
      <header class="agent-oversight-section-head">
        <div>
          <h3 id="agent-oversight-findings-title">{t("handover.findingsTitle")}</h3>
          <p>{t("handover.findingsHint")}</p>
        </div>
        <StatusPill
          kind={data.coverage.is_clean ? "success" : "warning"}
          label={t("handover.findingCount", { count: data.coverage.findings.length })}
        />
      </header>
      <ul class="agent-oversight-finding-groups">
        {groups.map((group) => (
          <li key={`${group.severity}:${group.code}`}>
            <StatusPill
              kind={group.severity === "warn" ? "warning" : "info"}
              label={t(`handover.severityValue.${group.severity}`)}
            />
            <div>
              <strong>{t(`handover.finding.${group.code}.title`)}</strong>
              <p>{t(`handover.finding.${group.code}.description`)}</p>
              <small>{group.agents.length > 0
                ? t("handover.affectedAgents", { agents: group.agents.join(", ") })
                : t("handover.mapWideFinding")}</small>
            </div>
            <span class="agent-oversight-finding-count">{group.count}</span>
          </li>
        ))}
      </ul>
      <details class="agent-oversight-raw-findings">
        <summary>{t("handover.rawFindings", { count: data.coverage.findings.length })}</summary>
        <div class="data-table-wrap"><table class="cs-table">
          <thead><tr><th>{t("handover.severity")}</th><th>{t("handover.code")}</th><th>{t("handover.agent")}</th><th>{t("handover.message")}</th></tr></thead>
          <tbody>{data.coverage.findings.map((finding, index) => (
            <tr key={`${finding.code}-${index}`}><td>{t(`handover.severityValue.${finding.severity}`)}</td><td><code>{finding.code}</code></td><td>{finding.agent ? <a href={routeHref("agents", { params: { agent: finding.agent } })}>{finding.agent}</a> : "-"}</td><td>{finding.message}</td></tr>
          ))}</tbody>
        </table></div>
      </details>
    </section>
  );
}

function StewardSubjects({ stewards }: { readonly stewards: readonly StewardDto[] }) {
  if (stewards.length === 0) return <>-</>;
  return (
    <span class="ownership-subject-list">
      {stewards.map((steward) => (
        <span class="ownership-subject" key={`${steward.kind}:${steward.id}`}>
          <code>{steward.id}</code>
          <small>
            {[
              t(`handover.subjectKind.${steward.kind}`),
              t(`handover.responsibility.${steward.responsibility}`),
              steward.duty ? t(`handover.duty.${steward.duty}`) : null,
            ].filter(Boolean).join(" / ")}
          </small>
        </span>
      ))}
    </span>
  );
}

function identityHealthPillKind(status: IdentityHealthStatus): "neutral" | "info" | "success" | "warning" {
  if (status === "clean") return "success";
  if (status === "warn") return "warning";
  if (status === "pending") return "info";
  return "neutral";
}

function readinessPillKind(
  status: OwnershipReadiness,
): "neutral" | "success" | "warning" | "danger" {
  if (status === "ready") return "success";
  if (status === "identity_unavailable") return "neutral";
  if (status === "review_required") return "warning";
  return "danger";
}

function agentStatusPillKind(
  status: OwnershipAgentStatus,
): "neutral" | "info" | "success" | "warning" | "danger" {
  if (status === "ready") return "success";
  if (status === "autonomous") return "info";
  if (status === "identity_unavailable") return "neutral";
  if (status === "identity_review" || status === "coverage_gap") return "warning";
  return "danger";
}

function ownershipMode(
  autonomous: boolean,
  identityHealth: IdentityHealthStatus,
): { readonly key: string; readonly kind: "neutral" | "info" | "success" | "warning" } {
  if (autonomous) return { key: "handover.autonomous", kind: "info" };
  if (identityHealth === "clean") return { key: "handover.mapped", kind: "success" };
  if (identityHealth === "warn") return { key: "handover.identityReview", kind: "warning" };
  if (identityHealth === "pending") return { key: "handover.identityPending", kind: "info" };
  return { key: "handover.identityUnverified", kind: "neutral" };
}

export interface CoverageFindingGroup {
  readonly code: FindingDto["code"];
  readonly severity: FindingDto["severity"];
  readonly count: number;
  readonly agents: readonly string[];
}

export function groupCoverageFindings(findings: readonly FindingDto[]): readonly CoverageFindingGroup[] {
  const groups = new Map<string, {
    code: FindingDto["code"];
    severity: FindingDto["severity"];
    count: number;
    agents: Set<string>;
  }>();
  for (const finding of findings) {
    const key = `${finding.severity}:${finding.code}`;
    const group = groups.get(key) ?? {
      code: finding.code,
      severity: finding.severity,
      count: 0,
      agents: new Set<string>(),
    };
    group.count += 1;
    if (finding.agent) group.agents.add(finding.agent);
    groups.set(key, group);
  }
  return [...groups.values()].map((group) => ({
    code: group.code,
    severity: group.severity,
    count: group.count,
    agents: [...group.agents].sort(),
  }));
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
