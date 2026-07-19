import type { AuditItem } from "../types";
import { StatusPill, type PillKind } from "../components/ui";
import type { AgentStreamStatus } from "../hooks/use-agent-stream";
import { observationSourceLabel, type ObservationSource } from "../hooks/observation-source";
import { routeHref } from "../router";
import { activityProvenanceCounts, auditProvenanceOf } from "./agent-activity-semantics";

export type ActivityWindow = "15m" | "1h" | "24h" | "7d";
export type ActivityLayer = "all" | "governance" | "pipeline" | "domain";
export type ActivityVerb =
  | "all"
  | "execute"
  | "approve"
  | "reject"
  | "rollback"
  | "abstain"
  | "audit";

export interface ActivityFilters {
  readonly window: ActivityWindow;
  readonly layer: ActivityLayer;
  readonly verb: ActivityVerb;
  readonly query: string;
}

export function activityFiltersFromSearch(search: URLSearchParams): ActivityFilters {
  const window = search.get("window");
  const layer = search.get("layer");
  const verb = search.get("verb");
  return {
    window: window === "15m" || window === "1h" || window === "7d" ? window : "24h",
    layer: layer === "governance" || layer === "pipeline" || layer === "domain" ? layer : "all",
    verb: verb === "execute" || verb === "approve" || verb === "reject" ||
      verb === "rollback" || verb === "abstain" || verb === "audit" ? verb : "all",
    query: search.get("q") ?? "",
  };
}

interface GroupedActivityProps {
  readonly items: readonly AuditItem[];
  readonly agentOf: (item: AuditItem) => string;
  readonly layerOf: (agent: string) => string;
}

interface ActivityToolbarProps {
  readonly filters: ActivityFilters;
  readonly onChange: (next: ActivityFilters) => void;
  readonly streamStatus: AgentStreamStatus;
  readonly streamSource: ObservationSource;
  readonly liveAgents: number;
  readonly lastEventAt: string | null;
  readonly refreshing: boolean;
}

const WINDOW_MS: Readonly<Record<ActivityWindow, number>> = {
  "15m": 15 * 60 * 1000,
  "1h": 60 * 60 * 1000,
  "24h": 24 * 60 * 60 * 1000,
  "7d": 7 * 24 * 60 * 60 * 1000,
};

const GOVERNANCE_AGENTS = new Set(["Odin", "Saga", "Mimir", "Muninn", "Norns"]);
const PIPELINE_AGENTS = new Set(["Thor", "Forseti", "Huginn", "Heimdall", "Var", "Vidar", "Bragi"]);
const DOMAIN_AGENTS = new Set(["Njord", "Freyr", "Loki"]);

export function pantheonLayerOf(agent: string): Exclude<ActivityLayer, "all"> | "system" {
  if (GOVERNANCE_AGENTS.has(agent)) return "governance";
  if (PIPELINE_AGENTS.has(agent)) return "pipeline";
  if (DOMAIN_AGENTS.has(agent)) return "domain";
  return "system";
}

export function activityVerb(item: AuditItem): Exclude<ActivityVerb, "all"> | "activity" {
  const value = [
    item.action_kind,
    stringEntry(item, "outcome"),
    stringEntry(item, "decision"),
    stringEntry(item, "pipeline_stage"),
  ].filter(Boolean).join(" ").toLowerCase();
  if (value.includes("rollback") || value.includes("revert")) return "rollback";
  if (value.includes("approve")) return "approve";
  if (value.includes("reject") || value.includes("deny")) return "reject";
  if (value.includes("abstain") || value.includes("escalat")) return "abstain";
  if (value.includes("audit") || value.includes("recorded")) return "audit";
  if (
    value.includes("execute") ||
    value.includes("dispatch") ||
    value.includes("published") ||
    value.includes("pr_opened") ||
    value.includes("auto")
  ) return "execute";
  return "activity";
}

