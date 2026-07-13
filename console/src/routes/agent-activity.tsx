/**
 * Agent activity - a per-agent timeline reconstructed from the audit log.
 *
 * The Audit and Trace panels answer "what terminal decisions were
 * recorded" and "reconstruct one correlation id". Neither answers the
 * operator's other natural question: **which agent did what work, when,
 * and how**. This panel projects the same append-only audit stream into
 * an agent-attributed timeline so an operator can watch the pantheon at
 * work (Huginn ingests, Forseti judges, Thor opens a remediation PR,
 * Var queues a HIL approval, Saga records it).
 *
 * Read-only: it reuses the GET-only `/audit` projection (no new
 * back-channel) and derives the acting agent from each entry's `actor`
 * (== the producing principal in the pantheon lifecycle). Entries whose
 * actor is not a known agent are grouped under "System".
 */

import { useEffect, useMemo, useState } from "preact/hooks";
import type { ComponentChildren } from "preact";
import type { ReadApiClient } from "../api";
import type { AuditItem } from "../types";
import {
  AsyncBoundary,
  EmptyState,
  PageHeader,
  StatusPill,
  type AsyncState,
  type PillKind,
} from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, agentTerm, composeGlossary } from "../deck/glossary";
import { t } from "../i18n";

interface Props {
  readonly client: ReadApiClient;
}

/** Number of audit rows pulled to build the timeline (newest first). */
const TIMELINE_LIMIT = 200;

/**
 * The 15 fixed pantheon agents keyed by their canonical name, mapped to
 * a coarse "layer" used only for colour + grouping. The names are
 * fork-locked upstream (see architecture.instructions.md § Agent
 * Pantheon), so a static map is safe and avoids a second fetch against
 * the optional `/pantheon/graph` route.
 */
const AGENT_LAYER: Readonly<Record<string, string>> = {
  Odin: "planning",
  Thor: "execution",
  Forseti: "judgment",
  Huginn: "sensing",
  Heimdall: "sensing",
  Var: "approval",
  Vidar: "recovery",
  Bragi: "conversational",
  Saga: "audit",
  Mimir: "governance",
  Norns: "governance",
  Muninn: "governance",
  Njord: "domain",
  Freyr: "domain",
  Loki: "domain",
};

const SYSTEM_AGENT = "System";

/**
 * Resolve the acting producer for one audit row.
 *
 * Attribution is defensive because the row shape differs by environment:
 * - The dev seed stamps a pantheon agent as ``actor`` (Odin, Forseti, ...).
 * - The live control loop stamps a dotted service ``actor``
 *   (``fdai.core.control_loop``, ``fdai.core.rca``, ...) and MAY stamp the
 *   owning agent as ``entry.producer_principal`` once the pantheon drives the
 *   hot path.
 *
 * Priority: known-agent ``actor`` -> ``producer_principal`` (agent, else any
 * non-empty label) -> humanized service ``actor`` -> ``System``. This keeps
 * the waterfall segmented by its real producer in live instead of collapsing
 * every core row into one ``System`` bucket.
 */
export function agentOf(item: AuditItem): string {
  if (item.actor in AGENT_LAYER) return item.actor;
  const principal = item.entry["producer_principal"];
  if (typeof principal === "string" && principal.trim()) {
    return principal in AGENT_LAYER ? principal : principal.trim();
  }
  if (item.actor && item.actor.trim()) return humanizeActor(item.actor);
  return SYSTEM_AGENT;
}

/** Shorten a dotted service actor for display: ``fdai.core.control_loop`` ->
 * ``core.control_loop``. Non-dotted actors pass through unchanged. */
function humanizeActor(actor: string): string {
  const parts = actor.split(".");
  if (parts.length >= 2 && parts[0] === "fdai") return parts.slice(1).join(".");
  return actor;
}

/** True when the label is one of the 15 fixed pantheon agents. */
function isKnownAgent(label: string): boolean {
  return label in AGENT_LAYER;
}

export function layerOf(agent: string): string {
  return AGENT_LAYER[agent] ?? "system";
}

/** Free-text "how" for the row: the audit outcome, if present. */
function outcomeOf(item: AuditItem): string | null {
  const outcome = item.entry["outcome"];
  return typeof outcome === "string" ? outcome : null;
}

function summaryOf(item: AuditItem): string | null {
  const summary = item.entry["summary"];
  return typeof summary === "string" ? summary : null;
}

