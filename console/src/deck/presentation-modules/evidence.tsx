import type { PresentationModuleProps } from "./types";
import { PresentationValue } from "./value";

export function EvidenceModule({ block }: PresentationModuleProps) {
  if (block.kind !== "evidence") return null;
  return (
    <dl class="deck-presentation-evidence">
      {block.data.items.map((item) => (
        <div key={item.label}>
          <dt>{item.label}</dt>
          <dd><PresentationValue value={item.value} label={item.label} /></dd>
        </div>
      ))}
    </dl>
  );
}
