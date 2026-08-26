import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const graphSource = readFileSync(
  fileURLToPath(new URL("./ontology-instance-graph.tsx", import.meta.url)),
  "utf8",
);
const instancesSource = readFileSync(
  fileURLToPath(new URL("./ontology-instances.tsx", import.meta.url)),
  "utf8",
);
const ontologySource = readFileSync(
  fileURLToPath(new URL("./ontology.tsx", import.meta.url)),
  "utf8",
);
const inspectorSource = readFileSync(
  fileURLToPath(new URL("./ontology-instances-inspector.tsx", import.meta.url)),
  "utf8",
);
const styles = readFileSync(
  fileURLToPath(new URL("./ontology-instances.css", import.meta.url)),
  "utf8",
);
const globalStyles = readFileSync(
  fileURLToPath(new URL("../styles.css", import.meta.url)),
  "utf8",
);

describe("Ontology Instances view controls", () => {
  it("keeps the instance controls inside the graph-first viewport", () => {
    expect(styles).toMatch(/\.ontology-instance-explorer\s*\{[^}]*gap:\s*10px/s);
    expect(styles).toMatch(/\.ontology-instance-toolbar\s*\{[^}]*min-height:\s*56px[^}]*padding:\s*8px\s*10px/s);
    expect(styles).toMatch(/\.ontology-instance-empty\s*\{[^}]*min-height:\s*min\(360px,\s*44vh\)/s);
    expect(instancesSource).not.toContain('class="ontology-instance-map-summary"');
    expect(styles).not.toContain(".ontology-instance-map-summary");
    expect(styles).toMatch(/\.ontology-instance-legend-dock\s*\{[^}]*position:\s*absolute[^}]*right:\s*12px[^}]*bottom:\s*12px[^}]*left:\s*12px[^}]*flex-wrap:\s*wrap/s);
    expect(styles).not.toMatch(/\.ontology-instance-legend-dock\s*\{[^}]*overflow-x:\s*auto/s);
    expect(styles).toMatch(/\.ontology-instance-graph-key i\.is-direction::after\s*\{[^}]*right:\s*-1px[^}]*border-left:\s*6px solid #637c93[^}]*content:\s*""/s);
    expect(styles).not.toContain('content: ">"');
    expect(styles).toMatch(/\.ontology-instance-graph-tools\s*\{[^}]*position:\s*absolute[^}]*top:\s*12px[^}]*right:\s*12px/s);
    expect(graphSource).toContain('class="ontology-instance-graph-viewport"');
    expect(graphSource).toContain('class="ontology-instance-legend-dock"');
    expect(graphSource).toContain("defaultInstanceLegendLinkTypes(linkTypeCounts)");
    expect(graphSource).toContain('aria-expanded={showAllRelationshipTypes}');
    expect(ontologySource).toContain('class={`stack governance-ontology is-${view}`}');
    expect(globalStyles).toMatch(/\.ontology-route:has\(\.governance-ontology\.is-instances\)\s*>\s*\.page-header \.page-header-subtitle\s*\{[^}]*display:\s*none/s);
    expect(instancesSource).toContain('class="ontology-instance-toolbar-status"');
    expect(instancesSource).not.toContain('class="ontology-instance-header"');
  });

  it("keeps all registry views in one compact scrollable tab row", () => {
    expect(globalStyles).toMatch(/\.ontology-tabs\s*\{[^}]*display:\s*flex[^}]*min-height:\s*34px[^}]*overflow-x:\s*auto/s);
    expect(globalStyles).toMatch(/\.ontology-tabs a\.is-active::after\s*\{[^}]*height:\s*2px/s);
    expect(globalStyles).not.toMatch(/\.ontology-tabs\s*\{[^}]*grid-template-columns:\s*repeat\(5/s);
    expect(ontologySource).toContain("tabsRef");
    expect(ontologySource).toContain("activeTab.offsetLeft");
    expect(ontologySource).toContain('window.addEventListener("resize", alignActiveTab)');
    expect(globalStyles).toMatch(/\.ontology-route:has\(\.governance-ontology\.is-instances\)[\s\S]*\.page-header-domain,[\s\S]*\.page-header-separator\s*\{\s*display:\s*none/s);
  });

  it("connects Resource autocomplete to the existing instance selection path", () => {
    expect(instancesSource).toContain('aria-autocomplete="list"');
    expect(instancesSource).toContain('role="listbox"');
    expect(instancesSource).toContain('role="option"');
    expect(instancesSource).toContain("ontologyInstanceAutocompleteSuggestions");
    expect(instancesSource).toContain("isOntologyInstanceDirectoryResource");
    expect(instancesSource).toContain(".filter(isOntologyInstanceDirectoryResource)");
    expect(instancesSource).toMatch(/selectedResource\s*&&\s*!isOntologyInstanceDirectoryResource\(selectedResource\)[\s\S]*selectResource\(null\)/);
    expect(instancesSource).toContain("resolveOntologyInstanceAutocomplete");
    expect(instancesSource).toContain("selectResource(resourceId)");
    expect(instancesSource).not.toContain("<datalist");
    expect(instancesSource).toContain('class="ontology-instance-autocomplete-kind"');
    expect(instancesSource).toContain('class="ontology-instance-autocomplete-copy"');
    expect(instancesSource).toContain('class="ontology-instance-autocomplete-type"');
    expect(styles).toMatch(/\.ontology-instance-combobox\s*>\s*ul\s*\{[^}]*width:\s*min\(480px,\s*calc\(100vw\s*-\s*48px\)\)[^}]*max-height:\s*min\(420px,\s*calc\(100vh\s*-\s*32px\)\)[^}]*background:\s*var\(--bg-elevated\)[^}]*color:\s*var\(--fg\)/s);
    expect(styles).toMatch(/@media\s*\(max-height:\s*720px\)\s*\{[^}]*\.ontology-instance-combobox\s*>\s*ul\s*\{[^}]*bottom:\s*calc\(100%\s*\+\s*4px\)/s);
    expect(styles).toMatch(/@media\s*\(max-width:\s*640px\)[\s\S]*\.ontology-instance-combobox\s*>\s*ul\s*\{[^}]*bottom:\s*calc\(100%\s*\+\s*4px\)[^}]*max-height:\s*min\(420px,\s*calc\(100vh\s*-\s*32px\)\)/s);
    expect(styles).toMatch(/@media\s*\(max-width:\s*640px\)[\s\S]*\.ontology-instance-combobox\s*>\s*ul\s*\{[^}]*width:\s*100%/s);
    expect(styles).toMatch(/@media\s*\(max-width:\s*640px\)[\s\S]*\.ontology-instance-dense-legend button\s*\{[^}]*min-height:\s*44px/s);
  });

  it("uses the FDAI graph tooltip instead of native SVG title bubbles", () => {
    expect(graphSource).toContain('class="app-tooltip ontology-instance-graph-tooltip"');
    expect(graphSource).toContain('role="tooltip"');
    expect(graphSource).not.toContain("<title>");
  });

  it("uses one fullscreen command while wheel input owns graph zoom", () => {
    expect(graphSource).toContain("requestFullscreen");
    expect(graphSource).toContain('document.addEventListener("fullscreenchange", sync)');
    expect(graphSource).toContain("aria-pressed={fullscreen}");
    expect(graphSource).toContain("instanceGraphWheelScale");
    expect(graphSource).not.toContain('t("ontology.instances.zoomOut")');
    expect(graphSource).not.toContain('t("ontology.instances.zoomIn")');
    expect(graphSource).not.toContain('t("ontology.instances.fitGraph")');
    expect(styles).toMatch(/\.ontology-instance-graph:fullscreen\s*\{[^}]*height:\s*100vh/s);
  });

  it("collapses and restores the selected-instance inspector accessibly", () => {
    expect(instancesSource).toContain('class="ontology-instance-inspector-toggle is-restore"');
    expect(instancesSource).toContain('aria-controls="ontology-instance-inspector"');
    expect(instancesSource).toContain('is-inspector-collapsed');
    expect(instancesSource).toContain("hidden={!inspectorOpen}");
    expect(inspectorSource).toContain('id="ontology-instance-inspector"');
    expect(inspectorSource).toContain("hidden={hidden}");
    expect(inspectorSource).toContain('class="ontology-instance-inspector-toggle"');
    expect(inspectorSource).toContain("onClick={onToggle}");
    expect(styles).toMatch(/\.ontology-instance-inspector\s*>\s*nav\s*\{[^}]*grid-template-columns:\s*repeat\(4,\s*minmax\(0,\s*1fr\)\)\s*auto/s);
    expect(styles).toMatch(/\.ontology-instance-workbench\.is-inspector-collapsed\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/s);
    expect(styles).toMatch(/\.ontology-instance-workbench\.is-inspector-collapsed \.ontology-instance-graph-tools\s*\{[^}]*right:\s*64px/s);
    expect(styles).toMatch(/\.ontology-instance-map-shell\s*>\s*\.tooltip-anchor:has\(\.ontology-instance-inspector-toggle\.is-restore\)\s*\{[^}]*position:\s*absolute[^}]*inset:\s*0[^}]*pointer-events:\s*none/s);
  });
});
