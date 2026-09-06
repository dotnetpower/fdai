import { createIamEditor } from "./settings-iam-editor.js";

const reader = ["view-console"];
const contributor = reader.concat(["author-draft-pr", "start-read-investigation"]);
const approver = contributor.concat(["review-governance-pr", "approve-quorum-promotion", "approve-exemption", "approve-override", "approve-runtime-hil"]);
const owner = approver.concat(["trigger-kill-switch", "manage-runtime-settings", "manage-group-membership", "apply-infra-iac"]);
const roles = [
  { name: "Reader", capabilities: reader, description: "Read-only operational access" },
  { name: "Contributor", capabilities: contributor, description: "Includes Reader permissions" },
  { name: "Approver", capabilities: approver, description: "Includes Contributor permissions" },
  { name: "Owner", capabilities: owner, description: "Includes Approver permissions" },
  { name: "BreakGlass", capabilities: ["view-console", "trigger-kill-switch", "grant-emergency-access"], description: "Separate emergency permissions", emergency: true }
];
const tabIds = ["my-access", "users", "roles", "requests"];
const scenarioLabels = { owner: "Owner", reader: "Reader", unavailable: "Unavailable", loading: "Loading", error: "Failed" };

function element(tag, text, className) {
  const node = document.createElement(tag);
  node.textContent = text;
  if (className) node.className = className;
  return node;
}

function capability(code) {
  const label = code.replace(/-/g, " ").replace(/\bpr\b/g, "PR").replace(/\bhil\b/g, "HIL").replace(/\biac\b/g, "IaC");
  const item = element("li", label.charAt(0).toUpperCase() + label.slice(1), "iam-capability");
  item.title = code;
  return item;
}

