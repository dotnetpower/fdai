import { bindWorkspaceTabs } from "./settings-workspace-tabs.js?v=1";

const root = document.querySelector("[data-integrations-workspace]");
if (root) bindWorkspaceTabs(root, {
  tabAttribute: "data-integration-tab",
  panelAttribute: "data-integration-panel",
  openAttribute: "data-open-integration",
  errorSelector: "[data-integration-error]",
  defaultTab: "overview",
  aliases: {
    "integrations-identity": "overview",
    "integrations-delivery": "overview",
    "integrations-teams": "teams-workflows",
    "integrations-diagnostics": "diagnostics",
    "integrations-email": "email-template",
  },
});
