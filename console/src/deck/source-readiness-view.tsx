import { useEffect, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import { getLocale, t } from "../i18n";
import { panelPath } from "../router";
import { presentationTimestamp } from "./presentation-value";
import {
  deckSourceReadiness,
  hasVerifiedSourceReadiness,
  latestSourceObservation,
  type DeckSourceKey,
  type DeckSourceReadiness,
} from "./source-readiness";

type ReadinessState =
  | { readonly status: "loading" }
  | { readonly status: "error" }
  | {
      readonly status: "ready";
      readonly sources: readonly DeckSourceReadiness[];
      readonly observedAt: string | null;
    };

const SOURCE_PANELS: Readonly<Record<DeckSourceKey, string>> = {
  inventory: "architecture",
  incidents: "incidents",
  audit: "audit",
  knowledge: "rules",
  automation: "scheduler-runs",
};

export function SourceReadinessStrip({ client }: { readonly client: OperatorApiClient }) {
  const [state, setState] = useState<ReadinessState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    client.dataSources().then((payload) => {
      if (cancelled) return;
      const sources = deckSourceReadiness(payload);
      setState({
        status: "ready",
        sources,
        observedAt: latestSourceObservation(sources),
      });
    }).catch(() => {
      if (!cancelled) setState({ status: "error" });
    });
    return () => {
      cancelled = true;
    };
  }, [client]);

  if (state.status === "loading") {
    return (
      <div class="deck-source-readiness is-loading" role="status" aria-busy="true">
        <span class="sr-only">{t("deck.sourceReadiness.loading")}</span>
        <span class="deck-source-readiness-skeleton skeleton-shimmer" aria-hidden="true" />
        <span class="deck-source-readiness-skeleton skeleton-shimmer" aria-hidden="true" />
        <span class="deck-source-readiness-skeleton skeleton-shimmer" aria-hidden="true" />
      </div>
    );
  }

  if (state.status === "error") {
    return (
      <div class="deck-source-readiness is-error" role="status">
        <span>{t("deck.sourceReadiness.unavailable")}</span>
        <a href={panelPath("settings-diagnostics")}>{t("deck.sourceReadiness.openDiagnostics")}</a>
      </div>
    );
  }

  if (!hasVerifiedSourceReadiness(state.sources)) return null;

  return (
    <nav class="deck-source-readiness" aria-label={t("deck.sourceReadiness.label")}>
      <span class="deck-source-readiness-label">{t("deck.sourceReadiness.label")}</span>
      <span class="deck-source-readiness-items">
        {state.sources.map((item) => (
          <a
            key={item.key}
            class={`deck-source-status is-${item.availability}`}
            href={panelPath(SOURCE_PANELS[item.key])}
            aria-label={`${t(`deck.sourceReadiness.source.${item.key}`)}: ${t(`deck.sourceReadiness.status.${item.availability}`)}`}
          >
            <span class="deck-source-status-dot" aria-hidden="true" />
            <span>{t(`deck.sourceReadiness.source.${item.key}`)}</span>
            <span class="sr-only">: {t(`deck.sourceReadiness.status.${item.availability}`)}</span>
          </a>
        ))}
      </span>
      <span class="deck-source-readiness-summary">{readinessSummary(state.sources)}</span>
      <span class="deck-source-readiness-time">
        {state.observedAt
          ? observedLabel(state.observedAt)
          : t("deck.sourceReadiness.observationUnknown")}
      </span>
    </nav>
  );
}

function readinessSummary(sources: readonly DeckSourceReadiness[]): string {
  const unavailable = sources.filter((source) => source.availability === "unavailable").length;
  const unknown = sources.filter((source) => source.availability === "unknown").length;
  const parts = [
    unavailable > 0 ? t("deck.sourceReadiness.unavailableCount", { count: unavailable }) : "",
    unknown > 0 ? t("deck.sourceReadiness.unknownCount", { count: unknown }) : "",
  ].filter(Boolean);
  return parts.length > 0 ? parts.join(", ") : t("deck.sourceReadiness.allAvailable");
}

function observedLabel(value: string): string {
  const timestamp = presentationTimestamp(value, getLocale() === "ko" ? "ko-KR" : "en-US");
  return timestamp
    ? t("deck.sourceReadiness.observed", { time: `${timestamp.date} ${timestamp.time}` })
    : t("deck.sourceReadiness.observationUnknown");
}
