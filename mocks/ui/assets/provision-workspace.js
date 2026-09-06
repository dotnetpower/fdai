import { bindWorkspaceTabs } from "./settings-workspace-tabs.js?v=1";

const root = document.querySelector(".pv-workspace");
const views = [
  ["stages", "Stages", ["pv-stage-title"]],
  ["readiness", "Readiness", ["pv-readiness-title", "pv-network-title", "pv-scan-title", "pv-handoff-title"]],
  ["runtime", "Runtime", ["pv-ontology-title", "pv-agents-title"]],
  ["resources", "Resources and setup", ["pv-resources-title", "pv-required-actions-title"]],
  ["events", "Events", ["pv-stream-title"]],
];
const sections = [...root.querySelectorAll(":scope > .pv-primary > section, :scope > .pv-secondary > section")];
const expected = views.flatMap((view) => view[2]);
if (sections.length !== expected.length || new Set(expected).size !== expected.length ||
    expected.some((id) => !sections.some((section) => section.getAttribute("aria-labelledby") === id))) {
  throw new Error("Every provisioning section must belong to exactly one preview view.");
}
const tabs = document.createElement("div");
tabs.className = "op-tabs";
tabs.setAttribute("role", "tablist");
tabs.setAttribute("aria-label", "Provisioning views");
const error = document.createElement("div");
error.dataset.opTabError = "";
error.setAttribute("role", "alert");
error.hidden = true;
error.textContent = "Preview view unavailable. Choose a registered provisioning view.";
const aliases = {};
const panels = views.map(([id, label, headings], index) => {
  const tab = document.createElement("button");
  tab.type = "button";
  tab.className = "cp-tab";
  tab.id = `pv-tab-${id}`;
  tab.dataset.opTab = id;
  tab.setAttribute("role", "tab");
  tab.setAttribute("aria-controls", `pv-panel-${id}`);
  tab.setAttribute("aria-selected", String(index === 0));
  tab.tabIndex = index === 0 ? 0 : -1;
  tab.textContent = label;
  tabs.append(tab);
  const panel = document.createElement("div");
  panel.id = `pv-panel-${id}`;
  panel.dataset.opPanel = id;
  panel.setAttribute("role", "tabpanel");
  panel.setAttribute("aria-labelledby", tab.id);
  panel.hidden = index !== 0;
  for (const heading of headings) {
    const section = sections.find((candidate) => candidate.getAttribute("aria-labelledby") === heading);
    aliases[heading] = id;
    panel.append(section);
  }
  return panel;
});
root.replaceChildren(tabs, error, ...panels);
root.classList.add("op-static-workspace");
bindWorkspaceTabs(root, {
  tabAttribute: "data-op-tab",
  panelAttribute: "data-op-panel",
  openAttribute: "data-open-op",
  errorSelector: "[data-op-tab-error]",
  defaultTab: "stages",
  aliases,
});
root.dataset.operatorReady = "true";
