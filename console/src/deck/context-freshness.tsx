import { useEffect, useState } from "preact/hooks";
import { Tooltip } from "../components/tooltip";
import { t } from "../i18n";

const MINUTE_MS = 60_000;
const STALE_AFTER_MS = 5 * MINUTE_MS;

export interface ContextFreshness {
  readonly state: "fresh" | "stale" | "unknown";
  readonly ageMinutes: number | null;
}

export function classifyContextFreshness(
  capturedAt: string,
  nowMs: number,
): ContextFreshness {
  const capturedMs = Date.parse(capturedAt);
  if (!Number.isFinite(capturedMs) || capturedMs > nowMs + MINUTE_MS) {
    return { state: "unknown", ageMinutes: null };
  }
  const ageMs = Math.max(0, nowMs - capturedMs);
  return {
    state: ageMs >= STALE_AFTER_MS ? "stale" : "fresh",
    ageMinutes: Math.floor(ageMs / MINUTE_MS),
  };
}

export function contextAgeLabel(freshness: ContextFreshness): string {
  if (freshness.ageMinutes === null) return t("deck.digest.freshness.unknown");
  if (freshness.ageMinutes < 1) return t("deck.digest.freshness.justNow");
  if (freshness.ageMinutes < 60) {
    return t("deck.digest.freshness.minutesAgo", { count: freshness.ageMinutes });
  }
  return t("deck.digest.freshness.hoursAgo", {
    count: Math.floor(freshness.ageMinutes / 60),
  });
}

export function ContextFreshnessIndicator({ capturedAt }: { readonly capturedAt: string }) {
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNowMs(Date.now()), MINUTE_MS);
    return () => window.clearInterval(timer);
  }, []);
  const freshness = classifyContextFreshness(capturedAt, nowMs);
  const age = contextAgeLabel(freshness);
  const exact = Number.isNaN(Date.parse(capturedAt))
    ? t("deck.digest.freshness.unknown")
    : new Date(capturedAt).toLocaleString();
  return (
    <div class="deck-context-freshness" data-state={freshness.state}>
      <Tooltip content={exact}>
        <time dateTime={capturedAt}>{age}</time>
      </Tooltip>
      {freshness.state === "stale" ? (
        <>
          <span class="deck-context-stale">{t("deck.digest.freshness.stale")}</span>
          <button type="button" onClick={() => window.location.reload()}>
            {t("deck.digest.freshness.refresh")}
          </button>
        </>
      ) : null}
    </div>
  );
}
