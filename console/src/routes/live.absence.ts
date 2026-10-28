/**
 * Cause-specific text for values a Live card did not receive.
 *
 * A missing field is not one condition: a failure, a finished item that never sent a
 * reason, and an item still in progress each need different wording. Every label states
 * only what the projection knows and never asserts why a value is absent.
 */

import { t } from "./i18n/live";
import type { TileState } from "./live.model";

export function tileReasonLabel(tile: TileState): string {
  if (tile.reason) return tile.reason;
  if (tile.failed) return t("live.absent.reasonFailed");
  return tile.completed ? t("live.absent.reasonCompleted") : t("live.absent.reasonPending");
}

export function tileScopeLabel(tile: TileState): string {
  return tile.scope ?? t("live.absent.scope");
}

export function tileAuthorityLabel(autonomy: string | null): string {
  return autonomy ?? t("live.absent.authority");
}

export function tileEffectLabel(tile: TileState, outcome: string | null): string {
  if (outcome) return outcome;
  if (tile.mode === "shadow") return t("live.absent.effectShadow");
  return tile.completed ? t("live.absent.effectUnreported") : t("live.absent.effectPending");
}

/** Plain-language label for a machine reason code; an unknown code is shown as recorded. */
export function observationReasonLabel(code: string): string {
  const key = `live.observations.reason.${code}`;
  const label = t(key);
  return label === key ? code : label;
}

export function observationReasonSummary(codes: readonly string[]): string {
  const [first, ...rest] = codes;
  if (first === undefined) return "";
  const reason = observationReasonLabel(first);
  return rest.length === 0
    ? reason
    : t("live.observations.reasonAndMore", { reason, count: rest.length });
}
