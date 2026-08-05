import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const view = readFileSync(
  new URL("./composer-attachments.view.tsx", import.meta.url),
  "utf8",
);
const styles = readFileSync(new URL("../styles.css", import.meta.url), "utf8");

describe("composer image attachment presentation", () => {
  it("uses a thumbnail-only image branch with a large shared tooltip preview", () => {
    const imageBranch = view.slice(
      view.indexOf("{entry.previewUrl ? ("),
      view.indexOf(") : (", view.indexOf("{entry.previewUrl ? (")),
    );

    expect(imageBranch).toContain("deck-attach-preview-layer");
    expect(imageBranch).toContain("deck-attach-thumb is-image");
    expect(imageBranch).not.toContain("deck-attach-name");
    expect(imageBranch).not.toContain("deck-attach-meta");
    expect(imageBranch).not.toContain("deck-attach-status");
    expect(styles).toContain(".deck-attach-item.is-image-preview");
    expect(view).toContain('variant="image-preview"');
    expect(styles).toContain("width: min(420px, calc(100vw - 32px))");
    expect(styles).toContain(
      ".deck-attach-item.is-image-preview > .tooltip-anchor:first-child",
    );
    expect(styles).toMatch(
      /\.deck-attach-item\.is-image-preview \.deck-attach-thumb\s*\{[^}]*cursor:\s*default;/,
    );
    expect(styles).not.toContain("cursor: zoom-in");
  });

  it("shares the neutral top-edge shimmer and reduced-motion contract", () => {
    expect(styles).toContain(
      ".is-content-updated::after,\n.deck-attach-item.is-scanning::after",
    );
    expect(styles).toContain("animation: content-update-top-edge 1.35s");
    expect(styles).toContain(
      ".is-content-updated::after,\n  .deck-attach-item.is-scanning::after { animation: none; }",
    );
  });
});
