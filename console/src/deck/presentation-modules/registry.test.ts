import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import type { PresentationBlock } from "../backend-types";
import { presentationModuleRegistration } from "./registry";

const kinds: PresentationBlock["kind"][] = [
  "summary",
  "callout",
  "table",
  "threshold_table",
  "list",
  "coverage",
  "bar",
  "time_series",
  "comparison",
  "timeline",
  "evidence",
];

describe("presentation module registry", () => {
  it("registers one responsive and accessible module for every closed block kind", () => {
    for (const kind of kinds) {
      const registered = presentationModuleRegistration(kind);
      expect(registered.component).toBeTypeOf("function");
      expect(["reflow", "scroll", "stack"]).toContain(registered.responsivePolicy);
      expect(["description-list", "exact-table", "ordered-list"])
        .toContain(registered.accessibilityFallback);
    }
  });

  it("keeps the shell kind-neutral and pins chart accessibility CSS", () => {
    const shell = readFileSync(
      fileURLToPath(new URL("../structured-reply.tsx", import.meta.url)),
      "utf8",
    );
    const css = readFileSync(
      fileURLToPath(new URL("../structured-reply.css", import.meta.url)),
      "utf8",
    );
    const value = readFileSync(
      fileURLToPath(new URL("./value.tsx", import.meta.url)),
      "utf8",
    );

    expect(shell).toContain("PresentationModuleView");
    expect(shell).not.toMatch(/block\.kind\s*===/);
    expect(css).toContain(".deck-presentation-exact-values");
    expect(css).toContain(".deck-presentation-series-point:focus-visible");
    expect(css).toContain(".deck-presentation-comparison-track:focus-visible");
    expect(css).toContain("@media (prefers-reduced-motion: reduce)");
    expect(value).toContain("isOpaqueIdentifierField(columnKey, label)");
    expect(value).toContain('class="deck-presentation-identifier"');
    expect(css).toMatch(/\.deck-presentation-identifier \{[^}]*text-overflow: ellipsis;[^}]*white-space: nowrap;/s);
    expect(css).toContain(".deck-presentation-table td > .tooltip-anchor:focus-within");
  });
});
