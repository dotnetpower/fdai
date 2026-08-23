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
const inspectorSource = readFileSync(
  fileURLToPath(new URL("./ontology-instances-inspector.tsx", import.meta.url)),
  "utf8",
);
const styles = readFileSync(
  fileURLToPath(new URL("./ontology-instances.css", import.meta.url)),
  "utf8",
);

describe("Ontology Instances view controls", () => {
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
    expect(instancesSource).toContain("aria-expanded={inspectorOpen}");
    expect(instancesSource).toContain('aria-controls="ontology-instance-inspector"');
    expect(instancesSource).toContain('is-inspector-collapsed');
    expect(instancesSource).toContain("hidden={!inspectorOpen}");
    expect(inspectorSource).toContain('id="ontology-instance-inspector"');
    expect(inspectorSource).toContain("hidden={hidden}");
    expect(styles).toMatch(/\.ontology-instance-workbench\.is-inspector-collapsed\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/s);
  });
});
