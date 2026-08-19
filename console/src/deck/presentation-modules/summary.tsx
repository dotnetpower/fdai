import { t } from "../../i18n";
import { presentationDuration, presentationTimestamp } from "../presentation-value";
import type { PresentationModuleProps } from "./types";
import { PresentationValue, presentationValueKind } from "./value";

export function SummaryModule({ block }: PresentationModuleProps) {
  if (block.kind !== "summary") return null;
  const timestamps = block.data.items
    .map((item) => item.value)
    .filter((value) => presentationTimestamp(value) !== null);
  const observedSpan = timestamps.length >= 2
    ? presentationDuration(timestamps[0]!, timestamps[timestamps.length - 1]!)
    : null;
  return (
    <dl class="deck-presentation-summary">
      {block.data.items.map((item) => (
        <div
          key={item.label}
          data-tone={item.tone}
          data-value-kind={presentationValueKind(item.label, item.value)}
        >
          <dt>{item.label}</dt>
          <dd><PresentationValue value={item.value} label={item.label} /></dd>
        </div>
      ))}
      {observedSpan ? (
        <div class="deck-presentation-derived" data-value-kind="duration">
          <dt>{t("deck.presentation.observedSpan")}</dt>
          <dd>{observedSpan}</dd>
        </div>
      ) : null}
    </dl>
  );
}
