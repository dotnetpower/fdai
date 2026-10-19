import type { ForecastHistoryDetails } from "./settings-runtime.model";
import { settingsIntegrationsText as text } from "./settings-integrations.i18n";

export function ForecastHistorySourceDetails({ details }: {
  readonly details: ForecastHistoryDetails | undefined;
}) {
  if (details === undefined) return null;
  return (
    <details>
      <summary>{text("forecastHistory.details")}</summary>
      <p class="muted">{text("forecastHistory.boundary")}</p>
      <dl>
        {details.sources.map((source) => (
          <div key={source.kind}>
            <dt>{text(`forecastHistory.kinds.${source.kind}`)}</dt>
            <dd>
              <p>{text(source.bound
                ? "forecastHistory.bound" : "forecastHistory.unbound")}</p>
              <p>{text(source.positiveCheckpoint
                ? "forecastHistory.checkpointPresent"
                : "forecastHistory.checkpointMissing")}</p>
              <small class="muted">{source.reader}: {source.limitation}</small>
            </dd>
          </div>
        ))}
      </dl>
      <h5>{text("forecastHistory.prerequisites")}</h5>
      <ul>
        {details.prerequisites.map((prerequisite) => (
          <li key={prerequisite.name}>
            <code>{prerequisite.name}</code>: {text(prerequisite.satisfied
              ? "forecastHistory.configured" : "forecastHistory.missing")}
          </li>
        ))}
      </ul>
    </details>
  );
}