function tierOf(item: AuditItem): string | null {
  const tier = item.entry["tier"];
  return typeof tier === "string" ? tier.toUpperCase() : null;
}

function outcomePill(outcome: string): PillKind {
  if (outcome.includes("hil") || outcome.includes("await")) return "hil";
  if (outcome.includes("escalat")) return "warning";
  if (outcome === "auto") return "auto";
  if (outcome.includes("pr_opened") || outcome.includes("recorded")) return "success";
  if (outcome.includes("matched") || outcome.includes("normalized")) return "info";
  return "neutral";
}

function modePill(mode: string): PillKind {
  if (mode === "enforce") return "enforce";
  if (mode === "shadow") return "shadow";
  return "neutral";
}

/** HH:MM:SS in the browser locale for a compact timeline stamp. */
function stamp(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleTimeString();
}

/** Epoch millis for an ISO stamp, or 0 when unparseable. */
function ms(iso: string): number {
  const t = new Date(iso).getTime();
  return Number.isNaN(t) ? 0 : t;
}

/** Read a string field from the audit entry payload, or null. */
function entryStr(item: AuditItem, key: string): string | null {
  const value = item.entry[key];
  return typeof value === "string" ? value : null;
}

/** Read a number field from the audit entry payload, or null. */
function entryNum(item: AuditItem, key: string): number | null {
  const value = item.entry[key];
  return typeof value === "number" ? value : null;
}

/** Read a flat string->string map field (inputs / outputs), or null. */
function entryMap(item: AuditItem, key: string): ReadonlyArray<readonly [string, string]> | null {
  const value = item.entry[key];
  if (value === null || typeof value !== "object" || Array.isArray(value)) return null;
  const pairs = Object.entries(value as Record<string, unknown>)
    .filter((e): e is [string, string] => typeof e[1] === "string");
  return pairs.length > 0 ? pairs : null;
}

/** One agent-to-agent conversational-port turn. */
interface AgentTurn {
  readonly from: string;
  readonly to: string;
  readonly text: string;
}

/** Read the agent-to-agent conversation attached to a row, or null. */
export function entryConversation(item: AuditItem): readonly AgentTurn[] | null {
  const value = item.entry["conversation"];
  if (!Array.isArray(value)) return null;
  const turns = value.filter(
    (t): t is AgentTurn =>
      t !== null &&
      typeof t === "object" &&
      typeof (t as AgentTurn).from === "string" &&
      typeof (t as AgentTurn).to === "string" &&
      typeof (t as AgentTurn).text === "string",
  );
  return turns.length > 0 ? turns : null;
}

/**
 * Entry keys already surfaced by a dedicated detail section, so the generic
 * "Other recorded fields" dump does not repeat them. Everything else the
 * pipeline persisted is shown verbatim - the audit ``entry`` is JSONB, so a
 * live producer (e.g. the executor's rollback / blast_radius / resource_ref)
 * is never silently dropped by a hardcoded allow-list.
 */
const SHOWN_ENTRY_KEYS: ReadonlySet<string> = new Set([
  "event_ts", "received_at", "started_at", "finished_at", "duration_ms", "queue_ms",
  "detail", "summary", "inputs", "outputs", "conversation",
  "tier", "outcome", "decision", "pipeline_stage", "reason",
  "producer_principal", "action_kind", "correlation_id", "recorded_at", "event_id",
  "actor", "mode",
]);

