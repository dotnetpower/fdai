// Mock-only interaction controller. No network, model, approval, or resource mutation.
(function () {
  "use strict";
  const { createSnapshot, query, statusKey, definitions, typeNames, typeCounts } = window.FdaiDashboardData;
  const { element, badge } = window.FdaiDashboardViews;
  const byId = (id) => document.getElementById(id);
  const state = { lens: "operation", view: "honeycomb", density: "comfortable", effectiveDensity: "comfortable", columns: 4, subscription: "all", group: "all", type: "all", status: null, query: "", selected: null, page: 0 };
  let snapshot;
  let result;
  const record = byId("resource-evidence");
  const touchLayout = matchMedia("(max-width: 700px), (pointer: coarse)");
  const preview = window.FdaiDashboardPreview.create(() => snapshot);
  const typePicker = window.FdaiDashboardTypePicker.create((type) => {
    state.type = type;
    state.page = 0;
    render();
  });
  const views = window.FdaiDashboardViews.create(selectResource, (kind, key) => {
    state[kind] = key;
    if (kind === "subscription") state.group = "all";
    state.view = kind === "subscription" ? "groups" : "honeycomb";
    state.page = 0;
    syncInputs();
    render();
    byId("resource-map-title").focus({ preventScroll: true });
  });
  const notes = {
    operation: "Running is not a health verdict. Stopped is not automatically an incident. Stale state is shown as unknown.",
    availability: "Availability is independent of power state. Unreadable, stale, and unsupported observations are not healthy.",
    observation: "This view describes state-reader coverage, not resource health or inventory completeness.",
  };
  function resetFilters() {
    Object.assign(state, { subscription: "all", group: "all", type: "all", status: null, query: "", page: 0 });
    syncInputs();
  }
  function syncInputs() {
    byId("resource-subscription").value = state.subscription;
    const groups = new Map(snapshot.resources
      .filter((resource) => state.subscription === "all" || resource.subscription === state.subscription)
      .map((resource) => [resource.group, resource.groupName]));
    options(byId("resource-group"), groups, "All groups");
    byId("resource-group").value = state.group;
    byId("resource-search").value = state.query;
  }
  function options(select, values, allLabel) {
    const all = element("option", "", allLabel);
    all.value = "all";
    select.replaceChildren(all);
    for (const [key, name] of values) {
      const option = element("option", "", name);
      option.value = key;
      select.appendChild(option);
    }
  }
  function selectResource(id) {
    if (!snapshot.byId.has(id)) throw new Error("Unknown example resource: " + id);
    if (state.selected !== id) record.open = false;
    state.selected = id;
    render();
    byId("resource-selection-status").textContent = snapshot.byId.get(id).name + " details pinned. The map position is unchanged.";
  }
  function inspector() {
    const resource = snapshot.byId.get(state.selected);
    byId("resource-inspector").hidden = !resource;
    byId("resource-side").classList.toggle("has-selection", Boolean(resource));
    byId("resource-selection-empty").hidden = Boolean(resource);
    byId("resource-selection").hidden = !resource;
    byId("resource-inspector").setAttribute("aria-labelledby", resource ? "resource-selected-name" : "resource-inspector-title");
    if (!resource) return;
    byId("resource-selected-type").textContent = typeNames[resource.type];
    byId("resource-selected-name").textContent = resource.name;
    byId("resource-selected-scope").textContent = `${resource.subscriptionName} / ${resource.groupName} / ${resource.id}`;
    byId("resource-selection-filtered").hidden = result.selectedMatches;
    byId("resource-selection-paged").hidden = !result.selectedMatches || result.selectedOnPage;
    const facts = byId("resource-selected-facts");
    facts.replaceChildren();
    [
      ["Operating state", badge("operation", statusKey(resource, "operation", snapshot))],
      ["Availability", badge("availability", statusKey(resource, "availability", snapshot))],
      ["Observation", badge("observation", statusKey(resource, "observation", snapshot))],
      ["State observed at", resource.time ? `05 Sep 2026, ${resource.time} KST` : "Not recorded"],
      ["Inventory recorded at", "05 Sep 2026, 12:00 KST"],
      ["Response owner / recovery", "Not recorded / not verified"],
    ].forEach(([label, value]) => {
      const definition = element("dd");
      if (typeof value === "string") definition.textContent = value;
      else definition.appendChild(value);
      const item = element("div");
      item.append(element("dt", "", label), definition);
      facts.appendChild(item);
    });
    byId("resource-selected-note").textContent = snapshot.mode === "stale" || resource.observation === "stale"
      ? `Last reported state was ${resource.operation}; it is too old to establish the snapshot's current state.`
      : resource.observation === "denied"
        ? "Inventory identity is present, but the state read was denied. No current state is inferred."
        : resource.operation === "na"
          ? "This resource type has no start/stop state in this view. That does not establish availability."
          : ["stopped", "deallocated"].includes(resource.operation)
            ? "The observed stopped state does not establish an incident or a planned shutdown. Intent and attribution are not recorded."
            : "Operation and availability are independent observations. A running resource can still be unavailable.";
    byId("resource-selected-evidence").textContent = JSON.stringify({
      synthetic: true, snapshot: snapshot.time, snapshot_id: snapshot.id, resource: resource.id,
      subscription: resource.subscription, group: resource.group, source: "example-provider-observation",
      observation: statusKey(resource, "observation", snapshot),
      recorded_operation: resource.operation, recorded_availability: resource.availability,
      state_observed_at: resource.time ? `2026-09-05T${resource.time}:00+09:00` : null,
      presented_operation: statusKey(resource, "operation", snapshot),
      presented_availability: statusKey(resource, "availability", snapshot),
      inventory_complete: snapshot.complete, execution_authority: false,
    }, null, 2);
  }
  let legendLens = "";
  function geometry() {
    const panel = document.querySelector(".dr-resource-panel");
    const style = getComputedStyle(panel);
    const width = panel.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
    return {
      columns: Math.max(4, Math.min(34, Math.floor((width - 11) / 26))),
      effectiveDensity: touchLayout.matches ? "comfortable" : state.density,
    };
  }
  function render() {
    preview.hide();
    typePicker.sync(state.type, typeCounts(snapshot, state), snapshot.complete);
    Object.assign(state, geometry());
    result = query(snapshot, state);
    state.page = result.page;
    const count = snapshot.resources.length;
    const grouped = state.view === "groups";
    byId("resource-count").textContent = grouped
      ? `${result.groups.length} groups shown / ${result.matchCount} match filters / ${count} in snapshot`
      : `${result.records.length} shown / ${result.eligibleCount} match scope / ${count} in snapshot`;
    byId("resource-lens-note").textContent = notes[state.lens];
    byId("resource-view-note").textContent = grouped
      ? `Grouped by ${result.grouping === "subscription" ? "subscription" : "resource group"}. Each summary contains multiple resources; open one to narrow the scope.`
      : "One cell is one resource. Hover or focus to inspect; click to pin. Not a dependency map.";
    byId("resource-density").hidden = state.view !== "honeycomb";
    byId("resource-density-note").hidden = !touchLayout.matches || state.view !== "honeycomb";
    document.querySelectorAll("[data-resource-density]").forEach((button) => {
      button.setAttribute("aria-pressed", String(button.dataset.resourceDensity === state.effectiveDensity));
      button.disabled = touchLayout.matches && button.dataset.resourceDensity === "dense";
    });
    byId("resource-empty").hidden = result.matchCount !== 0;
    byId("resource-empty-title").textContent = count ? "No matching resources" : "No resources in this example snapshot";
    byId("resource-breadcrumb").hidden = state.subscription === "all" && state.group === "all";
    byId("resource-scope-label").textContent = [
      state.subscription === "all" ? "All observed subscriptions" : snapshot.subscriptions.get(state.subscription),
      state.group === "all" ? "" : snapshot.groups.get(state.group),
    ].filter(Boolean).join(" / ");
    const legend = byId("resource-legend");
    if (legendLens !== state.lens) {
      legendLens = state.lens;
      legend.replaceChildren();
      ["all", ...Object.keys(definitions[state.lens])].forEach((key) => {
        const button = element("button");
        button.type = "button";
        button.dataset.stateKey = key;
        button.addEventListener("click", () => { state.status = key === "all" ? null : key; state.page = 0; render(); });
        legend.appendChild(button);
      });
    }
    for (const button of legend.children) {
      const key = button.dataset.stateKey;
      const total = key === "all" ? result.eligibleCount : result.counts[key];
      button.replaceChildren();
      if (key === "all") button.textContent = "All " + total;
      else {
        const [label, tone, symbol] = definitions[state.lens][key];
        const mark = element("span", "dr-key", symbol);
        mark.dataset.tone = tone;
        mark.setAttribute("aria-hidden", "true");
        button.append(mark, element("span", "", `${label} ${total}`));
      }
      button.dataset.count = String(total);
      button.setAttribute("aria-pressed", String(key === (state.status || "all")));
    }
    document.querySelectorAll("[data-resource-view]").forEach((button) => button.setAttribute("aria-pressed", String(state.view === button.dataset.resourceView)));
    document.querySelectorAll("[data-resource-lens]").forEach((button) => button.setAttribute("aria-pressed", String(state.lens === button.dataset.resourceLens)));
    byId("resource-pagination").hidden = result.total <= result.limit;
    byId("resource-page-label").textContent = `${grouped ? "Groups" : "Resources"} ${result.start + 1}-${Math.min(result.start + result.limit, result.total)} of ${result.total} matching / Page ${state.page + 1} of ${Math.max(1, Math.ceil(result.total / result.limit))}`;
    byId("resource-previous").disabled = state.page === 0;
    byId("resource-next").disabled = result.start + result.limit >= result.total;
    byId("resource-page-boundary").textContent = snapshot.complete
      ? `${count} observed resources. ${result.limit} ${grouped ? "group summaries" : "resources"} per page at most${state.view === "honeycomb" && state.effectiveDensity === "dense" ? " at this width" : ""}. Other pages are not missing observations. Groups are excluded from resource totals.`
      : `${count} observed resources from a partial inventory; full total unknown. Search and groups cover only received records. Other pages are separate from missing observations.`;
    views.render(result, state, snapshot);
    inspector();
  }
  function loadExample() {
    typePicker.close();
    const size = Number(byId("resource-example-size").value);
    const mode = byId("resource-example-state").value;
    snapshot = createSnapshot(size, mode);
    state.selected = null;
    state.lens = "operation";
    state.view = "honeycomb";
    state.density = size > 48 ? "dense" : "comfortable";
    record.open = false;
    options(byId("resource-subscription"), snapshot.subscriptions, "All subscriptions");
    resetFilters();
    const unavailable = mode === "loading" || mode === "error";
    byId("resource-data").hidden = unavailable;
    byId("resource-read-state").hidden = !unavailable;
    byId("resource-loading").hidden = mode !== "loading";
    byId("resource-read-error").hidden = mode !== "error";
    byId("resource-read-state").setAttribute("aria-busy", String(mode === "loading"));
    byId("resource-snapshot-id").textContent = snapshot.id;
    byId("resource-scope-name").textContent = snapshot.subscriptions.size === 1
      ? [...snapshot.subscriptions.values()][0] : `${snapshot.subscriptions.size} observed subscriptions`;
    byId("resource-scope-description").textContent = `${snapshot.groups.size} observed resource groups / Inventory only, not execution authority`;
    byId("resource-snapshot-status").textContent = mode === "partial" ? "Partial inventory / full total unknown"
      : mode === "stale" ? "Historical snapshot / current state unknown" : "State coverage is partial";
    byId("resource-snapshot-status").hidden = snapshot.resources.length === 0;
    const operations = snapshot.operationCounts;
    const known = snapshot.resources.length - operations.unknown - operations.na;
    byId("count-resources").textContent = snapshot.resources.length;
    byId("count-known").textContent = known;
    byId("count-unknown").textContent = operations.unknown;
    byId("count-na").textContent = operations.na;
    byId("inventory-coverage").textContent = `${snapshot.complete ? "Complete example" : "Partial example; full total unknown"} / ${snapshot.resources.length} observed resources / 12:00 KST`;
    byId("operation-coverage").textContent = `${known} known / ${operations.unknown} unknown / ${operations.na} not applicable`;
    const available = snapshot.availabilityCounts;
    byId("availability-coverage").textContent = `${available.available + available.degraded + available.unavailable} known / ${available.unknown + available.unsupported} unknown or unsupported`;
    byId("resource-priorities").hidden = snapshot.resources.length === 0;
    byId("resource-priorities-empty").hidden = snapshot.resources.length !== 0;
    document.querySelectorAll("[data-event-resource]").forEach((button) => {
      button.disabled = !snapshot.byId.has(button.dataset.eventResource);
      button.title = button.disabled ? "Resource is not in the received inventory; its recorded event remains visible." : "";
    });
    document.querySelectorAll("[data-priority-state]").forEach((label) => {
      const resource = snapshot.byId.get(label.dataset.priorityState);
      if (resource) label.replaceChildren(badge("availability", statusKey(resource, "availability", snapshot)));
    });
    render();
  }
  ["subscription", "group"].forEach((key) => byId("resource-" + key).addEventListener("change", (event) => {
    state[key] = event.target.value;
    if (key === "subscription") { state.group = "all"; syncInputs(); }
    state.page = 0; render();
  }));
  byId("resource-search").addEventListener("input", (event) => { state.query = event.target.value.trim().toLowerCase(); state.page = 0; render(); });
  byId("resource-reset").addEventListener("click", () => { resetFilters(); render(); });
  byId("resource-scope-reset").addEventListener("click", () => { resetFilters(); state.view = "groups"; render(); });
  document.querySelectorAll("[data-resource-lens]").forEach((button) => button.addEventListener("click", () => { state.lens = button.dataset.resourceLens; state.status = null; state.page = 0; render(); }));
  document.querySelectorAll("[data-resource-view]").forEach((button) => button.addEventListener("click", () => { state.view = button.dataset.resourceView; state.page = 0; render(); }));
  document.querySelectorAll("[data-resource-density]").forEach((button) => button.addEventListener("click", () => { state.density = button.dataset.resourceDensity; state.page = 0; render(); }));
  byId("resource-previous").addEventListener("click", () => { state.page -= 1; render(); });
  byId("resource-next").addEventListener("click", () => { state.page += 1; render(); });
  byId("resource-selection-clear").addEventListener("click", () => {
    state.selected = null; record.open = false; render();
    byId("resource-map-title").focus({ preventScroll: true });
    byId("resource-selection-status").textContent = "Selection cleared. Recorded highlights are shown.";
  });
  byId("resource-back").addEventListener("click", () => {
    const selected = document.querySelector(".dr-cell[aria-pressed='true'],.dr-list button[aria-pressed='true']");
    (selected || byId("resource-map-title")).focus();
    (selected || byId("resource-map-title")).scrollIntoView({ block: "center" });
  });
  document.querySelector(".dr-attention-jump").addEventListener("click", () => {
    state.selected = null; record.open = false; render();
  });
  document.querySelectorAll("[data-inspect-resource]").forEach((button) => button.addEventListener("click", () => { resetFilters(); selectResource(button.dataset.inspectResource); }));
  const eventSnapshot = createSnapshot(24, "complete");
  [
    ["11:57", "data-db-01", "Availability changed: available to degraded.", "Synthetic health event; no query-level cause."],
    ["11:55", "platform-vm-01", "Power changed: running to deallocated.", "Synthetic power observation; shutdown intent unknown."],
    ["11:40", "app-vm-02", "Transition to starting was observed.", "No completion event recorded in the sample."],
    ["11:20", "data-store-02", "State read denied; inventory identity retained.", "A failed read does not prove the resource is absent."],
  ].forEach(([time, id, text, note]) => {
    const resource = eventSnapshot.byId.get(id);
    const li = element("li");
    const stamp = element("time", "", time);
    stamp.dateTime = `2026-09-05T${time}:00+09:00`;
    const copy = element("div");
    const button = element("button", "dr-text-link", resource.name);
    button.type = "button";
    button.dataset.eventResource = id;
    button.addEventListener("click", () => { resetFilters(); selectResource(id); });
    copy.append(button, element("p", "", text), element("small", "", note));
    li.append(stamp, copy);
    byId("resource-changes").appendChild(li);
  });
  byId("resource-example-size").addEventListener("change", loadExample);
  byId("resource-example-state").addEventListener("change", loadExample);
  byId("resource-example-restore").addEventListener("click", () => { byId("resource-example-state").value = "complete"; loadExample(); });
  loadExample();
  function resize() {
    const next = geometry();
    if (next.columns !== state.columns || next.effectiveDensity !== state.effectiveDensity) {
      state.page = 0;
      render();
    }
  }
  new ResizeObserver(resize).observe(document.querySelector(".dr-resource-panel"));
  touchLayout.addEventListener("change", resize);
})();
