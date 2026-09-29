import { t } from "../i18n";
import { consoleDateTimeLocale } from "../time-format";
import type { ModelTrace, ModelTraceCall, ModelTraceMessage } from "./backend";
import { RunTrack } from "./conversation-execution-timeline-view";
import { formatJsonValue, JsonCodeBlock } from "./json-code-block";

const MIN_BAR_PCT = 2.5;
const SINGLETON_SPAN_MS = 1000;

export interface ModelTraceBar {
  readonly call: ModelTraceCall;
  readonly leftPct: number;
  readonly widthPct: number;
}

export interface ModelTraceMessageGroup {
  readonly role: ModelTraceMessage["role"];
  readonly contents: readonly string[];
}

export type ModelTracePresentationState = "disabled" | "not-captured" | "no-calls" | "calls";

export function modelTracePresentationState(
  trace?: ModelTrace,
  captureEnabled = true,
): ModelTracePresentationState {
  if (!captureEnabled) return "disabled";
  if (!trace) return "not-captured";
  return trace.calls.length === 0 ? "no-calls" : "calls";
}

export function groupModelTraceMessages(
  messages: readonly ModelTraceMessage[],
): readonly ModelTraceMessageGroup[] {
  const groups: ModelTraceMessageGroup[] = [];
  for (const message of messages) {
    const previous = groups.at(-1);
    if (message.role === "system" && previous?.role === "system") {
      groups[groups.length - 1] = {
        role: "system",
        contents: [...previous.contents, message.content],
      };
    } else {
      groups.push({ role: message.role, contents: [message.content] });
    }
  }
  return groups;
}

