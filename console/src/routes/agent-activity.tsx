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

/** Resolve the acting agent for one audit row. */
function agentOf(item: AuditItem): string {
  if (item.actor in AGENT_LAYER) return item.actor;
  const principal = item.entry["producer_principal"];
  if (typeof principal === "string" && principal in AGENT_LAYER) return principal;
  return SYSTEM_AGENT;
}

function layerOf(agent: string): string {
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
}

type ActivityView = "waterfall" | "timeline";

export function AgentActivityRoute({ client }: Props) {
  const [state, setState] = useState<AsyncState<Data>>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const page = await client.listAudit({ limit: TIMELINE_LIMIT });
        if (!cancelled) setState({ status: "ready", data: { items: page.items } });
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
    // Known agents first (in count order), System last.
    return [...counts.entries()]
      .sort((a, b) => {
        if (a[0] === SYSTEM_AGENT) return 1;
        if (b[0] === SYSTEM_AGENT) return -1;
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
      headline: `${data.items.length} audit row(s) across ${perAgent.length} agent(s)${
        selected ? ` - filtered to ${selected}` : ""
      }`,
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "rows", value: data.items.length, group: "page" },
        { key: "agents", value: perAgent.length, group: "page" },
        { key: "filter", value: selected ?? "all", group: "page" },
      ],
      records: {
        by_agent: perAgent.map(([agent, count]) => ({ agent, count })),
      },
    }),
    [data.items, perAgent, selected],
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
      <div class="agent-filter" role="tablist" aria-label="Filter by agent">
        <button
          type="button"
          class={`agent-chip ${selected === null ? "agent-chip-on" : ""}`}
          role="tab"
          aria-selected={selected === null}
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
            role="tab"
            aria-selected={selected === agent}
            data-layer={layerOf(agent)}
            onClick={() => setSelected((s) => (s === agent ? null : agent))}
          >
            <span class="agent-dot" data-layer={layerOf(agent)} aria-hidden="true" />
            {agent}
            <span class="agent-chip-count">{count}</span>
          </button>
        ))}
      </div>

      <div class="view-toggle" role="tablist" aria-label="Activity view">
        <button
          type="button"
          class="view-toggle-btn"
          role="tab"
          aria-selected={view === "waterfall"}
          onClick={() => setView("waterfall")}
        >
          Waterfall
        </button>
        <button
          type="button"
          class="view-toggle-btn"
          role="tab"
          aria-selected={view === "timeline"}
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
    const key = item.correlation_id || "(uncorrelated)";
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

  // When an agent is filtered, keep only incidents that agent touched (so the
  // hand-off context around it stays visible) and dim the other lanes.
  const shown = useMemo(
    () =>
      selected === null
        ? groups
        : groups.filter((g) => g.bars.some((b) => b.agent === selected)),
    [groups, selected],
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
    <div class="waterfall" aria-label="Agent activity waterfall">
      {shown.map((g) => (
        <section class="waterfall-group" key={g.correlation}>
          <header class="waterfall-group-head">
            <a
              class="waterfall-corr mono"
              href={`#/trace?correlation=${encodeURIComponent(g.correlation)}`}
              title="Open this correlation in the Trace panel"
            >
              {g.correlation}
            </a>
            <span class="waterfall-span mono muted">
              {stamp(new Date(g.startMs).toISOString())} · {g.bars.length} step(s) ·{" "}
              {fmtDur(g.spanMs)}
            </span>
          </header>
          <ol class="waterfall-lanes">
            {g.bars.map((bar) => {
              const dimmed = selected !== null && bar.agent !== selected;
              return (
                <li class="waterfall-lane" key={bar.item.seq}>
                  <div class="waterfall-label" title={bar.agent}>
                    <span class="agent-dot" data-layer={bar.layer} aria-hidden="true" />
                    <span class="waterfall-agent" data-layer={bar.layer}>
                      {bar.agent}
                    </span>
                    <span class="waterfall-action mono muted">{bar.item.action_kind}</span>
                  </div>
                  <div class="waterfall-track">
                    <div
                      class={`waterfall-bar ${dimmed ? "waterfall-bar-dim" : ""}`}
                      data-layer={bar.layer}
                      style={`left:${bar.leftPct.toFixed(2)}%;width:${bar.widthPct.toFixed(2)}%`}
                      title={`${bar.agent} · ${bar.item.action_kind} · ${stamp(bar.item.recorded_at)}`}
                    >
                      <span class="waterfall-bar-time mono">{stamp(bar.item.recorded_at)}</span>
                    </div>
                  </div>
                </li>
              );
            })}
          </ol>
        </section>
      ))}
    </div>
  );
}
