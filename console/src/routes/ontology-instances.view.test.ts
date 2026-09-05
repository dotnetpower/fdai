import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const graphSource = readFileSync(
  fileURLToPath(new URL("./ontology-instance-graph.tsx", import.meta.url)),
  "utf8",
);
const graphModelSource = readFileSync(
  fileURLToPath(new URL("./ontology-instance-graph.model.ts", import.meta.url)),
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
    expect(graphSource).toContain('class="ontology-instance-presentation-coverage"');
    expect(graphSource).toContain("ontologyInstancePresentationCoverage");
    expect(graphSource).toContain('id="ontology-instance-map-description"');
    expect(instancesSource).not.toContain('id="ontology-instance-map-description"');
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

  it("keeps indirect relationship inspection bounded without calling it an ordered path", () => {
    expect(inspectorSource).toContain("INDIRECT_RELATIONSHIP_PAGE_SIZE");
    expect(inspectorSource).toContain("<PaginatedRelationshipList");
    expect(inspectorSource).toContain("ontology.instances.indirectRelationships");
    expect(inspectorSource).toContain("ontology.instances.relationshipPageStatus");
    expect(inspectorSource).toContain("ontology.instances.showMoreRelationships");
  });

  it("shows semantic status badges and visible-tab automatic refresh state", () => {
    expect(graphSource).toContain("ontologyInstanceStatusTone");
    expect(graphSource).toContain("ontology-instance-state-badge");
    expect(inspectorSource).toContain("<StatusPill");
    expect(inspectorSource).toContain("ontologyInstanceStatusTone(root.status)");
    expect(instancesSource).toContain("installOntologyInstanceRefresh");
    expect(instancesSource).toContain("useOntologyInvalidationStream");
    expect(instancesSource).toContain("formatOntologyRefreshCountdown");
    expect(instancesSource).toContain('new Event("fdai:ontology-invalidated")');
    expect(instancesSource).toContain('class={`ontology-instance-refresh-status is-${mode}`}');
    expect(instancesSource).toContain("setDetailRefreshStatus(\"error\")");
    expect(styles).toContain(".ontology-instance-refresh-status");
    expect(styles).toContain(".ontology-instance-state-badge.is-warning");
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

  it("searches the server directory and never selects an unchosen suggestion", () => {
    expect(instancesSource).toContain("ONTOLOGY_INSTANCE_SEARCH_DEBOUNCE_MS");
    expect(instancesSource).toMatch(
      /window\.setTimeout\(\s*\(\)\s*=>\s*setSearch\(draft\),\s*ONTOLOGY_INSTANCE_SEARCH_DEBOUNCE_MS,?\s*\)/s,
    );
    expect(instancesSource).toContain("window.clearTimeout(timer)");
    expect(instancesSource).toContain("useState<number | null>(null)");
    expect(instancesSource).toContain('event.key === "Enter" && activeSuggestionIndex !== null');
    expect(instancesSource).toContain("activeSuggestionIndex !== null");
    expect(instancesSource).not.toMatch(/setActiveSuggestionIndex\(0\)/);
  });

  it("states the bounded directory as its own notice", () => {
    expect(instancesSource).toContain('class="ontology-instance-bound-notice"');
    expect(instancesSource).toContain('role="note"');
    expect(styles).toContain(".ontology-instance-bound-notice");
  });

  it("selects through the search control alone and refuses an unmatchable query", () => {
    expect(instancesSource).not.toContain("<select");
    expect(instancesSource).not.toContain("ontology.instances.resourceSelector");
    expect(instancesSource).not.toContain("ontology.instances.chooseResource");
    expect(instancesSource).toContain("isMatchableOntologyInstanceQuery");
    expect(instancesSource).toContain("ontology.instances.searchNotMatchable");
    expect(instancesSource).toMatch(
      /draft === search \|\| !isMatchableOntologyInstanceQuery\(draft\)/,
    );
    expect(instancesSource).toContain("if (searchUnmatchable) return;");
    expect(instancesSource).toMatch(/autocompleteOpen\s*&&\s*!searchUnmatchable/s);
    expect(instancesSource).toMatch(
      /setDirectory\(\(current\) =>\s*current\.status === "ready" \? current : \{ status: "loading" \}\)/s,
    );
  });

  it("uses the FDAI graph tooltip instead of native SVG title bubbles", () => {
    expect(graphSource).toContain('class="app-tooltip ontology-instance-graph-tooltip"');
    expect(graphSource).toContain('role="tooltip"');
    expect(graphSource).not.toContain("<title>");
  });

  it("gives the canvas the viewport instead of a fixed box", () => {    expect(styles).toMatch(
      /\.ontology-instance-graph-scroll\s*\{[^}]*max-height:\s*clamp\(560px,\s*calc\(100vh\s*-\s*300px\),\s*900px\)/s,
    );
    expect(graphModelSource).toContain("const INSTANCE_MAX_ROWS = 10;");
    expect(graphModelSource).toContain("const INSTANCE_SCOPE_DIRECT_LIMIT = 7;");
    expect(graphSource).toContain("minScaleRef");
    expect(graphSource).toContain("clampInstanceGraphScale(requestedScale, minScaleRef.current)");
    expect(graphSource).toContain("minScaleRef.current = initialScale;");
    expect(graphSource).toContain(
      'edge.link.link_type === "contains" ? "descend" : "side"',
    );
    expect(graphModelSource).toContain("const ownerY = new Map<string, number>();");
    expect(graphModelSource).toContain("INSTANCE_CONTAINMENT_GROUP_GAP");
    expect(graphModelSource).toMatch(
      /link\.link_type === "contains" && ranks\.get\(link\.target\)\?\.parentId === link\.source/,
    );
    expect(graphModelSource).toContain("rootContainedTop - INSTANCE_ROW_HEIGHT");
  });

  it("draws what a cluster namespace holds without hiding its own repeats", () => {
    expect(graphModelSource).toContain("expandKubernetesNamespaceContext");
    expect(graphModelSource).toContain("INSTANCE_KUBERNETES_NAMESPACE_CHILD_LIMIT");
    expect(graphModelSource).toContain("INSTANCE_KUBERNETES_CHILD_PRIORITY");
    expect(graphModelSource).toMatch(/"kubernetes\.deployment",[\s\S]*"kubernetes\.pod",/);
    expect(graphModelSource).toContain("readonly occurrences: number;");
    expect(graphModelSource).toContain("readonly clusterManaged: boolean;");
    expect(graphModelSource).toContain('"azure.aks-attached-to-node-resource-group"');
    expect(graphSource).toContain('t("ontology.instances.nodeRepeated"');
    expect(graphSource).toContain('t("ontology.instances.nodeClusterManaged"');
    expect(graphSource).toContain('class="ontology-instance-node-repeat"');
    expect(styles).toContain(".ontology-instance-node-repeat");
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
