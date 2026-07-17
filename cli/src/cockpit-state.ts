import { t, type Locale } from "./i18n/index.js";
import type { View } from "./cockpit-view.js";
import type { StageFrame } from "./cockpit-sse.js";

const SAGE = "\x1b[38;2;127;176;119m";
const TERRA = "\x1b[38;2;214;146;95m";
const DIM = "\x1b[38;2;124;132;139m";
const RESET = "\x1b[0m";

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
  view: View;
  status: string;
  lastQ: string;
  answerTarget: string;
  answerShown: number;
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
  view: { mode: "stream", paused: false },
  status: "connecting",
  lastQ: "",
  answerTarget: "",
  answerShown: 0,
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
    const routed = String(detail.routed_to ?? "abstain");
    state.perEvent.set(frame.event_id, {
      resource: String(detail.resource_type ?? "") || "resource",
      tier: routed,
      routed,
    });
    state.byTier[routed] = (state.byTier[routed] ?? 0) + 1;
  }
  if (frame.stage === "verify" && frame.phase === "done") {
    const record = state.perEvent.get(frame.event_id);
    if (record && detail.tier) record.tier = String(detail.tier);
  }
  if (frame.stage !== "audit" || frame.phase !== "done") return null;

  state.handled++;
  const record = state.perEvent.get(frame.event_id);
  const tier = record?.tier ?? "t0";
  const resource = record?.resource ?? "resource";
  const outcome = String(detail.outcome ?? "");
  const decision = String(detail.decision ?? "");
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
    state.resourceCounts[resource] = (state.resourceCounts[resource] ?? 0) + 1;
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
