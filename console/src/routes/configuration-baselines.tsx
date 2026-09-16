import type { ComponentChildren } from "preact";
import { useEffect, useState } from "preact/hooks";

import { isOptionalOperatorApiUnavailable, type OperatorApiClient } from "../api";
import {
  AsyncBoundary,
  EmptyState,
  KpiCard,
  KpiGrid,
  PageHeader,
  StatusPill,
  type AsyncState,
  type PillKind,
} from "../components/ui";
import { currentRoute, navigate, routeHref } from "../router";
import { formatConsoleTimestamp } from "../time-format";
import { configurationBaselinesText } from "./configuration-baselines.i18n";
import {
  decodeConfigurationBaselines,
  type ConfigurationBaselineVersionView,
  type ConfigurationBaselinesView,
} from "./configuration-baselines.model";

export { decodeConfigurationBaselines };

type ConfigurationBaselineView = "baseline" | "drift" | "review";

const CONFIGURATION_BASELINE_VIEWS = [
  { id: "baseline", label: "viewBaseline" },
  { id: "drift", label: "viewDrift" },
  { id: "review", label: "viewReview" },
] as const;

export function ConfigurationBaselinesRoute({ client }: { readonly client: OperatorApiClient }) {
  const [state, setState] = useState<AsyncState<ConfigurationBaselinesView>>({ status: "loading" });
  const view = activeConfigurationBaselineView();
  useEffect(() => {
    let active = true;
    setState({ status: "loading" });
    void loadConfigurationBaselines(client).then((next) => { if (active) setState(next); });
    return () => { active = false; };
  }, [client]);
  return (
    <div class="stack configuration-baselines-route">
      <PageHeader
        title={configurationBaselinesText("title")}
        subtitle={configurationBaselinesText("subtitle")}
      />
      <ConfigurationBaselineTabs activeView={view} />
      {CONFIGURATION_BASELINE_VIEWS.map((item) => (
        <div
          key={item.id}
          id={`configuration-baselines-panel-${item.id}`}
          class="configuration-baselines-panel"
          role="tabpanel"
          aria-labelledby={`configuration-baselines-tab-${item.id}`}
          hidden={view !== item.id}
        >
          {view === item.id ? (
            <AsyncBoundary
              state={state}
              resourceLabel={configurationBaselinesText("resourceLabel")}
            >
              {(data) => <ConfigurationBaselinesBody data={data} view={view} />}
            </AsyncBoundary>
          ) : null}
        </div>
      ))}
    </div>
  );
}

export async function loadConfigurationBaselines(client: OperatorApiClient): Promise<AsyncState<ConfigurationBaselinesView>> {
  try {
    return { status: "ready", data: decodeConfigurationBaselines(await client.panel<unknown>("/configuration-baselines")) };
  } catch (error) {
    return isOptionalOperatorApiUnavailable(error) ? { status: "unavailable", message: configurationBaselinesText("unavailable") } : { status: "error", message: error instanceof Error ? error.message : String(error) };
  }
}

function ConfigurationBaselineTabs({ activeView }: { readonly activeView: ConfigurationBaselineView }) {
  return (
    <nav
      class="configuration-baselines-tabs"
      role="tablist"
      aria-label={configurationBaselinesText("viewsLabel")}
    >
      {CONFIGURATION_BASELINE_VIEWS.map((item, index) => (
        <button
          key={item.id}
          id={`configuration-baselines-tab-${item.id}`}
          class={activeView === item.id ? "active" : undefined}
          type="button"
          role="tab"
          aria-selected={activeView === item.id}
          aria-controls={`configuration-baselines-panel-${item.id}`}
          tabIndex={activeView === item.id ? 0 : -1}
          onClick={() => navigate(configurationBaselineViewHref(item.id))}
          onKeyDown={(event) => {
            const targetIndex = event.key === "ArrowRight"
              ? (index + 1) % CONFIGURATION_BASELINE_VIEWS.length
              : event.key === "ArrowLeft"
                ? (index - 1 + CONFIGURATION_BASELINE_VIEWS.length) % CONFIGURATION_BASELINE_VIEWS.length
                : event.key === "Home"
                  ? 0
                  : event.key === "End"
                    ? CONFIGURATION_BASELINE_VIEWS.length - 1
                    : null;
            if (targetIndex === null) return;
            event.preventDefault();
            const next = CONFIGURATION_BASELINE_VIEWS[targetIndex]!;
            navigate(configurationBaselineViewHref(next.id));
            queueMicrotask(() => document.getElementById(`configuration-baselines-tab-${next.id}`)?.focus());
          }}
        >
          {configurationBaselinesText(item.label)}
        </button>
      ))}
    </nav>
  );
}

