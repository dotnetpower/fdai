import type { PresentationArtifact, PresentationBlock } from "./backend-types";
import { PresentationModuleView } from "./presentation-modules/registry";
import "./structured-reply.css";

export function StructuredReply({ artifact }: { readonly artifact: PresentationArtifact }) {
  return (
    <div class="deck-presentation" data-layout={artifact.layout} data-schema={artifact.schemaVersion}>
      {artifact.blocks.map((block) => (
        <PresentationBlockView key={block.slotId} block={block} />
      ))}
    </div>
  );
}

function PresentationBlockView({ block }: { readonly block: PresentationBlock }) {
  const body = <PresentationModuleView block={block} />;
  if (block.collapsed) {
    return (
      <details class="deck-presentation-block is-collapsible" data-emphasis={block.emphasis}>
        <summary>{block.title}</summary>
        <div class="deck-presentation-block-body">{body}</div>
      </details>
    );
  }
  const headingId = `deck-presentation-${block.slotId}`;
  return (
    <section
      class="deck-presentation-block"
      data-kind={block.kind}
      data-emphasis={block.emphasis}
      aria-labelledby={headingId}
    >
      <h4 id={headingId}>{block.title}</h4>
      {body}
    </section>
  );
}
