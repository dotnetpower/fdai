import { Fragment } from "preact";
import type { PresentationArtifact, PresentationBlock } from "./backend-types";
import {
  PresentationModuleView,
  presentationBlockStaysExpanded,
} from "./presentation-modules/registry";
import "./structured-reply.css";

/** A typed presentation artifact on the conversation layer's answer block roles. A Markdown
 *  document is one document card; every other layout flows with the answer like the mock's
 *  operational brief, so a reply never stacks a second surface with its own chrome. */
export function StructuredReply({ artifact }: { readonly artifact: PresentationArtifact }) {
  const document = artifact.layout === "markdown_document";
  return (
    <div
      class={`deck-presentation${document ? " cs-deck-document" : ""}`}
      data-layout={artifact.layout}
      data-schema={artifact.schemaVersion}
    >
      {artifact.assembly ? <PresentationAssemblyView assembly={artifact.assembly} /> : null}
      {artifact.blocks.map((block) => (
        <PresentationBlockView key={block.slotId} block={block} document={document} />
      ))}
    </div>
  );
}

/** One quiet line names how the reply was assembled: its label, section count, governed input
 *  kinds, and the short assembly digest. */
function PresentationAssemblyView({
  assembly,
}: {
  readonly assembly: NonNullable<PresentationArtifact["assembly"]>;
}) {
  return (
    <p class="deck-presentation-assembly cs-deck-document-assembly">
      <strong>{assembly.label}</strong>
      <span aria-hidden="true">·</span>
      <span>§ {assembly.sectionCount}</span>
      {assembly.inputKinds.map((kind) => (
        <Fragment key={kind}>
          <span aria-hidden="true">·</span>
          <code>{kind}</code>
        </Fragment>
      ))}
      <span aria-hidden="true">·</span>
      <code>{assembly.digest.slice("sha256:".length, "sha256:".length + 12)}</code>
    </p>
  );
}

export function presentationBlockCanCollapse(block: PresentationBlock): boolean {
  return block.collapsed
    && block.slotId !== "limitations"
    && !presentationBlockStaysExpanded(block);
}

function PresentationBlockView({
  block,
  document,
}: {
  readonly block: PresentationBlock;
  readonly document: boolean;
}) {
  const body = <PresentationModuleView block={block} />;
  if (presentationBlockCanCollapse(block)) {
    return (
      <details
        class="deck-presentation-block is-collapsible cs-deck-disclosure"
        data-kind={block.kind}
        data-slot={block.slotId}
        data-emphasis={block.emphasis}
      >
        <summary class="cs-deck-disclosure-summary">
          <span class="cs-deck-disclosure-title">{block.title}</span>
          <span class="cs-run-chevron" aria-hidden="true" />
        </summary>
        <div class="deck-presentation-block-body cs-deck-disclosure-body">{body}</div>
      </details>
    );
  }
  const headingId = `deck-presentation-${block.slotId}`;
  return (
    <section
      class={`deck-presentation-block${document ? " cs-deck-document-section" : ""}`}
      data-kind={block.kind}
      data-slot={block.slotId}
      data-emphasis={block.emphasis}
      aria-labelledby={headingId}
    >
      <h4 id={headingId} class={document ? "cs-deck-document-heading" : "deck-presentation-block-title"}>
        {block.title}
      </h4>
      {body}
    </section>
  );
}
