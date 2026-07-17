import { useEffect, useMemo, useState } from "preact/hooks";
import type { AuditItem } from "../types";
import { Tooltip } from "../components/tooltip";
import { EmptyState } from "../components/ui";
import { t } from "../i18n";
import { currentRoute, navigate, routeHref } from "../router";
import { StepDetail } from "./agent-activity-detail";
import {
  agentOf,
  entryConversation,
  entryNum,
  fmtDur,
  layerOf,
  milliseconds,
  startClockOf,
} from "./agent-activity-semantics";
import type { ActivityFilters } from "./agent-activity-groups";

function activityFiltersFromRoute(): ActivityFilters {
  const search = currentRoute().search;
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
    const sorted = [...rows].sort(
      (a, b) => milliseconds(a.recorded_at) - milliseconds(b.recorded_at),
    );
    const startMs = milliseconds(sorted[0]!.recorded_at);
    const endMs = milliseconds(sorted[sorted.length - 1]!.recorded_at);
    const actualSpanMs = Math.max(endMs - startMs, 0);
    // Padded denominator for layout: a trailing tail gives the terminal event
    // (no next hand-off) a visible bar, and a singleton fills the whole track.
    const tailMs = actualSpanMs > 0 ? actualSpanMs * 0.2 : SINGLETON_SPAN_MS;
    const denom = actualSpanMs + tailMs;
    const bars: WaterfallBar[] = sorted.map((item, i) => {
      const s = milliseconds(item.recorded_at);
      const next = i + 1 < sorted.length
        ? milliseconds(sorted[i + 1]!.recorded_at)
        : endMs + tailMs;
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

interface ActivityWaterfallProps {
  readonly items: readonly AuditItem[];
  readonly selected: string | null;
}

export function ActivityWaterfall({ items, selected }: ActivityWaterfallProps) {
  const groups = useMemo(() => buildGroups(items), [items]);
  // Collapsed correlation ids (default: all expanded). Chevron toggles a group.
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set());
  // The audit row whose detail drawer is open, by stable `seq`.
  const [selectedSeq, setSelectedSeq] = useState<number | null>(() => {
    const value = Number(currentRoute().search.get("step"));
    return Number.isInteger(value) && value > 0 ? value : null;
  });

  useEffect(() => {
    const sync = () => {
      const value = Number(currentRoute().search.get("step"));
      setSelectedSeq(Number.isInteger(value) && value > 0 ? value : null);
    };
    window.addEventListener("popstate", sync);
    window.addEventListener("fdai:route-changed", sync);
    return () => {
      window.removeEventListener("popstate", sync);
      window.removeEventListener("fdai:route-changed", sync);
    };
  }, []);

  const openStep = (step: number | null): void => {
    const filters = activityFiltersFromRoute();
    navigate(routeHref("agent-activity", {
      params: {
        agent: selected,
        view: "waterfall",
        step,
        window: filters.window === "24h" ? null : filters.window,
        layer: filters.layer === "all" ? null : filters.layer,
        verb: filters.verb === "all" ? null : filters.verb,
        q: filters.query || null,
      },
    }));
  };

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
                  <Tooltip content={t("tooltip.openTrace")}>
                    <a
                      class="waterfall-corr mono"
                      href={routeHref("trace", { params: { correlation: g.correlation } })}
                    >
                      {g.correlation}
                    </a>
                  </Tooltip>
                )}
                <Tooltip content={t("tooltip.activitySpan", { count: g.bars.length, duration: fmtDur(g.spanMs) })}>
                  <span class="waterfall-span mono muted">
                    {startClockOf(g.bars[0]!.item)} · {g.bars.length}
                  </span>
                </Tooltip>
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
                          onClick={() => openStep(active ? null : bar.item.seq)}
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
                              <Tooltip content={t("tooltip.agentMessages", { count: convo.length })}>
                                <span class="waterfall-conv-badge">
                                  <ChatGlyph />
                                  {convo.length}
                                </span>
                              </Tooltip>
                            ) : null}
                          </span>
                          <span class="waterfall-mini" aria-hidden="true">
                            <span
                              class="waterfall-mini-bar"
                              data-layer={bar.layer}
                              style={`left:${bar.leftPct.toFixed(2)}%;width:${bar.widthPct.toFixed(2)}%`}
                            />
                          </span>
                          <Tooltip
                            content={work !== null
                              ? t("tooltip.workTiming", {
                                  start: startClockOf(bar.item),
                                  duration: fmtDur(work),
                                })
                              : undefined}
                          >
                            <span class="waterfall-time mono muted">
                              {startClockOf(bar.item)}
                            </span>
                          </Tooltip>
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
          <StepDetail item={selectedItem} onClose={() => openStep(null)} />
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
