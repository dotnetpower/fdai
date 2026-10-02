import type { PresentationBlock } from "../backend-types";
import type { PresentationModuleProps } from "./types";

export function calloutRequiresAttention(block: PresentationBlock): boolean {
  if (block.kind !== "callout") return false;
  return block.data.tone === "attention" || block.data.tone === "warning";
}

export function CalloutModule({ block }: PresentationModuleProps) {
  if (block.kind !== "callout") return null;
  return (
    <ul class="deck-presentation-callout" data-tone={block.data.tone}>
      {block.data.lines.map((line) => <li key={line}>{line}</li>)}
    </ul>
  );
}
