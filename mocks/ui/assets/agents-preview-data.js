/* Synthetic, browser-only fixtures for the three Agents previews. */
(function () {
  "use strict";
  const agents = [
    { name: "Odin", role: "Master Planner", layer: "governance", manager: null, owns: "ArbitrationDecision", state: "idle", since: "09:30:00", work: "Waiting for cross-vertical arbitration", summary: "Cross-vertical arbitration and final tie-breaking before a verdict is finalized." },
    { name: "Heimdall", role: "Observer", layer: "pipeline", manager: "Forseti", owns: "Anomaly, Drift, Forecast, ForecastOutcome", state: "watching", since: "09:42:00", work: "Monitoring discovery freshness and observation coverage", summary: "Correlates signals into findings. Freshness and coverage are evidence, not health guarantees." },
    { name: "Huginn", role: "Event Collector", layer: "pipeline", manager: "Forseti", owns: "Event", state: "watching", since: "09:40:00", work: "Normalizing the synthetic inventory ingress", binding: "raw ingress subscriber", summary: "Owns resource-discovery ingress and event normalization. Cloud I/O remains in adapters." },
    { name: "Forseti", role: "Judge", layer: "pipeline", manager: "Odin", owns: "Verdict, RCA, SecurityEvent, ArbitrationRequest", state: "engaged", runtimeState: "deciding", since: "09:44:58", incident: "sample-change", work: "Reviewing a change that requires human approval", flags: "Hot-path LLM (T2 only)", summary: "Issues auto, hil, or deny verdicts after grounding, cross-check, and deterministic verification." },
    { name: "Var", role: "Approver", layer: "pipeline", manager: "Thor", owns: "Approval", state: "engaged", runtimeState: "approving", since: "09:45:03", incident: "sample-change", attention: "Awaiting human approval", work: "Tracking a pending human approval; no execution authority", summary: "Coordinates human-in-the-loop approval. Human approval and Thor's executor identity stay distinct." },
    { name: "Thor", role: "Responder", layer: "pipeline", manager: "Odin", owns: "ActionRun, ActionAttempt", state: "idle", since: "09:43:00", work: "Waiting for an authorized, verified action", summary: "Sole privileged executor; dispatches governed actions and never judges." },
    { name: "Vidar", role: "Recovery", layer: "pipeline", manager: "Thor", owns: "Rollback", state: "engaged", runtimeState: "executing (shadow)", since: "09:33:07", incident: "sample-recovery", attention: "Recovery probe", work: "Checking the rollback plan in a shadow recovery probe", flags: "Hard dependency", summary: "Owns rollback and disaster-recovery failover, within the governed recovery boundary." },
    { name: "Saga", role: "Auditor", layer: "governance", manager: "Odin", staff: true, owns: "AuditEntry, Issue", state: "watching", since: "09:30:00", work: "Recording terminal outcomes in the audit projection", flags: "Hard dependency", summary: "Records append-only terminal-state evidence and materializes handoffs." },
    { name: "Bragi", role: "Narrator", layer: "pipeline", manager: "Thor", owns: "Conversation, Turn, UserPreference", state: "idle", since: "09:35:00", work: "Waiting for a grounded operator question", flags: "Hot-path LLM (T2 only)", summary: "Conversational-port translator only. Does not call an executor directly or grant authority." },
    { name: "Njord", role: "Cost", layer: "domain", manager: "Forseti", owns: "CostAnomaly, Budget", state: "unobserved", binding: "external adapter", summary: "Cost and FinOps specialist. Advises Forseti and does not execute." },
    { name: "Freyr", role: "Capacity", layer: "domain", manager: "Forseti", owns: "CapacityForecast, SizingRecommendation", state: "unobserved", binding: "external adapter", summary: "Capacity and forecast specialist. Advises Forseti and does not execute." },
    { name: "Loki", role: "Chaos", layer: "domain", manager: "Forseti", owns: "ChaosExperiment, ResilienceScore", state: "unobserved", binding: "scheduled trigger", summary: "Chaos and resilience specialist. Proposes and schedules experiments behind human-approval gates." },
    { name: "Mimir", role: "Rule Steward", layer: "governance", manager: "Odin", staff: true, owns: "Rule, Policy", state: "idle", since: "09:06:00", work: "Waiting for rule-catalog changes", summary: "Owns the rule catalog and grounds Forseti's judgments in current rules." },
    { name: "Norns", role: "Learner", layer: "governance", manager: "Odin", staff: true, owns: "RuleCandidate, Pattern", state: "idle", since: "09:00:00", work: "Waiting for audited outcomes", flags: "Off-path learning", summary: "Learns from audited outcomes and proposes rule revisions to Mimir; does not schedule runtime tasks." },
    { name: "Muninn", role: "Memory", layer: "governance", manager: "Odin", staff: true, owns: "StateSnapshot, ContextIndex", state: "watching", since: "09:29:00", work: "Maintaining prior-incident evidence context", summary: "Supplies memory and prior-incident context to Forseti and Bragi." }
  ].map((item) => ({ binding: "event-bus subscriber", ...item, slug: item.name.toLowerCase() }));

  const incidents = [
    { id: "sample-change", ticket: "SAMPLE-104", title: "Recovery-policy change needs approval", status: "investigating", severity: "high", updated: "09:47:16", involved: ["Forseti", "Var", "Thor", "Saga"], rca: null,
      turns: [["Forseti", "Var", "Deterministic review requires a current human approval for this change."], ["Var", "Forseti", "Approval is pending. Silence does not authorize dispatch."]] },
    { id: "sample-recovery", ticket: "SAMPLE-103", title: "Shadow recovery probe needs evidence", status: "open", severity: "medium", updated: "09:33:07", involved: ["Vidar", "Thor", "Saga"], rca: null,
      turns: [["Vidar", "Thor", "Rollback preconditions are being checked. No managed-resource effect has occurred."]] },
    { id: "sample-observation", ticket: "SAMPLE-102", title: "Synthetic observation gap reviewed", status: "resolved", severity: "low", updated: "09:30:00", involved: ["Huginn", "Heimdall", "Forseti", "Saga"], rca: "Synthetic replay evidence identifies a delayed observation frame. This is a fixture conclusion, not a live diagnosis.",
      turns: [["Huginn", "Heimdall", "The delayed fixture frame is available with its original observation timestamp."], ["Heimdall", "Forseti", "Freshness can be evaluated separately from the resource's health."]] },
    { id: "sample-budget", ticket: "SAMPLE-101", title: "Synthetic cost review archived", status: "resolved", severity: "low", updated: "08:12:44", involved: ["Njord", "Forseti", "Saga"], rca: "Synthetic cost evidence was reviewed without requesting a resource change.",
      turns: [["Njord", "Forseti", "Advisory cost evidence is attached. This does not grant execution authority."]] }
  ];

  const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
  const byName = (name) => agents.find((item) => item.slug === String(name || "").toLowerCase()) || null;
  const params = () => new URLSearchParams(location.search);
  const sourceStates = ["snapshot", "disconnected", "unobserved", "loading", "error"];
  const source = () => document.getElementById("previewState").value;
  const stateOf = (agent) => ["unobserved", "loading", "error"].includes(source()) ? "unobserved" : agent.state;
  const retained = () => source() === "disconnected";
  const available = () => ["snapshot", "disconnected"].includes(source());
  const stateLabel = (agent) => {
    const state = stateOf(agent);
    const label = state === "unobserved" ? state : agent.runtimeState || state;
    return retained() && state !== "unobserved" ? "Last: " + label : label;
  };
  const taskOf = (agent) => stateOf(agent) === "unobserved" ? "Unavailable without a runtime signal" : retained() ? "Current work unknown. Last sample: " + agent.work : agent.work;
  const fields = (pairs) => '<dl class="ap-kv">' + pairs.map(([key, value]) => "<div><dt>" + escape(key) + "</dt><dd>" + escape(value) + "</dd></div>").join("") + "</dl>";
  function writeParams(values) {
    const url = new URL(location.href);
    Object.entries(values).forEach(([key, value]) => value === null || value === "" ? url.searchParams.delete(key) : url.searchParams.set(key, value));
    history.replaceState(null, "", url);
    if (window.fdaiPublishMockRoute) window.fdaiPublishMockRoute();
  }
  function href(page, values = {}) {
    const search = new URLSearchParams({ ...values, ...(source() !== "snapshot" ? { sampleState: source() } : {}) });
    return page + (search.size ? "?" + search.toString() : "");
  }
  function setupSource(onChange) {
    const select = document.getElementById("previewState");
    const requested = params().get("sampleState");
    select.value = sourceStates.includes(requested) ? requested : "snapshot";
    function update() {
      const state = source();
      const notes = {
        snapshot: ["Synthetic snapshot", "Fixture observation time: 2026-09-06 09:47:16 UTC. No backend, live model, or executor is connected."],
        disconnected: ["Disconnected - retained synthetic evidence", "Current state and readiness are unknown. Last fixture observations are retained, not treated as live."],
        unobserved: ["No runtime signals - catalog only", "The 15 role declarations remain available. No runtime readiness, incident absence, or health is inferred."],
        loading: ["Loading scenario - synthetic", "The skeleton represents an in-flight source request. This preview performs no network request."],
        error: ["Source error scenario - synthetic", "The simulated source request failed. This is not an empty result or a healthy runtime."]
      };
      document.getElementById("previewSourceLabel").textContent = notes[state][0];
      document.getElementById("previewSourceNote").textContent = notes[state][1];
      const panel = document.getElementById("previewSourceState");
      panel.hidden = !["loading", "error"].includes(state);
      panel.classList.toggle("is-error", state === "error");
      panel.setAttribute("role", "status");
      panel.setAttribute("aria-busy", String(state === "loading"));
      panel.innerHTML = state === "loading"
        ? '<strong>Loading evidence</strong><div class="ap-skeleton" aria-hidden="true"><span></span><span></span><span></span></div>'
        : state === "error" ? '<strong>Evidence source unavailable</strong><p>No request was sent. Restore the synthetic snapshot to continue exploring.</p><button type="button" data-restore-preview>Restore sample</button>' : "";
      const restore = panel.querySelector("[data-restore-preview]");
      if (restore) restore.addEventListener("click", () => { select.value = "snapshot"; update(); select.focus(); });
      writeParams({ sampleState: state === "snapshot" ? null : state });
      onChange();
    }
    select.addEventListener("change", update);
    update();
  }
  function explainUnavailable(context) {
    let dialog = document.getElementById("agentsPreviewDialog");
    if (!dialog) {
      dialog = document.createElement("dialog");
      dialog.id = "agentsPreviewDialog";
      dialog.className = "ap-dialog";
      dialog.setAttribute("aria-labelledby", "agentsPreviewDialogTitle");
      dialog.innerHTML = '<h2 id="agentsPreviewDialogTitle">Not connected in this preview</h2><p id="agentsPreviewDialogContext"></p><p>Chat, approvals, retries, and privileged operations require the authenticated production Console and server-owned gates. This mock sends no request, opens no conversation, and grants no authority.</p><form method="dialog"><button type="submit" autofocus>Close</button></form>';
    }
    (document.fullscreenElement || document.querySelector(".ap-journal.is-fullscreen-fallback") || document.body).appendChild(dialog);
    document.getElementById("agentsPreviewDialogContext").textContent = context;
    dialog.showModal();
  }
  window.AgentsPreview = { agents, incidents, escape, byName, params, source, stateOf, stateLabel, taskOf, retained, available, fields, href, writeParams, setupSource, explainUnavailable };
}());
