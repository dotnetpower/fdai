/* Browser-only log controls, source scenarios, and audit-waterfall navigation. */
(function () {
  "use strict";
  const P = window.AgentsPreview;
  const D = window.AgentActivityPreviewData;
  const W = window.AgentActivityPreviewWaterfall;
  // Mirrors AGENT_LOG_LIMIT in console/src/routes/agent-activity-log-model.ts, not the live-frame buffer.
  const LOCAL_LOG_LIMIT = 200;
  const esc = P.escape;
  const find = (id) => document.getElementById(id);
  const params = P.params();
  const agentFilter = find("activityAgentFilter");
  const query = find("activityKeywordFilter");
  const correlation = find("activityCorrelation");
  const windowFilter = find("activityWindow");
  const layer = find("activityLayer");
  const verb = find("activityVerb");
  const journal = find("activityJournal");
  const log = find("activityLog");
  const rows = find("activityRows");
  const columns = find("activityColumns");
  const fullscreen = find("activityFullscreen");
  let view = params.get("view") === "waterfall" ? "waterfall" : "activity";
  const requestedStep = Number(params.get("step"));
  let step = Number.isInteger(requestedStep) && requestedStep > 0 ? requestedStep : null;
  let lane = "all";
  let following = true;
  let appended = 0;
  let tailFrame = 0;
  let wasFullscreen = false;
  let originalFocus = null;
  const openRecords = new Set();
  const retainedRows = [...D.audit, ...D.operational].sort((a, b) => Date.parse(a.time) - Date.parse(b.time));
  find("activityRetention").textContent = "Local synthetic retention: latest " + LOCAL_LOG_LIMIT + " rows";
  const lanes = [
    ["all", "All activity"], ["inventory.scan", "Inventory scan"], ["current-state.read", "Current-state read"],
    ["inventory.ontology-projection", "Ontology projection"], ["observation", "Observation"]
  ];
  P.agents.forEach((agent) => agentFilter.add(new Option(agent.name, agent.name)));
  const selectedAgent = P.byName(params.get("agent"));
  if (selectedAgent) agentFilter.value = selectedAgent.name;
  else if (params.get("agent")) {
    agentFilter.add(new Option(params.get("agent") + " (not in pantheon)", params.get("agent")));
    agentFilter.value = params.get("agent");
  }
  query.value = params.get("q") || "";
  [...new Set(retainedRows.map((row) => row.correlation).filter(Boolean))].forEach((id) => correlation.add(new Option(id, id)));
  if (params.get("correlation")) {
    if (![...correlation.options].some((option) => option.value === params.get("correlation"))) correlation.add(new Option(params.get("correlation") + " (not retained)", params.get("correlation")));
    correlation.value = params.get("correlation");
  }
  [windowFilter, layer, verb].forEach((select) => {
    const key = select === windowFilter ? "window" : select === layer ? "layer" : "verb";
    if ([...select.options].some((option) => option.value === params.get(key))) select.value = params.get(key);
  });
  if (lanes.some(([id]) => id === params.get("lane"))) lane = params.get("lane");
  function auditLink(row) {
    return P.href("agent-activity.html", { view: "waterfall", correlation: row.correlation, step: row.seq, window: "7d" });
  }
  function evidenceDetail(row) {
    return P.fields([
      ["Source", row.source], ["Event ID", row.id], ["Recorded / observed at", row.time],
      ["Operational lane", row.lane || "Not an operational lane"], ["Observation domain", row.domain || "Not supplied"],
      ["Correlation", row.correlation || "None"], ["Audit trace", row.seq ? "Supplied synthetic audit record" : "Unavailable; operational correlation only"],
      ["Authority", "No execution or approval is granted by this fixture"]
    ]);
  }
  function rowHtml(row) {
    const correlationCell = row.correlation
      ? row.seq ? '<a href="' + esc(auditLink(row)) + '">' + esc(row.correlation) + '</a><small>Audit trace (sample)</small>' : "<code>" + esc(row.correlation) + "</code><small>No audit trace</small>"
      : "<code>" + esc(row.id) + "</code><small>No correlation</small>";
    return '<tr data-record="' + esc(row.id) + '" data-operational-kind="' + esc(row.lane || "") + '">' +
      '<td data-column="time"><time datetime="' + row.time + '">' + row.time.slice(11, 19) + "</time><small>" + row.time.slice(0, 10) + "</small></td>" +
      '<td data-column="route">' + row.route.map((name) => P.byName(name) ? '<a href="' + esc(P.href("agents-constellation.html", { agent: name })) + '">' + name + "</a>" : esc(name)).join(" -&gt; ") + "</td>" +
      '<td data-column="type">' + esc(row.kind) + '</td><td data-column="detail"><span>' + esc(row.summary) + "</span>" +
      '<details data-record-details="' + esc(row.id) + '"' + (openRecords.has(row.id) ? " open" : "") + '><summary>Evidence details<small class="ap-log-source">' + (row.seq ? "Synthetic audit" : "Synthetic operational") + "</small></summary>" +
      (row.context || row.domain ? '<p class="ap-meta">' + esc([row.domain, row.context].filter(Boolean).join(" - ")) + "</p>" : "") +
      (row.conversation ? '<div class="ap-log-conversation">' + row.conversation.map(([from, to, text]) => "<p><strong>" + esc(from + " -> " + to) + "</strong><br />" + esc(text) + "</p>").join("") + "</div>" : "") +
      evidenceDetail(row) + "</details></td>" +
      '<td data-column="correlation">' + correlationCell + "</td></tr>";
  }
  function filteredRows() {
    const text = query.value.trim().toLowerCase();
    return P.available() ? retainedRows.filter((row) => {
      const participants = [...row.route, ...(row.conversation || []).flatMap(([from, to]) => [from, to])];
      return (!agentFilter.value || participants.includes(agentFilter.value)) &&
        (!correlation.value || row.correlation === correlation.value) &&
        (lane === "all" || row.lane === lane) &&
        (!text || JSON.stringify(row).toLowerCase().includes(text));
    }) : [];
  }
  function filteredAudit() {
    const windows = { "15m": 900000, "1h": 3600000, "24h": 86400000, "7d": 604800000 };
    const latest = Math.max(...D.audit.map((row) => Date.parse(row.time)));
    const text = query.value.trim().toLowerCase();
    return P.available() ? D.audit.filter((row) =>
      Date.parse(row.time) >= latest - windows[windowFilter.value] &&
      (layer.value === "all" || P.byName(row.agent)?.layer === layer.value) &&
      (verb.value === "all" || row.verb === verb.value) &&
      (!correlation.value || row.correlation === correlation.value) &&
      (!text || JSON.stringify(row).toLowerCase().includes(text))) : [];
  }
  function updateColumns() {
    const inputs = [...columns.querySelectorAll("input")];
    if (!inputs.some((input) => input.checked)) inputs.find((input) => input.value === "detail").checked = true;
    inputs.forEach((input) => find("activityTable").querySelectorAll('[data-column="' + input.value + '"]').forEach((cell) => { cell.hidden = !input.checked; }));
  }
  function updateTail(value) {
    following = value;
    find("activityFollow").setAttribute("aria-pressed", String(following));
    find("activityFollow").textContent = following ? "Tail on" : "Resume tail";
    find("activityFollow").setAttribute("aria-label", following ? "Pause automatic scrolling" : "Resume automatic scrolling");
    cancelAnimationFrame(tailFrame);
    if (following && view === "activity") tailFrame = requestAnimationFrame(() => { log.scrollTop = log.scrollHeight; });
  }
  function render() {
    rows.querySelectorAll("[data-record-details]").forEach((detail) => detail.open ? openRecords.add(detail.dataset.recordDetails) : openRecords.delete(detail.dataset.recordDetails));
    const loading = P.source() === "loading";
    const isWaterfall = view === "waterfall";
    journal.hidden = loading || isWaterfall;
    find("activityWaterfallView").hidden = loading || !isWaterfall;
    find("waterfallFilters").hidden = !isWaterfall;
    document.querySelectorAll("[data-view]").forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.view === view)));
    find("activitySelection").hidden = !agentFilter.value;
    const knownAgent = P.byName(agentFilter.value);
    find("activitySelectionText").textContent = agentFilter.value + (!knownAgent ? ": not in the fixed pantheon. Choose an agent or clear filters." : isWaterfall ? ": showing touched audit correlations with other-agent context retained." : ": filtering attributed work and conversation participants.");
    find("activityAgentLink").hidden = !knownAgent;
    find("activityAgentLink").href = P.href("agents-constellation.html", { agent: agentFilter.value });
    const visible = filteredRows();
    rows.innerHTML = visible.map(rowHtml).join("");
    find("activityLogEmpty").hidden = visible.length !== 0;
    find("activityLogEmpty").innerHTML = '<strong>' + (P.available() ? "No rows match the selection." : "Activity evidence unavailable.") + "</strong><p>" +
      (P.available() ? "Change agent, correlation, search, or operational lane. The retained sample is bounded, not a complete history." : "Missing source data is not an observed empty log or an idle fleet.") + "</p>";
    find("activityTable").hidden = visible.length === 0;
    find("activityRowCount").textContent = visible.length + " of " + (P.available() ? retainedRows.length : 0) + " retained synthetic rows";
    find("activityStreamState").textContent = P.retained() ? "Disconnected - last synthetic observations retained" : P.available() ? "Synthetic snapshot - no live connection" : "Source unavailable - no activity inferred";
    find("activityAppend").disabled = P.source() !== "snapshot";
    find("activityAppend").title = P.source() === "snapshot" ? "Append one deterministic local fixture frame; no network request" : "Restore the synthetic snapshot before appending a fixture frame";
    find("activityLanes").innerHTML = lanes.map(([id, title]) => '<button type="button" data-lane="' + id + '" aria-pressed="' + String(lane === id) + '">' + title + "<small>" +
      (P.available() ? retainedRows.filter((row) => id === "all" || row.lane === id).length : "-") + "</small></button>").join("");
    updateColumns();
    if (isWaterfall) W.render(filteredAudit(), agentFilter.value || null, step);
    P.writeParams({
      agent: agentFilter.value || null, q: query.value || null, correlation: correlation.value || null,
      view: isWaterfall ? "waterfall" : null, step: isWaterfall ? step : null, lane: !isWaterfall && lane !== "all" ? lane : null,
      window: isWaterfall && windowFilter.value !== "24h" ? windowFilter.value : null,
      layer: isWaterfall && layer.value !== "all" ? layer.value : null, verb: isWaterfall && verb.value !== "all" ? verb.value : null
    });
    updateTail(following);
  }
  function syncFullscreen() {
    const active = document.fullscreenElement === journal || journal.classList.contains("is-fullscreen-fallback");
    fullscreen.setAttribute("aria-pressed", String(active));
    fullscreen.textContent = active ? "Exit full screen" : "Full screen";
    if (wasFullscreen && !active) {
      document.querySelectorAll("[data-ap-inert]").forEach((node) => { node.inert = false; node.removeAttribute("data-ap-inert"); });
      (originalFocus || fullscreen).focus();
    }
    wasFullscreen = active;
  }
  function exitFallback() {
    journal.classList.remove("is-fullscreen-fallback");
    document.body.classList.remove("ap-fullscreen");
    syncFullscreen();
  }
  function enterFallback() {
    journal.classList.add("is-fullscreen-fallback");
    document.body.classList.add("ap-fullscreen");
    let child = journal;
    while (child.parentElement && child.parentElement !== document.documentElement) {
      [...child.parentElement.children].forEach((sibling) => {
        if (sibling !== child && !sibling.inert && !["SCRIPT", "STYLE", "LINK"].includes(sibling.tagName)) {
          sibling.inert = true;
          sibling.setAttribute("data-ap-inert", "");
        }
      });
      child = child.parentElement;
    }
    syncFullscreen();
    fullscreen.focus();
  }
  fullscreen.addEventListener("click", async () => {
    if (journal.classList.contains("is-fullscreen-fallback")) { exitFallback(); return; }
    if (document.fullscreenElement === journal) {
      try { await document.exitFullscreen(); } catch { fullscreen.title = "Use Escape to exit browser full screen."; }
      return;
    }
    originalFocus = document.activeElement;
    if (!journal.requestFullscreen || document.fullscreenElement) { enterFallback(); return; }
    try { await journal.requestFullscreen(); } catch { enterFallback(); }
  });
  document.addEventListener("fullscreenchange", syncFullscreen);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      if (columns.open) { columns.open = false; columns.querySelector("summary").focus(); }
      if (journal.classList.contains("is-fullscreen-fallback")) exitFallback();
    }
    if (event.key === "Tab" && journal.classList.contains("is-fullscreen-fallback")) {
      const controls = [...journal.querySelectorAll("button:not(:disabled), a, input, summary, [tabindex='0']")].filter((node) => node.getClientRects().length && !node.closest("[hidden]"));
      const first = controls[0], last = controls.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  });
  document.addEventListener("pointerdown", (event) => { if (!columns.contains(event.target)) columns.open = false; });
  columns.addEventListener("change", updateColumns);
  find("activityFollow").addEventListener("click", () => updateTail(!following));
  log.addEventListener("scroll", () => { if (following && log.scrollHeight - log.scrollTop - log.clientHeight > 24) updateTail(false); }, { passive: true });
  document.querySelectorAll("[data-view]").forEach((button) => button.addEventListener("click", () => { view = button.dataset.view; render(); }));
  [agentFilter, correlation, windowFilter, layer, verb].forEach((control) => control.addEventListener("change", render));
  query.addEventListener("input", render);
  find("activityClear").addEventListener("click", () => {
    agentFilter.value = query.value = correlation.value = "";
    windowFilter.value = "24h"; layer.value = verb.value = lane = "all"; step = null;
    render();
  });
  find("activityLanes").addEventListener("click", (event) => {
    const button = event.target.closest("[data-lane]");
    if (!button) return;
    lane = button.dataset.lane;
    render();
    find("activityLanes").querySelector('[data-lane="' + lane + '"]').focus();
  });
  find("activityWaterfallView").addEventListener("click", (event) => {
    const button = event.target.closest("[data-step]");
    if (button) {
      step = Number(button.dataset.step);
      render();
      find("activityStep").querySelector("h2").focus();
    } else if (event.target.closest("[data-close-step]")) {
      const previousStep = step;
      step = null;
      render();
      (find("activityWaterfall").querySelector('[data-step="' + previousStep + '"]') || document.querySelector('[data-view="waterfall"]')).focus();
    } else if (event.target.closest("[data-audit-unavailable]")) {
      P.explainUnavailable("Production audit evidence and hash verification are unavailable. These records are explicitly synthetic.");
    }
  });
  find("activityOlder").addEventListener("click", () => P.explainUnavailable("The preview retains a bounded fixture only. Older evidence requires the authenticated production audit source; no source request was sent."));
  find("activityAppend").addEventListener("click", () => {
    if (P.source() !== "snapshot") return;
    appended += 1;
    retainedRows.push({
      id: "sample-appended-" + appended, time: new Date(Date.parse("2026-09-06T09:47:16Z") + appended * 1000).toISOString(),
      route: ["Heimdall"], lane: "observation", kind: "observation", correlation: "sample-observe", domain: "availability",
      source: "Synthetic operational activity", summary: "Manually appended fixture observation " + appended + "; current runtime readiness remains unverified.",
      context: "Local replay only; not a network frame"
    });
    while (retainedRows.length > LOCAL_LOG_LIMIT) {
      const removed = retainedRows.shift();
      openRecords.delete(removed.id);
    }
    render();
  });
  window.addEventListener("pagehide", () => { cancelAnimationFrame(tailFrame); exitFallback(); });
  P.setupSource(render);
}());
