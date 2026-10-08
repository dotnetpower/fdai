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
  const ICON = {
    normalized_input_reference: "M1.5 8h8M6.5 5l3 3-3 3M13.5 2.5v11",
    routing_decision: "M3 2.5v4a3 3 0 0 0 3 3h7.5M10.5 6.5l3 3-3 3M3 13.5v.01",
    assistant_output: "M2.5 3h11v8h-6l-3 2.5V11h-2z",
    tool_request: "M2.5 8h10M9.5 5l3 3-3 3M2.5 3v10",
    tool_receipt: "M13.5 8h-10M6.5 5l-3 3 3 3M13.5 3v10",
    action_request: "M9 1.5 3 9h4.5L7 14.5 13 7H8.5z",
    action_receipt: "M3.5 1.5h9v13l-2-1.2-2.5 1.2-2.5-1.2-2 1.2zM6 5.5h4M6 8.5h4",
    verifier_result: "M8 1.5 13.5 3.5v4c0 3.5-2.5 6-5.5 7-3-1-5.5-3.5-5.5-7v-4zM5.5 8l1.8 1.8 3.2-3.3",
    risk_result: "M8 2 14.5 13.5h-13zM8 6.5v3M8 11.5v.01",
    approval: "M6 7a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM1.5 14c0-2.5 2-4 4.5-4 1.6 0 2.8.6 3.6 1.6M10.5 12.5l1.5 1.5 3-3",
    terminal_outcome: "M3.5 14.5V2M3.5 2.5h8l-1.5 3 1.5 3h-8",
    rollback_state: "M2.5 3v3.5H6M2.9 6.5A5.5 5.5 0 1 1 3.2 10"
  };
  const GLYPH = {
    done: "M4 8.5 6.5 11 12 5.5",
    good: "M4 8.5 6.5 11 12 5.5",
    attention: "M8 4v5M8 11.5v.01",
    failed: "M5 5l6 6M11 5l-6 6",
    bad: "M5 5l6 6M11 5l-6 6",
    waiting: "",
    skipped: "M5 8h6"
  };
  const SHIELD = "M8 1.5 13.5 3.5v4c0 3.5-2.5 6-5.5 7-3-1-5.5-3.5-5.5-7v-4z";
  const CLOCK = "M8 1.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13zM8 4.5V8l2.5 1.5";
  const CHEVRON = "M6 4l4 4-4 4";
  const PHASES = [
    ["intake", "Intake", ["normalized_input_reference"]],
    ["evidence", "Evidence", ["tool_request", "tool_receipt"]],
    ["judgment", "Judgment", ["routing_decision", "verifier_result", "risk_result", "assistant_output"]],
    ["authorization", "Authorization", ["approval"]],
    ["execution", "Execution", ["action_request", "action_receipt", "rollback_state"]],
    ["outcome", "Outcome", ["terminal_outcome"]]
  ];
  const ATTENTION = new Set(["partial", "pending", "hil", "unproven", "abstained"]);
  const BAD = new Set(["failed"]);
  const GOOD = new Set(["passed", "succeeded", "completed", "approved"]);
  const OUTCOME_LABEL = { completed: "Completed", failed: "Failed", cancelled: "Cancelled", timed_out: "Timed out", abstained: "Abstained", ambiguous: "Ambiguous" };
  const opened = new Map();
  let selected = P.params().get("trajectory");
  let requestedStep = Number.parseInt(P.params().get("trajectoryStep") || "", 10);
  let onChange = () => {};

  const svg = (path, size = 16) => '<svg viewBox="0 0 16 16" width="' + size + '" height="' + size + '" aria-hidden="true" focusable="false"><path d="' + path + '"/></svg>';
  const avatar = (agent) => '<span class="tj-avatar"><img src="../../console/public/agent-icons/' + esc(agent.toLowerCase()) + '.svg" alt="" /></span>';
  const time = (value) => Date.parse(value);
  const startOf = (step) => time(step.at) - step.ms;
  function span(trajectory) {
    const start = Math.min(...trajectory.steps.map(startOf));
    const end = Math.max(...trajectory.steps.map((step) => time(step.at)));
    return { start, end, total: Math.max(end - start, 1) };
  }
  function duration(ms) {
    if (ms < 1000) return Math.round(ms) + " ms";
    if (ms < 60000) return (ms / 1000).toFixed(ms < 10000 ? 2 : 1).replace(/\.?0+$/, "") + " s";
    const minutes = Math.floor(ms / 60000);
    const seconds = Math.round((ms % 60000) / 1000);
    return minutes + "m " + seconds + "s";
  }
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
    if (GOOD.has(status)) return "good";
    return "neutral";
  }
  const trajectoryTone = (trajectory) => trajectory.terminal ? tone(trajectory.terminal) : "attention";
  const pill = (label, value) => '<span class="tj-status" data-tone="' + value + '">' + esc(label) + "</span>";
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

  /* Piecewise time scale: covered time is linear, long idle gaps are compressed and labeled. */
  function scaleFor(trajectory) {
    const intervals = trajectory.steps.map((step) => [startOf(step), time(step.at)]);
    const marks = [...new Set(intervals.flat())].sort((left, right) => left - right);
    const segments = [];
    for (let index = 1; index < marks.length; index += 1) {
      const [a, b] = [marks[index - 1], marks[index]];
      segments.push({ a, b, covered: intervals.some(([s, e]) => s < b && e > a) });
    }
    const active = segments.filter((item) => item.covered).reduce((total, item) => total + item.b - item.a, 0);
    const cap = Math.max(active * 0.08, 40);
    let cursor = 0;
    const breaks = [];
    segments.forEach((item) => {
      const real = item.b - item.a;
      item.from = cursor;
      item.weight = !item.covered && real > cap * 3 && real > 1000 ? cap : real;
      cursor += item.weight;
      if (item.weight !== real) breaks.push({ at: item.from + item.weight / 2, real });
    });
    const total = Math.max(cursor, 1);
    const x = (t) => {
      const item = segments.find((entry) => t >= entry.a && t <= entry.b);
      if (!item) return t <= marks[0] ? 0 : 100;
      const ratio = item.b === item.a ? 0 : (t - item.a) / (item.b - item.a);
      return (item.from + ratio * item.weight) / total * 100;
    };
    return { x, breaks: breaks.map((entry) => ({ left: entry.at / total * 100, real: entry.real })) };
  }

  function listHtml(items, current) {
    return '<ul class="tj-list-items">' + items.map((trajectory) => {
      const s = span(trajectory);
      const agents = agentsOf(trajectory);
      return '<li><button type="button" class="tj-item" data-trajectory="' + esc(trajectory.correlation) + '" aria-pressed="' + String(trajectory === current) + '" aria-controls="activityTrajectoryDetail">' +
        '<span class="tj-item-head"><strong>' + esc(trajectory.title) + "</strong>" + pill(outcomeOf(trajectory), trajectoryTone(trajectory)) + "</span>" +
        '<span class="tj-item-meta"><span class="tj-stack" aria-label="' + esc(agents.join(", ")) + '">' + agents.map(avatar).join("") + "</span>" +
        "<span>" + trajectory.steps.length + " steps &middot; " + duration(s.total) + "</span></span>" +
        '<span class="tj-item-id"><code>' + esc(trajectory.correlation) + "</code><span>" + esc(trajectory.tier) + "</span></span>" +
        "</button></li>";
    }).join("") + "</ul>";
  }

  function routeHtml(trajectory) {
    return '<ol class="tj-route" aria-label="Agent route">' + agentsOf(trajectory).map((agent) => {
      const steps = trajectory.steps.filter((step) => step.agent === agent);
      const worst = steps.some((step) => BAD.has(step.status)) ? "bad" : steps.some((step) => ATTENTION.has(step.status)) ? "attention" : "neutral";
      return '<li data-tone="' + worst + '">' + avatar(agent) + '<span><strong>' + esc(agent) + "</strong><small>" + steps.length + (steps.length === 1 ? " step" : " steps") + "</small></span></li>";
    }).join("") + "</ol>";
  }

  function metricsHtml(trajectory, s) {
    const requests = trajectory.steps.filter((step) => step.kind === "tool_request").length;
    const failed = trajectory.steps.filter((step) => step.kind === "tool_receipt" && step.tool && step.tool.status !== "succeeded").length;
    const handoffs = trajectory.steps.filter((step) => step.handoff).length;
    const metric = (label, value, note) => "<div><dt>" + esc(label) + "</dt><dd>" + esc(value) + (note ? "<small>" + esc(note) + "</small>" : "") + "</dd></div>";
    return '<dl class="tj-metrics">' +
      metric("Elapsed", duration(s.total), trajectory.terminal ? "to terminal outcome" : "so far") +
      metric("Steps", String(trajectory.steps.length), agentsOf(trajectory).length + " agents") +
      metric("Tool calls", String(requests), failed ? failed + " failed" : requests ? "all succeeded" : "none") +
      metric("Handoffs", String(handoffs), "via event bus") + "</dl>" +
      '<p class="tj-facts"><span>Started <strong>' + stamp(s.start) + "</strong></span><span>" + (trajectory.terminal ? "Finished" : "Last step") + " <strong>" + stamp(s.end) + "</strong></span>" +
      "<span>Tier <strong>" + esc(trajectory.tier) + "</strong></span><span>Mode <strong>" + esc(P.label(trajectory.mode)) + "</strong></span><span>Outcome <strong>" + esc(outcomeOf(trajectory)) + "</strong></span></p>";
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
      return '<li data-phase="' + id + '" data-state="' + state + '"><span class="tj-phase-node">' + svg(GLYPH[state], 14) + '</span><strong>' + label + "</strong><small>" + esc(note) + "</small></li>";
    }).join("") + "</ol>";
  }

  function mapHtml(trajectory, s) {
    const scale = scaleFor(trajectory);
    const lanes = agentsOf(trajectory);
    const laneHeight = 36;
    const yOf = (agent) => lanes.indexOf(agent) * laneHeight + laneHeight / 2;
    const paths = trajectory.steps.slice(1).map((step, offset) => {
      const previous = trajectory.steps[offset];
      if (previous.agent === step.agent) return "";
      const x1 = scale.x(time(previous.at)) * 10;
      const x2 = scale.x(startOf(step)) * 10;
      const mid = (x1 + x2) / 2;
      return '<path d="M' + x1.toFixed(1) + " " + yOf(previous.agent) + " C" + mid.toFixed(1) + " " + yOf(previous.agent) + " " + mid.toFixed(1) + " " + yOf(step.agent) + " " + x2.toFixed(1) + " " + yOf(step.agent) + '"/>';
    }).join("");
    const marks = trajectory.steps.map((step, index) => {
      const left = scale.x(startOf(step));
      const width = Math.max(scale.x(time(step.at)) - left, 0);
      return '<button type="button" class="tj-mark" data-step-jump="' + index + '" data-tone="' + tone(step.status) + '" style="top:' + (yOf(step.agent) - 22) + "px;left:" + left.toFixed(2) + "%;width:" + width.toFixed(2) + '%" aria-label="Step ' + index + ": " + esc(step.agent + " " + KIND[step.kind] + ", " + duration(step.ms) + ", " + P.label(step.status)) + '" title="' + esc(index + " · " + KIND[step.kind] + " · " + duration(step.ms)) + '"></button>';
    }).join("");
    const breaks = scale.breaks.map((entry) => '<span class="tj-break" style="left:' + entry.left.toFixed(2) + '%" title="' + duration(entry.real) + ' idle, compressed"></span>').join("");
    const note = scale.breaks.length ? '<p class="tj-map-note">Compressed idle gaps (dotted lines): ' + scale.breaks.map((entry) => "<strong>" + duration(entry.real) + "</strong>").join(", ") + "</p>" : "";
    return '<figure class="tj-map" aria-labelledby="activityTrajectoryMapTitle">' +
      '<figcaption><h3 id="activityTrajectoryMapTitle">Trajectory map</h3><span>Long idle gaps are compressed and labeled. Select a marker to open its step.</span></figcaption>' +
      '<div class="tj-map-grid" style="--tj-lanes:' + lanes.length + '">' +
      '<ul class="tj-lanes" aria-hidden="true">' + lanes.map((agent) => "<li>" + avatar(agent) + "<span>" + esc(agent) + "</span></li>").join("") + "</ul>" +
      '<div class="tj-plot" style="height:' + lanes.length * laneHeight + 'px">' + lanes.map((agent, index) => '<span class="tj-lane-line" style="top:' + (index * laneHeight + laneHeight / 2) + 'px"></span>').join("") +
      breaks + '<svg class="tj-links" viewBox="0 0 1000 ' + lanes.length * laneHeight + '" preserveAspectRatio="none" aria-hidden="true">' + paths + "</svg>" + marks + "</div>" +
      '<span></span><div class="tj-axis"><span>+0</span><span>+' + duration(s.total) + "</span></div></div>" + note + "</figure>";
  }

  function scalar(value) {
    if (typeof value === "boolean") return '<span class="tj-v-bool">' + String(value) + "</span>";
    if (typeof value === "number") return '<span class="tj-v-num">' + value.toLocaleString("en-US") + "</span>";
    if (/^\d{4}-\d{2}-\d{2}T/.test(String(value))) return '<time datetime="' + esc(value) + '">' + esc(stamp(value)) + "</time>";
    return esc(value);
  }
  function dataHtml(object) {
    return '<dl class="tj-data">' + Object.entries(object).map(([key, value]) => {
      let rendered;
      if (Array.isArray(value)) {
        rendered = value.every((item) => typeof item !== "object")
          ? '<span class="tj-chips">' + value.map((item) => '<span class="tj-chip">' + esc(item) + "</span>").join("") + "</span>"
          : value.map((item) => '<span class="tj-chips">' + Object.entries(item).map(([k, v]) => '<span class="tj-chip"><span>' + esc(k) + "</span> " + scalar(v) + "</span>").join("") + "</span>").join("");
      } else rendered = scalar(value);
      return "<div><dt>" + esc(key).replace(/_/g, "_<wbr>") + "</dt><dd>" + rendered + "</dd></div>";
    }).join("") + "</dl>";
  }
  function block(title, body, wide) {
    return '<section class="tj-block' + (wide ? " tj-wide" : "") + '"><h4>' + esc(title) + "</h4>" + body + "</section>";
  }
  function stepBody(trajectory, step, index) {
    const primary = [];
    const secondary = [];
    if (step.input) primary.push(block("Received", dataHtml(step.input)));
    if (step.output) primary.push(block("Produced", dataHtml(step.output)));
    if (step.decision) secondary.push(block("Decision basis", dataHtml(step.decision)));
    if (step.tool) secondary.push(block("Tool call", dataHtml(step.tool)));
    if (step.checks) {
      secondary.push(block("Checks", '<ul class="tj-checks">' + step.checks.map(([name, result]) =>
        '<li data-tone="' + tone(result) + '">' + svg(GLYPH[tone(result)] || GLYPH.done, 14) + "<span>" + esc(name) + "</span><small>" + esc(P.label(result)) + "</small></li>").join("") + "</ul>"));
    }
    if (step.conversation) {
      secondary.push(block("Agent message", step.conversation.map(([from, to, text]) =>
        '<blockquote class="tj-message"><span>' + avatar(from) + "<strong>" + esc(from) + "</strong> to " + esc(to) + "</span><p>" + esc(text) + "</p></blockquote>").join("")));
    }
    const safeguards = step.safeguards ? block("Safeguards", '<dl class="tj-safeguards">' + step.safeguards.map(([name, value]) =>
      "<div>" + svg(GLYPH.done, 14) + "<dt>" + esc(name) + "</dt><dd>" + esc(value) + "</dd></div>").join("") + "</dl>", true) : "";
    const sha = digest(trajectory.correlation + ":" + step.source.id);
    const source = '<p class="tj-source"><span>Source record</span><code>' + esc(step.source.type + " / " + step.source.id) + "</code>" +
      '<span title="Synthetic digest">sha256 <code>' + sha.slice(0, 10) + "\u2026" + sha.slice(-6) + "</code></span><span>Recorded " + esc(clock(step.at)) + " UTC</span><span>Sequence " + index + "</span></p>";
    return '<div class="tj-step-body"><div class="tj-step-grid">' +
      (primary.length ? '<div class="tj-col">' + primary.join("") + "</div>" : "") +
      (secondary.length ? '<div class="tj-col">' + secondary.join("") + "</div>" : "") +
      "</div>" + safeguards + source + "</div>";
  }

  function stepsHtml(trajectory, filters, s) {
    const key = trajectory.correlation;
    if (!opened.has(key)) {
      const preset = Number.isInteger(requestedStep) && trajectory.correlation === selected ? requestedStep : -1;
      const firstAttention = trajectory.steps.findIndex((step) => tone(step.status) === "attention" || tone(step.status) === "bad");
      opened.set(key, new Set([preset >= 0 ? preset : firstAttention].filter((index) => index >= 0)));
    }
    const open = opened.get(key);
    return '<ol class="tj-steps">' + trajectory.steps.map((step, index) => {
      const context = filters.agent && step.agent !== filters.agent ? " is-context" : "";
      const flagged = tone(step.status) === "attention" || tone(step.status) === "bad";
      const handoff = step.handoff && index < trajectory.steps.length - 1
        ? '<li class="tj-handoff"><span>' + svg("M2 8h10M9 5l3 3-3 3", 12) + "Event bus <code>" + esc(step.handoff.topic) + "</code> to " + step.handoff.to.map(esc).join(", ") + "</span></li>"
        : "";
      return '<li class="tj-step' + context + '" data-kind="' + step.kind + '" data-tone="' + tone(step.status) + '"><details data-step-index="' + index + '"' + (open.has(index) ? " open" : "") + ">" +
        '<summary><span class="tj-node" title="' + esc(KIND[step.kind]) + '">' + svg(ICON[step.kind]) + "</span>" +
        '<span class="tj-step-main"><span class="tj-step-head"><span class="tj-step-who">' + avatar(step.agent) + "<strong>" + esc(step.agent) + "</strong><span>" + esc(KIND[step.kind]) + "</span></span>" +
        '<span class="tj-step-when"><time datetime="' + step.at + '">+' + duration(time(step.at) - s.start) + "</time><span>" + clock(step.at) + "</span></span></span>" +
        '<span class="tj-step-summary">' + esc(step.summary) + "</span>" +
        '<span class="tj-step-foot">' + (flagged ? pill(P.label(step.status), tone(step.status)) : '<span class="tj-step-state">' + esc(P.label(step.status)) + "</span>") +
        '<span class="tj-step-ms">' + duration(step.ms) + "</span></span></span>" +
        '<span class="tj-chevron">' + svg(CHEVRON, 14) + "</span></summary>" +
        stepBody(trajectory, step, index) + "</details></li>" + handoff;
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
    return '<table class="tj-tools"><caption>Catalog order, including tools this trajectory did not use</caption><thead><tr><th scope="col">Tool</th><th scope="col">Requests</th><th scope="col">Succeeded</th><th scope="col">Failed</th></tr></thead><tbody>' +
      [...counts].map(([id, [requests, succeeded, failed]]) => "<tr" + (requests ? "" : ' class="is-unused"') + '><th scope="row"><code>' + esc(id) + "</code></th><td>" + requests + "</td><td>" + succeeded + "</td><td" + (failed ? ' data-tone="bad"' : "") + ">" + failed + "</td></tr>").join("") +
      "</tbody></table>";
  }

  function detailHtml(trajectory, filters) {
    const s = span(trajectory);
    const sources = trajectory.steps.reduce((map, step) => map.set(step.source.type, (map.get(step.source.type) || 0) + 1), new Map());
    const incident = trajectory.incident ? '<a class="ap-button" href="' + esc(P.href("incidents.html", { correlation: trajectory.correlation })) + '">Incident ' + esc(trajectory.incident) + "</a>" : "";
    return '<header class="tj-hero"><div class="tj-hero-copy"><span class="tj-eyebrow">Trajectory <code>' + esc(trajectory.correlation) + "</code></span>" +
      '<h2 id="activityTrajectoryTitle" tabindex="-1">' + esc(trajectory.title) + "</h2><p>" + esc(trajectory.trigger) + "</p></div>" +
      '<span class="tj-status tj-status-lg" data-tone="' + trajectoryTone(trajectory) + '">' + esc(trajectory.status) + "</span></header>" +
      routeHtml(trajectory) +
      '<div class="tj-notices"><p class="tj-notice">' + svg(SHIELD) + "<span>" + esc(trajectory.authority) + "</span></p>" +
      (trajectory.terminal ? "" : '<p class="tj-notice tj-open-note" data-tone="attention" role="note">' + svg(CLOCK) + "<span>Open trajectory: no terminal outcome is recorded yet. This is a partial view of retained records, not a governed trajectory export.</span></p>") + "</div>" +
      metricsHtml(trajectory, s) +
      phasesHtml(trajectory) +
      mapHtml(trajectory, s) +
      '<section class="tj-timeline" aria-labelledby="activityTrajectoryStepsTitle"><div class="tj-section-head"><div><h3 id="activityTrajectoryStepsTitle">Steps</h3>' +
      "<p>Times are UTC. Only observable inputs, outputs, and receipts are recorded; model reasoning is not captured.</p></div>" +
      '<div class="tj-segmented"><button type="button" data-trajectory-expand="all">Expand all</button><button type="button" data-trajectory-expand="none">Collapse all</button></div></div>' +
      stepsHtml(trajectory, filters, s) + "</section>" +
      '<section class="tj-section"><div class="tj-section-head"><div><h3>Tool calls</h3></div></div>' + toolsHtml(trajectory) + "</section>" +
      '<footer class="tj-footer"><details class="tj-provenance"><summary>Trajectory provenance</summary>' + P.fields([
        ["Schema", "Trajectory envelope 1.0 (synthetic)"],
        ["Trajectory ID", "trace-sample:" + trajectory.correlation],
        ["Source records", [...sources].map(([type, count]) => count + " " + type).join(", ")],
        ["Evidence profile", "Synthetic fixture"],
        ["Redaction policy", "redaction-sample-v2"],
        ["Export state", trajectory.terminal ? "Eligible after access authorization" : "Not exportable until terminal"]
      ]) + "</details>" +
      '<div class="tj-actions"><a class="ap-button tj-primary" href="' + esc(P.href("rule-trace.html", { correlation: trajectory.correlation })) + '">Open trace</a>' +
      '<button type="button" data-trajectory-log="' + esc(trajectory.correlation) + '">Show in activity log</button>' + incident + "</div></footer>";
  }

  function render(filters) {
    const view = document.getElementById("activityTrajectoryView");
    const list = document.getElementById("activityTrajectoryList");
    const detail = document.getElementById("activityTrajectoryDetail");
    const count = document.getElementById("activityTrajectoryCount");
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
      const jump = event.target.closest("[data-step-jump]");
      if (jump) {
        const node = view.querySelector('details[data-step-index="' + jump.dataset.stepJump + '"]');
        node.open = true;
        node.scrollIntoView({ block: "center", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
        node.querySelector("summary").focus({ preventScroll: true });
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
