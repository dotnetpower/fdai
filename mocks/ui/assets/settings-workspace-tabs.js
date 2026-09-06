/** Bind accessible, route-aware preview tabs without granting settings or execution authority. */
export function bindWorkspaceTabs(root, {
  tabAttribute = "data-settings-tab",
  panelAttribute = "data-settings-panel",
  openAttribute = "data-open-settings",
  errorSelector = "[data-settings-error]",
  defaultTab,
  aliases = {},
}) {
  const tabs = [...root.querySelectorAll(`[${tabAttribute}]`)];
  const panels = [...root.querySelectorAll(`[${panelAttribute}]`)];
  const error = root.querySelector(errorSelector);
  let active = null;

  function selectTab(requested, userInitiated = false, focus = false) {
    const id = Object.hasOwn(aliases, requested) ? aliases[requested] : requested;
    const tab = tabs.find((item) => item.getAttribute(tabAttribute) === id);
    const changed = active !== id;
    active = id;
    error.hidden = Boolean(tab);
    panels.forEach((panel) => { panel.hidden = panel.getAttribute(panelAttribute) !== id; });
    tabs.forEach((item, index) => {
      const selected = item === tab;
      item.setAttribute("aria-selected", String(selected));
      item.tabIndex = selected || (!tab && index === 0) ? 0 : -1;
    });
    if (!tab) {
      console.warn("Unregistered Settings preview tab.");
      return;
    }
    if (focus) tab.focus();
    if (userInitiated && changed) {
      history.pushState(null, "", "#" + id);
      window.scrollTo({ top: 0, behavior: "instant" });
    }
    if (window.parent !== window) {
      window.parent.postMessage({ type: "fdai:mock-section", section: id }, window.location.origin);
    }
  }

  root.addEventListener("click", (event) => {
    const trigger = event.target.closest(`[${tabAttribute}], [${openAttribute}]`);
    if (!trigger || trigger.disabled) return;
    selectTab(trigger.getAttribute(tabAttribute) || trigger.getAttribute(openAttribute), true, trigger.hasAttribute(openAttribute));
  });
  root.addEventListener("keydown", (event) => {
    const tab = event.target.closest(`[${tabAttribute}]`);
    if (!tab || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const current = tabs.indexOf(tab);
    const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1
      : (current + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
    selectTab(tabs[next].getAttribute(tabAttribute), true, true);
  });
  window.addEventListener("hashchange", () => selectTab(window.location.hash.slice(1) || defaultTab));
  selectTab(window.location.hash.slice(1) || defaultTab);
  root.dataset.settingsTabsReady = "true";
}
