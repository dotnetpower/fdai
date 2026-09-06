/* Fleet filtering and local synthetic evidence drilldowns; no runtime calls. */
(function () {
  "use strict";
  const P = window.AgentsPreview;
  const esc = P.escape;
  const search = document.getElementById("fleetSearch");
  const attention = document.getElementById("fleetAttention");
  const grid = document.getElementById("fleetGrid");
  const requested = P.params();
  const filters = {
    layer: ["governance", "pipeline", "domain"].includes(requested.get("layer")) ? requested.get("layer") : "all",
    state: ["engaged", "watching", "idle", "unobserved"].includes(requested.get("state")) ? requested.get("state") : "all"
  };
  search.value = requested.get("q") || "";
  attention.checked = requested.get("attention") === "true";
  const openDetails = new Set();
  function card(agent) {
    const state = P.stateOf(agent);
    const current = P.available() && agent.incident ? P.incidents.find((item) => item.id === agent.incident) : null;
    const details = P.fields([
      ["Owns", agent.owns], ["Reports to", (agent.manager || "Root") + (agent.staff ? " (staff)" : "")],
      ["Runtime binding", agent.binding], ["Recent incidents", P.available() ? P.incidents.filter((item) => item.involved.includes(agent.name)).length + " in synthetic history" : "Unavailable"],
      ["Boundary", agent.name === "Thor" ? "Sole governed executor; never judges" : agent.name === "Var" ? "Human approval; separate executor identity" : "No executor authority"],
      ["Flags", agent.flags || "Deterministic-first"], ["Runtime evidence", state === "unobserved" ? "Not observed" : "Synthetic only; not a readiness assessment"]
    ]);
    const incidentHref = current ? P.href("agents-constellation.html", { agent: agent.name, correlation: current.id }) : "";
    return '<article class="fl-card" data-agent="' + agent.slug + '">' +
      '<header class="fl-card-head"><span class="fl-avatar"><img src="../../console/public/agent-icons/' + agent.slug + '.svg" alt="" /></span>' +
      '<div class="fl-identity"><h2>' + agent.name + "</h2><p>" + agent.role + " - " + agent.layer + '</p></div><span class="ap-state is-' + state + '">' + P.stateLabel(agent) + "</span></header>" +
      '<p class="fl-work"><span>' + (P.retained() ? "Retained work" : "Current work in sample") + "</span><strong>" + esc(P.taskOf(agent)) + "</strong></p>" +
      (agent.attention && P.available() ? '<span class="ap-state is-attention">' + esc(agent.attention) + (P.retained() ? " (retained)" : "") + "</span>" : "") +
      '<dl class="ap-kv fl-metrics"><div><dt>' + (P.retained() ? "Last linked incident" : "Active incident") + "</dt><dd>" +
      (current ? '<a href="' + esc(incidentHref) + '">' + current.ticket + "</a>" : state === "unobserved" ? "Unknown" : "None linked") +
      "</dd></div><div><dt>State since (UTC)</dt><dd>" + (state === "unobserved" ? "Not observed" : agent.since) + "</dd></div></dl>" +
      '<details class="fl-details" data-details="' + agent.slug + '"' + (openDetails.has(agent.slug) ? " open" : "") + '><summary>Details</summary><p class="ap-meta">' + esc(agent.summary) + "</p>" + details + "</details>" +
      '<footer class="ap-actions"><a class="ap-button" href="' + esc(P.href("agents-constellation.html", { agent: agent.name })) + '">Open</a>' +
      '<a class="ap-button" href="' + esc(P.href("agent-activity.html", { agent: agent.name })) + '">Activity</a><button type="button" data-ask="' + agent.name + '" aria-label="Ask ' + agent.name + ' in preview">Ask</button></footer></article>';
  }
  function render() {
    grid.querySelectorAll("[data-details]").forEach((node) => node.open ? openDetails.add(node.dataset.details) : openDetails.delete(node.dataset.details));
    const query = search.value.trim().toLowerCase();
    const visible = P.agents.filter((agent) =>
      (filters.layer === "all" || agent.layer === filters.layer) &&
      (filters.state === "all" || (filters.state !== "engaged" || !P.retained()) && P.stateOf(agent) === filters.state) &&
      (!attention.checked || P.available() && agent.attention) &&
      (agent.name + " " + agent.role + " " + agent.owns + " " + P.taskOf(agent)).toLowerCase().includes(query));
    grid.hidden = P.source() === "loading";
    document.querySelector(".fl-summary").hidden = P.source() === "loading";
    document.getElementById("fleetResults").hidden = P.source() === "loading";
    grid.innerHTML = visible.length ? visible.map(card).join("") : '<div class="ap-empty"><strong>No agents match these filters.</strong><p>Try another state or clear the filters. An empty selection does not imply an empty fleet.</p><button type="button" data-clear-fleet>Clear filters</button></div>';
    const count = P.agents.filter((agent) => P.stateOf(agent) !== "unobserved").length;
    document.getElementById("fleetResults").textContent = visible.length + " of 15 agents - " + (P.retained() ? count + " retained observations; current state unknown" : count + " observed in fixture");
    document.querySelectorAll("[data-summary-state]").forEach((button) => {
      const state = button.dataset.summaryState;
      const unavailable = state !== "unobserved" && P.source() !== "snapshot";
      button.querySelector("strong").textContent = unavailable ? "-" : String(P.agents.filter((agent) => P.stateOf(agent) === state).length);
      button.querySelector("small").textContent = unavailable ? "current state unavailable" : state === "unobserved" ? "no runtime evidence" : "synthetic observations";
      button.setAttribute("aria-pressed", String(filters.state === state));
    });
    document.querySelectorAll("[data-filter-group]").forEach((group) => group.querySelectorAll("button").forEach((button) => {
      button.setAttribute("aria-pressed", String(filters[group.dataset.filterGroup] === button.dataset.filter));
    }));
    P.writeParams({ layer: filters.layer === "all" ? null : filters.layer, state: filters.state === "all" ? null : filters.state, q: search.value || null, attention: attention.checked ? "true" : null });
  }
  function clear() {
    filters.layer = filters.state = "all";
    search.value = "";
    attention.checked = false;
    render();
  }
  document.querySelectorAll("[data-filter-group]").forEach((group) => group.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-filter]");
    if (!button) return;
    filters[group.dataset.filterGroup] = button.dataset.filter;
    render();
  }));
  document.querySelectorAll("[data-summary-state]").forEach((button) => button.addEventListener("click", () => {
    filters.state = filters.state === button.dataset.summaryState ? "all" : button.dataset.summaryState;
    render();
  }));
  grid.addEventListener("click", (event) => {
    const ask = event.target.closest("[data-ask]");
    if (ask) P.explainUnavailable("Ask " + ask.dataset.ask + ": a production chat would carry this agent's role and recorded evidence, not confer authority.");
    if (event.target.closest("[data-clear-fleet]")) clear();
  });
  search.addEventListener("input", render);
  attention.addEventListener("change", render);
  document.getElementById("fleetClear").addEventListener("click", clear);
  P.setupSource(render);
}());
