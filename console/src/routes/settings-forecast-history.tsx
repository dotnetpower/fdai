import { t } from "../i18n";
import type { ForecastHistoryDetails } from "./settings-runtime.model";

export function ForecastHistorySourceDetails({ details }: {
  readonly details: ForecastHistoryDetails | undefined;
}) {
  if (details === undefined) return null;
  return (
    <details>
      <summary>{t("settings.forecastHistory.details")}</summary>
      <p class="muted">{t("settings.forecastHistory.boundary")}</p>
      <dl>
        {details.sources.map((source) => (
          <div key={source.kind}>
            <dt>{t(`settings.forecastHistory.kinds.${source.kind}`)}</dt>
            <dd>
              <p>{t(source.bound
                ? "settings.forecastHistory.bound" : "settings.forecastHistory.unbound")}</p>
              <p>{t(source.positiveCheckpoint
                ? "settings.forecastHistory.checkpointPresent"
                : "settings.forecastHistory.checkpointMissing")}</p>
              <small class="muted">{source.reader}: {source.limitation}</small>
            </dd>
          </div>
        ))}
      </dl>
      <h5>{t("settings.forecastHistory.prerequisites")}</h5>
      <ul>
        {details.prerequisites.map((prerequisite) => (
          <li key={prerequisite.name}>
            <code>{prerequisite.name}</code>: {t(prerequisite.satisfied
              ? "settings.forecastHistory.configured" : "settings.forecastHistory.missing")}
          </li>
        ))}
      </ul>
    </details>
  );
}
