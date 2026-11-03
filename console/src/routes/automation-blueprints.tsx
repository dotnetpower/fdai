import { useEffect, useMemo, useState } from "preact/hooks";
import { isOptionalOperatorApiUnavailable, type OperatorApiClient } from "../api";
import { EvidenceRefresh } from "../components/evidence-refresh";
import {
  AsyncBoundary,
  DataTable,
  EmptyState,
  KpiCard,
  KpiGrid,
  PageHeader,
  StatusPill,
  kpiEvidenceLabel,
  type AsyncState,
  type Column,
} from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { composeGlossary } from "../deck/glossary";
import { getLocale } from "../i18n";
import { currentRoute, routeHref } from "../router";
import { formatConsoleTimestamp } from "../time-format";
import { presentationLabel, t } from "./i18n/evidence";
import {
  panelArray,
  panelBoolean,
  panelNonEmptyString,
  panelNonNegativeInteger,
  panelNonNegativeNumber,
  panelRecord,
  panelStringArray,
} from "./panel-decode";

interface BlueprintCard {
  readonly candidate_id: string;
  readonly state: string;
  readonly normalized_task_intent: string;
  readonly schedule_expression: string;
  readonly resource_scope: string;
  readonly delivery_intent: string;
  readonly required_tools: readonly string[];
  readonly isolation_profile: {
    readonly profile_id: string;
    readonly max_session_seconds: number;
    readonly max_context_chars: number;
    readonly max_tool_calls: number;
    readonly allowed_tool_ids: readonly string[];
  };
  readonly estimated_cost_microusd: number;
  readonly evidence_fingerprints: readonly string[];
  readonly confidence: number;
  readonly expires_at: string;
  readonly enabled: boolean;
  readonly shadow_only: boolean;
  readonly mutation_tool_ids: readonly string[];
}

export interface AutomationBlueprintResponse {
  readonly source: string;
  readonly mutation_controls: boolean;
  readonly count: number;
  readonly candidates: readonly BlueprintCard[];
  readonly metrics: {
    readonly proposed: number;
    readonly accepted: number;
    readonly rejected: number;
    readonly expired: number;
    readonly materialized: number;
    readonly realized_usage: number;
    readonly candidate_precision: number;
    readonly acceptance_rate: number;
  };
}

export function AutomationBlueprintsRoute({ client }: { readonly client: OperatorApiClient }) {
  const [refreshRevision, setRefreshRevision] = useState(0);
  const [state, setState] = useState<AsyncState<AutomationBlueprintResponse>>({ status: "loading" });
  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    client.panel<unknown>("/automation-blueprints")
      .then((value) => { if (!cancelled) setState({ status: "ready", data: decodeAutomationBlueprints(value) }); })
      .catch((error: unknown) => { if (!cancelled) setState({ status: isOptionalOperatorApiUnavailable(error) ? "unavailable" : "error", message: error instanceof Error ? error.message : String(error) }); });
    return () => { cancelled = true; };
  }, [client, refreshRevision]);
  return (
    <div class="stack cs-workspace-route">
      <PageHeader
        title={t("route.automationBlueprints")}
        subtitle={t("nav.panelSub.automationBlueprints")}
        actions={
          <EvidenceRefresh
            loading={state.status === "loading"}
            onRefresh={() => {
              setState({ status: "loading" });
              setRefreshRevision((revision) => revision + 1);
            }}
          />
        }
      />
      <AsyncBoundary state={state} resourceLabel={t("evidence.blueprints.resource")}>
        {(data) => <BlueprintBody data={data} />}
      </AsyncBoundary>
    </div>
  );
}

