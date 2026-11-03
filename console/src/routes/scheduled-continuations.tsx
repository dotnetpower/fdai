import { useEffect, useMemo, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import { EvidenceRefresh } from "../components/evidence-refresh";
import {
  AsyncBoundary,
  CopyButton,
  DataTable,
  EmptyState,
  KpiCard,
  KpiGrid,
  PageHeader,
  StatusPill,
  type AsyncState,
  type Column,
} from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { composeGlossary } from "../deck/glossary";
import { currentRoute, routeHref } from "../router";
import { formatConsoleTimestamp } from "../time-format";
import { presentationLabel, t } from "./i18n/evidence";
import {
  decodeUserContext,
  fetchUserContext,
  type ScheduledContinuationPayload,
  UserContextRequestError,
} from "../user-context-client";
import type { ConsoleDataMode } from "../console-data-mode";
import { OPERATIONS_SAMPLE_CONTINUATIONS } from "./operations.sample";

interface ContinuationResponse {
  readonly continuations: readonly ScheduledContinuationPayload[];
}

export function ScheduledContinuationsRoute({
  client,
  dataMode,
}: {
  readonly client: OperatorApiClient;
  readonly dataMode: ConsoleDataMode;
}) {
  const [refreshRevision, setRefreshRevision] = useState(0);
  const [state, setState] = useState<AsyncState<ContinuationResponse>>({ status: "loading" });
  useEffect(() => {
    let cancelled = false;
    if (dataMode === "sample") {
      setState({
        status: "ready",
        data: { continuations: OPERATIONS_SAMPLE_CONTINUATIONS },
      });
      return () => {
        cancelled = true;
      };
    }
    setState({ status: "loading" });
    fetchUserContext()
      .then((context) => ({ continuations: context.scheduled_continuations }))
      .catch(async (primaryError: unknown) => {
        try {
          return decodeScheduledContinuations(await client.panel<unknown>("/me/context"));
        } catch {
          throw primaryError;
        }
      })
      .then((data) => {
        if (!cancelled) setState({ status: "ready", data });
      })
      .catch((error: unknown) => {
        if (!cancelled) setState({
          status: error instanceof UserContextRequestError && error.status === 503
            ? "unavailable"
            : "error",
          message: error instanceof Error ? error.message : String(error),
        });
      });
    return () => { cancelled = true; };
  }, [client, dataMode, refreshRevision]);
  return (
    <div class="stack cs-workspace-route">
      <PageHeader
        title={t("route.scheduledContinuations")}
        subtitle={t("nav.panelSub.scheduledContinuations")}
        actions={
          <EvidenceRefresh
            loading={state.status === "loading"}
            onRefresh={() => setRefreshRevision((revision) => revision + 1)}
          />
        }
      />
      <AsyncBoundary state={state} resourceLabel={t("evidence.continuations.resource")}>
        {(data) => <ContinuationBody data={data} />}
      </AsyncBoundary>
    </div>
  );
}

export function decodeScheduledContinuations(value: unknown): ContinuationResponse {
  return { continuations: decodeUserContext(value).scheduled_continuations };
}

export function scheduledContinuationColumns(): readonly Column<ScheduledContinuationPayload>[] {
  return [
    { key: "result", header: t("evidence.continuations.column.result"), render: (item) => <div><strong>{item.result_summary.split("\n", 1)[0]}</strong><small>{item.run_id}</small></div> },
    { key: "state", header: t("evidence.continuations.column.state"), render: (item) => <StatusPill kind={item.state === "active" ? "success" : "neutral"} label={presentationLabel("status", item.state)} /> },
    { key: "scope", header: t("evidence.continuations.column.scope"), render: (item) => <code>{item.scope_ref}</code> },
    { key: "window", header: t("evidence.continuations.column.window"), render: (item) => `${formatConsoleTimestamp(item.observation_started_at)} - ${formatConsoleTimestamp(item.observation_ended_at)}` },
    { key: "origin", header: t("evidence.continuations.column.origin"), render: (item) => `${item.origin.channel_kind}:${item.origin.conversation_ref}${item.origin.thread_ref ? `:${item.origin.thread_ref}` : ""}` },
    { key: "evidence", header: t("evidence.continuations.column.evidence"), render: (item) => item.evidence_refs.length, cellClass: "num" },
    { key: "digest", header: t("evidence.continuations.column.digest"), render: (item) => <code>{item.result_digest.slice(0, 12)}</code> },
    { key: "expiry", header: t("evidence.continuations.column.expiry"), render: (item) => formatConsoleTimestamp(item.expires_at) },
  ];
}

function ContinuationBody({ data }: { readonly data: ContinuationResponse }) {
  const columns = scheduledContinuationColumns();
  const [query, setQuery] = useState("");
  const [stateFilter, setStateFilter] = useState("all");
  const [selectedAnchorId, setSelectedAnchorId] = useState<string | null>(
    () => data.continuations[0]?.anchor_id ?? null,
  );
  const states = useMemo(
    () => [...new Set(data.continuations.map((item) => item.state))].sort(),
    [data.continuations],
  );
  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return data.continuations.filter((item) => {
      if (stateFilter !== "all" && item.state !== stateFilter) return false;
      if (!needle) return true;
      return [
        item.anchor_id,
        item.task_id,
        item.run_id,
        item.scope_ref,
        item.result_summary,
        item.origin.channel_kind,
        item.origin.conversation_ref,
        ...item.evidence_refs,
      ].join(" ").toLocaleLowerCase().includes(needle);
    });
  }, [data.continuations, query, stateFilter]);
  const selected = filtered.find((item) => item.anchor_id === selectedAnchorId) ?? filtered[0] ?? null;
  const activeCount = data.continuations.filter((item) => item.state === "active").length;
  const archivedCount = data.continuations.length - activeCount;
  const totalEvidenceRefs = data.continuations.reduce((sum, item) => sum + item.evidence_refs.length, 0);
  const anchorsHref = `${routeHref("scheduled-continuations", {
    params: { data: currentRoute().search.get("data") === "sample" ? "sample" : null },
  })}#scheduled-continuation-anchors`;

  usePublishViewContext(
    () => ({
      routeId: "scheduled-continuations",
      routeLabel: t("route.scheduledContinuations"),
      purpose: t("evidence.continuations.viewPurpose"),
      glossary: composeGlossary([], [{ term: t("evidence.continuations.glossaryTerm"), plain: t("evidence.continuations.glossaryPlain"), tech: "ScheduledConversationAnchor" }]),
      headline: t("evidence.continuations.headline", { count: activeCount }),
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "anchor_count", value: data.continuations.length, group: "continuity" },
        { key: "active_count", value: activeCount, group: "continuity" },
        { key: "evidence_ref_count", value: totalEvidenceRefs, group: "continuity" },
        { key: "mutation_controls", value: false, group: "safety" },
      ],
      records: { continuations: data.continuations.map((item) => ({ ...item })) },
    }),
    [activeCount, data, totalEvidenceRefs],
  );

  return (
    <div class="stack">
      <div class="governance-readonly-banner">
        <strong>{t("evidence.continuations.bannerTitle")}</strong>
        <span>{t("evidence.continuations.bannerBody")}</span>
      </div>
      <KpiGrid>
        <KpiCard href={anchorsHref} label={t("evidence.continuations.column.result")} value={data.continuations.length.toLocaleString()} />
        <KpiCard href={anchorsHref} label={presentationLabel("status", "active")} value={activeCount.toLocaleString()} tone={activeCount > 0 ? "positive" : "default"} />
        <KpiCard href={anchorsHref} label={presentationLabel("status", "expired")} value={archivedCount.toLocaleString()} />
        <KpiCard href={anchorsHref} label={t("evidence.continuations.column.evidence")} value={totalEvidenceRefs.toLocaleString()} />
      </KpiGrid>
      <div class="cs-filter-toolbar" role="search">
        <label class="is-wide">
          <span>{t("evidence.continuations.column.result")}</span>
          <input
            type="search"
            value={query}
            placeholder="run_id, scope, conversation..."
            onInput={(event) => setQuery(event.currentTarget.value)}
          />
        </label>
        <label>
          <span>{t("evidence.continuations.column.state")}</span>
          <select value={stateFilter} onChange={(event) => setStateFilter(event.currentTarget.value)}>
            <option value="all">{t("shared.all")}</option>
            {states.map((state) => (
              <option key={state} value={state}>{presentationLabel("status", state)}</option>
            ))}
          </select>
        </label>
        <span class="cs-filter-count" role="status" aria-live="polite">
          {filtered.length} / {data.continuations.length}
        </span>
      </div>
      <div id="scheduled-continuation-anchors" class={`cs-workspace-split${selected ? " has-selection" : ""}`}>
        <div class="cs-workspace-main">
          <DataTable
            rows={filtered}
            columns={columns}
            keyOf={(item) => item.anchor_id}
            onRowClick={(item) => setSelectedAnchorId(item.anchor_id)}
            isRowActive={(item) => item.anchor_id === selected?.anchor_id}
            rowActionLabel={(item) => `${t("evidence.continuations.column.result")}: ${item.run_id}`}
            rowActionControls="scheduled-continuation-detail"
            scrollRegionLabel={t("route.scheduledContinuations")}
            empty={<EmptyState title={t("evidence.continuations.empty")} />}
          />
        </div>
        {selected ? (
          <aside id="scheduled-continuation-detail" class="cs-inspector-pane" aria-label={selected.run_id}>
            <header class="cs-inspector-head">
              <div>
                <span class="cs-inspector-kicker">{selected.anchor_id}</span>
                <h3>{selected.result_summary.split("\n", 1)[0]}</h3>
                <p>{selected.result_summary}</p>
              </div>
              <StatusPill
                kind={selected.state === "active" ? "success" : "neutral"}
                label={presentationLabel("status", selected.state)}
              />
            </header>
            <dl class="cs-facts-grid">
              <div><dt>{t("evidence.continuations.column.scope")}</dt><dd><code>{selected.scope_ref}</code></dd></div>
              <div><dt>Task / Run</dt><dd><code>{selected.task_id}</code> / <code>{selected.run_id}</code></dd></div>
              <div><dt>{t("evidence.continuations.column.origin")}</dt><dd><code>{selected.origin.channel_kind}:{selected.origin.conversation_ref}</code></dd></div>
              <div><dt>{t("evidence.continuations.column.window")}</dt><dd>{formatConsoleTimestamp(selected.observation_started_at)} - {formatConsoleTimestamp(selected.observation_ended_at)}</dd></div>
              <div><dt>{t("evidence.continuations.column.expiry")}</dt><dd>{formatConsoleTimestamp(selected.expires_at)}</dd></div>
              <div>
                <dt>{t("evidence.continuations.column.digest")}</dt>
                <dd>
                  <code>{selected.result_digest.slice(0, 16)}...</code>{" "}
                  <CopyButton text={selected.result_digest} label={t("evidence.continuations.column.digest")} />
                </dd>
              </div>
              <div>
                <dt>{t("evidence.continuations.column.evidence")}</dt>
                <dd>{selected.evidence_refs.length ? selected.evidence_refs.map((ref) => <code key={ref}>{ref} </code>) : t("evidence.common.none")}</dd>
              </div>
            </dl>
          </aside>
        ) : null}
      </div>
    </div>
  );
}
