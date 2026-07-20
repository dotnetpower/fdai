import { observationSourceLabel } from "../hooks/observation-source";
import { formatConsoleTimestamp } from "../time-format";
import { routeHref } from "../router";
import {
  isLiveWorkActivity,
  type LiveAgentActivityEvent,
} from "./agents.model";

const DISPLAY_LIMIT = 20;

interface Props {
  readonly events: readonly LiveAgentActivityEvent[];
  readonly selectedAgent: string | null;
}

export function LiveActivityJournal({ events, selectedAgent }: Props) {
  const visible = events.slice(0, DISPLAY_LIMIT);
  const workCount = events.filter(isLiveWorkActivity).length;
  const subject = selectedAgent ?? "the Pantheon";

  return (
    <section class="aa-live-journal" aria-labelledby="aa-live-journal-title">
      <header>
        <div>
          <span>THIS BROWSER SESSION</span>
          <h3 id="aa-live-journal-title">Observed live activity</h3>
        </div>
        <span>{events.length} frame{events.length === 1 ? "" : "s"} · {workCount} work event{workCount === 1 ? "" : "s"}</span>
      </header>

      {workCount === 0 ? (
        <p class="aa-live-waiting">
          <strong>No work event observed yet</strong>
          <span>{subject} is connected and waiting for an ingress event. Runtime heartbeats below prove connectivity but are not operational work.</span>
        </p>
      ) : null}

      {visible.length === 0 ? (
        <p class="aa-live-empty">No runtime frame has arrived during this browser session.</p>
      ) : (
        <ol class="aa-live-events">
          {visible.map((event, index) => (
            <li key={`${event.kind}:${event.ts}:${event.agent}:${event.correlationId ?? "none"}:${index}`}>
              <time dateTime={event.ts}>{formatConsoleTimestamp(event.ts)}</time>
              <span class={`aa-live-kind ${isLiveWorkActivity(event) ? "is-work" : ""}`}>
                {eventKindLabel(event)}
              </span>
              <div>
                <strong>{event.agents.join(" -> ") || event.agent}</strong>
                <span>{event.summary}</span>
                {event.detail && event.detail !== event.summary ? <small>{event.detail}</small> : null}
              </div>
              <div class="aa-live-evidence">
                <span>{observationSourceLabel(event.source)}</span>
                {event.correlationId ? (
                  <a href={routeHref("trace", { params: { correlation: event.correlationId } })}>
                    {event.correlationId}
                  </a>
                ) : <span>No correlation</span>}
              </div>
            </li>
          ))}
        </ol>
      )}
      {events.length > DISPLAY_LIMIT ? (
        <p class="aa-live-retention">Showing the newest {DISPLAY_LIMIT} of {events.length} in-memory frames.</p>
      ) : null}
    </section>
  );
}

function eventKindLabel(event: LiveAgentActivityEvent): string {
  if (event.kind === "incident.ticket") return "Incident";
  if (event.kind === "conversation.turn") return "Handoff";
  return event.state ?? "State";
}
