/* Fixed reporting tree and independent agent/incident focus for the Org preview. */
(function () {
  "use strict";
  const P = window.AgentsPreview;
  const esc = P.escape;
  const requested = P.params();
  let selectedAgent = P.byName(requested.get("agent"));
  let selectedId = requested.get("correlation") || P.incidents[0].id;
  let following = !requested.has("correlation");
  const tree = document.getElementById("orgTree");
  const focus = document.getElementById("agentFocus");
  const list = document.getElementById("incidentList");
  const workflow = document.getElementById("incidentWorkflow");
  const status = document.getElementById("incidentStatus");
  function node(name) {
    const agent = P.byName(name);
    const incident = P.available() ? P.incidents.find((item) => item.id === selectedId) : null;
    const involved = incident && incident.involved.includes(name);
    return '<button type="button" class="ap-node" data-agent="' + agent.slug + '" aria-pressed="' + String(selectedAgent === agent) + '">' +
      '<img src="../../console/public/agent-icons/' + agent.slug + '.svg" alt="" /><span class="ap-node-copy"><strong>' + name + "</strong><small>" + agent.role + '</small><span class="ap-state is-' + P.stateOf(agent) + '">' + P.stateLabel(agent) + "</span>" +
      (involved ? '<span class="ap-participation">In selected incident</span>' : "") + "</span></button>";
  }
  function incidentButton(incident) {
    return '<button type="button" class="ap-incident" data-incident="' + incident.id + '" aria-pressed="' + String(incident.id === selectedId) + '"><span>' + incident.status + "</span><small>" + incident.ticket + "</small><strong>" + incident.title + "</strong><small>" + incident.severity + " severity</small><small>" + incident.updated + " UTC</small></button>";
  }
  function renderFocus() {
    if (!selectedAgent) {
      focus.innerHTML = '<h2>Agent focus</h2><p class="ap-meta">Select an agent to inspect its role, reporting line, runtime evidence, and incident participation.</p>';
      return;
    }
    const agent = selectedAgent;
    const relevant = P.available() ? P.incidents.filter((item) => item.involved.includes(agent.name)) : [];
    focus.innerHTML = '<header class="ap-section-head"><h2>' + agent.name + " / " + agent.role + '</h2><button type="button" data-close-focus aria-label="Close agent focus">Close</button></header><p>' + agent.summary + "</p>" +
      P.fields([["Reports to", (agent.manager || "Root") + (agent.staff ? " (staff)" : "")], ["State", P.stateLabel(agent)], ["Binding", agent.binding], ["Owns", agent.owns]]) +
      "<p>" + esc(P.taskOf(agent)) + '</p><div class="ap-actions"><a class="ap-button" href="' + esc(P.href("agent-activity.html", { agent: agent.name })) + '">Activity</a><button type="button" data-ask>Chat with ' + agent.name + "</button></div>" +
      '<details open><summary>Related incidents (' + (P.available() ? relevant.length : "unknown") + ")</summary>" +
      (relevant.length ? relevant.map(incidentButton).join("") : '<p class="ap-meta">' + (P.available() ? "No participation in the retained synthetic incidents. This does not imply the agent is idle." : "Incident evidence unavailable in this scenario.") + "</p>") + "</details>";
  }
  function renderWorkflow() {
    const incident = P.available() ? P.incidents.find((item) => item.id === selectedId) : null;
    if (!incident) {
      workflow.innerHTML = '<h2>Incident detail</h2><p class="ap-meta">' + (P.available() ? "No retained incident matches the selected correlation. Choose an incident above." : "No incident evidence is available. Catalog declarations cannot reconstruct an incident.") + "</p>";
      return;
    }
    const completed = incident.status === "resolved" ? 3 : incident.status === "investigating" ? 2 : 1;
    workflow.innerHTML = '<header class="ap-section-head"><h2>' + incident.ticket + '</h2><span class="ap-badge">' + incident.status + "</span></header><p><strong>" + incident.title + "</strong></p>" +
      '<p class="ap-meta">' + incident.severity + " severity - " + (P.retained() ? "retained" : "synthetic") + " evidence - " + incident.updated + " UTC</p>" +
      '<ol class="ap-steps" aria-label="Incident progress">' + ["Detect", "Ticket", "RCA", "Resolve"].map((label, index) => '<li' + (index === completed ? ' aria-current="step"' : "") + "><strong>" + label + "</strong><small>" + (index < completed || incident.status === "resolved" ? "complete" : index === completed ? "current" : "pending") + "</small></li>").join("") + "</ol>" +
      '<h3>Root cause</h3><p>' + (incident.rca || "Not established. Pending evidence or review; correlation alone does not establish causation.") + "</p>" +
      '<div class="ap-actions"><a class="ap-button" href="' + esc(P.href("agent-activity.html", { correlation: incident.id })) + '">Related activity</a><a class="ap-button" href="' + esc(P.href("agent-activity.html", { view: "waterfall", correlation: incident.id })) + '">Audit waterfall</a><button type="button" data-ask>Ask about incident</button></div>' +
      '<details open><summary>Agent collaboration (' + incident.turns.length + ')</summary><p class="ap-meta">Synthetic event-bus messages, not direct agent calls.</p><ol class="ap-conversation">' +
      incident.turns.map(([from, to, text]) => "<li><strong>" + from + " -&gt; " + to + "</strong><p>" + esc(text) + "</p></li>").join("") + "</ol></details>" +
      '<details><summary>Evidence boundary</summary><p class="ap-meta">All incident IDs and observations are synthetic. Local activity preserves this correlation. External RCA, approval, and trace services are not connected.</p><code>' + incident.id + "</code></details>";
  }
  function render() {
    tree.innerHTML = '<div class="ap-org-root">' + node("Odin") + '</div><div class="ap-org-branches">' +
      [{ manager: "Thor", reports: ["Vidar", "Bragi", "Var"] }, { manager: "Forseti", reports: ["Huginn", "Heimdall", "Njord", "Freyr", "Loki"] }].map((branch) =>
        '<section class="ap-org-branch"><h3>Reports to Odin</h3>' + node(branch.manager) + '<ul aria-label="Reports to ' + branch.manager + '">' + branch.reports.map((name) => "<li>" + node(name) + "</li>").join("") + "</ul></section>").join("") +
      '</div><section class="ap-org-staff"><h3>Staff to Odin - governance</h3><ul>' + ["Mimir", "Muninn", "Saga", "Norns"].map((name) => "<li>" + node(name) + "</li>").join("") + "</ul></section>";
    document.getElementById("orgWorkspace").hidden = P.source() === "loading";
    const visible = P.available() ? P.incidents.filter((item) => status.value === "all" || item.status === status.value) : [];
    list.innerHTML = visible.length ? visible.map(incidentButton).join("") : '<p class="ap-empty">' + (P.available() ? "No incidents match this status." : "Incident source unavailable, not an observed empty result.") + "</p>";
    renderFocus();
    renderWorkflow();
    const follow = document.getElementById("incidentFollow");
    follow.setAttribute("aria-pressed", String(following));
    follow.textContent = following ? "Following latest" : "Follow latest";
    follow.title = "Follow the newest retained synthetic incident; no live subscription.";
    P.writeParams({ agent: selectedAgent ? selectedAgent.name : null, correlation: following ? null : selectedId });
  }
  document.getElementById("orgWorkspace").addEventListener("click", (event) => {
    const agent = event.target.closest("[data-agent]");
    const incident = event.target.closest("[data-incident]");
    if (agent) {
      selectedAgent = P.byName(agent.dataset.agent);
      render();
      tree.querySelector('[data-agent="' + selectedAgent.slug + '"]').focus();
    } else if (incident) {
      selectedId = incident.dataset.incident;
      following = false;
      const container = focus.contains(incident) ? focus : list;
      render();
      container.querySelector('[data-incident="' + selectedId + '"]')?.focus();
    } else if (event.target.closest("[data-close-focus]")) {
      const slug = selectedAgent.slug;
      selectedAgent = null;
      render();
      tree.querySelector('[data-agent="' + slug + '"]').focus();
    } else if (event.target.closest("[data-ask]")) {
      P.explainUnavailable("Agent or incident chat is unavailable. The selection remains local to this synthetic preview.");
    }
  });
  tree.addEventListener("keydown", (event) => {
    if (!["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    const buttons = [...tree.querySelectorAll("[data-agent]")];
    const index = buttons.indexOf(document.activeElement);
    if (index < 0) return;
    event.preventDefault();
    const next = event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1 : (index + (["ArrowUp", "ArrowLeft"].includes(event.key) ? -1 : 1) + buttons.length) % buttons.length;
    buttons[next].focus();
  });
  status.addEventListener("change", render);
  document.getElementById("incidentFollow").addEventListener("click", () => {
    following = !following;
    if (following) selectedId = P.incidents[0].id;
    render();
  });
  P.setupSource(render);
}());
