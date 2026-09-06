import { bindWorkspaceTabs } from "./settings-workspace-tabs.js?v=1";

const profiles = {
  general: {
    tabs: [
      { id: "appearance", label: "Appearance", sections: ["settings-appearance"] },
      { id: "account", label: "Account", sections: ["settings-context", "settings-reset"] },
      { id: "briefings", label: "Briefings", sections: ["settings-briefings", "settings-recent-briefings"] },
      { id: "memory", label: "Memory", sections: ["settings-memory"] },
    ],
  },
  models: {
    tabs: [
      { id: "overview", label: "Overview", sections: ["models-automation", "models-binding-policy", "models-inventory"] },
      { id: "catalog", label: "Catalog", sections: ["models-catalog"] },
      { id: "routing", label: "Routing", sections: ["models-operator-preferences", "models-t2-policy"] },
      { id: "web-search", label: "Web search", sections: ["models-web-search"] },
    ],
  },
  runtime: {
    tabs: [
      { id: "effective-settings", label: "Effective settings", sections: ["runtime-policy-settings"], lead: ".cp-kpis" },
      { id: "override-editor", label: "Override editor", sections: ["runtime-override-editor"] },
    ],
  },
  memory: {
    shared: ["memory-filter"],
    tabs: [
      { id: "entries", label: "Memory entries", sections: ["memory-entries"] },
      { id: "compaction-review", label: "Compaction review", sections: ["memory-compactions"] },
    ],
  },
  diagnostics: {
    tabs: [
      { id: "runtime", label: "Runtime", sections: ["diagnostics-runtime"] },
      { id: "policy", label: "Policy", sections: ["diagnostics-policy"] },
      { id: "data-sources", label: "Data sources", sections: ["diagnostics-sources"] },
    ],
  },
};

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text) element.textContent = text;
  return element;
}

function secondarySection(section) {
  const header = section.querySelector(".cs-settings-section-head, .cp-section-head");
  const heading = header.querySelector("h2, h3");
  const details = node("details", "cs-settings-disclosure cs-settings-workspace-secondary");
  const summary = node("summary");
  summary.append(heading);
  const scope = header.querySelector(".cs-settings-scope");
  if (scope) summary.append(scope);
  const body = node("div", "cs-settings-workspace-detail");
  body.append(...header.querySelectorAll("p"));
  body.append(...[...section.children].filter((child) => child !== header));
  details.append(summary, body);
  return details;
}

function mountWorkspace(root) {
  const name = root.dataset.settingsProfile;
  const profile = profiles[name];
  if (!profile) throw new Error("Unregistered Settings workspace profile.");
  const sectionIds = [...(profile.shared || []), ...profile.tabs.flatMap((tab) => tab.sections)];
  const sections = new Map(sectionIds.map((id) => {
    const target = root.querySelector("#" + id);
    const section = target?.closest(".cs-settings-section, .cp-section");
    if (!section) throw new Error("Settings workspace is missing section " + id + ".");
    return [id, section];
  }));
  const authored = [...root.querySelectorAll(".cs-settings-section, .cp-section")];
  if (new Set(sections.values()).size !== sectionIds.length || authored.some((section) => ![...sections.values()].includes(section))) {
    throw new Error("Every Settings section must belong to exactly one workspace view.");
  }
  const leads = new Map(profile.tabs.filter((tab) => tab.lead).map((tab) => {
    const lead = root.querySelector(tab.lead);
    if (!lead) throw new Error("Settings workspace is missing its summary.");
    return [tab.id, lead];
  }));
  const originalHeader = root.querySelector(":scope > .cs-page-header, :scope > .cp-header");
  if (!originalHeader) throw new Error("Settings workspace is missing its page header.");
  const notice = root.querySelector(":scope > .cs-settings-preview-note, :scope > .cs-readonly-banner")
    || node("p", "", "Synthetic preview. No settings are saved or requests sent.");
  notice.classList.add("cs-settings-workspace-notice");
  notice.id = `settings-${name}-preview-note`;
  let header = originalHeader;
  if (!header.classList.contains("cp-header")) {
    header = node("header", "cp-header");
    const copy = node("div", "cp-header-copy");
    copy.append(...originalHeader.childNodes);
    header.append(copy);
  }
  const nav = node("div", "cs-settings-workspace-nav");
  const tablist = node("div", "cs-settings-workspace-tabs");
  tablist.setAttribute("role", "tablist");
  tablist.setAttribute("aria-label", header.querySelector("h1").textContent.trim() + " views");
  tablist.dataset.tabCount = String(profile.tabs.length);
  const hint = node("span", "cs-settings-workspace-note", "Demo data");
  hint.title = notice.textContent.trim();
  hint.setAttribute("aria-describedby", notice.id);
  nav.append(tablist, hint);
  const error = node("div", "integrations-workspace-error");
  error.dataset.settingsError = "";
  error.setAttribute("role", "alert");
  error.hidden = true;
  const recovery = node("button", "cs-control-button", "Return to " + profile.tabs[0].label);
  recovery.type = "button";
  recovery.dataset.openSettings = profile.tabs[0].id;
  error.append(node("strong", "", "Settings view unavailable"), node("p", "", "This view is not registered. Select a tab to continue."), recovery);
  const aliases = {};
  const panels = profile.tabs.map((tab, index) => {
    const button = node("button", "cp-tab", tab.label);
    button.type = "button";
    button.id = `settings-${name}-tab-${tab.id}`;
    button.dataset.settingsTab = tab.id;
    button.setAttribute("role", "tab");
    button.setAttribute("aria-selected", String(index === 0));
    button.tabIndex = index === 0 ? 0 : -1;
    const panel = node("div", "cs-settings-workspace-panel");
    panel.id = `settings-${name}-panel-${tab.id}`;
    panel.dataset.settingsPanel = tab.id;
    panel.hidden = index !== 0;
    panel.setAttribute("role", "tabpanel");
    panel.setAttribute("aria-labelledby", button.id);
    button.setAttribute("aria-controls", panel.id);
    tablist.append(button);
    if (leads.has(tab.id)) panel.append(leads.get(tab.id));
    tab.sections.forEach((id, sectionIndex) => {
      aliases[id] = tab.id;
      panel.append(sectionIndex === 0 ? sections.get(id) : secondarySection(sections.get(id)));
    });
    return panel;
  });
  const shared = (profile.shared || []).map((id) => {
    aliases[id] = profile.tabs[0].id;
    const details = secondarySection(sections.get(id));
    details.classList.add("cs-settings-workspace-filters");
    return details;
  });
  root.classList.add("cs-settings-workspace");
  root.replaceChildren(header, nav, error, ...shared, ...panels, notice);
  bindWorkspaceTabs(root, { defaultTab: profile.tabs[0].id, aliases });
  root.dataset.settingsReady = "true";
}

function initialize() {
  document.querySelectorAll("[data-settings-profile]").forEach((root) => {
    try {
      mountWorkspace(root);
    } catch (error) {
      console.error("Settings workspace could not load.", error);
      const message = node("p", "", "Settings workspace could not load. Reload the preview after its section configuration is corrected.");
      message.setAttribute("role", "alert");
      const header = root.querySelector(":scope > .cp-header, :scope > .cs-page-header");
      root.replaceChildren(...(header ? [header, message] : [message]));
      root.dataset.settingsReady = "error";
    }
  });
}

if (document.readyState === "complete") initialize();
else document.addEventListener("DOMContentLoaded", initialize, { once: true });