/** Format one arbitrary persisted value for the generic field viewer. */
function fmtScalar(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

function fmtEntryValue(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (Array.isArray(v)) return v.map(fmtScalar).join(", ");
  if (typeof v === "object") {
    return Object.entries(v as Record<string, unknown>)
      .map(([k, x]) => `${k}: ${fmtScalar(x)}`)
      .join(" · ");
  }
  return String(v);
}

/**
 * Every persisted ``entry`` field not already shown in a dedicated section,
 * formatted for display. This is what makes the pane a faithful full view of
 * what was actually stored (nothing hidden), and stable across schema
 * additions - new producer fields appear automatically.
 */
export function otherEntryFields(item: AuditItem): ReadonlyArray<readonly [string, string]> {
  return Object.entries(item.entry)
    .filter(([k, v]) => !SHOWN_ENTRY_KEYS.has(k) && v !== null && v !== undefined && v !== "")
    .map(([k, v]) => [k, fmtEntryValue(v)] as const)
    .filter(([, v]) => v !== "");
}

/** HH:MM:SS.mmm local clock for the precise lifecycle stepper. */
function clockMs(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const mmm = String(d.getMilliseconds()).padStart(3, "0");
  return `${hms(iso)}.${mmm}`;
}

/** HH:MM:SS 24-hour local clock - compact enough for a left-list row. */
function hms(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  const ss = String(d.getSeconds()).padStart(2, "0");
  return `${hh}:${mm}:${ss}`;
}

/** The clock at which this step began work (started_at, else recorded_at). */
function startClockOf(item: AuditItem): string {
  return hms(entryStr(item, "started_at") ?? item.recorded_at);
}

/** Compact human duration for a millisecond span (e.g. "1m 30s", "820ms"). */
function fmtDur(millis: number): string {
  if (millis <= 0) return "0s";
  if (millis < 1000) return `${Math.round(millis)}ms`;
  const totalSec = Math.round(millis / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  if (m === 0) return `${s}s`;
  if (s === 0) return `${m}m`;
  return `${m}m ${s}s`;
}

interface Data {
  readonly items: readonly AuditItem[];
  readonly olderAvailable: boolean;
}

type ActivityView = "waterfall" | "timeline";

export function AgentActivityRoute({ client }: Props) {
  const [state, setState] = useState<AsyncState<Data>>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const page = await client.listAudit({ limit: TIMELINE_LIMIT });
        if (!cancelled) {
          setState({
            status: "ready",
            data: { items: page.items, olderAvailable: page.next_cursor !== null },
          });
        }
      } catch (err) {
        if (!cancelled) {
          setState({
            status: "error",
            message: err instanceof Error ? err.message : String(err),
          });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [client]);

  return (
    <div class="stack">
      <PageHeader
        title={t("route.agentActivity")}
        subtitle="Per-agent timeline reconstructed from the audit log - which agent did what, when, and how. Read-only projection of the same append-only record."
      />
      <AsyncBoundary state={state} resourceLabel="agent activity">
        {(data) => <ActivityBody data={data} />}
      </AsyncBoundary>
    </div>
  );
}

interface BodyProps {
  readonly data: Data;
}

function ActivityBody({ data }: BodyProps) {
  const [selected, setSelected] = useState<string | null>(null);
  const [view, setView] = useState<ActivityView>("waterfall");

  // Newest first: the audit projection already returns newest-first, so
  // preserve that order for the timeline.
  const perAgent = useMemo(() => {
    const counts = new Map<string, number>();
    for (const item of data.items) {
      const agent = agentOf(item);
      counts.set(agent, (counts.get(agent) ?? 0) + 1);
    }
    // Order: known pantheon agents first (by count), then service producers
    // (by count), then the System catch-all last.
    const rank = (label: string): number =>
      label === SYSTEM_AGENT ? 2 : isKnownAgent(label) ? 0 : 1;
    return [...counts.entries()].sort((a, b) => {
      const ra = rank(a[0]);
      const rb = rank(b[0]);
      if (ra !== rb) return ra - rb;
      return b[1] - a[1];
    });
  }, [data.items]);

  const visible = useMemo(
    () =>
      selected === null
        ? data.items
        : data.items.filter((item) => agentOf(item) === selected),
    [data.items, selected],
  );

  usePublishViewContext(
    () => ({
      routeId: "agent-activity",
      routeLabel: "Agent activity",
      purpose:
        "Per-agent timeline reconstructed from the audit log - which pantheon " +
        "agent did what, when, and why. Each incident (correlation id) is one " +
        "hand-off cascade: Huginn senses, Forseti judges, Thor opens a " +
        "remediation PR, Var queues a HIL approval, Saga records it. Read-only.",
      glossary: composeGlossary([
        TERMS.correlationId,
        TERMS.waterfall,
        TERMS.actionKind,
        TERMS.tier,
        TERMS.mode,
        TERMS.outcome,
        agentTerm(),
      ]),
      headline: `${data.items.length} audit row(s) across ${perAgent.length} agent(s)${
        selected ? ` - filtered to ${selected}` : ""
      }${data.olderAvailable ? " - older activity available" : ""}`,
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "rows", value: data.items.length, group: "page" },
        { key: "agents", value: perAgent.length, group: "page" },
        { key: "filter", value: selected ?? "all", group: "page" },
        { key: "older_available", value: data.olderAvailable, group: "page" },
      ],
      records: {
        by_agent: perAgent.map(([agent, count]) => ({ agent, count })),
        // The visible timeline rows (respecting the agent filter) so the deck
        // can answer "what did this agent do / what happened when / why did
        // this start?" from real activity. The causal fields (`summary`,
        // `detail`, `reason`, `tier`, `outcome`) are kept - NOT projected away -
        // so the narrator can quote the recorded "why" instead of shrugging.
        // Newest-first; capped so the snapshot stays lean.
        activity: visible.slice(0, 40).map((item) => ({
          agent: agentOf(item),
          action_kind: item.action_kind,
          mode: item.mode,
          recorded_at: item.recorded_at,
          correlation_id: item.correlation_id ?? "-",
          event_id: item.event_id,
          tier: tierOf(item) ?? "-",
          outcome: outcomeOf(item) ?? "-",
          summary: summaryOf(item) ?? "-",
          detail: entryStr(item, "detail") ?? "-",
          reason: entryStr(item, "reason") ?? "-",
        })),
      },
    }),
    [data.items, data.olderAvailable, perAgent, selected, visible],
  );

  if (data.items.length === 0) {
    return (
      <EmptyState
        title="No agent activity yet"
        body="Once the control loop records decisions, each agent's work appears here as a timeline."
      />
    );
  }

  return (
    <div class="stack">
      {data.olderAvailable ? (
        <p class="muted footnote">Showing the latest {data.items.length} audit rows; older activity is available in the Audit log.</p>
      ) : null}
      <div class="agent-filter" role="group" aria-label="Filter by agent">
        <button
          type="button"
          class={`agent-chip ${selected === null ? "agent-chip-on" : ""}`}
          aria-pressed={selected === null}
          onClick={() => setSelected(null)}
        >
          All
          <span class="agent-chip-count">{data.items.length}</span>
        </button>
        {perAgent.map(([agent, count]) => (
          <button
            key={agent}
            type="button"
            class={`agent-chip ${selected === agent ? "agent-chip-on" : ""}`}
            aria-pressed={selected === agent}
            data-layer={layerOf(agent)}
            onClick={() => setSelected((s) => (s === agent ? null : agent))}
          >
            <span class="agent-dot" data-layer={layerOf(agent)} aria-hidden="true" />
            {agent}
            <span class="agent-chip-count">{count}</span>
          </button>
        ))}
      </div>

      <div class="view-toggle" role="group" aria-label="Activity view">
        <button
          type="button"
          class="view-toggle-btn"
          aria-pressed={view === "waterfall"}
          onClick={() => setView("waterfall")}
        >
          Waterfall
        </button>
        <button
          type="button"
          class="view-toggle-btn"
          aria-pressed={view === "timeline"}
          onClick={() => setView("timeline")}
        >
          Timeline
        </button>
      </div>

      {view === "timeline" ? (
        <ol class="timeline" aria-label="Agent activity timeline">
          {visible.map((item) => (
            <TimelineRow key={item.seq} item={item} />
          ))}
        </ol>
      ) : (
        <Waterfall items={data.items} selected={selected} />
      )}
    </div>
  );
}