export function filterAgentActivity(
  items: readonly AuditItem[],
  filters: ActivityFilters,
  agentOf: (item: AuditItem) => string,
): readonly AuditItem[] {
  const latest = items.reduce((value, item) => Math.max(value, timestamp(item.recorded_at)), 0);
  const cutoff = latest > 0 ? latest - WINDOW_MS[filters.window] : 0;
  const query = normalizeSearch(filters.query);
  return items.filter((item) => {
    const agent = agentOf(item);
    if (cutoff > 0 && timestamp(item.recorded_at) < cutoff) return false;
    if (filters.layer !== "all" && pantheonLayerOf(agent) !== filters.layer) return false;
    if (filters.verb !== "all" && activityVerb(item) !== filters.verb) return false;
    if (query && !normalizeSearch(activitySearchText(item, agent)).includes(query)) return false;
    return true;
  });
}

export function ActivityToolbar({
  filters,
  onChange,
  streamStatus,
  streamSource,
  liveAgents,
  lastEventAt,
  refreshing,
}: ActivityToolbarProps) {
  return (
    <section class="aa-toolbar" aria-label="Agent activity filters">
      <div class="aa-live-state">
        <span class={`agents-conn conn-${streamStatus}`}>{streamStatus}</span>
        <span class="status-pill status-pill-neutral">
          {observationSourceLabel(streamSource)}
        </span>
        <span><strong>{liveAgents}</strong> engaged</span>
        <span>{refreshing ? "Refreshing audit..." : lastEventAt ? `Last signal ${clock(lastEventAt)}` : "Waiting for signal"}</span>
      </div>
      <FilterSet
        label="Window"
        values={["15m", "1h", "24h", "7d"]}
        selected={filters.window}
        onSelect={(window) => onChange({ ...filters, window: window as ActivityWindow })}
      />
      <FilterSet
        label="Layer"
        values={["all", "governance", "pipeline", "domain"]}
        selected={filters.layer}
        onSelect={(layer) => onChange({ ...filters, layer: layer as ActivityLayer })}
      />
      <FilterSet
        label="Verb"
        values={["all", "execute", "approve", "reject", "rollback", "abstain", "audit"]}
        selected={filters.verb}
        onSelect={(verb) => onChange({ ...filters, verb: verb as ActivityVerb })}
      />
      <label class="aa-search">
        <span class="sr-only">Search agent activity</span>
        <input
          type="search"
          value={filters.query}
          placeholder="event, resource, correlation, or summary"
          onInput={(event) => onChange({ ...filters, query: event.currentTarget.value })}
        />
      </label>
    </section>
  );
}

function FilterSet({
  label,
  values,
  selected,
  onSelect,
}: {
  readonly label: string;
  readonly values: readonly string[];
  readonly selected: string;
  readonly onSelect: (value: string) => void;
}) {
  return (
    <div class="aa-filter-set">
      <span>{label}</span>
      <div role="group" aria-label={`${label} filter`}>
        {values.map((value) => (
          <button
            key={value}
            type="button"
            class={selected === value ? "is-active" : undefined}
            aria-pressed={selected === value}
            onClick={() => onSelect(value)}
          >
            {title(value)}
          </button>
        ))}
      </div>
    </div>
  );
}

export function GroupedAgentActivity({ items, agentOf, layerOf }: GroupedActivityProps) {
  const groups = new Map<string, AuditItem[]>();
  for (const item of items) {
    const agent = agentOf(item);
    const rows = groups.get(agent) ?? [];
    rows.push(item);
    groups.set(agent, rows);
  }
  const ordered = [...groups.entries()].sort((left, right) => {
    const leftTime = Math.max(...left[1].map((item) => timestamp(item.recorded_at)));
    const rightTime = Math.max(...right[1].map((item) => timestamp(item.recorded_at)));
    return rightTime - leftTime;
  });
  return (
    <div class="aa-groups">
      {ordered.map(([agent, rows]) => (
        <AgentActivityGroup
          key={agent}
          agent={agent}
          items={rows}
          displayLayer={layerOf(agent)}
        />
      ))}
    </div>
  );
}