export function formatModelTraceMessageGroup(group: ModelTraceMessageGroup): {
  readonly text: string;
  readonly format: "json" | "text";
} {
  const formatted = group.contents.map((content) =>
    formatJsonValue(content, { expandNestedStrings: true })
  );
  return {
    text: formatted.map((item) => item.text).join("\n\n"),
    format: formatted.length === 1 && formatted[0]?.isJson ? "json" : "text",
  };
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

/** The model provider waterfall on the conversation layer's trace roles: one lane per captured call
 *  with its model, kind, position, start, and duration, opening in place to the redacted request,
 *  prompt manifest, response, usage, and applied redactions. */
export function ModelTraceWaterfall({
  trace,
  captureEnabled = true,
}: {
  readonly trace?: ModelTrace;
  readonly captureEnabled?: boolean;
}) {
  const presentationState = modelTracePresentationState(trace, captureEnabled);
  if (presentationState === "disabled" || presentationState === "not-captured") {
    return (
      <section class="cs-model-trace is-empty" aria-label={t("deck.modelTrace.title")}>
        <header class="cs-model-trace-head">
          <h4 class="cs-model-trace-title">{t("deck.modelTrace.title")}</h4>
        </header>
        <div class="cs-model-trace-note" role="note">
          {presentationState === "disabled" ? (
            <>
              <strong>{t("deck.modelTrace.captureDisabledTitle")}</strong>
              <p>{t("deck.modelTrace.captureDisabledDetail")}</p>
            </>
          ) : (
            <p>{t("deck.modelTrace.notCaptured")}</p>
          )}
        </div>
      </section>
    );
  }
  if (!trace) return null;
  const bars = buildModelTraceBars(trace);
  return (
    <section class="cs-model-trace" aria-label={t("deck.modelTrace.title")}>
      <header class="cs-model-trace-head">
        <div>
          <h4 class="cs-model-trace-title">{t("deck.modelTrace.title")}</h4>
          <p class="cs-model-trace-notice">{t("deck.modelTrace.redactionNotice")}</p>
        </div>
        <span class="cs-model-trace-count">
          {t("deck.modelTrace.callCount", { count: trace.calls.length })}
        </span>
      </header>
      {trace.omitted_calls > 0 ? (
        <p class="cs-model-trace-notice">
          {t("deck.modelTrace.omitted", { count: trace.omitted_calls })}
        </p>
      ) : null}
      {presentationState === "no-calls" ? (
        <div class="cs-model-trace-note" role="note">
          <strong>{t("deck.modelTrace.noCallsTitle")}</strong>
          <p>{t("deck.modelTrace.noCallsDetail")}</p>
        </div>
      ) : (
        <ol class="cs-model-trace-lanes">
          {bars.map(({ call, leftPct, widthPct }, index) => (
            <li key={call.call_id} class="cs-model-trace-lane" data-status={call.status}>
              <details>
                <summary class="cs-model-trace-lane-summary">
                  <span class="cs-model-trace-index">{String(index + 1).padStart(2, "0")}</span>
                  <span class="cs-model-trace-model">{call.model}</span>
                  <span class="cs-model-trace-kind">{call.kind}</span>
                  <RunTrack leftPct={leftPct} widthPct={widthPct} />
                  <time class="cs-model-trace-clock" dateTime={call.started_at}>
                    {formatClock(call.started_at)}
                  </time>
                  <span class="cs-model-trace-duration">
                    {call.duration_ms === null
                      ? t("deck.modelTrace.incomplete")
                      : formatDuration(call.duration_ms)}
                  </span>
                  <span class="cs-run-chevron" aria-hidden="true" />
                </summary>
                <ModelTraceDetail call={call} />
              </details>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function ModelTraceDetail({ call }: { readonly call: ModelTraceCall }) {
  const manifest = call.prompt_manifest;
  return (
    <div class="cs-model-trace-detail">
      <TraceHash label={t("deck.modelTrace.requestHash")} value={call.request.sha256} />
      {manifest ? (
        <section class="cs-run-payload" aria-label={t("deck.modelTrace.promptManifest")}>
          <strong>{t("deck.modelTrace.promptManifest")}</strong>
          <TraceHash label={t("deck.modelTrace.systemHash")} value={manifest.system_text_sha256} />
          <dl class="cs-run-facts">
            <div>
              <dt>{t("deck.modelTrace.profile")}</dt>
              <dd>{manifest.profile_id ?? t("deck.modelTrace.noProfile")}</dd>
            </div>
            {manifest.profile_digest ? (
              <div>
                <dt>{t("deck.modelTrace.profileDigest")}</dt>
                <dd><code>{manifest.profile_digest}</code></dd>
              </div>
            ) : null}
            <div>
              <dt>{t("deck.modelTrace.tokenBudget")}</dt>
              <dd>{manifest.token_estimate} / {manifest.system_token_budget ?? "-"}</dd>
            </div>
          </dl>
          <ol class="cs-model-trace-layers" aria-label={t("deck.modelTrace.promptLayers")}>
            {manifest.layers.map((layer) => (
              <li key={`${layer.id}-${layer.version}-${layer.layer}`}>
                <code>{layer.layer}</code>
                <span><span class="sr-only">{t("deck.modelTrace.layerIdentity")}: </span>{layer.id} v{layer.version}</span>
                <span><span class="sr-only">{t("deck.modelTrace.layerTokens")}: </span>{layer.token_estimate}</span>
              </li>
            ))}
          </ol>
        </section>
      ) : null}
      <ol class="cs-model-trace-messages">
        {groupModelTraceMessages(call.request.messages).map((group, groupIndex) => (
          <li key={`${call.call_id}-request-${groupIndex}`}>
            <strong class="cs-model-trace-role">{group.role}</strong>
            <TraceMessageContent group={group} />
          </li>
        ))}
      </ol>
      {call.response ? (
        <section class="cs-run-payload" aria-label={t("deck.modelTrace.response")}>
          <strong>{t("deck.modelTrace.response")}</strong>
          <TraceHash label={t("deck.modelTrace.responseHash")} value={call.response.sha256} />
          <JsonCodeBlock value={call.response.content} expandNestedStrings />
        </section>
      ) : (
        <p class="cs-model-trace-notice">{t("deck.modelTrace.responseMissing")}</p>
      )}
      {call.usage || call.redactions.length > 0 ? (
        <dl class="cs-run-facts">
          {Object.entries(call.usage ?? {}).map(([key, value]) => (
            <div key={key}><dt>{key}</dt><dd>{value}</dd></div>
          ))}
          {call.redactions.length > 0 ? (
            <div>
              <dt>{t("deck.modelTrace.redactions")}</dt>
              <dd>
                {call.redactions
                  .map((redaction) => `${redaction.rule} x${redaction.replacements}`)
                  .join(", ")}
              </dd>
            </div>
          ) : null}
        </dl>
      ) : null}
    </div>
  );
}

/** Each message content keeps its own code block, so a JSON context message is highlighted as JSON
 *  and a grouped system prompt stays readable as text. */
function TraceMessageContent({ group }: { readonly group: ModelTraceMessageGroup }) {
  return (
    <>
      {group.contents.map((content, index) => (
        <JsonCodeBlock key={index} value={formatJsonValue(content, { expandNestedStrings: true }).text} />
      ))}
    </>
  );
}

function TraceHash({ label, value }: { readonly label: string; readonly value: string }) {
  return <p class="cs-model-trace-hash"><span>{label}</span><code>{value}</code></p>;
}

function formatClock(value: string): string {
  return new Date(value).toLocaleTimeString(consoleDateTimeLocale(), {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    fractionalSecondDigits: 3,
  });
}

function formatDuration(durationMs: number): string {
  return durationMs < 1000 ? `${durationMs} ms` : `${(durationMs / 1000).toFixed(2)} s`;
}