function TimelineRow({ item }: { readonly item: AuditItem }) {
  const agent = agentOf(item);
  const layer = layerOf(agent);
  const outcome = outcomeOf(item);
  const summary = summaryOf(item);
  const tier = tierOf(item);

  return (
    <li class="timeline-row">
      <span class="timeline-marker" data-layer={layer} aria-hidden="true" />
      <div class="timeline-card">
        <div class="timeline-head">
          <span class="timeline-agent" data-layer={layer}>
            {agent}
          </span>
          <span class="timeline-action mono">{item.action_kind}</span>
          <span class="timeline-time mono muted">{stamp(item.recorded_at)}</span>
        </div>
        {summary ? <p class="timeline-summary">{summary}</p> : null}
        <div class="timeline-meta">
          {tier ? <span class="timeline-tier mono">{tier}</span> : null}
          <StatusPill kind={modePill(item.mode)} label={item.mode} />
          {outcome ? <StatusPill kind={outcomePill(outcome)} label={outcome} /> : null}
          {item.correlation_id ? (
            <a
              class="timeline-corr mono"
              href={`#/trace?correlation=${encodeURIComponent(item.correlation_id)}`}
              title="Open this correlation in the Trace panel"
            >
              {item.correlation_id}
            </a>
          ) : null}
        </div>
      </div>
    </li>
  );
}

