import { kpiEvidenceLabel } from "../components/ui";
import { getLocale } from "../i18n";
import { formatConsoleTimestamp } from "../time-format";
import type { ForecastLearningResponse } from "./forecast-learning";
import en from "./i18n/forecast-activity.en.json";
import ko from "./i18n/forecast-activity.ko.json";

function text(key: keyof typeof en): string {
  return (getLocale() === "ko" ? ko[key] : undefined) || en[key];
}

/** Preserve recorded activity and queue evidence without inferring prediction quality. */
export function forecastActivityRows(data: ForecastLearningResponse) {
  return [
    { key: "total", label: text("total"), value: data.episodes.total },
    { key: "open", label: text("open"), value: data.episodes.open },
    { key: "closed", label: text("closed"), value: data.episodes.closed },
    { key: "abstained", label: text("abstained"), value: data.episodes.abstained },
    { key: "pendingRetention", label: text("pendingRetention"), value: data.retention.pending },
    {
      key: "oldestPending",
      label: text("oldestPending"),
      value: formatConsoleTimestamp(
        data.publication.oldest_pending_at ?? null,
        kpiEvidenceLabel("not-measured"),
      ),
    },
  ];
}

/** Show recorded episodes even while no scored terminal outcomes exist. */
export function ForecastActivity({ data }: { readonly data: ForecastLearningResponse }) {
  return (
    <section class="stack-section" aria-labelledby="forecast-activity-title">
      <h3 id="forecast-activity-title">{text("title")}</h3>
      <p>{text("description")}</p>
      <dl class="details-list">
        {forecastActivityRows(data).map((row) =>
          <div key={row.key}><dt>{row.label}</dt><dd>{row.value}</dd></div>,
        )}
      </dl>
    </section>
  );
}
