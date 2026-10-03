import { useEffect, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import { getLocale, t } from "../i18n";
import { panelPath } from "../router";
import { answerEvidenceText } from "./answer-evidence-i18n";
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
      <div class="deck-source-readiness cs-deck-readiness is-loading" role="status" aria-busy="true">
        <span class="sr-only">{t("deck.sourceReadiness.loading")}</span>
        <span class="cs-deck-skeleton" aria-hidden="true" />
        <span class="cs-deck-skeleton" aria-hidden="true" />
        <span class="cs-deck-skeleton" aria-hidden="true" />
      </div>
    );
  }

  if (state.status === "error") {
    return (
      <div class="deck-source-readiness cs-deck-readiness is-error" role="status">
        <span>{t("deck.sourceReadiness.unavailable")}</span>
        <a href={panelPath("settings-diagnostics")}>{t("deck.sourceReadiness.openDiagnostics")}</a>
      </div>
    );
  }

  if (!hasVerifiedSourceReadiness(state.sources)) return null;

  const summary = readinessSummary(state.sources);
  // Evidence services fold into one summary line that states their availability; opening it shows
  // each source. An available source is a plain link; only an exception carries a mark and its
  // state.
  return (
    <details class="deck-source-readiness-disclosure">
      <summary>
        <span class="cs-deck-readiness-label">{answerEvidenceText("evidenceServices")}</span>
        <strong class={`deck-source-readiness-summary cs-deck-readiness-summary${summary.tone ? ` is-${summary.tone}` : ""}`}>
          {summary.text}
        </strong>
        <span class="cs-run-chevron" aria-hidden="true" />
      </summary>
      <nav class="deck-source-readiness cs-deck-readiness" aria-label={t("deck.sourceReadiness.label")}>
        <ul class="deck-source-readiness-items cs-deck-readiness-items">
          {state.sources.map((item) => (
            <li key={item.key}>
              <a
                class={`deck-source-status cs-deck-readiness-item is-${item.availability}`}
                href={panelPath(SOURCE_PANELS[item.key])}
                aria-label={`${t(`deck.sourceReadiness.source.${item.key}`)}: ${t(`deck.sourceReadiness.status.${item.availability}`)}`}
              >
                <span class="cs-deck-readiness-mark" aria-hidden="true">
                  {READINESS_MARK[item.availability]}
                </span>
                <span>{t(`deck.sourceReadiness.source.${item.key}`)}</span>
                {item.availability === "available" ? null : (
                  <span class="cs-deck-readiness-state">
                    {t(`deck.sourceReadiness.status.${item.availability}`)}
                  </span>
                )}
              </a>
            </li>
          ))}
        </ul>
        <span class="deck-source-readiness-time cs-deck-readiness-time">
          {state.observedAt
            ? <ObservedTime value={state.observedAt} />
            : t("deck.sourceReadiness.observationUnknown")}
        </span>
      </nav>
    </details>
  );
}

const READINESS_MARK: Readonly<Record<DeckSourceReadiness["availability"], string>> = {
  available: "\u2713",
  unavailable: "!",
  unknown: "?",
};

function readinessSummary(
  sources: readonly DeckSourceReadiness[],
): { readonly text: string; readonly tone: "attention" | "unknown" | null } {
  const unavailable = sources.filter((source) => source.availability === "unavailable").length;
  const unknown = sources.filter((source) => source.availability === "unknown").length;
  const parts = [
    unavailable > 0 ? t("deck.sourceReadiness.unavailableCount", { count: unavailable }) : "",
    unknown > 0 ? t("deck.sourceReadiness.unknownCount", { count: unknown }) : "",
  ].filter(Boolean);
  if (parts.length === 0) return { text: t("deck.sourceReadiness.allAvailable"), tone: null };
  return { text: parts.join(", "), tone: unavailable > 0 ? "attention" : "unknown" };
}

// The localized template supplies the label around the time, so a narrow strip can hide the label
// and keep the timestamp.
function ObservedTime({ value }: { readonly value: string }) {
  const timestamp = presentationTimestamp(value, getLocale() === "ko" ? "ko-KR" : "en-US");
  if (!timestamp) return <>{t("deck.sourceReadiness.observationUnknown")}</>;
  const marker = "\u0000";
  const [label = "", suffix = ""] = t("deck.sourceReadiness.observed", { time: marker }).split(marker);
  return (
    <time dateTime={value}>
      {label ? <span class="cs-deck-readiness-time-label">{label}</span> : null}
      {`${timestamp.date} ${timestamp.time}${suffix}`}
    </time>
  );
}
