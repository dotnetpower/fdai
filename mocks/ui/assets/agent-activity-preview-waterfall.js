/* Local audit grouping and step evidence; operational frames never become audit traces. */
(function () {
  "use strict";
  const P = window.AgentsPreview;
  const esc = P.escape;
  const collapsed = new Set();
  const clock = (time) => time.slice(11, 19);
  function groupsFor(items, agent) {
    const buckets = new Map();
    items.forEach((item) => {
      const key = item.correlation || "uncorrelated:" + item.seq;
      if (!buckets.has(key)) buckets.set(key, []);
      buckets.get(key).push(item);
    });
    return [...buckets].map(([correlation, rows]) => ({
      correlation, rows: rows.sort((a, b) => Date.parse(a.time) - Date.parse(b.time))
    })).filter((group) => !agent || group.rows.some((row) => row.agent === agent))
      .sort((a, b) => Date.parse(b.rows[0].time) - Date.parse(a.rows[0].time));
  }
  function render(items, selectedAgent, step) {
    const container = document.getElementById("activityWaterfall");
    container.querySelectorAll("[data-waterfall-group]").forEach((group) => {
      if (group.open) collapsed.delete(group.dataset.waterfallGroup);
      else collapsed.add(group.dataset.waterfallGroup);
    });
    const groups = groupsFor(items, selectedAgent);
    document.getElementById("waterfallCount").textContent = groups.length + " correlation groups - " + groups.reduce((total, group) => total + group.rows.length, 0) + " synthetic audit records";
    container.innerHTML = groups.length ? groups.map((group) => {
      const start = Date.parse(group.rows[0].time);
      const span = Date.parse(group.rows.at(-1).time) - start;
      const tail = span > 0 ? span * .2 : 1000;
      const denominator = span + tail;
      return '<details class="ap-waterfall-group" data-waterfall-group="' + esc(group.correlation) + '"' + (collapsed.has(group.correlation) ? "" : " open") + '><summary><span>' + esc(group.correlation) + "</span><small>" + group.rows.length + " records / " + (span / 1000).toFixed(1) + "s handoff span</small></summary>" +
        group.rows.map((row, index) => {
          const offset = Date.parse(row.time) - start;
          const next = index + 1 < group.rows.length ? Date.parse(group.rows[index + 1].time) - start : denominator;
          const left = offset / denominator * 100;
          const width = Math.min(Math.max((next - offset) / denominator * 100, 2.5), 100 - left);
          return '<div class="ap-waterfall-row' + (selectedAgent && row.agent !== selectedAgent ? " is-context" : "") + '"><span class="ap-waterfall-agent">' + row.agent +
            '</span><div class="ap-waterfall-track" aria-hidden="true"><span class="ap-waterfall-bar" style="left:' + left + "%;width:" + width + '%"></span></div>' +
            '<button type="button" class="ap-waterfall-open" data-step="' + row.seq + '" aria-pressed="' + String(step === row.seq) + '"><span>' + esc(row.action) + "</span><small>" + clock(row.time) + " UTC / +" + (offset / 1000).toFixed(1) + "s" + (row.conversation ? " / conversation" : "") + "</small></button></div>";
        }).join("") + "</details>";
    }).join("") : '<div class="ap-empty"><strong>No audit records in this selection.</strong><p>' + (P.available() ? "Try another window or clear the filters. Operational-only correlations cannot be reconstructed as audit traces." : "Audit evidence is unavailable in this source scenario, not confirmed empty.") + "</p></div>";
    const selected = groups.flatMap((group) => group.rows).find((row) => row.seq === step);
    renderDetail(selected, step);
  }
  function renderDetail(item, requestedStep) {
    const panel = document.getElementById("activityStep");
    panel.hidden = !requestedStep;
    if (!requestedStep) { panel.innerHTML = ""; return; }
    if (!item) {
      panel.innerHTML = '<header class="ap-section-head"><h2 tabindex="-1">Step unavailable</h2><button type="button" data-close-step>Close</button></header><p>The requested step is not in the selected retained audit records. Clear filters or choose another step.</p>';
      return;
    }
    panel.innerHTML = '<header class="ap-section-head"><h2 tabindex="-1">' + item.agent + " / audit step " + item.seq + '</h2><button type="button" data-close-step aria-label="Close audit step">Close</button></header>' +
      '<p><strong>' + esc(item.action) + "</strong></p><p>" + esc(item.summary) + "</p>" +
      P.fields([["Evidence", "Synthetic audit; fixture only"], ["Mode", item.mode], ["Tier", item.tier || "Not supplied"], ["Outcome", item.outcome], ["Reason", item.reason || "See the recorded fixture summary"], ["Correlation", item.correlation || "Uncorrelated"]]) +
      '<h3>Lifecycle</h3><ol class="ap-lifecycle"><li><strong>Received</strong><small>Not supplied</small></li><li><strong>Started</strong><small>Not supplied</small></li><li><strong>Recorded</strong><small>' + esc(item.time) + "</small></li></ol>" +
      '<p class="ap-meta">Fixture work: ' + item.duration + "ms / queue: " + item.queue + "ms. Handoff bar width is not work duration.</p>" +
      (item.conversation ? '<h3>Agent conversation</h3><ol class="ap-conversation">' + item.conversation.map(([from, to, text]) => "<li><strong>" + from + " -&gt; " + to + "</strong><p>" + esc(text) + "</p></li>").join("") + "</ol>" : "") +
      '<details open><summary>Inputs and outputs</summary><h3>Inputs</h3><pre>' + esc(JSON.stringify(item.inputs, null, 2)) + "</pre><h3>Outputs</h3><pre>" + esc(JSON.stringify(item.outputs, null, 2)) + "</pre></details>" +
      '<details><summary>Audit record metadata</summary>' + P.fields([["Sequence", item.seq], ["Event ID", item.id], ["Entry hash", "Not supplied in this fixture"], ["Previous hash", "Not supplied in this fixture"], ["Recorded at", item.time]]) + "</details>" +
      '<div class="ap-actions"><a class="ap-button" href="' + esc(P.href("agents-constellation.html", { agent: item.agent, correlation: item.correlation })) + '">Agent and incident</a><button type="button" data-audit-unavailable>Production audit</button></div>';
  }
  window.AgentActivityPreviewWaterfall = { render, renderDetail };
}());
