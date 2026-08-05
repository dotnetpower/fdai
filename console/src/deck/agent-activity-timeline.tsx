import { tForLocale } from "../i18n";
import { Tooltip } from "../components/tooltip";
import type { AgentActivityItem } from "./agent-activity-block";

export function AgentActivityTimeline({
  items,
  locale,
}: {
  readonly items: readonly AgentActivityItem[];
  readonly locale: "en" | "ko";
}) {
  const localeTag = locale === "ko" ? "ko-KR" : "en-US";
  return (
    <section class="deck-agent-activity" aria-label={tForLocale(locale, "deck.rich.agentActivity.title")}>
      <header>
        <h4>{tForLocale(locale, "deck.rich.agentActivity.title")}</h4>
        <span>{tForLocale(locale, "deck.rich.agentActivity.count", { count: items.length })}</span>
      </header>
      <ol>
        {items.map((item, index) => (
          <li key={`${item.agent}-${item.event}-${item.at}`}>
            <span
              class="deck-agent-activity-icon"
              style={{ "--deck-agent-icon": agentIconUrl(item.agent) }}
              aria-hidden="true"
            />
            <span class="deck-agent-activity-copy">
              <span class="deck-agent-activity-heading">
                <strong>{item.agent}</strong>
                <span class="deck-agent-activity-event">
                  {activityEventLabel(locale, item.event)}
                </span>
                {index === 0 ? (
                  <span class="deck-agent-activity-latest">
                    {tForLocale(locale, "deck.rich.agentActivity.latest")}
                  </span>
                ) : null}
              </span>
              <span class="deck-agent-activity-meta">
                <code>{item.event}</code>
                <Tooltip content={item.at}>
                  <time dateTime={item.at}>
                    {new Date(item.at).toLocaleString(localeTag, {
                      dateStyle: "medium",
                      timeStyle: "medium",
                    })}
                  </time>
                </Tooltip>
              </span>
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}

function activityEventLabel(locale: "en" | "ko", event: string): string {
  if (event === "rca.hypothesis") {
    return tForLocale(locale, "deck.rich.agentActivity.event.rcaHypothesis");
  }
  if (event === "incident.open") {
    return tForLocale(locale, "deck.rich.agentActivity.event.incidentOpen");
  }
  return tForLocale(locale, "deck.rich.agentActivity.event.recorded");
}

function agentIconUrl(agent: string): string {
  const base = typeof import.meta.env.BASE_URL === "string" ? import.meta.env.BASE_URL : "/";
  return `url("${base}agent-icons/${agent.toLowerCase()}.svg")`;
}
