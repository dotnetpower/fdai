/**
 * Briefing CONTRACT - the presentation-neutral data the console reads.
 *
 * This mirrors the shape a real deployment would receive from the read-only
 * `console-tool` calls (see `src/fdai/delivery/read_api/read_model.py` and
 * `console/src/types.ts`). It is the raw content; `build-briefing.ts` compiles
 * it into the surface-neutral block IR. Nothing here is presentation.
 *
 * Every value in the shipped sample is synthetic and customer-agnostic.
 */

import type { RiskLevel, SideEffectClass } from "./blocks.js";

/** One trust-tier's share of the window's events. */
export interface TierShare {
  tier: "T0" | "T1" | "T2";
  /** Plain-language label; the tier code is shown dimmed beside it. */
  name: string;
  pct: number;
}

/** One item autonomy handed to a human (HIL). */
export interface HilItem {
  risk: RiskLevel;
  chip: string;
  chipSideEffect: SideEffectClass;
  /** Plain-language title. */
  title: string;
  /** Precise internal action-type id, shown dimmed. */
  actionType: string;
  change: string;
  why: string;
  basis: string;
  basisTech: string;
  safety: string;
  how: string;
  who: string;
  check: string;
  reference: string;
  irreversible: boolean;
}

/** The whole briefing payload for one operator, one window. */
export interface BriefingPayload {
  env: string;
  operator: string;
  clock: string;
  windowLabel: string;
  events: number;
  autoResolved: number;
  rollbacks: number;
  shadowCandidates: number;
  overridesActive: number;
  tiers: readonly TierShare[];
  /** events-per-5min buckets across the window. */
  throughput: readonly number[];
  /** peak caption pieces so copy stays data-driven, not hardcoded. */
  peakHourLabel: string;
  hil: readonly HilItem[];
  suggestions: readonly string[];
}