export function decodeAutomationBlueprints(value: unknown): AutomationBlueprintResponse {
  const root = panelRecord(value, "automation blueprints");
  const candidates = panelArray(root["candidates"], "automation blueprints.candidates")
    .map((raw, index) => decodeCard(raw, index));
  const seenIds = new Set<string>();
  for (const candidate of candidates) {
    if (seenIds.has(candidate.candidate_id)) {
      throw new Error("invalid Operator API response: automation blueprint candidate_id MUST be unique");
    }
    seenIds.add(candidate.candidate_id);
  }
  const count = panelNonNegativeInteger(root, "count", "automation blueprints");
  if (count !== candidates.length) throw new Error("invalid Operator API response: automation blueprint count MUST match candidates");
  const mutationControls = panelBoolean(root, "mutation_controls", "automation blueprints");
  if (mutationControls) {
    throw new Error("automation blueprints mutation controls MUST be false");
  }
  const metrics = panelRecord(root["metrics"], "automation blueprints.metrics");
  return {
    source: panelNonEmptyString(root, "source", "automation blueprints"),
    mutation_controls: false,
    count,
    candidates,
    metrics: {
      proposed: panelNonNegativeInteger(metrics, "proposed", "automation blueprints.metrics"),
      accepted: panelNonNegativeInteger(metrics, "accepted", "automation blueprints.metrics"),
      rejected: panelNonNegativeInteger(metrics, "rejected", "automation blueprints.metrics"),
      expired: panelNonNegativeInteger(metrics, "expired", "automation blueprints.metrics"),
      materialized: panelNonNegativeInteger(metrics, "materialized", "automation blueprints.metrics"),
      realized_usage: panelNonNegativeInteger(metrics, "realized_usage", "automation blueprints.metrics"),
      candidate_precision: ratio(metrics, "candidate_precision"),
      acceptance_rate: ratio(metrics, "acceptance_rate"),
    },
  };
}

function decodeCard(value: unknown, index: number): BlueprintCard {
  const label = `automation blueprints.candidates[${index}]`;
  const item = panelRecord(value, label);
  const isolation = panelRecord(item["isolation_profile"], `${label}.isolation_profile`);
  return {
    candidate_id: panelNonEmptyString(item, "candidate_id", label),
    state: panelNonEmptyString(item, "state", label),
    normalized_task_intent: panelNonEmptyString(item, "normalized_task_intent", label),
    schedule_expression: panelNonEmptyString(item, "schedule_expression", label),
    resource_scope: panelNonEmptyString(item, "resource_scope", label),
    delivery_intent: panelNonEmptyString(item, "delivery_intent", label),
    required_tools: panelStringArray(item["required_tools"], `${label}.required_tools`),
    isolation_profile: {
      profile_id: panelNonEmptyString(isolation, "profile_id", `${label}.isolation_profile`),
      max_session_seconds: panelNonNegativeInteger(isolation, "max_session_seconds", `${label}.isolation_profile`),
      max_context_chars: panelNonNegativeInteger(isolation, "max_context_chars", `${label}.isolation_profile`),
      max_tool_calls: panelNonNegativeInteger(isolation, "max_tool_calls", `${label}.isolation_profile`),
      allowed_tool_ids: panelStringArray(isolation["allowed_tool_ids"], `${label}.isolation_profile.allowed_tool_ids`),
    },
    estimated_cost_microusd: panelNonNegativeInteger(item, "estimated_cost_microusd", label),
    evidence_fingerprints: panelStringArray(item["evidence_fingerprints"], `${label}.evidence_fingerprints`),
    confidence: ratio(item, "confidence"),
    expires_at: panelNonEmptyString(item, "expires_at", label),
    enabled: panelBoolean(item, "enabled", label),
    shadow_only: panelBoolean(item, "shadow_only", label),
    mutation_tool_ids: panelStringArray(item["mutation_tool_ids"], `${label}.mutation_tool_ids`),
  };
}

function ratio(value: Readonly<Record<string, unknown>>, key: string): number {
  const result = panelNonNegativeNumber(value, key, "automation blueprints");
  if (result > 1) throw new Error(`invalid Operator API response: ${key} MUST be <= 1`);
  return result;
}

export function automationBlueprintColumns(): readonly Column<BlueprintCard>[] {
  return [
    { key: "intent", header: t("evidence.blueprints.column.automation"), render: (item) => <div><strong>{item.normalized_task_intent}</strong><small>{item.schedule_expression}</small></div> },
    { key: "state", header: t("evidence.blueprints.column.state"), render: (item) => <StatusPill kind={item.state === "draft" ? "shadow" : item.state === "materialized" ? "success" : "warning"} label={presentationLabel("status", item.state)} /> },
    { key: "scope", header: t("evidence.blueprints.column.scope"), render: (item) => <code>{item.resource_scope}</code> },
    { key: "evidence", header: t("evidence.blueprints.column.evidence"), render: (item) => item.evidence_fingerprints.length },
    { key: "tools", header: t("evidence.blueprints.column.tools"), render: (item) => item.required_tools.join(", ") || t("evidence.common.none") },
    { key: "isolation", header: t("evidence.blueprints.column.isolation"), render: (item) => `${item.isolation_profile.profile_id}; ${t("evidence.blueprints.toolCalls", { count: item.isolation_profile.max_tool_calls })}` },
    { key: "cost", header: t("evidence.blueprints.column.cost"), render: (item) => t("evidence.blueprints.microUsd", { cost: item.estimated_cost_microusd }) },
    { key: "confidence", header: t("evidence.blueprints.column.confidence"), render: (item) => `${(item.confidence * 100).toFixed(1)}%` },
  ];
}