function AgentActivityGroup({
  agent,
  items,
  displayLayer,
}: {
  readonly agent: string;
  readonly items: readonly AuditItem[];
  readonly displayLayer: string;
}) {
  const counts = new Map<string, number>();
  for (const item of items) {
    const verb = activityVerb(item);
    counts.set(verb, (counts.get(verb) ?? 0) + 1);
  }
  const summary = [...counts.entries()].map(([verb, count]) => `${verb} ${count}`).join(" / ");
  const provenance = activityProvenanceCounts(items);
  return (
    <section class="aa-group">
      <header class="aa-group-head">
        <span class="aa-dot" data-layer={displayLayer} aria-hidden="true" />
        <strong>{agent}</strong>
        <span class="aa-layer-tag">{pantheonLayerOf(agent)}</span>
        <span class="aa-group-meta">
          {items.length} records
          {provenance.sample > 0 ? ` · ${provenance.sample} local sample` : ""}
          {` · ${summary}`}
        </span>
      </header>
      <div class="aa-rows">
        {items.map((item) => <AgentActivityRow key={item.seq} item={item} />)}
      </div>
    </section>
  );
}

function AgentActivityRow({ item }: { readonly item: AuditItem }) {
  const verb = activityVerb(item);
  const outcome = stringEntry(item, "outcome");
  const summary =
    stringEntry(item, "summary") ||
    stringEntry(item, "detail") ||
    stringEntry(item, "reason") ||
    item.action_kind;
  const target = stringEntry(item, "resource_ref") || stringEntry(item, "target_resource_ref");
  const provenance = auditProvenanceOf(item);
  return (
    <div class="aa-row">
      <time dateTime={item.recorded_at}>{clock(item.recorded_at)}</time>
      <span class={`aa-verb is-${verb}`}>{title(verb)}</span>
      <span class="aa-summary">
        <strong>{item.action_kind}</strong>
        {target ? <> on <code>{target}</code></> : null}
        {summary !== item.action_kind ? <> · {summary}</> : null}
      </span>
      <span class="aa-row-meta">
        {provenance === "sample" ? <StatusPill kind="neutral" label="local sample" /> : null}
        <StatusPill kind={modePill(item.mode)} label={item.mode} />
        {outcome ? <StatusPill kind={outcomePill(outcome)} label={outcome} /> : null}
        {item.correlation_id ? (
          <a href={routeHref("trace", { params: { correlation: item.correlation_id } })}>
            {item.correlation_id}
          </a>
        ) : <code>{item.event_id}</code>}
      </span>
    </div>
  );
}

function activitySearchText(item: AuditItem, agent: string): string {
  return [
    agent,
    item.actor,
    item.action_kind,
    item.event_id,
    item.correlation_id,
    stringEntry(item, "summary"),
    stringEntry(item, "detail"),
    stringEntry(item, "reason"),
    stringEntry(item, "resource_ref"),
    stringEntry(item, "target_resource_ref"),
    stringEntry(item, "rule_id"),
  ].filter(Boolean).join(" ").toLocaleLowerCase();
}

function normalizeSearch(value: string): string {
  return value
    .toLocaleLowerCase()
    .replace(/[-_.:/]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function stringEntry(item: AuditItem, key: string): string | null {
  const value = item.entry[key];
  return typeof value === "string" && value.trim() ? value : null;
}

function modePill(mode: string): PillKind {
  if (mode === "enforce") return "enforce";
  if (mode === "shadow") return "shadow";
  return "neutral";
}

function outcomePill(outcome: string): PillKind {
  const normalized = outcome.toLowerCase();
  if (normalized.includes("hil") || normalized.includes("await")) return "hil";
  if (normalized.includes("reject") || normalized.includes("deny") || normalized.includes("fail")) return "danger";
  if (normalized.includes("auto") || normalized.includes("published") || normalized.includes("recorded")) return "success";
  return "neutral";
}

function timestamp(value: string): number {
  const parsed = new Date(value).getTime();
  return Number.isNaN(parsed) ? 0 : parsed;
}

function clock(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function title(value: string): string {
  return value ? `${value[0]!.toUpperCase()}${value.slice(1)}` : value;
}