// ---------------------------------------------------------------------------
// Waterfall view - one horizontal lane per audit event, grouped by the
// correlation id (incident) they belong to. Each bar starts at the event's
// timestamp and stretches until the next agent picks the incident up, so an
// operator reads the pantheon hand-off cascade (Huginn -> Heimdall -> Forseti
// -> Thor -> Saga) left to right. The bar width is time held, not work done -
// audit rows are point events, so "held until next hand-off" is the honest
// span we can derive without inventing durations.
// ---------------------------------------------------------------------------

/** Small speech-bubble glyph marking a row that carries an agent-to-agent
 * conversation. Inline SVG (no emoji in code per the language policy). */
function ChatGlyph() {
  return (
    <svg viewBox="0 0 16 16" width="11" height="11" aria-hidden="true">
      <path
        d="M2 3.2h12v7.2H7.4L4.4 13v-2.6H2z"
        fill="none"
        stroke="currentColor"
        stroke-width="1.3"
        stroke-linejoin="round"
      />
    </svg>
  );
}

/** Minimum bar width (percent of the group span) so a near-instant hand-off
 * still renders a clickable sliver. */
const MIN_BAR_PCT = 2.5;
/** Nominal span (ms) used when a correlation has a single event or zero
 * elapsed time, so its single bar still fills the track. */
const SINGLETON_SPAN_MS = 1000;

interface WaterfallBar {
  readonly item: AuditItem;
  readonly agent: string;
  readonly layer: string;
  readonly leftPct: number;
  readonly widthPct: number;
}

interface WaterfallGroup {
  readonly correlation: string;
  readonly startMs: number;
  readonly spanMs: number;
  readonly bars: readonly WaterfallBar[];
}

function buildGroups(items: readonly AuditItem[]): readonly WaterfallGroup[] {
  const byCorr = new Map<string, AuditItem[]>();
  for (const item of items) {
    const key = item.correlation_id || `uncorrelated:${item.seq}`;
    const bucket = byCorr.get(key);
    if (bucket) bucket.push(item);
    else byCorr.set(key, [item]);
  }

  const groups: WaterfallGroup[] = [];
  for (const [correlation, rows] of byCorr) {
    const sorted = [...rows].sort((a, b) => ms(a.recorded_at) - ms(b.recorded_at));
    const startMs = ms(sorted[0]!.recorded_at);
    const endMs = ms(sorted[sorted.length - 1]!.recorded_at);
    const actualSpanMs = Math.max(endMs - startMs, 0);
    // Padded denominator for layout: a trailing tail gives the terminal event
    // (no next hand-off) a visible bar, and a singleton fills the whole track.
    const tailMs = actualSpanMs > 0 ? actualSpanMs * 0.2 : SINGLETON_SPAN_MS;
    const denom = actualSpanMs + tailMs;
    const bars: WaterfallBar[] = sorted.map((item, i) => {
      const s = ms(item.recorded_at);
      const next = i + 1 < sorted.length ? ms(sorted[i + 1]!.recorded_at) : endMs + tailMs;
      const leftPct = ((s - startMs) / denom) * 100;
      const rawWidth = ((next - s) / denom) * 100;
      const widthPct = Math.min(Math.max(rawWidth, MIN_BAR_PCT), 100 - leftPct);
      const agent = agentOf(item);
      return { item, agent, layer: layerOf(agent), leftPct, widthPct };
    });
    groups.push({ correlation, startMs, spanMs: actualSpanMs, bars });
  }
  // Newest incident first, matching the audit projection's newest-first order.
  groups.sort((a, b) => b.startMs - a.startMs);
  return groups;
}