function BlueprintBody({ data }: { readonly data: AutomationBlueprintResponse }) {
  const columns = automationBlueprintColumns();
  const [query, setQuery] = useState("");
  const [stateFilter, setStateFilter] = useState("all");
  const [selectedId, setSelectedId] = useState<string | null>(
    () => data.candidates[0]?.candidate_id ?? null,
  );
  const states = useMemo(
    () => [...new Set(data.candidates.map((item) => item.state))].sort(),
    [data.candidates],
  );
  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return data.candidates.filter((item) => {
      if (stateFilter !== "all" && item.state !== stateFilter) return false;
      if (!needle) return true;
      return [
        item.candidate_id,
        item.normalized_task_intent,
        item.schedule_expression,
        item.resource_scope,
        item.delivery_intent,
        item.isolation_profile.profile_id,
        ...item.required_tools,
      ].join(" ").toLocaleLowerCase().includes(needle);
    });
  }, [data.candidates, query, stateFilter]);
  const selected = filtered.find((item) => item.candidate_id === selectedId) ?? filtered[0] ?? null;

  usePublishViewContext(
    () => ({
      routeId: "automation-blueprints",
      routeLabel: t("route.automationBlueprints"),
      purpose: t("evidence.blueprints.viewPurpose"),
      glossary: composeGlossary([], [{ term: t("evidence.blueprints.glossaryTerm"), plain: t("evidence.blueprints.glossaryPlain"), tech: "AutomationBlueprintCandidate" }]),
      headline: t("evidence.blueprints.headline", { count: data.count, materialized: data.metrics.materialized }),
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "source", value: data.source, group: "provenance" },
        { key: "candidate_count", value: data.count, group: "quality" },
        { key: "candidate_precision", value: data.metrics.candidate_precision, group: "quality" },
        { key: "realized_usage", value: data.metrics.realized_usage, group: "quality" },
        { key: "selected_candidate", value: selected?.candidate_id ?? "-", group: "quality" },
        { key: "mutation_controls", value: data.mutation_controls, group: "safety" },
      ],
      records: {
        candidates: data.candidates.map((item) => ({
          ...item,
          expires_at: formatConsoleTimestamp(item.expires_at),
        })),
      },
    }),
    [data, selected],
  );
  const candidatesHref = `${routeHref("automation-blueprints", {
    params: { data: currentRoute().search.get("data") === "sample" ? "sample" : null },
  })}#automation-blueprint-candidates`;
  return (
    <div class="stack">
      <div class="governance-readonly-banner">
        <strong>{t("evidence.blueprints.bannerTitle")}</strong>
        <span>{t("evidence.blueprints.bannerBody")}</span>
      </div>
      <KpiGrid>
        <KpiCard href={candidatesHref} label={t("evidence.blueprints.candidates")} value={data.count.toLocaleString()} />
        <KpiCard href={candidatesHref} label={t("evidence.blueprints.accepted")} value={data.metrics.accepted.toLocaleString()} tone={data.metrics.accepted > 0 ? "positive" : "default"} />
        <KpiCard href={candidatesHref} label={t("evidence.blueprints.rejected")} value={data.metrics.rejected.toLocaleString()} />
        <KpiCard href={candidatesHref} label={t("evidence.blueprints.realizedUsage")} value={data.metrics.realized_usage.toLocaleString()} />
        <KpiCard
          evidenceState={data.count === 0 ? "insufficient-sample" : "measured"}
          href={candidatesHref}
          label={t("evidence.blueprints.column.confidence")}
          value={data.count === 0 ? kpiEvidenceLabel("insufficient-sample") : `${(data.metrics.candidate_precision * 100).toFixed(1)}%`}
        />
      </KpiGrid>
      <div class="cs-filter-toolbar" role="search">
        <label class="is-wide">
          <span>{t("evidence.blueprints.column.automation")}</span>
          <input
            type="search"
            value={query}
            placeholder={getLocale() === "ko" ? "후보 ID, 작업 의도, 범위, 도구..." : "candidate, intent, scope, tool..."}
            onInput={(event) => setQuery(event.currentTarget.value)}
          />
        </label>
        <label>
          <span>{t("evidence.blueprints.column.state")}</span>
          <select value={stateFilter} onChange={(event) => setStateFilter(event.currentTarget.value)}>
            <option value="all">{getLocale() === "ko" ? "전체" : "All"}</option>
            {states.map((state) => (
              <option key={state} value={state}>{presentationLabel("status", state)}</option>
            ))}
          </select>
        </label>
        <span class="cs-filter-count" role="status" aria-live="polite">
          {filtered.length} / {data.candidates.length}
        </span>
      </div>
      <div id="automation-blueprint-candidates" class={`cs-workspace-split${selected ? " has-selection" : ""}`}>
        <div class="cs-workspace-main">
          <DataTable
            rows={filtered}
            columns={columns}
            keyOf={(item) => item.candidate_id}
            onRowClick={(item) => setSelectedId(item.candidate_id)}
            isRowActive={(item) => item.candidate_id === selected?.candidate_id}
            rowActionLabel={(item) => `${t("evidence.blueprints.column.automation")}: ${item.candidate_id}`}
            rowActionControls="automation-blueprint-detail"
            scrollRegionLabel={t("route.automationBlueprints")}
            empty={<EmptyState title={t("evidence.blueprints.empty")} />}
          />
        </div>
        {selected ? (
          <aside id="automation-blueprint-detail" class="cs-inspector-pane" aria-label={selected.candidate_id}>
            <header class="cs-inspector-head">
              <div>
                <span class="cs-inspector-kicker">{selected.candidate_id}</span>
                <h3>{selected.normalized_task_intent}</h3>
                <p>{selected.schedule_expression} / {selected.delivery_intent}</p>
              </div>
              <StatusPill
                kind={selected.state === "draft" ? "shadow" : selected.state === "materialized" ? "success" : "warning"}
                label={presentationLabel("status", selected.state)}
              />
            </header>
            <dl class="cs-facts-grid">
              <div><dt>{t("evidence.blueprints.column.scope")}</dt><dd><code>{selected.resource_scope}</code></dd></div>
              <div><dt>{t("evidence.blueprints.column.isolation")}</dt><dd><code>{selected.isolation_profile.profile_id}</code> ({selected.isolation_profile.max_session_seconds}s / {selected.isolation_profile.max_context_chars} chars)</dd></div>
              <div><dt>{t("evidence.blueprints.column.tools")}</dt><dd>{selected.required_tools.join(", ") || t("evidence.common.none")}</dd></div>
              <div><dt>{getLocale() === "ko" ? "허용된 도구" : "Allowed tools"}</dt><dd>{selected.isolation_profile.allowed_tool_ids.join(", ") || t("evidence.common.none")} ({t("evidence.blueprints.toolCalls", { count: selected.isolation_profile.max_tool_calls })})</dd></div>
              <div><dt>{t("evidence.blueprints.column.cost")}</dt><dd>{t("evidence.blueprints.microUsd", { cost: selected.estimated_cost_microusd })}</dd></div>
              <div><dt>{t("evidence.blueprints.column.confidence")}</dt><dd>{`${(selected.confidence * 100).toFixed(1)}%`}</dd></div>
              <div><dt>{t("evidence.continuations.column.expiry")}</dt><dd>{formatConsoleTimestamp(selected.expires_at)}</dd></div>
              <div><dt>{t("evidence.blueprints.column.evidence")}</dt><dd>{selected.evidence_fingerprints.length}</dd></div>
              <div><dt>{getLocale() === "ko" ? "모드 / 변경 도구" : "Mode / Mutation tools"}</dt><dd>{selected.shadow_only ? presentationLabel("status", "shadow") : presentationLabel("status", "enforce")} / {selected.mutation_tool_ids.join(", ") || t("evidence.common.none")}</dd></div>
            </dl>
          </aside>
        ) : null}
      </div>
    </div>
  );
}
