import type { PresentationModuleProps } from "./types";

export function CalloutModule({ block }: PresentationModuleProps) {
  if (block.kind !== "callout") return null;
  return (
    <ul class="deck-presentation-callout" data-tone={block.data.tone}>
      {block.data.lines.map((line) => <li key={line}>{line}</li>)}
    </ul>
  );
}
