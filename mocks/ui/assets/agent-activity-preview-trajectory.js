/* Trajectory view: one governed-shaped trajectory per correlation, rendered step by step.
   Only observable inputs, outputs, decisions, and receipts are shown; model reasoning is never captured. */
(function () {
  "use strict";
  const P = window.AgentsPreview;
  const T = window.AgentActivityPreviewTrajectories;
  const esc = P.escape;
  const KIND = {
    normalized_input_reference: "Input received",
    routing_decision: "Routing decision",
    assistant_output: "Answer composed",
    tool_request: "Tool request",
    tool_receipt: "Tool result",
    action_request: "Action requested",
    action_receipt: "Action receipt",
    verifier_result: "Verification",
    risk_result: "Risk assessment",
    approval: "Approval",
    terminal_outcome: "Terminal outcome",
    rollback_state: "Rollback state"
  };
  const PHASES = [
    ["intake", "Intake", ["normalized_input_reference"]],
    ["evidence", "Evidence", ["tool_request", "tool_receipt"]],
    ["judgment", "Judgment", ["routing_decision", "verifier_result", "risk_result", "assistant_output"]],
    ["authorization", "Authorization", ["approval"]],
    ["execution", "Execution", ["action_request", "action_receipt", "rollback_state"]],
    ["outcome", "Outcome", ["terminal_outcome"]]
  ];
  const ATTENTION = new Set(["failed", "partial", "pending", "hil", "unproven", "abstained"]);
  const BAD = new Set(["failed"]);
  const OUTCOME_LABEL = { completed: "Completed", failed: "Failed", cancelled: "Cancelled", timed_out: "Timed out", abstained: "Abstained", ambiguous: "Ambiguous" };
  const opened = new Map();
  let selected = P.params().get("trajectory");
  let requestedStep = Number.parseInt(P.params().get("trajectoryStep") || "", 10);
  let onChange = () => {};

  const time = (value) => Date.parse(value);
  const startOf = (step) => time(step.at) - step.ms;
  function span(trajectory) {
    const start = Math.min(...trajectory.steps.map(startOf));
    const end = Math.max(...trajectory.steps.map((step) => time(step.at)));
    return { start, end, total: Math.max(end - start, 1) };
  }
  function duration(ms) {
    if (ms < 1000) return Math.round(ms) + " ms";
    if (ms < 60000) return (ms / 1000).toFixed(ms < 10000 ? 2 : 1) + " s";
    const minutes = Math.floor(ms / 60000);
    return minutes + " min " + Math.round((ms % 60000) / 1000) + " s";
  }
  const offset = (ms) => "+" + duration(ms);
  const clock = (value) => new Date(value).toISOString().slice(11, 23);
  const stamp = (value) => new Date(value).toISOString().replace("T", " ").slice(0, 19) + " UTC";
  function digest(seed) {
    let hex = "";
    let state = 2166136261;
    for (let round = 0; round < 8; round += 1) {
      for (const char of seed + ":" + round) state = Math.imul(state ^ char.charCodeAt(0), 16777619) >>> 0;
      hex += state.toString(16).padStart(8, "0");
    }
    return hex;
  }
  function tone(status) {
    if (BAD.has(status)) return "bad";
    if (ATTENTION.has(status)) return "attention";
    return "neutral";
  }
  function agentsOf(trajectory) {
    return [...new Set(trajectory.steps.map((step) => step.agent))];
  }
  function outcomeOf(trajectory) {
    return trajectory.terminal ? OUTCOME_LABEL[trajectory.terminal] : "Open";
  }
  function matches(trajectory, filters) {
    const text = filters.query.trim().toLowerCase();
    return (!filters.agent || agentsOf(trajectory).includes(filters.agent)) &&
      (!filters.correlation || trajectory.correlation === filters.correlation) &&
      (!text || JSON.stringify(trajectory).toLowerCase().includes(text));
  }

  function listHtml(items, current) {
    return '<ul class="tj-list-items">' + items.map((trajectory) => {
      const s = span(trajectory);
      return '<li><button type="button" class="tj-item" data-trajectory="' + esc(trajectory.correlation) + '" aria-pressed="' + String(trajectory === current) + '" aria-controls="activityTrajectoryDetail">' +
        '<span class="tj-item-head"><strong>' + esc(trajectory.title) + '</strong><span class="tj-status" data-tone="' + (trajectory.terminal ? tone(trajectory.terminal) : "attention") + '">' + esc(outcomeOf(trajectory)) + "</span></span>" +
        '<span class="tj-item-route">' + agentsOf(trajectory).map(esc).join(" &rarr; ") + "</span>" +
        '<span class="tj-item-meta"><code>' + esc(trajectory.correlation) + "</code><span>" + trajectory.steps.length + " steps &middot; " + duration(s.total) + " &middot; " + esc(trajectory.tier) + "</span></span>" +
        "</button></li>";
    }).join("") + "</ul>";
  }

  function phasesHtml(trajectory) {
    return '<ol class="tj-phases" aria-label="Lifecycle phases">' + PHASES.map(([id, label, kinds]) => {
      const steps = trajectory.steps.filter((step) => kinds.includes(step.kind));
      let state = "done";
      let note = steps.length + (steps.length === 1 ? " step" : " steps");
      if (!steps.length) {
        state = trajectory.terminal ? "skipped" : "waiting";
        note = trajectory.terminal ? "Not required" : "Not reached";
      } else if (steps.some((step) => BAD.has(step.status))) {
        state = "failed";
        note = "Failed";
      } else if (steps.some((step) => ATTENTION.has(step.status))) {
        state = "attention";
        note = steps.find((step) => ATTENTION.has(step.status)).status === "pending" ? "Pending" : "Needs review";
      }
      return '<li data-phase="' + id + '" data-state="' + state + '"><strong>' + label + "</strong><small>" + esc(note) + "</small></li>";
    }).join("") + "</ol>";
  }

  function json(value) {
    return "<pre>" + esc(JSON.stringify(value, null, 2)) + "</pre>";
  }
  function pairs(object) {
    return P.fields(Object.entries(object).map(([key, value]) => [key.replace(/_/g, " "), Array.isArray(value) ? value.join(", ") : value]));
  }
  function stepBody(trajectory, step, index) {
    const parts = [];
    if (step.input) parts.push('<section><h4>Received</h4>' + json(step.input) + "</section>");
    if (step.output) parts.push('<section><h4>Produced</h4>' + json(step.output) + "</section>");
    if (step.decision) parts.push('<section><h4>Decision basis</h4>' + pairs(step.decision) + "</section>");
    if (step.tool) parts.push('<section><h4>Tool call</h4>' + pairs(step.tool) + "</section>");
    if (step.checks) {
      parts.push('<section><h4>Checks</h4><ul class="tj-checks">' + step.checks.map(([name, result]) =>
        '<li><span class="tj-status" data-tone="' + tone(result) + '">' + esc(P.label(result)) + "</span>" + esc(name) + "</li>").join("") + "</ul></section>");
    }
    if (step.safeguards) {
      parts.push('<section class="tj-wide"><h4>Safeguards</h4><dl class="tj-safeguards">' + step.safeguards.map(([name, value]) =>
        "<div><dt>" + esc(name) + "</dt><dd>" + esc(value) + "</dd></div>").join("") + "</dl></section>");
    }
    if (step.conversation) {
      parts.push('<section><h4>Agent message</h4>' + step.conversation.map(([from, to, text]) =>
        '<p class="tj-message"><strong>' + esc(from) + " &rarr; " + esc(to) + "</strong>" + esc(text) + "</p>").join("") + "</section>");
    }
    if (step.handoff) {
      parts.push('<section><h4>Handoff</h4><p>Published <code>' + esc(step.handoff.topic) + "</code> on the event bus. Subscribers: " + step.handoff.to.map(esc).join(", ") + ". No direct agent call.</p></section>");
    }
    const sha = digest(trajectory.correlation + ":" + step.source.id);
    parts.push('<section><h4>Source record</h4>' + P.fields([
      ["Record", step.source.type + " / " + step.source.id],
      ["Recorded at", step.at],
      ["Digest (synthetic)", "sha256:" + sha.slice(0, 12) + "\u2026" + sha.slice(-8)],
      ["Trajectory sequence", String(index)]
    ]) + "</section>");
    return '<div class="tj-step-body">' + parts.join("") + "</div>";
  }

  function stepsHtml(trajectory, filters) {
    const s = span(trajectory);
    const key = trajectory.correlation;
    if (!opened.has(key)) {
      const preset = Number.isInteger(requestedStep) && trajectory.correlation === selected ? requestedStep : -1;
      const firstAttention = trajectory.steps.findIndex((step) => ATTENTION.has(step.status));
      opened.set(key, new Set([preset >= 0 ? preset : firstAttention].filter((index) => index >= 0)));
    }
    const open = opened.get(key);
    const ruler = [0, 0.25, 0.5, 0.75, 1].map((fraction) => "<span>" + offset(s.total * fraction) + "</span>").join("");
    return '<div class="tj-ruler" aria-hidden="true"><span></span><span class="tj-ruler-scale">' + ruler + "</span></div>" +
      '<ol class="tj-steps">' + trajectory.steps.map((step, index) => {
        const left = (startOf(step) - s.start) / s.total * 100;
        const width = Math.max(step.ms / s.total * 100, 0.8);
        const context = filters.agent && step.agent !== filters.agent ? " is-context" : "";
        return '<li class="tj-step' + context + '" data-kind="' + step.kind + '"><details data-step-index="' + index + '"' + (open.has(index) ? " open" : "") + ">" +
          '<summary><span class="tj-seq">' + index + "</span>" +
          '<span class="tj-when"><time datetime="' + step.at + '">' + offset(time(step.at) - s.start) + "</time><small>" + clock(step.at) + "</small></span>" +
          '<span class="tj-main"><span class="tj-kind"><strong>' + esc(step.agent) + "</strong> " + esc(KIND[step.kind]) + "</span><span>" + esc(step.summary) + "</span></span>" +
          '<span class="tj-bar" title="' + esc(duration(step.ms)) + '"><span class="tj-track"><span data-tone="' + tone(step.status) + '" style="left:' + left.toFixed(2) + "%;width:" + width.toFixed(2) + '%"></span></span><small>' + duration(step.ms) + "</small></span>" +
          '<span class="tj-status" data-tone="' + tone(step.status) + '">' + esc(P.label(step.status)) + "</span>" +
          "</summary>" + stepBody(trajectory, step, index) + "</details></li>";
      }).join("") + "</ol>";
  }

  function toolsHtml(trajectory) {
    const counts = new Map(T.toolCatalog.map((id) => [id, [0, 0, 0]]));
    trajectory.steps.forEach((step) => {
      if (!step.tool) return;
      const row = counts.get(step.tool.id);
      if (step.kind === "tool_request") row[0] += 1;
      if (step.kind === "tool_receipt") row[step.tool.status === "succeeded" ? 1 : 2] += 1;
    });
    return '<table class="tj-tools"><caption>Tool calls in catalog order, including unused tools</caption><thead><tr><th scope="col">Tool</th><th scope="col">Requests</th><th scope="col">Succeeded</th><th scope="col">Failed</th></tr></thead><tbody>' +
      [...counts].map(([id, [requests, succeeded, failed]]) => '<tr' + (requests ? "" : ' class="is-unused"') + '><th scope="row"><code>' + esc(id) + "</code></th><td>" + requests + "</td><td>" + succeeded + "</td><td" + (failed ? ' data-tone="bad"' : "") + ">" + failed + "</td></tr>").join("") +
      "</tbody></table>";
  }

  function detailHtml(trajectory, filters) {
    const s = span(trajectory);
    const sources = trajectory.steps.reduce((map, step) => map.set(step.source.type, (map.get(step.source.type) || 0) + 1), new Map());
    const incident = trajectory.incident ? '<a class="ap-button" href="' + esc(P.href("incidents.html", { correlation: trajectory.correlation })) + '">Incident ' + esc(trajectory.incident) + "</a>" : "";
    return '<header class="tj-head"><div><span class="tj-eyebrow">Trajectory <code>' + esc(trajectory.correlation) + "</code></span>" +
      '<h2 id="activityTrajectoryTitle" tabindex="-1">' + esc(trajectory.title) + "</h2><p>" + esc(trajectory.trigger) + "</p></div>" +
      '<span class="tj-status tj-status-lg" data-tone="' + (trajectory.terminal ? tone(trajectory.terminal) : "attention") + '">' + esc(trajectory.status) + "</span></header>" +
      '<p class="tj-authority">' + esc(trajectory.authority) + "</p>" +
      (trajectory.terminal ? "" : '<p class="tj-open-note" role="note">Open trajectory: no terminal outcome is recorded yet. This is a partial view of retained records, not a governed trajectory export.</p>') +
      '<dl class="tj-facts">' + [
        ["Started", stamp(s.start)],
        [trajectory.terminal ? "Finished" : "Last step", stamp(s.end)],
        ["Elapsed", duration(s.total)],
        ["Steps", String(trajectory.steps.length)],
        ["Agents", agentsOf(trajectory).join(", ")],
        ["Tier", trajectory.tier],
        ["Mode", P.label(trajectory.mode)],
        ["Terminal outcome", outcomeOf(trajectory)]
      ].map(([key, value]) => "<div><dt>" + esc(key) + "</dt><dd>" + esc(value) + "</dd></div>").join("") + "</dl>" +
      phasesHtml(trajectory) +
      '<section class="tj-timeline" aria-labelledby="activityTrajectoryStepsTitle"><div class="ap-section-head"><h3 id="activityTrajectoryStepsTitle">Steps</h3>' +
      '<div class="ap-actions"><button type="button" data-trajectory-expand="all">Expand all</button><button type="button" data-trajectory-expand="none">Collapse all</button></div></div>' +
      '<p class="ap-meta">Clock times are UTC. Bars place each step on one time scale: receipts span their request latency, other steps their recorded processing time. Only observable inputs, outputs, and receipts are recorded; model reasoning is not captured.</p>' +
      stepsHtml(trajectory, filters) + "</section>" +
      '<section class="tj-section"><h3>Tool calls</h3>' + toolsHtml(trajectory) + "</section>" +
      '<details class="tj-provenance"><summary>Trajectory provenance</summary>' + P.fields([
        ["Schema", "Trajectory envelope 1.0 (synthetic)"],
        ["Trajectory ID", "trace-sample:" + trajectory.correlation],
        ["Source records", [...sources].map(([type, count]) => count + " " + type).join(", ")],
        ["Evidence profile", "Synthetic fixture"],
        ["Redaction policy", "redaction-sample-v2"],
        ["Export state", trajectory.terminal ? "Eligible after access authorization" : "Not exportable until terminal"]
      ]) + "</details>" +
      '<div class="ap-actions"><a class="ap-button" href="' + esc(P.href("rule-trace.html", { correlation: trajectory.correlation })) + '">Open trace</a>' +
      '<button type="button" data-trajectory-log="' + esc(trajectory.correlation) + '">Show in activity log</button>' + incident + "</div>";
  }

  function render(filters) {
    const view = document.getElementById("activityTrajectoryView");
    const list = document.getElementById("activityTrajectoryList");
    const detail = document.getElementById("activityTrajectoryDetail");
    const count = document.getElementById("activityTrajectoryCount");
    detail.querySelectorAll("details[data-step-index]").forEach((node) => {
      const set = opened.get(view.dataset.current);
      if (set) node.open ? set.add(Number(node.dataset.stepIndex)) : set.delete(Number(node.dataset.stepIndex));
    });
    if (!P.available()) {
      count.textContent = "Trajectory evidence unavailable";
      list.innerHTML = "";
      detail.innerHTML = '<div class="ap-empty"><strong>Trajectory evidence unavailable.</strong><p>Missing source data is not an empty history or an idle fleet.</p></div>';
      view.dataset.current = "";
      return;
    }
    const items = T.trajectories.filter((trajectory) => matches(trajectory, filters))
      .sort((left, right) => span(right).start - span(left).start);
    const current = items.find((trajectory) => trajectory.correlation === selected) || items[0] || null;
    count.textContent = items.length + " of " + T.trajectories.length + " synthetic trajectories" + (P.retained() ? " - retained, not live" : "");
    list.innerHTML = items.length ? listHtml(items, current) : "";
    detail.innerHTML = current ? detailHtml(current, filters)
      : '<div class="ap-empty"><strong>No trajectories match the selection.</strong><p>Change the agent, correlation, or search. Operational-only activity without audit records does not form a trajectory.</p></div>';
    view.dataset.current = current ? current.correlation : "";
    P.writeParams({ trajectory: current && current.correlation !== (items[0] || {}).correlation ? current.correlation : null });
  }

  function bind(handlers) {
    onChange = handlers.onChange;
    const view = document.getElementById("activityTrajectoryView");
    view.addEventListener("click", (event) => {
      const item = event.target.closest("[data-trajectory]");
      if (item) {
        selected = item.dataset.trajectory;
        requestedStep = Number.NaN;
        onChange();
        document.getElementById("activityTrajectoryTitle").focus();
        return;
      }
      const expand = event.target.closest("[data-trajectory-expand]");
      if (expand) {
        const all = expand.dataset.trajectoryExpand === "all";
        view.querySelectorAll("details[data-step-index]").forEach((node) => { node.open = all; });
        return;
      }
      const log = event.target.closest("[data-trajectory-log]");
      if (log) handlers.onShowLog(log.dataset.trajectoryLog);
    });
    view.addEventListener("toggle", (event) => {
      const node = event.target;
      if (!node.matches || !node.matches("details[data-step-index]")) return;
      const index = Number(node.dataset.stepIndex);
      const set = opened.get(view.dataset.current);
      if (!set || set.has(index) === node.open) return;
      node.open ? set.add(index) : set.delete(index);
      P.writeParams({ trajectoryStep: node.open ? index : null });
    }, true);
  }

  window.AgentActivityPreviewTrajectory = { render, bind, kinds: KIND };
}());
