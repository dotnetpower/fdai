import type { RecordedResourceStates, RecordedStateAxis } from "../recorded-resource-state";
import { getLocale } from "../i18n";
import { recordedText } from "./recorded-state-text";
import "./recorded-state-facts.css";

function time(value: string | null): string {
  return value === null
    ? recordedText("unknown")
    : new Date(value).toLocaleString(getLocale() === "ko" ? "ko-KR" : "en-US");
}

/** Both resource screens show the same source values and qualifications, never a computed verdict. */
export function RecordedStateFacts({ states }: { readonly states: RecordedResourceStates }) {
  return <section class="recorded-state-facts">
    <h4>{recordedText("heading")}</h4>
    <p>{recordedText("boundary")}</p>
    {(["operational", "provisioning", "availability"] as const).map((axis: RecordedStateAxis) => {
      const fact = states[axis];
      return <div class="recorded-state-axis" data-state-axis={axis} key={axis}>
        <div><span>{recordedText(axis)}</span><strong>{fact.value ?? recordedText("missing")}</strong></div>
        <span class="recorded-state-freshness">{recordedText("freshness")}: {recordedText(fact.freshness)}</span>
        <details><summary>{recordedText("evidence")}</summary><dl>
          <div><dt>{recordedText("source")}</dt><dd>{fact.source_path ?? recordedText("unknown")}</dd></div>
          <div><dt>{recordedText("observed")}</dt><dd>{time(fact.observed_at)}</dd></div>
          <div><dt>{recordedText("recorded")}</dt><dd>{time(fact.recorded_at)}</dd></div>
          <div><dt>{recordedText("completeness")}</dt><dd>{fact.completeness === null ? recordedText("unknown") : `${Math.round(fact.completeness * 100)}%`}</dd></div>
          {fact.conflicts.length > 0 && <div><dt>{recordedText("conflicts")}</dt><dd>{fact.conflicts.join(", ")}</dd></div>}
          {fact.reason && <div><dt>{recordedText("reason")}</dt><dd>{fact.reason}</dd></div>}
        </dl></details>
      </div>;
    })}
  </section>;
}
