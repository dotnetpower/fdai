import { t, type Locale } from "./i18n/index.js";
import { safeDisplayLine } from "./display-text.js";
import type { View } from "./cockpit-view.js";
import type { StageFrame } from "./cockpit-sse.js";
import type { OperatorApiAuthMode } from "./operator-api-session.js";

const SAGE = "\x1b[38;2;127;176;119m";
const TERRA = "\x1b[38;2;214;146;95m";
const DIM = "\x1b[38;2;124;132;139m";
const RESET = "\x1b[0m";
const MAX_PENDING_EVENTS = 1024;
const MAX_COMPLETED_EVENTS = 4096;
const MAX_RESOURCE_KINDS = 128;
const ROUTING_TIERS = new Set(["t0", "t1", "t2", "abstain"]);

export interface Activity {
  marker: string;
  resource: string;
  text: string;
  tier: string;
}

export interface CockpitState {
  handled: number;
  byTier: Record<string, number>;
  autoApplied: number;
  awaitingYou: number;
  undone: number;
  errors: number;
  activity: Activity[];
  resourceCounts: Record<string, number>;
  spark: number[];
  handledAtLastTick: number;
  perEvent: Map<string, { resource: string; tier: string; routed: string }>;
  completedEventIds: Set<string>;
  view: View;
  status: string;
  authMode: OperatorApiAuthMode;
  authRoles: readonly string[];
  lastQ: string;
  answerTarget: string;
  answerShown: number;
  answerModel: string;
  answerLatencyMs: number | null;
  questionStartedAt: number | null;
  thinkingFrame: number;
  thinking: boolean;
  busy: boolean;
  input: string[];
  cursor: number;
  history: string[];
  historyIndex: number | null;
}

export const createCockpitState = (): CockpitState => ({
  handled: 0,
  byTier: {},
  autoApplied: 0,
  awaitingYou: 0,
  undone: 0,
  errors: 0,
  activity: [],
  resourceCounts: {},
  spark: [],
  handledAtLastTick: 0,
  perEvent: new Map(),
  completedEventIds: new Set(),
  view: { mode: "stream", paused: false },
  status: "connecting",
  authMode: "none",
  authRoles: [],
  lastQ: "",
  answerTarget: "",
  answerShown: 0,
  answerModel: "",
  answerLatencyMs: null,
  questionStartedAt: null,
  thinkingFrame: 0,
  thinking: false,
  busy: false,
  input: [],
  cursor: 0,
  history: [],
  historyIndex: null,
});

export function reduceStageFrame(
  state: CockpitState,
  frame: StageFrame,
  locale: Locale,
): Activity | null {
  const detail = frame.detail ?? {};
  if (frame.phase === "failed") state.errors++;
  if (frame.stage === "route" && frame.phase === "done") {
    const candidate = safeDisplayLine(String(detail.routed_to ?? "abstain"), 64).toLowerCase();
    const routed = ROUTING_TIERS.has(candidate) ? candidate : "unrouted";
    state.perEvent.set(frame.event_id, {
      resource: safeDisplayLine(String(detail.resource_type ?? ""), 256) || "resource",
      tier: routed,
      routed,
    });
    trimOldest(state.perEvent, MAX_PENDING_EVENTS);
    state.byTier[routed] = (state.byTier[routed] ?? 0) + 1;
  }
  if (frame.stage === "verify" && frame.phase === "done") {
    const record = state.perEvent.get(frame.event_id);
    if (record && detail.tier) {
      const candidate = safeDisplayLine(String(detail.tier), 64).toLowerCase();
      if (ROUTING_TIERS.has(candidate)) record.tier = candidate;
    }
  }
  if (frame.stage !== "audit" || frame.phase !== "done") return null;
  if (state.completedEventIds.has(frame.event_id)) return null;
  state.completedEventIds.add(frame.event_id);
  trimOldest(state.completedEventIds, MAX_COMPLETED_EVENTS);

  state.handled++;
  const record = state.perEvent.get(frame.event_id);
  const tier = record?.tier ?? "t0";
  const resource = record?.resource ?? "resource";
  const outcome = safeDisplayLine(String(detail.outcome ?? ""), 512);
  const decision = safeDisplayLine(String(detail.decision ?? ""), 64);
  let activity: Activity;
  if (decision === "auto" || outcome === "executed") {
    state.autoApplied++;
    activity = {
      marker: `${SAGE}\u2713${RESET}`,
      resource,
      text: t("cockpit.feed.autoApplied", locale),
      tier,
    };
  } else if (outcome.includes("hil") || decision === "hil") {
    state.awaitingYou++;
    activity = {
      marker: `${TERRA}\u2691${RESET}`,
      resource,
      text: t("cockpit.feed.awaiting", locale),
      tier,
    };
  } else if (outcome.startsWith("abstained")) {
    const why = outcome.includes("routing")
      ? t("cockpit.feed.whyRouting", locale)
      : t("cockpit.feed.whyNoRule", locale);
    activity = {
      marker: `${DIM}\u00b7${RESET}`,
      resource,
      text: t("cockpit.feed.steppedBack", locale, { why }),
      tier,
    };
  } else {
    activity = {
      marker: `${DIM}\u00b7${RESET}`,
      resource,
      text: outcome || t("cockpit.feed.handled", locale),
      tier,
    };
  }
  state.activity.push(activity);
  if (state.activity.length > 400) state.activity.shift();
  if (resource !== "resource") {
    const existing = state.resourceCounts[resource];
    if (existing !== undefined) state.resourceCounts[resource] = existing + 1;
    else if (Object.keys(state.resourceCounts).length < MAX_RESOURCE_KINDS) {
      state.resourceCounts[resource] = 1;
    } else {
      state.resourceCounts.other = (state.resourceCounts.other ?? 0) + 1;
    }
  }
  state.perEvent.delete(frame.event_id);
  return activity;
}

export const topResourcesText = (state: CockpitState, count: number): string => {
  const resources = Object.entries(state.resourceCounts)
    .sort((left, right) => right[1] - left[1])
    .slice(0, count)
    .map(([name, total]) => `${name} x${total}`);
  return resources.length ? resources.join(", ") : "nothing yet";
};

export const liveOverviewText = (state: CockpitState): string =>
  `Live so far - ${state.handled} events handled: T0=${state.byTier.t0 ?? 0} ` +
  `T1=${state.byTier.t1 ?? 0} T2=${state.byTier.t2 ?? 0} ` +
  `stepped-back=${state.byTier.abstain ?? 0}; ${state.autoApplied} auto-applied, ` +
  `${state.awaitingYou} awaiting you, ${state.undone} undone, ${state.errors} errors. ` +
  `By resource type: ${topResourcesText(state, 10)}. ` +
  `These are live event types from the stream, not a named resource-group inventory.`;

function trimOldest<T>(collection: Map<string, T> | Set<string>, maximum: number): void {
  while (collection.size > maximum) {
    const oldest = collection.keys().next().value as string | undefined;
    if (oldest === undefined) return;
    collection.delete(oldest);
  }
}
