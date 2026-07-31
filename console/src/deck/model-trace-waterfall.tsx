import { t } from "../i18n";
import type { ModelTrace, ModelTraceCall } from "./backend";

const MIN_BAR_PCT = 2.5;
const SINGLETON_SPAN_MS = 1000;

export interface ModelTraceBar {
  readonly call: ModelTraceCall;
  readonly leftPct: number;
  readonly widthPct: number;
}

export function buildModelTraceBars(trace: ModelTrace): readonly ModelTraceBar[] {
  if (trace.calls.length === 0) return [];
  const sorted = [...trace.calls].sort(
    (left, right) => Date.parse(left.started_at) - Date.parse(right.started_at),
  );
  const startMs = Date.parse(sorted[0]!.started_at);
  const endMs = Math.max(
    ...sorted.map((call) => Date.parse(call.completed_at ?? call.started_at)),
  );
  const actualSpanMs = Math.max(0, endMs - startMs);
  const tailMs = actualSpanMs > 0 ? actualSpanMs * 0.1 : SINGLETON_SPAN_MS;
  const denominator = actualSpanMs + tailMs;
  return sorted.map((call) => {
    const callStart = Date.parse(call.started_at);
    const callEnd = Date.parse(call.completed_at ?? call.started_at);
    const leftPct = ((callStart - startMs) / denominator) * 100;
    const rawWidth = ((Math.max(callStart, callEnd) - callStart) / denominator) * 100;
    return {
      call,
      leftPct,
      widthPct: Math.min(Math.max(rawWidth, MIN_BAR_PCT), 100 - leftPct),
    };
  });
}

export function ModelTraceWaterfall({ trace }: { readonly trace?: ModelTrace }) {
  if (!trace) {
    return (
      <section class="deck-model-trace is-empty" aria-label={t("deck.modelTrace.title")}>
        <header><h4>{t("deck.modelTrace.title")}</h4></header>
        <p>{t("deck.modelTrace.notCaptured")}</p>
      </section>
    );
  }
  const bars = buildModelTraceBars(trace);
  return (
    <section class="deck-model-trace" aria-label={t("deck.modelTrace.title")}>
      <header class="deck-model-trace-head">
        <div>
          <h4>{t("deck.modelTrace.title")}</h4>
          <p>{t("deck.modelTrace.redactionNotice")}</p>
        </div>
        <span>{t("deck.modelTrace.callCount", { count: trace.calls.length })}</span>
      </header>
      {trace.omitted_calls > 0 ? (
        <p class="deck-model-trace-omitted">
          {t("deck.modelTrace.omitted", { count: trace.omitted_calls })}
        </p>
      ) : null}
      <ol class="deck-model-trace-lanes">
        {bars.map(({ call, leftPct, widthPct }, index) => (
          <li key={call.call_id} data-status={call.status}>
            <details>
              <summary>
                <span class="deck-model-trace-index">{String(index + 1).padStart(2, "0")}</span>
                <span class="deck-model-trace-model">{call.model}</span>
                <span class="deck-model-trace-kind">{call.kind}</span>
                <span class="deck-model-trace-bar" aria-hidden="true">
                  <span style={{ left: `${leftPct}%`, width: `${widthPct}%` }} />
                </span>
                <time>{formatClock(call.started_at)}</time>
                <span class="deck-model-trace-duration">
                  {call.duration_ms === null
                    ? t("deck.modelTrace.incomplete")
                    : formatDuration(call.duration_ms)}
                </span>
              </summary>
              <div class="deck-model-trace-detail">
                <TraceHash label={t("deck.modelTrace.requestHash")} value={call.request.sha256} />
                <ol class="deck-model-trace-messages">
                  {call.request.messages.map((message, messageIndex) => (
                    <li key={`${call.call_id}-request-${messageIndex}`}>
                      <span>{message.role}</span>
                      <pre><code>{message.content}</code></pre>
                    </li>
                  ))}
                </ol>
                {call.response ? (
                  <section class="deck-model-trace-response">
                    <h5>{t("deck.modelTrace.response")}</h5>
                    <TraceHash label={t("deck.modelTrace.responseHash")} value={call.response.sha256} />
                    <pre><code>{call.response.content}</code></pre>
                  </section>
                ) : (
                  <p class="deck-model-trace-missing">{t("deck.modelTrace.responseMissing")}</p>
                )}
                <div class="deck-model-trace-meta">
                  {call.usage ? (
                    <dl>
                      {Object.entries(call.usage).map(([key, value]) => (
                        <div key={key}><dt>{key}</dt><dd>{value}</dd></div>
                      ))}
                    </dl>
                  ) : null}
                  {call.redactions.length > 0 ? (
                    <ul aria-label={t("deck.modelTrace.redactions")}>
                      {call.redactions.map((redaction) => (
                        <li key={redaction.rule}>{redaction.rule} x{redaction.replacements}</li>
                      ))}
                    </ul>
                  ) : null}
                </div>
              </div>
            </details>
          </li>
        ))}
      </ol>
    </section>
  );
}

function TraceHash({ label, value }: { readonly label: string; readonly value: string }) {
  return <p class="deck-model-trace-hash"><span>{label}</span><code>{value}</code></p>;
}

function formatClock(value: string): string {
  return new Date(value).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    fractionalSecondDigits: 3,
  });
}

function formatDuration(durationMs: number): string {
  return durationMs < 1000 ? `${durationMs} ms` : `${(durationMs / 1000).toFixed(2)} s`;
}
