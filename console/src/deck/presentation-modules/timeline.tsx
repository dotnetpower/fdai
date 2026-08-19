import { getLocale } from "../../i18n";
import { presentationTimestamp } from "../presentation-value";
import type { PresentationModuleProps } from "./types";
import { ExactTableDisclosure } from "./charts";

export function TimelineModule({ block }: PresentationModuleProps) {
  if (block.kind !== "timeline") return null;
  return (
    <div class="deck-presentation-accessible-chart">
      <p>{block.data.description}</p>
      <ol class="deck-presentation-timeline">
        {block.data.items.map((item) => {
          const timestamp = presentationTimestamp(
            item.timestamp,
            getLocale() === "ko" ? "ko-KR" : "en-US",
          );
          return (
            <li key={item.timestamp}>
              <time dateTime={item.timestamp}>
                {timestamp ? `${timestamp.date} ${timestamp.time}` : item.timestamp}
              </time>
              <span>{item.label}</span>
            </li>
          );
        })}
      </ol>
      <ExactTableDisclosure data={block.data.exactTable} />
    </div>
  );
}