function initialize(mount, template) {
  mount.replaceChildren(template.cloneNode(true));
  const root = mount.querySelector("[data-iam-content]");
  const routeMode = mount.hasAttribute("data-iam-route");
  const state = { active: routeMode ? window.location.hash.slice(1) || "my-access" : "my-access", scenario: "owner", filter: "all", query: "", requestFilter: "all" };
  const find = (selector) => root.querySelector(selector);
  const all = (selector) => [...root.querySelectorAll(selector)];
  const setText = (selector, text) => all(selector).forEach((node) => { node.textContent = text; });
  const tabs = all("[data-iam-tab]");
  const rows = all("[data-roster] > tr");
  const requestRows = all("[data-requests] > tr");
  const announce = (message) => setText("[data-iam-announcement]", message);
  const isOwner = () => state.scenario === "owner" || state.scenario === "unavailable";
  const editor = createIamEditor(root, {
    roles: roles.filter((role) => !role.emergency).map((role) => role.name),
    canRequest: () => state.scenario === "owner",
    canReview: isOwner,
    announce
  });

  roles.forEach((role) => {
    const row = document.createElement("tr");
    row.dataset.role = role.name;
    const name = element("td", "");
    name.dataset.label = "Role";
    name.append(element("strong", role.name, "iam-role-name"));
    const capabilities = element("td", "");
    capabilities.dataset.label = "Capabilities";
    const details = element("details", "", "iam-details iam-role-capabilities");
    const summary = element("summary", "");
    summary.append(element("span", role.description, "iam-role-description"), element("span", role.capabilities.length + (role.capabilities.length === 1 ? " capability" : " capabilities"), "iam-role-count"));
    details.append(summary);
    const list = element("ul", "", "iam-capability-list");
    list.append(...role.capabilities.map(capability));
    details.append(list);
    capabilities.append(details);
    const assignment = element("td", role.emergency ? "Emergency activation only" : "Entra role group");
    assignment.dataset.label = "Assignment";
    row.append(name, capabilities, assignment);
    find("[data-role-definitions]").append(row);
  });

  function updateRoster(notify = false) {
    const available = state.scenario !== "unavailable";
    const eligible = rows.filter((row) => available || row.dataset.principalType === "person");
    const people = eligible.filter((row) => row.dataset.principalType === "person").length;
    const groups = eligible.length - people;
    const query = state.query.trim().toLowerCase();
    const activeQuery = query.length >= 2 ? query : "";
    let shown = 0;
    rows.forEach((row) => {
      const searchable = (row.dataset.principalName + " " + row.dataset.principalAccount).toLowerCase();
      row.hidden = !eligible.includes(row) || (state.filter !== "all" && row.dataset.principalType !== state.filter) || !searchable.includes(activeQuery);
      if (!row.hidden) shown++;
    });
    setText("[data-roster-total]", people + " people / " + groups + (groups === 1 ? " group" : " groups"));
    const result = shown + " of " + eligible.length + " shown" + (available ? "" : " / request references");
    setText("[data-roster-count]", result);
    setText("[data-search-hint]", query.length === 1 ? "Enter at least 2 characters to search." : "Search by name or email.");
    find("[data-roster-empty]").hidden = shown > 0;
    all("[data-clear-roster]").forEach((button) => { button.disabled = !query && state.filter === "all"; });
    all("[data-roster-filter]").forEach((button) => {
      const active = button.dataset.rosterFilter === state.filter;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
      button.disabled = !available && button.dataset.rosterFilter === "group";
      button.title = button.disabled ? "Groups require an available directory." : "";
    });
    if (notify) announce(query.length === 1 ? "Enter at least 2 characters to search." : result);
  }

  function updateRequests(notify = false) {
    let shown = 0;
    requestRows.forEach((row) => {
      row.hidden = state.requestFilter !== "all" && row.dataset.requestState !== state.requestFilter;
      if (!row.hidden) shown++;
    });
    const result = shown + " of " + requestRows.length + " shown";
    setText("[data-request-result]", result);
    find("[data-request-empty]").hidden = shown > 0;
    if (notify) announce(result);
  }

  function resetFilters() {
    state.query = "";
    state.filter = "all";
    state.requestFilter = "all";
    find("#iam-user-search").value = "";
    find("[data-request-filter]").value = "all";
  }

  function update() {
    const ownerAccess = isOwner();
    const busy = ["loading", "error"].includes(state.scenario);
    const invalid = !tabIds.includes(state.active);
    const available = state.scenario !== "unavailable";
    find("[data-iam-loading]").hidden = state.scenario !== "loading";
    find("[data-iam-error]").hidden = state.scenario !== "error" && !invalid;
    setText("[data-error-copy]", invalid ? "This identity and access view is not registered. Choose a tab or reset the preview." : "Failed to load identity and access data. No current authorization or directory state is available.");
    setText("[data-scenario-label]", scenarioLabels[state.scenario]);
    tabs.forEach((tab) => {
      const restricted = !ownerAccess && ["users", "requests"].includes(tab.dataset.iamTab);
      tab.disabled = busy || restricted;
      tab.setAttribute("aria-selected", String(tab.dataset.iamTab === state.active));
      tab.tabIndex = !tab.disabled && tab.dataset.iamTab === state.active ? 0 : -1;
      if (restricted) tab.setAttribute("aria-describedby", "iam-owner-required-help");
      else tab.removeAttribute("aria-describedby");
      tab.title = restricted ? "FDAI Owner access required" : "";
      const lock = tab.querySelector(".iam-tab-lock");
      if (lock) lock.hidden = !restricted;
    });
    if (!tabs.some((tab) => tab.tabIndex === 0)) {
      const enabled = tabs.find((tab) => !tab.disabled);
      if (enabled) enabled.tabIndex = 0;
    }
    all("[data-iam-panel]").forEach((panel) => { panel.hidden = busy || invalid || panel.dataset.iamPanel !== state.active; });
    all("[data-iam-locked]").forEach((panel) => { panel.hidden = ownerAccess; });
    all("[data-iam-sensitive]").forEach((panel) => { panel.hidden = !ownerAccess; });
    setText("[data-current-role]", ownerAccess ? "Owner" : "Reader");
    setText("[data-current-account]", ownerAccess ? "owner@example.com" : "reader@example.com");
    setText("[data-management-access]", ownerAccess ? "Available" : "Not assigned");
    setText("[data-owner-title]", ownerAccess ? "FDAI Owner access is verified" : "FDAI Owner access is not assigned");
    find("[data-owner-recovery]").hidden = ownerAccess;
    setText("[data-capability-count]", String(ownerAccess ? owner.length : reader.length));
    find("[data-current-capabilities]").replaceChildren(...(ownerAccess ? owner : reader).map(capability));
    setText("[data-directory-status]", available ? "Available" : "Unavailable");
    find("[data-directory-status]").className = "cs-status " + (available ? "ok" : "idle");
    setText("[data-directory-detail]", available ? "Last authoritative observation: 2026-09-06 03:00 UTC" : "No authoritative directory observation is available in this process.");
    find("[data-roster-unavailable]").hidden = available;
    all("[data-observed-role]").forEach((node) => { node.hidden = !available; });
    all("[data-unknown-role]").forEach((node) => { node.hidden = available; });
    all("button[data-request-role], [data-directory-search] input").forEach((control) => { control.disabled = !ownerAccess || !available; });
    find("[data-directory-assignment]").dataset.requestState = available ? "assigned" : "assignment-pending";
    setText("[data-assigned-status]", available ? "Assigned" : "Assignment pending");
    find("[data-assigned-status]").className = "cs-status " + (available ? "ok" : "wait");
    setText("[data-assigned-evidence]", available ? "Verified by directory" : "Directory verification unavailable");
    updateRoster();
    updateRequests();
  }

  function publishTab(id, push) {
    if (!routeMode) return;
    if (push) history.pushState(null, "", "#" + id);
    if (window.parent !== window) window.parent.postMessage({ type: "fdai:mock-section", section: id }, window.location.origin);
  }

  function selectTab(id, focus, push) {
    const changed = state.active !== id;
    if (changed) editor.closeAll();
    state.active = id;
    update();
    const tab = tabs.find((item) => item.dataset.iamTab === id);
    if (focus && tab && !tab.disabled) tab.focus();
    publishTab(id, push && changed);
    if (changed && push && routeMode) window.scrollTo({ top: 0, behavior: "instant" });
  }

  function clearRoster() {
    state.query = "";
    state.filter = "all";
    find("#iam-user-search").value = "";
    updateRoster(true);
    if (!find("#iam-user-search").disabled) find("#iam-user-search").focus();
  }

  root.addEventListener("click", (event) => {
    const tab = event.target.closest("[data-iam-tab]");
    if (tab && !tab.disabled) selectTab(tab.dataset.iamTab, false, true);
    const filter = event.target.closest("[data-roster-filter]");
    if (filter && !filter.disabled) { state.filter = filter.dataset.rosterFilter; updateRoster(true); }
    if (event.target.closest("[data-clear-roster]")) clearRoster();
    if (event.target.closest("[data-clear-requests]")) {
      state.requestFilter = "all";
      find("[data-request-filter]").value = "all";
      updateRequests(true);
      find("[data-request-filter]").focus();
    }
    const request = event.target.closest("button[data-request-role]");
    if (request && !request.disabled) editor.openRequest(request.closest("[data-principal-name]"), request);
    const review = event.target.closest("[data-review-request]");
    if (review) editor.openReview(review.closest("[data-request-id]"), review);
    if (event.target.closest("[data-open-my-access]")) selectTab("my-access", true, true);
    if (event.target.closest("[data-recover-preview]")) {
      state.scenario = "owner";
      find("[data-iam-scenario]").value = "owner";
      resetFilters();
      selectTab("my-access", true, true);
      announce("Owner preview restored. No live request was made.");
    }
  });
  root.addEventListener("keydown", (event) => {
    const tab = event.target.closest("[data-iam-tab]");
    if (!tab || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    const enabled = tabs.filter((item) => !item.disabled);
    const current = enabled.indexOf(tab);
    const next = event.key === "Home" ? 0 : event.key === "End" ? enabled.length - 1 : current + (event.key === "ArrowRight" ? 1 : -1);
    event.preventDefault();
    selectTab(enabled[(next + enabled.length) % enabled.length].dataset.iamTab, true, true);
  });
  find("[data-directory-search]").addEventListener("submit", (event) => {
    event.preventDefault();
    state.query = find("#iam-user-search").value.trim();
    find("#iam-user-search").value = state.query;
    updateRoster(true);
  });
  find("#iam-user-search").addEventListener("input", (event) => { state.query = event.target.value; updateRoster(true); });
  find("[data-request-filter]").addEventListener("change", (event) => { state.requestFilter = event.target.value; updateRequests(true); });
  find("[data-iam-scenario]").addEventListener("change", (event) => {
    editor.closeAll();
    state.scenario = event.target.value;
    resetFilters();
    update();
    find(".iam-preview-controls").open = false;
    find(".iam-preview-controls summary").focus();
    announce("Preview changed to " + scenarioLabels[state.scenario] + ". Filters and drafts reset.");
  });
  if (routeMode) window.addEventListener("hashchange", () => selectTab(window.location.hash.slice(1) || "my-access", false, false));
  update();
  mount.dataset.iamReady = "true";
}

const mounts = [...document.querySelectorAll("[data-iam-mock]")];
async function loadPreview() {
  if (!mounts.length) return;
  mounts.forEach((mount) => {
    delete mount.dataset.iamReady;
    const loading = element("div", "", "cs-state-block");
    loading.setAttribute("role", "status");
    loading.setAttribute("aria-busy", "true");
    loading.setAttribute("aria-label", "Loading identity and access preview");
    const lines = element("div", "", "cs-state-loading-lines");
    lines.setAttribute("aria-hidden", "true");
    lines.append(element("span", ""), element("span", ""), element("span", ""));
    loading.append(lines);
    mount.replaceChildren(loading);
  });
  try {
    const response = await fetch("assets/settings-iam-content.html?v=workspace-v2");
    if (!response.ok) throw new Error("IAM preview template returned HTTP " + response.status);
    const html = await response.text();
    const template = new DOMParser().parseFromString(html, "text/html").querySelector("[data-iam-content]");
    if (!template) throw new Error("IAM preview template has no content root.");
    mounts.forEach((mount) => initialize(mount, template));
  } catch (error) {
    console.error("IAM preview could not load.", error);
    mounts.forEach((mount) => {
      const message = element("div", "", "iam-error");
      message.setAttribute("role", "alert");
      message.append(element("p", "Unable to load the identity and access preview."));
      const retry = element("button", "Retry preview", "cs-control-button");
      retry.type = "button";
      retry.addEventListener("click", loadPreview, { once: true });
      message.append(retry);
      mount.replaceChildren(message);
    });
  }
}
loadPreview();