function ConfigurationBaselinesBody({
  data,
  view,
}: {
  readonly data: ConfigurationBaselinesView;
  readonly view: ConfigurationBaselineView;
}) {
  const published = data.baseline.lifecycle !== "not-published";
  const driftEvaluated = data.drift.observedAt !== null && data.drift.verdict !== "not-evaluated";
  const knowledgeIndexed = data.knowledge.status === "cited";
  return (
    <div class="stack configuration-baselines-body">
      <div class="governance-readonly-banner">
        <strong>{configurationBaselinesText("bannerTitle")}</strong>
        <span>{configurationBaselinesText("bannerBody")}</span>
      </div>
      <KpiGrid>
        <KpiCard
          evidenceState={published ? "measured" : "not-measured"}
          href={configurationBaselineViewHref("baseline")}
          label={configurationBaselinesText("version")}
          value={published ? data.baseline.version : configurationBaselinesText("notPublished")}
          hint={configurationBaselinesText("versionHint")}
        />
        <KpiCard
          evidenceState={driftEvaluated ? "measured" : "not-measured"}
          href={configurationBaselineViewHref("drift")}
          label={configurationBaselinesText("decision")}
          value={verdictLabel(data.drift.verdict)}
          hint={configurationBaselinesText("driftHint")}
        />
        <KpiCard
          evidenceState={knowledgeIndexed ? "measured" : "not-measured"}
          href={configurationBaselineViewHref("drift")}
          label={configurationBaselinesText("citations")}
          value={knowledgeIndexed
            ? data.knowledge.citationCount
            : knowledgeStatusLabel(data.knowledge.status)}
          hint={configurationBaselinesText("citationsHint")}
        />
        <KpiCard
          evidenceState={data.performance === null ? "not-measured" : "measured"}
          href={configurationBaselineViewHref("drift")}
          label={configurationBaselinesText("totalLatency")}
          value={formatLatency(data.performance?.totalMs ?? null)}
          hint={configurationBaselinesText("latencyHint")}
        />
      </KpiGrid>
      <div class="configuration-baselines-view">
        {view === "baseline" ? (
          <>
            <EvidenceSection
              id="baseline"
              title={configurationBaselinesText("baseline")}
              rows={[
                [configurationBaselinesText("scope"), published ? <code class="small">{data.baseline.scope}</code> : configurationBaselinesText("notConfigured")],
                [configurationBaselinesText("created"), formatConsoleTimestamp(data.baseline.createdAt, configurationBaselinesText("notAvailable"))],
                [configurationBaselinesText("document"), published ? <code class="small">{data.baseline.documentName}</code> : configurationBaselinesText("notAvailable")],
                [configurationBaselinesText("lifecycle"), <StatusPill kind={tone(data.baseline.lifecycle)} label={lifecycleLabel(data.baseline.lifecycle)} />],
                [configurationBaselinesText("resources"), published ? data.baseline.resourceCount : configurationBaselinesText("notAvailable")],
                [configurationBaselinesText("topology"), published ? data.baseline.topologyCount : configurationBaselinesText("notAvailable")],
                [configurationBaselinesText("unknown"), published ? data.baseline.unknownCount : configurationBaselinesText("notAvailable")],
              ]}
            />
            <BaselineHistory versions={data.versions} />
          </>
        ) : null}
        {view === "drift" ? (
          <>
            <EvidenceSection
              id="drift"
              title={configurationBaselinesText("drift")}
              description={configurationBaselinesText("driftDescription")}
              rows={[
                [configurationBaselinesText("decision"), <StatusPill kind={tone(data.drift.verdict)} label={verdictLabel(data.drift.verdict)} />],
                [configurationBaselinesText("findings"), driftEvaluated ? data.drift.findingCount : configurationBaselinesText("notAvailable")],
                [configurationBaselinesText("observed"), formatConsoleTimestamp(data.drift.observedAt, configurationBaselinesText("notAvailable"))],
              ]}
            />
            <EvidenceSection
              id="knowledge"
              title={configurationBaselinesText("knowledge")}
              description={configurationBaselinesText("knowledgeDescription")}
              rows={[
                [configurationBaselinesText("decision"), <StatusPill kind={tone(data.knowledge.status)} label={knowledgeStatusLabel(data.knowledge.status)} />],
                [configurationBaselinesText("citations"), knowledgeIndexed ? data.knowledge.citationCount : configurationBaselinesText("notAvailable")],
              ]}
            />
            <EvidenceSection
              id="performance"
              title={configurationBaselinesText("performance")}
              description={configurationBaselinesText("performanceDescription")}
              rows={[
                [configurationBaselinesText("totalLatency"), formatLatency(data.performance?.totalMs ?? null)],
                [configurationBaselinesText("observationLatency"), formatLatency(data.performance?.observationMs ?? null)],
                [configurationBaselinesText("knowledgeLatency"), formatLatency(data.performance?.knowledgeMs ?? null)],
              ]}
            />
          </>
        ) : null}
        {view === "review" ? (
          <>
            <EvidenceSection
              id="review"
              title={configurationBaselinesText("review")}
              description={configurationBaselinesText("reviewDescription")}
              rows={[
                [configurationBaselinesText("decision"), reviewLabel(data.review)],
                [configurationBaselinesText("completedRuns"), data.review.configured ? `${data.review.completedRuns}/${data.review.requiredRuns}` : configurationBaselinesText("notAvailable")],
                [configurationBaselinesText("failedAttempts"), data.review.configured ? data.review.failedAttempts : configurationBaselinesText("notAvailable")],
              ]}
            />
            <EvidenceSection
              id="safety"
              title={configurationBaselinesText("safety")}
              description={configurationBaselinesText("safetyDescription")}
              rows={[
                [configurationBaselinesText("mutation"), published ? data.safety.mutation : configurationBaselinesText("notAvailable")],
                [configurationBaselinesText("approval"), published ? data.safety.approval : configurationBaselinesText("notAvailable")],
                [configurationBaselinesText("mitigation"), published ? data.safety.mitigation : configurationBaselinesText("notAvailable")],
                [configurationBaselinesText("unsupported"), published ? data.safety.unsupported : configurationBaselinesText("notAvailable")],
              ]}
            />
          </>
        ) : null}
      </div>
    </div>
  );
}