function Waterfall({
  items,
  selected,
}: {
  readonly items: readonly AuditItem[];
  readonly selected: string | null;
}) {
  const groups = useMemo(() => buildGroups(items), [items]);
  // Collapsed correlation ids (default: all expanded). Chevron toggles a group.
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set());
  // The audit row whose detail drawer is open, by stable `seq`.
  const [selectedSeq, setSelectedSeq] = useState<number | null>(null);

  const toggle = (correlation: string) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(correlation)) next.delete(correlation);
      else next.add(correlation);
      return next;
    });

  // When an agent is filtered, keep only incidents that agent touched (so the
  // hand-off context around it stays visible) and dim the other lanes.
  const shown = useMemo(
    () =>
      selected === null
        ? groups
        : groups.filter((g) => g.bars.some((b) => b.agent === selected)),
    [groups, selected],
  );

  const selectedItem = useMemo(
    () =>
      selectedSeq === null ? null : (items.find((i) => i.seq === selectedSeq) ?? null),
    [items, selectedSeq],
  );

  if (shown.length === 0) {
    return (
      <EmptyState
        title="No matching incidents"
        body="No correlated activity for this agent yet. Clear the filter to see the full waterfall."
      />
    );
  }

  return (
    <div class="waterfall-wrap">
      <div class="waterfall" aria-label="Agent activity waterfall">
        {shown.map((g) => {
          const isCollapsed = collapsed.has(g.correlation);
          return (
            <section
              class={`waterfall-group ${isCollapsed ? "waterfall-group-collapsed" : ""}`}
              key={g.correlation}
            >
              <div class="waterfall-group-head">
                <button
                  type="button"
                  class="waterfall-toggle"
                  aria-expanded={!isCollapsed}
                  aria-label={isCollapsed ? "Expand incident" : "Collapse incident"}
                  onClick={() => toggle(g.correlation)}
                >
                  <span class={`waterfall-chevron ${isCollapsed ? "" : "waterfall-chevron-open"}`} aria-hidden="true">
                    ▶
                  </span>
                </button>
                {g.correlation.startsWith("uncorrelated:") ? (
                  <span class="waterfall-corr mono muted">uncorrelated event #{g.bars[0]!.item.seq}</span>
                ) : (
                  <a
                    class="waterfall-corr mono"
                    href={`#/trace?correlation=${encodeURIComponent(g.correlation)}`}
                    title="Open this correlation in the Trace panel"
                  >
                    {g.correlation}
                  </a>
                )}
                <span class="waterfall-span mono muted" title={`${g.bars.length} step(s) · ${fmtDur(g.spanMs)}`}>
                  {startClockOf(g.bars[0]!.item)} · {g.bars.length}
                </span>
              </div>
              {isCollapsed ? null : (
                <ol class="waterfall-lanes">
                  {g.bars.map((bar) => {
                    const dimmed = selected !== null && bar.agent !== selected;
                    const active = selectedSeq === bar.item.seq;
                    const work = entryNum(bar.item, "duration_ms");
                    const convo = entryConversation(bar.item);
                    return (
                      <li class="waterfall-lane" key={bar.item.seq}>
                        <button
                          type="button"
                          class={`waterfall-row ${active ? "waterfall-row-active" : ""} ${dimmed ? "waterfall-row-dim" : ""}`}
                          aria-pressed={active}
                          onClick={() =>
                            setSelectedSeq((s) => (s === bar.item.seq ? null : bar.item.seq))
                          }
                        >
                          <span class="agent-dot" data-layer={bar.layer} aria-hidden="true" />
                          <span class="waterfall-agent" data-layer={bar.layer}>
                            {bar.agent}
                          </span>
                          <span class="waterfall-action mono muted">
                            {bar.item.action_kind}
                          </span>
                          <span class="waterfall-conv">
                            {convo ? (
                              <span
                                class="waterfall-conv-badge"
                                title={`${convo.length} agent-to-agent message(s)`}
                              >
                                <ChatGlyph />
                                {convo.length}
                              </span>
                            ) : null}
                          </span>
                          <span class="waterfall-mini" aria-hidden="true">
                            <span
                              class="waterfall-mini-bar"
                              data-layer={bar.layer}
                              style={`left:${bar.leftPct.toFixed(2)}%;width:${bar.widthPct.toFixed(2)}%`}
                            />
                          </span>
                          <span
                            class="waterfall-time mono muted"
                            title={work !== null ? `started ${startClockOf(bar.item)} · worked ${fmtDur(work)}` : undefined}
                          >
                            {startClockOf(bar.item)}
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ol>
              )}
            </section>
          );
        })}
      </div>
      <div class="waterfall-detail-pane">
        {selectedItem ? (
          <StepDetail item={selectedItem} onClose={() => setSelectedSeq(null)} />
        ) : (
          <div class="waterfall-detail-empty">
            <p class="waterfall-detail-empty-title">Select a step</p>
            <p class="muted">
              Pick any agent step on the left to see its full lifecycle - when the
              event was sent and received, how long it queued and worked, what it
              consumed and produced, and the recorded decision.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

/** One phase of the lifecycle stepper: a label, an absolute timestamp, and the
 * elapsed gap from the previous phase. */
interface LifecyclePhase {
  readonly key: string;
  readonly label: string;
  readonly iso: string | null;
  readonly gapLabel: string | null;
}

/** Build the send -> receive -> start -> finish lifecycle from the entry's
 * trace fields. Missing fields collapse gracefully (phases with no timestamp
 * are dropped) so an un-enriched row still renders its `recorded_at`. */
export function lifecycleOf(item: AuditItem): readonly LifecyclePhase[] {
  const sent = entryStr(item, "event_ts");
  const received = entryStr(item, "received_at");
  const started = entryStr(item, "started_at");
  const finished = entryStr(item, "finished_at") ?? item.recorded_at;
  const raw: readonly (readonly [string, string, string | null])[] = [
    ["sent", "Event sent", sent],
    ["received", "Received", received],
    ["started", "Work started", started],
    ["finished", "Finished", finished],
  ];
  const present = raw.filter((r) => r[2] !== null) as (readonly [string, string, string])[];
  return present.map(([key, label, iso], i) => {
    const prev = i > 0 ? present[i - 1]![2] : null;
    const gap = prev !== null ? ms(iso) - ms(prev) : null;
    return {
      key,
      label,
      iso,
      gapLabel: gap === null ? null : gap <= 0 ? "0s" : `+${fmtDur(gap)}`,
    };
  });
}

/**
 * Large detail pane for one selected audit row - the "click a step, see
 * exactly what it did" surface. It renders the append-only entry verbatim
 * (no re-derivation): a lifecycle stepper (sent -> received -> started ->
 * finished with gap latencies), the narrative detail, structured inputs /
 * outputs, and the full record fields.
 */
function StepDetail({ item, onClose }: { readonly item: AuditItem; readonly onClose: () => void }) {
  const agent = agentOf(item);
  const layer = layerOf(agent);
  const tier = tierOf(item);
  const outcome = outcomeOf(item);
  const summary = summaryOf(item);
  const detail = entryStr(item, "detail");
  const decision = entryStr(item, "decision");
  const reason = entryStr(item, "reason");
  const stage = entryStr(item, "pipeline_stage");
  const durationMs = entryNum(item, "duration_ms");
  const queueMs = entryNum(item, "queue_ms");
  const inputs = entryMap(item, "inputs");
  const outputs = entryMap(item, "outputs");
  const conversation = entryConversation(item);
  const phases = lifecycleOf(item);
  const otherFields = otherEntryFields(item);

  const record: readonly (readonly [string, ComponentChildren])[] = [
    ["Tier", tier ? <span class="mono">{tier}</span> : null],
    ["Mode", <StatusPill kind={modePill(item.mode)} label={item.mode} />],
    ["Outcome", outcome ? <StatusPill kind={outcomePill(outcome)} label={outcome} /> : null],
    ["Decision", decision ? <span class="mono">{decision}</span> : null],
    ["Pipeline stage", stage ? <span class="mono">{stage}</span> : null],
    ["Reason", reason],
    [
      "Correlation",
      item.correlation_id ? (
        <a
          class="mono"
          href={`#/trace?correlation=${encodeURIComponent(item.correlation_id)}`}
          title="Open this correlation in the Trace panel"
        >
          {item.correlation_id}
        </a>
      ) : null,
    ],
    ["Seq", <span class="mono">{item.seq}</span>],
    ["Event id", <span class="mono waterfall-hash">{item.event_id}</span>],
    ["Entry hash", <span class="mono waterfall-hash">{item.entry_hash}</span>],
    ["Prev hash", <span class="mono waterfall-hash">{item.previous_hash}</span>],
  ];

  return (
    <aside class="waterfall-detail" aria-label="Step detail">
      <header class="waterfall-detail-head">
        <span class="waterfall-detail-title">
          <span class="agent-dot agent-dot-lg" data-layer={layer} aria-hidden="true" />
          <span class="waterfall-detail-agent" data-layer={layer}>{agent}</span>
          <span class="waterfall-detail-action mono">{item.action_kind}</span>
          {tier ? <span class="timeline-tier mono">{tier}</span> : null}
          <StatusPill kind={modePill(item.mode)} label={item.mode} />
          {outcome ? <StatusPill kind={outcomePill(outcome)} label={outcome} /> : null}
        </span>
        <button type="button" class="waterfall-detail-close" onClick={onClose} aria-label="Close detail">
          ×
        </button>
      </header>

      {summary ? <p class="waterfall-detail-summary">{summary}</p> : null}

      <section class="waterfall-section">
        <h3 class="waterfall-section-title">Lifecycle</h3>
        <ol class="waterfall-life">
          {phases.map((p) => (
            <li class="waterfall-life-step" key={p.key}>
              <span class="waterfall-life-dot" data-layer={layer} aria-hidden="true" />
              <span class="waterfall-life-body">
                <span class="waterfall-life-label">{p.label}</span>
                {p.iso ? <span class="waterfall-life-time mono">{clockMs(p.iso)}</span> : null}
              </span>
              {p.gapLabel ? <span class="waterfall-life-gap mono">{p.gapLabel}</span> : null}
            </li>
          ))}
        </ol>
        <p class="waterfall-life-note muted">
          {durationMs !== null ? <>Worked <strong>{fmtDur(durationMs)}</strong></> : null}
          {durationMs !== null && queueMs !== null ? " · " : null}
          {queueMs !== null ? <>queued <strong>{fmtDur(queueMs)}</strong></> : null}
        </p>
      </section>

      {detail ? (
        <section class="waterfall-section">
          <h3 class="waterfall-section-title">What it did</h3>
          <p class="waterfall-detail-text">{detail}</p>
        </section>
      ) : null}

      {conversation ? (
        <section class="waterfall-section">
          <h3 class="waterfall-section-title">
            Agent conversation
            <span class="waterfall-conv-count">{conversation.length}</span>
          </h3>
          <ol class="waterfall-chat">
            {conversation.map((turn, idx) => (
              <li class="waterfall-chat-turn" key={idx} data-layer={layerOf(turn.from)}>
                <div class="waterfall-chat-meta">
                  <span class="waterfall-chat-from" data-layer={layerOf(turn.from)}>
                    {turn.from}
                  </span>
                  <span class="waterfall-chat-arrow" aria-hidden="true">-&gt;</span>
                  <span class="waterfall-chat-to" data-layer={layerOf(turn.to)}>
                    {turn.to}
                  </span>
                </div>
                <p class="waterfall-chat-text">{turn.text}</p>
              </li>
            ))}
          </ol>
        </section>
      ) : null}

      {inputs || outputs ? (
        <div class="waterfall-io">
          {inputs ? (
            <section class="waterfall-section">
              <h3 class="waterfall-section-title">Inputs</h3>
              <dl class="waterfall-kv">
                {inputs.map(([k, v]) => (
                  <div class="waterfall-kv-row" key={k}>
                    <dt class="mono">{k}</dt>
                    <dd class="mono">{v}</dd>
                  </div>
                ))}
              </dl>
            </section>
          ) : null}
          {outputs ? (
            <section class="waterfall-section">
              <h3 class="waterfall-section-title">Outputs</h3>
              <dl class="waterfall-kv">
                {outputs.map(([k, v]) => (
                  <div class="waterfall-kv-row" key={k}>
                    <dt class="mono">{k}</dt>
                    <dd class="mono">{v}</dd>
                  </div>
                ))}
              </dl>
            </section>
          ) : null}
        </div>
      ) : null}

      <section class="waterfall-section">
        <h3 class="waterfall-section-title">Record</h3>
        <dl class="waterfall-detail-grid">
          {record.map(([label, value]) =>
            value === null || value === undefined ? null : (
              <div class="waterfall-detail-row" key={label}>
                <dt>{label}</dt>
                <dd>{value}</dd>
              </div>
            ),
          )}
        </dl>
      </section>

      {otherFields.length > 0 ? (
        <section class="waterfall-section">
          <h3 class="waterfall-section-title">Other recorded fields</h3>
          <dl class="waterfall-detail-grid">
            {otherFields.map(([key, value]) => (
              <div class="waterfall-detail-row" key={key}>
                <dt class="mono">{key}</dt>
                <dd class="mono">{value}</dd>
              </div>
            ))}
          </dl>
        </section>
      ) : null}
    </aside>
  );
}
