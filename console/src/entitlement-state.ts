/**
 * Trial expiry watermark state: the latest entitlement stamp from any Operator response.
 *
 * The Operator stamps Core's notice as `X-FDAI-Entitlement` on every authenticated
 * response. This module keeps the most recent stamp and decides whether the watermark
 * shows. A missing, unknown, or stale stamp shows it; only a recent `none` hides it.
 * No preference, setting, or route can switch it off, and the watermark grants and
 * removes no authority: the Core execution ceiling still decides every acting request.
 */

export const ENTITLEMENT_HEADER = "x-fdai-entitlement";
/** How long the Console waits for the first stamp before treating it as missing. */
export const FIRST_STAMP_WAIT_MS = 10_000;
/** A stamp older than this is stale and shows the watermark. */
export const STAMP_STALE_MS = 5 * 60_000;
/** How often the watermark refreshes the stamp with an authenticated read. */
export const PROBE_INTERVAL_MS = 60_000;

export type WatermarkNotice = "evaluation-ended" | "not-activated";
export type EntitlementNotice = "none" | WatermarkNotice;

export interface EntitlementStamp {
  readonly notice: EntitlementNotice;
  /** Monotonic receipt time in milliseconds. */
  readonly receivedAt: number;
}

/** Map a header value onto the closed vocabulary; anything unknown fails closed. */
export function parseEntitlementNotice(value: string): EntitlementNotice {
  const notice = value.trim();
  return notice === "none" || notice === "evaluation-ended" ? notice : "not-activated";
}

/**
 * Return the notice to render now, or null when the watermark stays hidden.
 *
 * Before the first stamp the watermark waits `FIRST_STAMP_WAIT_MS` from `startedAt`.
 */
export function watermarkNotice(
  stamp: EntitlementStamp | null,
  timing: { readonly startedAt: number; readonly now: number },
): WatermarkNotice | null {
  if (stamp === null) {
    return timing.now - timing.startedAt >= FIRST_STAMP_WAIT_MS ? "not-activated" : null;
  }
  if (timing.now - stamp.receivedAt > STAMP_STALE_MS) return "not-activated";
  return stamp.notice === "none" ? null : stamp.notice;
}

function monotonicNow(): number {
  return globalThis.performance.now();
}

/** Process-local store of the latest stamp with change notification. */
export class EntitlementStampStore {
  readonly #clock: () => number;
  readonly #listeners = new Set<() => void>();
  #latest: EntitlementStamp | null = null;

  constructor(clock: () => number = monotonicNow) {
    this.#clock = clock;
  }

  /** Record a response's header value. A response without the header changes nothing. */
  record(value: string | null): void {
    if (value === null) return;
    this.#latest = { notice: parseEntitlementNotice(value), receivedAt: this.#clock() };
    for (const listener of this.#listeners) listener();
  }

  latest(): EntitlementStamp | null {
    return this.#latest;
  }

  subscribe(listener: () => void): () => void {
    this.#listeners.add(listener);
    return () => {
      this.#listeners.delete(listener);
    };
  }
}

/** The store every Operator transport records into by default. */
export const entitlementStamps = new EntitlementStampStore();
