import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";

const mock = readFileSync(
  fileURLToPath(new URL("../../../mocks/ui/blast-radius.html", import.meta.url)),
  "utf8",
);
const mockStyles = readFileSync(
  fileURLToPath(
    new URL(
      "../../../mocks/ui/assets/governance-evidence-workspace.css",
      import.meta.url,
    ),
  ),
  "utf8",
);
const route = readFileSync(
  fileURLToPath(new URL("../routes/blast-radius.tsx", import.meta.url)),
  "utf8",
);
const impactView = readFileSync(
  fileURLToPath(new URL("../routes/blast-radius-impact.tsx", import.meta.url)),
  "utf8",
);
const resourcePicker = readFileSync(
  fileURLToPath(
    new URL("../routes/blast-radius-resource-picker.tsx", import.meta.url),
  ),
  "utf8",
);
const styles = readFileSync(fileURLToPath(new URL("../styles.css", import.meta.url)), "utf8");

describe("Impact scope controls", () => {
  test("defines the complete control system in the mockup first", () => {
    expect(mock).toContain('class="fg-toolbar" data-fg-static-form');
    expect(mock.match(/class="fg-field"/g)).toHaveLength(3);
    expect(mock).toContain("<span>Target Resource</span>");
    expect(mock).toContain('type="search"');
    expect(mock).toContain('list="impact-resource-options"');
    expect(mock).toContain(
      '<button class="fg-button is-primary" type="submit">Simulate impact</button>',
    );
    expect(mockStyles).toContain(".cs-governance-evidence .fg-toolbar");
    expect(mockStyles).toContain(".cs-governance-evidence .fg-field input");
    expect(mockStyles).toContain(".cs-governance-evidence .fg-field select");
    expect(mockStyles).toContain(
      ".cs-governance-evidence .fg-toolbar .fg-button { width: 100%; }",
    );
  });

  test("maps the approved mockup controls into the production route", () => {
    expect(route).toContain('class="blast-readonly-banner"');
    expect(impactView).toContain('class="blast-summary-metrics"');
    expect(route).toContain('class="impact-query-panel"');
    expect(route).toContain('class="impact-query-input"');
    expect(route).toContain('class="impact-query-check-box"');
    expect(route).toContain('class="btn primary impact-query-submit"');
    expect(route).toContain("<ImpactResourcePicker");
    expect(resourcePicker).toContain("<SearchableSelect");
    expect(resourcePicker).toContain('client.panel<unknown>("/ontology/instances", params)');
    expect(resourcePicker).toContain('class="impact-resource-direct"');
    expect(resourcePicker).toContain("onSelect(resource.id)");
    expect(impactView).toContain('class="blast-impact-graph"');
    expect(impactView).toContain('class="blast-impact-inspector"');
    expect(impactView).toContain('class="blast-traversal-contract"');
    expect(impactView).toContain(
      'aria-pressed={selectedNode.resource_id === node.resource_id}',
    );
    expect(route.match(/aria-pressed=\{view === "(impact|map|table)"\}/g)).toHaveLength(3);
    expect(route).toContain('header: t("ontology.blast.columnVerification")');
    expect(route).toContain("verification_status: e.verification_status");
    expect(route).toContain("evidence_status: e.evidence?.status ?? \"legacy\"");
    expect(route).toContain("evidence_source: e.evidence?.source");
    expect(route).toContain('key: "relationship_source_accounting_complete"');
    expect(route).toContain('key: "relationship_source_fully_materialized"');
    expect(route).not.toContain('key: "relationship_source_complete"');
    expect(styles).toContain(".blast-summary-metrics");
    expect(styles).toContain(".impact-resource-selection");
    expect(styles).toContain(".impact-resource-direct");
    expect(styles).toContain(".impact-query-check input:checked + .impact-query-check-box");
    expect(styles).toContain(".impact-query-submit:disabled");
    expect(styles).toContain(".impact-query-submit { width: 100%; }");
    expect(styles).toContain(".blast-impact-node[aria-pressed=\"true\"]");
    expect(styles).toContain(".blast-impact-inspector");
    expect(styles).toContain(".segmented-control button:focus-visible");
    expect(styles).toContain(".blast-radius-route .segmented-control button { min-height: 44px; }");
    expect(styles).toContain("@media (max-width: 1120px)");
    expect(styles).toContain(".blast-impact-layout { grid-template-columns: 1fr; }");
  });
});
