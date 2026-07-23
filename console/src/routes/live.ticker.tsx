import { Tooltip } from "../components/tooltip";
import type { LiveStageEvent } from "../hooks/use-live-stream";
import { routeHref } from "../router";
import { t } from "./i18n/live";
import { shortTime } from "./live.model";

export function liveTraceHref(correlationId: string): string {
  return routeHref("trace", { params: { correlation: correlationId } });
}

function decisionLabel(decision: string): string {
  const key = `live.decision.${decision}`;
  const label = t(key);
  return label === key ? decision : label;
}

export function LiveTicker({
  events,
  collapsed,
  paused,
  onToggleCollapse,
}: {
  readonly events: readonly LiveStageEvent[];
  readonly collapsed: boolean;
  readonly paused: boolean;
  readonly onToggleCollapse: () => void;
}) {
  return (
    <aside
      class={`live-ticker live-ticker-panel${collapsed ? " live-ticker-collapsed" : ""}${paused ? " live-ticker-paused" : ""}`}
      aria-label={t("live.outcomes.ariaLabel")}
    >
      <header class="live-ticker-header">
        <h3>
          {t("live.outcomes.title")} <span class="muted">- {t("live.outcomes.count", { count: events.length })}</span>
        </h3>
        <div class="live-ticker-controls" role="toolbar" aria-label={t("live.outcomes.toolbarLabel")}>
          <Tooltip content={collapsed ? t("live.outcomes.expand") : t("live.outcomes.collapse")}>
            <button
              type="button"
              class="live-ticker-btn"
              onClick={onToggleCollapse}
              aria-expanded={!collapsed}
              aria-label={collapsed ? t("live.outcomes.expand") : t("live.outcomes.collapse")}
            >
              {collapsed ? (
                <svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true">
                  <path d="M2 8 L6 4 L10 8" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />
                </svg>
              ) : (
                <svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true">
                  <path d="M2 4 L6 8 L10 4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />
                </svg>
              )}
            </button>
          </Tooltip>
        </div>
      </header>
      {collapsed ? null : (
        <ol>
          {events.map((event, index) => {
            const tier = (event.detail?.tier as string | undefined) ?? "abstain";
            const gate = event.detail?.gate_decision as string | undefined;
            const rule = event.detail?.rule as string | undefined;
            const action = event.detail?.action_type as string | undefined;
            const scope = event.detail?.scope as string | undefined;
            const outcome = event.detail?.outcome as string | undefined;
            return (
              <li key={`${event.event_id}-${event.stage}-${event.phase}-${event.ts}-${index}`}>
                <span class="muted">{shortTime(event.ts)}</span>
                <span class={`live-tier live-tier-${tier}`}>
                  {tier === "abstain" ? "N/A" : tier.toUpperCase()}
                </span>
                <Tooltip content={event.correlation_id}>
                  <a href={liveTraceHref(event.correlation_id)}>
                    <code>{event.event_id.slice(0, 8)}</code>
                  </a>
                </Tooltip>
                {action ? <strong>{action}</strong> : null}
                {scope ? <span class="live-ticker-scope">@{scope}</span> : null}
                {rule && rule !== action ? <span class="muted">({rule})</span> : null}
                {gate ? <span class={`live-gate live-gate-${gate}`}>{decisionLabel(gate)}</span> : null}
                {outcome && outcome !== gate ? (
                  <span class={`live-ticker-tail ${outcome}`}>{outcome}</span>
                ) : null}
              </li>
            );
          })}
          {events.length === 0 ? <li class="muted">{t("live.outcomes.waiting")}</li> : null}
        </ol>
      )}
      <footer class="live-ticker-footer">
        <a href={routeHref("audit")}>{t("live.outcomes.viewAll")}</a>
      </footer>
    </aside>
  );
}
