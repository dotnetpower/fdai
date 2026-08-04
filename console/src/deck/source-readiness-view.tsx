import { useEffect, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import { t } from "../i18n";
import { panelPath } from "../router";
import {
  deckSourceReadiness,
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

  return (
    <nav class="deck-source-readiness" aria-label={t("deck.sourceReadiness.label")}>
      <span class="deck-source-readiness-label">{t("deck.sourceReadiness.label")}</span>
      <span class="deck-source-readiness-items">
        {state.sources.map((item) => (
          <a
            key={item.key}
            class={`deck-source-status is-${item.availability}`}
            href={panelPath(SOURCE_PANELS[item.key])}
          >
            <span class="deck-source-status-dot" aria-hidden="true" />
            <span>{t(`deck.sourceReadiness.source.${item.key}`)}</span>
            <span class="sr-only">: {t(`deck.sourceReadiness.status.${item.availability}`)}</span>
          </a>
        ))}
      </span>
      <span class="deck-source-readiness-time">
        {state.observedAt
          ? t("deck.sourceReadiness.observed", {
              time: new Date(state.observedAt).toLocaleString(),
            })
          : t("deck.sourceReadiness.observationUnknown")}
      </span>
    </nav>
  );
}
