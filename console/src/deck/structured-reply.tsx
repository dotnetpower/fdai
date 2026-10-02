import type { PresentationArtifact, PresentationBlock } from "./backend-types";
import { PresentationModuleView } from "./presentation-modules/registry";
import "./structured-reply.css";

export function StructuredReply({ artifact }: { readonly artifact: PresentationArtifact }) {
  return (
    <div class="deck-presentation" data-layout={artifact.layout} data-schema={artifact.schemaVersion}>
      {artifact.assembly ? <PresentationAssemblyView assembly={artifact.assembly} /> : null}
      {artifact.blocks.map((block) => (
        <PresentationBlockView key={block.slotId} block={block} />
      ))}
    </div>
  );
}

function PresentationAssemblyView({
  assembly,
}: {
  readonly assembly: NonNullable<PresentationArtifact["assembly"]>;
}) {
  return (
    <details class="deck-presentation-assembly">
      <summary>
        <strong>{assembly.label}</strong>
        <span>§ {assembly.sectionCount}</span>
        <code>{assembly.digest.slice("sha256:".length, "sha256:".length + 12)}</code>
      </summary>
      <ul>
        {assembly.inputKinds.map((kind) => (
          <li key={kind}><code>{kind}</code></li>
        ))}
      </ul>
    </details>
  );
}

export function presentationBlockCanCollapse(block: PresentationBlock): boolean {
  const critical = block.kind === "callout" && (
    block.data.tone === "attention" || block.data.tone === "warning"
  );
  return block.collapsed && block.slotId !== "limitations" && !critical;
}

function PresentationBlockView({ block }: { readonly block: PresentationBlock }) {
  const body = <PresentationModuleView block={block} />;
  if (presentationBlockCanCollapse(block)) {
    return (
      <details
        class="deck-presentation-block is-collapsible"
        data-kind={block.kind}
        data-slot={block.slotId}
        data-emphasis={block.emphasis}
      >
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
      data-slot={block.slotId}
      data-emphasis={block.emphasis}
      aria-labelledby={headingId}
    >
      <h4 id={headingId}>{block.title}</h4>
      {body}
    </section>
  );
}
