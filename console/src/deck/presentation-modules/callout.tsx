import type { PresentationBlock } from "../backend-types";
import type { PresentationModuleProps } from "./types";

export function calloutRequiresAttention(block: PresentationBlock): boolean {
  if (block.kind !== "callout") return false;
  return block.data.tone === "attention" || block.data.tone === "warning";
}

/** Attention and warning lines state limits and gaps, so they read as the conversation layer's
 *  evidence note; a neutral or positive callout is context and stays a quiet note. */
export function CalloutModule({ block }: PresentationModuleProps) {
  if (block.kind !== "callout") return null;
  const lines = <ul>{block.data.lines.map((line) => <li key={line}>{line}</li>)}</ul>;
  if (!calloutRequiresAttention(block)) {
    return (
      <div class="deck-presentation-callout cs-deck-answer-note" data-tone={block.data.tone}>
        {lines}
      </div>
    );
  }
  return (
    <div
      class="deck-presentation-callout cs-deck-evidence-note"
      data-tone={block.data.tone}
      role="note"
    >
      <span class="cs-deck-evidence-note-mark" aria-hidden="true">!</span>
      {lines}
    </div>
  );
}