function BaselineHistory({ versions }: { readonly versions: readonly ConfigurationBaselineVersionView[] }) {
  return (
    <section id="versions" class="stack-section" aria-labelledby="configuration-baseline-history-title">
      <header class="configuration-baselines-section-header">
        <h3 id="configuration-baseline-history-title" class="section-title">
          {configurationBaselinesText("history")}
        </h3>
        <p>{configurationBaselinesText("historyDescription")}</p>
      </header>
      {versions.length === 0 ? (
        <EmptyState
          title={configurationBaselinesText("historyEmptyTitle")}
          body={configurationBaselinesText("historyEmptyBody")}
        />
      ) : (
        <div class="data-table-wrap configuration-baselines-history">
          <table class="data-table">
            <caption class="sr-only">{configurationBaselinesText("historyCaption")}</caption>
            <thead>
              <tr>
                <th scope="col">{configurationBaselinesText("version")}</th>
                <th scope="col">{configurationBaselinesText("lifecycle")}</th>
                <th scope="col">{configurationBaselinesText("created")}</th>
                <th scope="col" class="num">{configurationBaselinesText("resources")}</th>
                <th scope="col">{configurationBaselinesText("comparison")}</th>
                <th scope="col" class="num">{configurationBaselinesText("findings")}</th>
              </tr>
            </thead>
            <tbody>
              {versions.map((version) => (
                <tr key={version.version}>
                  <td><code class="small">{version.version}</code></td>
                  <td><StatusPill kind={tone(version.status)} label={statusLabel(version.status)} /></td>
                  <td>{formatConsoleTimestamp(version.createdAt)}</td>
                  <td class="num">{version.resourceCount}</td>
                  <td><StatusPill kind={tone(version.comparison.verdict)} label={verdictLabel(version.comparison.verdict)} /></td>
                  <td class="num">{version.comparison.findingCount}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function EvidenceSection({
  id,
  title,
  description,
  rows,
}: {
  readonly id: string;
  readonly title: string;
  readonly description?: string;
  readonly rows: readonly (readonly [string, ComponentChildren])[];
}) {
  const titleId = `configuration-baselines-${id}-title`;
  return (
    <section id={id} class="stack-section" aria-labelledby={titleId}>
      <header class="configuration-baselines-section-header">
        <h3 id={titleId} class="section-title">{title}</h3>
        {description ? <p>{description}</p> : null}
      </header>
      <dl class="details-list">
        {rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
      </dl>
    </section>
  );
}

function tone(value: string): PillKind {
  if (value === "passed" || value === "cited" || value === "active" || value === "active-pinned") {
    return "success";
  }
  if (value === "failed") return "danger";
  if (value === "blocked" || value === "paused-failed") return "warning";
  return "neutral";
}

function reviewLabel(review: ConfigurationBaselinesView["review"]): string {
  if (!review.configured) return configurationBaselinesText("reviewNotConfigured");
  if (review.state === "active") return configurationBaselinesText("reviewActive");
  if (review.state === "ready-for-weekly") return configurationBaselinesText("reviewReady");
  if (review.state === "paused-failed") return configurationBaselinesText("reviewPaused");
  return review.state;
}

function statusLabel(status: string): string {
  if (status === "active") return configurationBaselinesText("statusActive");
  if (status === "candidate") return configurationBaselinesText("statusCandidate");
  if (status === "superseded") return configurationBaselinesText("statusSuperseded");
  if (status === "archived") return configurationBaselinesText("statusArchived");
  return status;
}

function lifecycleLabel(lifecycle: string): string {
  if (lifecycle === "active-pinned") return configurationBaselinesText("statusActivePinned");
  if (lifecycle === "not-published") return configurationBaselinesText("notPublished");
  return statusLabel(lifecycle);
}

function verdictLabel(verdict: string): string {
  if (verdict === "passed") return configurationBaselinesText("verdictPassed");
  if (verdict === "failed") return configurationBaselinesText("verdictFailed");
  if (verdict === "blocked") return configurationBaselinesText("verdictBlocked");
  if (verdict === "not-evaluated") return configurationBaselinesText("verdictNotEvaluated");
  return verdict;
}

function knowledgeStatusLabel(status: string): string {
  if (status === "cited") return configurationBaselinesText("knowledgeCited");
  if (status === "not-indexed") return configurationBaselinesText("knowledgeNotIndexed");
  if (status === "not-configured") return configurationBaselinesText("notConfigured");
  return verdictLabel(status);
}

function formatLatency(value: number | null): string {
  return value === null
    ? configurationBaselinesText("notMeasured")
    : `${value.toFixed(1)} ms`;
}

function isConfigurationBaselineView(value: string | undefined): value is ConfigurationBaselineView {
  return value === "baseline" || value === "drift" || value === "review";
}

function activeConfigurationBaselineView(): ConfigurationBaselineView {
  const value = currentRoute().segments[0];
  return isConfigurationBaselineView(value) ? value : "baseline";
}

function configurationBaselineViewHref(view: ConfigurationBaselineView): string {
  return routeHref("configuration-baselines", {
    segments: view === "baseline" ? [] : [view],
    params: Object.fromEntries(currentRoute().search.entries()),
  });
}
