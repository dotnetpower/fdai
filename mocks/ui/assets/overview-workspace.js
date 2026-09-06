import { bindWorkspaceTabs } from "./settings-workspace-tabs.js";

// Only presentation state changes. Hashes never carry approval or execution authority.
document.querySelectorAll("[data-overview-tabs]").forEach((root) => {
  bindWorkspaceTabs(root, {
    tabAttribute: "data-overview-tab",
    panelAttribute: "data-overview-panel",
    openAttribute: "data-open-overview",
    errorSelector: "[data-overview-error]",
    defaultTab: root.dataset.overviewTabs,
    aliases: { touchpoints: "human-touchpoints", "lead-time": "change-lead-time", cost: "cost-per-resolved-event" },
  });
});

const guardFilter = document.querySelector("[data-guard-filter]");
if (guardFilter) {
  const applyGuard = () => {
    const key = guardFilter.value;
    let shown = 0;
    document.querySelectorAll("[data-guard-key]").forEach((row) => {
      row.hidden = Boolean(key) && row.dataset.guardKey !== key;
      if (!row.hidden) shown += 1;
    });
    document.querySelector("[data-guard-empty]").hidden = shown > 0;
    const url = new URL(location.href);
    if (key) url.searchParams.set("guard", key); else url.searchParams.delete("guard");
    history.replaceState(null, "", url);
    if (window.fdaiPublishMockRoute) window.fdaiPublishMockRoute();
  };
  const initial = new URL(location.href).searchParams.get("guard");
  if (initial && ![...guardFilter.options].some((option) => option.value === initial)) {
    guardFilter.add(new Option("Unknown guard", initial));
  }
  guardFilter.value = initial || "";
  guardFilter.addEventListener("change", applyGuard);
  applyGuard();
}

const indicatorFilter = document.querySelector("[data-indicator-filter]");
if (indicatorFilter) {
  const applyIndicator = () => {
    let shown = 0;
    document.querySelectorAll("[data-indicator]").forEach((row) => {
      row.hidden = Boolean(indicatorFilter.value) && row.dataset.indicator !== indicatorFilter.value;
      if (!row.hidden) shown += 1;
    });
    document.querySelector("[data-indicator-empty]").hidden = shown > 0;
    const url = new URL(location.href);
    if (indicatorFilter.value) url.searchParams.set("indicator", indicatorFilter.value);
    else url.searchParams.delete("indicator");
    history.replaceState(null, "", url);
    if (window.fdaiPublishMockRoute) window.fdaiPublishMockRoute();
  };
  const initial = new URL(location.href).searchParams.get("indicator");
  if (initial && ![...indicatorFilter.options].some((option) => option.value === initial)) indicatorFilter.add(new Option("Unknown indicator", initial));
  indicatorFilter.value = initial || "";
  indicatorFilter.addEventListener("change", applyIndicator);
  applyIndicator();
  function markTier() {
    const active = location.hash.slice(1) || "t2";
    document.querySelectorAll(".ov-tier").forEach((card) => {
      if (card.getAttribute("href") === "#" + active) card.setAttribute("aria-current", "page");
      else card.removeAttribute("aria-current");
    });
    if (active === "t0" || active === "t1") { indicatorFilter.value = ""; applyIndicator(); }
  }
  window.addEventListener("hashchange", markTier);
  markTier();
  document.querySelectorAll("[data-overview-tab]").forEach((tab) => {
    tab.addEventListener("click", () => {
      if (tab.dataset.overviewTab !== "t2") { indicatorFilter.value = ""; applyIndicator(); }
      queueMicrotask(markTier);
    });
  });
}
