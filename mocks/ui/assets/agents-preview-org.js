/* Fixed reporting tree and role focus for the read-only Org preview. */
(function () {
  "use strict";
  const P = window.AgentsPreview;
  const esc = P.escape;
  const requested = P.params();
  const overlay = requested.get("overlay") === "1";
  if (overlay) document.body.classList.add("ap-role-overlay");
  let selectedAgent = P.byName(requested.get("agent"));
  const tree = document.getElementById("orgTree");
  const focus = document.getElementById("agentFocus");
  const reportingEdges = [
    ["Thor", "Odin", false],
    ["Forseti", "Odin", false],
    ["Vidar", "Thor", false],
    ["Bragi", "Thor", false],
    ["Var", "Thor", false],
    ["Huginn", "Forseti", false],
    ["Heimdall", "Forseti", false],
    ["Njord", "Forseti", false],
    ["Freyr", "Forseti", false],
    ["Loki", "Forseti", false],
    ["Mimir", "Odin", true],
    ["Muninn", "Odin", true],
    ["Saga", "Odin", true],
    ["Norns", "Odin", true]
  ];
  function node(name) {
    const agent = P.byName(name);
    const state = P.stateOf(agent);
    const selected = selectedAgent === agent;
    const classes = [
      "ap-node",
      "layer-" + agent.visualLayer,
      "state-" + state,
      state === "engaged" ? "is-engaged" : "",
      selected ? "is-selected" : ""
    ].filter(Boolean).join(" ");
    const icon = "../../console/public/agent-icons/" + agent.slug + ".svg";
    return '<button type="button" class="' + classes + '" data-agent="' + agent.slug + '" aria-pressed="' + String(selected) + '" aria-label="' + esc(agent.name + ", " + agent.role + ", " + P.stateLabel(agent)) + '">' +
      '<span class="ap-node-ring" aria-hidden="true"><span class="ap-node-icon" style="-webkit-mask-image:url(' + icon + ');mask-image:url(' + icon + ')"></span></span>' +
      '<span class="ap-node-name">' + esc(agent.name) + '</span><span class="ap-node-role">' + esc(agent.role) + '</span>' +
      '<span class="ap-node-tooltip" role="tooltip"><span class="ap-node-tooltip-head"><strong>' + esc(agent.name) + '</strong><span class="ap-state is-' + state + '">' + esc(P.stateLabel(agent)) + "</span></span></span></button>";
  }
  function drawReportingLines() {
    const svg = tree.querySelector(".ap-org-lines");
    if (!svg || tree.clientWidth === 0 || tree.clientHeight === 0) return;
    const origin = tree.getBoundingClientRect();
    tree.querySelectorAll(".ap-node").forEach((agentNode) => {
      agentNode.classList.remove("tooltip-align-left", "tooltip-align-right");
      const nodeBox = agentNode.getBoundingClientRect();
      const tooltip = agentNode.querySelector(".ap-node-tooltip");
      const tooltipWidth = tooltip.getBoundingClientRect().width;
      const center = nodeBox.left + nodeBox.width / 2;
      if (center - tooltipWidth / 2 < origin.left + 8) {
        agentNode.classList.add("tooltip-align-left");
      } else if (center + tooltipWidth / 2 > origin.right - 8) {
        agentNode.classList.add("tooltip-align-right");
      }
    });
    svg.setAttribute("width", String(origin.width));
    svg.setAttribute("height", String(origin.height));
    svg.setAttribute("viewBox", "0 0 " + origin.width + " " + origin.height);
    svg.replaceChildren();
    reportingEdges.forEach(([fromName, toName, staff]) => {
      const from = tree.querySelector('[data-agent="' + P.byName(fromName).slug + '"]');
      const to = tree.querySelector('[data-agent="' + P.byName(toName).slug + '"]');
      if (!from || !to) return;
      const fromBox = from.getBoundingClientRect();
      const toBox = to.getBoundingClientRect();
      const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
      line.setAttribute("class", "ap-org-edge" + (staff ? " is-staff" : ""));
      line.setAttribute("x1", String(fromBox.left + fromBox.width / 2 - origin.left));
      line.setAttribute("y1", String(fromBox.top + fromBox.height / 2 - origin.top));
      line.setAttribute("x2", String(toBox.left + toBox.width / 2 - origin.left));
      line.setAttribute("y2", String(toBox.top + toBox.height / 2 - origin.top));
      svg.appendChild(line);
    });
  }
  function renderFocus() {
    if (!selectedAgent) {
      focus.innerHTML = '<span class="ap-focus-kicker">Selected role</span><h2>Select an agent</h2><p class="ap-meta">Inspect its responsibility, reporting line, owned object types, and observed runtime state.</p><p class="ap-role-boundary">This view describes accountability. It grants no judgment, approval, execution, or recovery authority.</p>';
      return;
    }
    const agent = selectedAgent;
    focus.innerHTML = '<header class="ap-section-head"><div><span class="ap-focus-kicker">Selected role</span><h2>' + esc(agent.name) + " / " + esc(agent.role) + '</h2></div><button type="button" data-close-focus aria-label="Close agent focus">Close</button></header><p>' + esc(agent.summary) + "</p>" +
      P.fields([["Reports to", (agent.manager || "Organization root") + (agent.staff ? " (staff)" : "")], ["Observed state", P.stateLabel(agent)], ["Runtime binding", agent.binding], ["Owns", agent.owns]]) +
      '<p class="ap-role-boundary">This view describes accountability. It grants no judgment, approval, execution, or recovery authority.</p><div class="ap-actions"><a class="ap-button" href="' + esc(P.href("agent-activity.html", { view: "waterfall", agent: agent.name })) + '"' + (overlay ? ' target="_top"' : "") + '>Open ' + esc(agent.name) + ' activity</a></div>';
  }
  function render() {
    tree.innerHTML = '<svg class="ap-org-lines" aria-hidden="true"></svg><div class="ap-org-structure"><div class="ap-org-tier ap-org-root">' + node("Odin") + '</div><div class="ap-org-tier ap-org-branches">' +
      [{ manager: "Thor", reports: ["Vidar", "Bragi", "Var"] }, { manager: "Forseti", reports: ["Huginn", "Heimdall", "Njord", "Freyr", "Loki"] }].map((branch) =>
        '<section class="ap-org-branch"><div class="ap-org-manager">' + node(branch.manager) + '</div><div class="ap-org-reports" aria-label="Reports to ' + branch.manager + '">' + branch.reports.map(node).join("") + "</div></section>").join("") +
      '<section class="ap-org-branch ap-org-staff"><h3>Staff to Odin</h3><div class="ap-org-reports">' + ["Mimir", "Muninn", "Saga", "Norns"].map(node).join("") + "</div></section></div></div>";
    document.getElementById("orgWorkspace").hidden = P.source() === "loading";
    renderFocus();
    P.writeParams({ agent: selectedAgent ? selectedAgent.name : null });
    if (overlay) {
      window.parent.postMessage({
        type: "fdai:role-agent",
        agent: selectedAgent ? selectedAgent.name : null
      }, location.origin);
    }
    drawReportingLines();
  }
  document.getElementById("orgWorkspace").addEventListener("click", (event) => {
    const agent = event.target.closest("[data-agent]");
    if (agent) {
      const nextAgent = P.byName(agent.dataset.agent);
      selectedAgent = selectedAgent === nextAgent ? null : nextAgent;
      render();
      tree.querySelector('[data-agent="' + nextAgent.slug + '"]').focus();
    } else if (event.target.closest("[data-close-focus]")) {
      const slug = selectedAgent.slug;
      selectedAgent = null;
      render();
      tree.querySelector('[data-agent="' + slug + '"]').focus();
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
  document.addEventListener("keydown", (event) => {
    if (!overlay || event.key !== "Escape") return;
    event.preventDefault();
    window.parent.postMessage({ type: "fdai:role-dialog-close" }, location.origin);
  });
  window.addEventListener("resize", drawReportingLines);
  if ("ResizeObserver" in window) {
    let observedSize = `${tree.clientWidth}x${tree.clientHeight}`;
    new ResizeObserver(() => {
      const nextSize = `${tree.clientWidth}x${tree.clientHeight}`;
      if (nextSize === observedSize) return;
      observedSize = nextSize;
      drawReportingLines();
    }).observe(tree);
  }
  P.setupSource(render);
}());
