// These fixtures mirror projected fields; absent breakdowns are deliberately not synthesized.
(() => {
  const metrics = [
    ["human-touchpoints", "Operator work that remains", "Human interactions per 100 events; read-only views do not count.", "13.3", "26.7", "hil.html", "Interaction type", "Interactions by vertical"],
    ["mttr", "Time to resolve", "Elapsed resolution time from the projected operating metric.", "15 min", "26 min", "incidents.html?status=resolved", "Resolution latency distribution", "Latency by severity"],
    ["change-lead-time", "Governed change lead time", "Request-to-delivery time; acceptance does not establish a verified operational effect.", "48 min", "98 min", "audit.html?window=30d", "Delivery stage contribution", "Delivery path comparison"],
    ["cost-per-resolved-event", "Attributable spend per resolved result", "Outcome-attributed cost is distinct from provider token usage and candidate savings.", "Unavailable", "No baseline", "llm-cost.html", "Attributed cost composition", "Cost by resolved unit"],
  ];
  for (const [key, title, description, current, baseline, href, analysis, breakdown] of metrics) {
    const panel = document.getElementById(key);
    panel.innerHTML = `
      <header class="ov-metric-intro"><div><h2>${title}</h2><p>${description}</p></div><span>Lower is better when guards hold</span></header>
      ${key === "cost-per-resolved-event" ? '<p class="ow-note">Standard-price estimates are reference values, not invoice reconciliation. No attributable cost is connected in this example.</p>' : ""}
      <div class="cs-metric-grid">
        <a class="cs-metric-link" href="${href}"><span>Current</span><strong${current === "Unavailable" ? ' class="oq-value-label"' : ""}>${current}</strong><small>${current === "Unavailable" ? "USD attribution not connected" : "Synthetic metric"}</small></a>
        <a class="cs-metric-link" href="audit.html?window=30d"><span>Baseline</span><strong${baseline === "No baseline" ? ' class="oq-value-label"' : ""}>${baseline}</strong><small>${baseline === "No baseline" ? "Comparison unavailable" : "Paired scenario set"}</small></a>
        <a class="cs-metric-link" href="audit.html?window=30d"><span>Sample size</span><strong>30 events</strong><small>Autonomy measurement sample</small></a>
      </div>
      <div class="ow-grid">
        <section class="ow-gap"><h3>${title} trend</h3><strong>Unavailable</strong><p class="ow-note">Fewer than two projected trend samples. No interpolated history or invented percentiles.</p><a href="${href}">Inspect source evidence</a></section>
        <section class="ow-gap"><h3>${analysis}</h3><strong>Not connected</strong><p class="ow-note">The current projection supplies the aggregate metric, not this detailed analysis.</p><a href="${href}">Open owning workspace</a></section>
      </div>
      <section class="ow-gap"><h3>${breakdown}</h3><strong>Unavailable</strong><p class="ow-note">The service does not project this breakdown. Missing records do not imply zero activity.</p></section>
      <nav class="ov-footer-links" aria-label="Metric evidence"><a href="${href}">Supporting evidence</a><a href="audit.html?window=30d">Window audit</a><a href="control-assurance.html">Guard boundary</a></nav>`;
  }
})();
